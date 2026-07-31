"""Service ingest: parse file -> simpan Transaction kanonik (idempoten via row_hash)."""
import os
import re
import tempfile
from datetime import timedelta
from pathlib import Path

from django.db import IntegrityError, transaction as db_tx
from django.utils import timezone

from core.audit import catat
from transactions.models import Transaction, owner_from_filename

from .models import SourceType, Upload
from .parsers.banks import BCACSVParser, BRIParser, MandiriParser
from .parsers.bca_pdf import BCAPDFParser
from .parsers.bni_pdf import BNIPDFParser
from .parsers.bonus import BracketBonusParser, PanelBonusParser
from .parsers.bracket import BracketParser
from .parsers.cor import (
    CORPanelBankParser,
    CORPanelQRISParser,
    CORQRISGatewayParser,
    CORQRISWDGatewayParser,
)
from .parsers.gateways import (
    NXPayParser,
    QRFlyerParser,
    QHokiParser,
    RPayGatewayParser,
    RPayWDGatewayParser,
    RPayDPXlsxParser,
    RPayWDXlsxParser,
)
from .parsers.panel import PanelParser

# parser_key -> kelas parser (parser.source_key menentukan SourceType-nya)
PARSERS = {
    "bracket": BracketParser,
    "panel": PanelParser,
    "bri": BRIParser,
    "bca_csv": BCACSVParser,
    "bca_pdf": BCAPDFParser,
    "bni_pdf": BNIPDFParser,
    "mandiri": MandiriParser,
    "nxpay": NXPayParser,
    "qrflyer": QRFlyerParser,
    "cor_panel_bank": CORPanelBankParser,
    "cor_panel_qris": CORPanelQRISParser,
    "cor_qris_gateway": CORQRISGatewayParser,
    "cor_qris_wd_gateway": CORQRISWDGatewayParser,
    "rpay": RPayGatewayParser,
    "rpay_wd": RPayWDGatewayParser,
    "rpay_xlsx": RPayDPXlsxParser,
    "rpay_wd_xlsx": RPayWDXlsxParser,
    "qhoki": QHokiParser,
    "panel_bonus": PanelBonusParser,
    "bracket_bonus": BracketBonusParser,
}

# Magic bytes: OLE2/CDFV2 compound-file header (e-statement terenkripsi "agile encryption").
_OLE2_MAGIC = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"


def is_encrypted_xlsx(path):
    """True bila `path` adalah xlsx terenkripsi (OLE2/CDFV2). xlsx normal diawali ``PK\\x03\\x04``."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return False
    return head == _OLE2_MAGIC


def _decrypt_to_temp(path, password):
    """Dekripsi xlsx terenkripsi ke file .xlsx sementara; kembalikan path-nya.

    Gagal (password salah / file rusak) → temp dibersihkan + ValueError berpesan
    jelas (pesan ini tampil apa adanya di form upload)."""
    import msoffcrypto

    import contextlib

    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)

    def _cleanup():
        tmp.close()
        with contextlib.suppress(OSError):  # gagal hapus jangan menutupi error asli
            os.remove(tmp.name)

    try:
        with open(path, "rb") as f:
            off = msoffcrypto.OfficeFile(f)
            off.load_key(password=password)
            off.decrypt(tmp)
    except OSError:
        _cleanup()
        raise  # file sumber hilang/tak terbaca — BUKAN soal password
    except Exception as e:
        _cleanup()
        raise ValueError(
            "Password salah atau file terenkripsi rusak — periksa kembali."
        ) from e
    tmp.close()
    return tmp.name


def ingest(parser_key, file_path, recon_date=None, account=None, flow="", user=None, toko=None, provider="", password="", original_name=""):
    """Parse `file_path` dengan parser `parser_key`, simpan sebagai Transaction.

    File terenkripsi (Mandiri e-statement) didekripsi dulu memakai `password`.
    `original_name` = nama file APA ADANYA dari pengunggah; `file_path` menunjuk
    file staging yang namanya bisa dibubuhi sufiks acak oleh storage Django.
    Mengembalikan (upload, created, duplicate).
    """
    if parser_key not in PARSERS:
        raise ValueError(f"Parser '{parser_key}' tidak dikenal. Pilihan: {', '.join(PARSERS)}")

    parser = PARSERS[parser_key]()

    parse_path, tmp_path = file_path, None
    if is_encrypted_xlsx(file_path):
        if not password:
            raise ValueError("File terenkripsi — butuh password untuk membukanya.")
        tmp_path = _decrypt_to_temp(file_path, password)
        parse_path = tmp_path
    try:
        rows = parser.parse(parse_path, flow=flow)
        st = SourceType.objects.get(key=parser.source_key)
        # Pemilik rekening: header file (BCA/Mandiri) dulu, fallback nama file (BRI).
        # getattr: parser double di test boleh tanpa .meta.
        meta = getattr(parser, "meta", {}) or {}
        owner = meta.get("owner_name", "") or owner_from_filename(Path(file_path).name)
        try:
            return _persist_rows(rows, st, file_path, recon_date, account, flow, user, toko, provider, owner, original_name)
        except IntegrityError:
            # Balapan ingest ganda (double-submit / dua worker): constraint DB
            # menolak baris kembar. Ulang SEKALI — percobaan kedua membaca ulang
            # row_hash yang baru saja di-commit proses lain → terhitung duplikat.
            return _persist_rows(rows, st, file_path, recon_date, account, flow, user, toko, provider, owner, original_name)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


# Sufiks acak yang ditambahkan storage Django saat nama staging bentrok
# ("X.xlsx" -> "X_1pZwg1n.xlsx") — dibuang agar nama file bisa dibandingkan.
_SUFIKS_STORAGE_RE = re.compile(r"_[A-Za-z0-9]{7}(?=\.[^.]+$)")

# Batas usia kandidat. Bukan aturan bisnis — tak ada tenggat yang dijanjikan;
# bukti sebenarnya adalah superset row_hash di bawah. Jendela ini membatasi
# kandidat yang diperiksa dan menahan kejutan pada ekspor kumulatif sama-nama
# (file bulan ini yang memuat seluruh isi file bulan lalu).
TIBAN_JENDELA = timedelta(days=14)


def _nama_kunci(name):
    return _SUFIKS_STORAGE_RE.sub("", (name or "").strip()).casefold()


def _tandai_tiban(up, st, toko, file_hashes, user):
    """Upload ulang yang LEBIH LENGKAP menandai file lama sama-nama 'ketiban'.

    Kasusnya: file tarikan bank kadang kepotong DI BAWAH; versi utuhnya di-upload
    ulang dgn nama yang sama. Bukti utamanya superset row_hash: SELURUH isi file
    kandidat (baris miliknya + baris dedup yang ter-link padanya) harus tercakup
    file baru. Murni metadata — transaksi, atribusi, dan batch tak disentuh
    sama sekali.

    Batas yang diketahui: parser BCA PDF memakai row_hash posisional; bila baris
    DI ATAS overlap ikut berubah, bukti superset gagal dan file lama tidak
    ditandai — itu perilaku fail-safe yang benar.
    """
    kunci = _nama_kunci(up.original_name)
    if not kunci:
        return
    kandidat = Upload.objects.filter(
        toko=toko, source_type=st, superseded_by__isnull=True,
        created_at__gte=timezone.now() - TIBAN_JENDELA,
    ).exclude(pk=up.pk)
    for cand in kandidat:
        if _nama_kunci(cand.original_name) != kunci:
            continue
        # Isi file kandidat = baris miliknya + baris dedup yang ter-link padanya.
        # Diambil sebagai himpunan (2 query) alih-alih dua `exclude(row_hash__in=…)`
        # supaya file besar tidak berubah jadi ribuan parameter SQL.
        isi = set(
            Transaction.objects.filter(upload=cand).values_list("row_hash", flat=True)
        ) | set(cand.duplicate_transactions.values_list("row_hash", flat=True))
        if not isi or not isi <= file_hashes:
            continue  # kandidat kosong = tanpa bukti; selebihnya = bukan superset
        cand.superseded_by = up
        cand.save(update_fields=["superseded_by", "updated_at"])
        catat(user, "upload_tiban", f"Upload #{cand.pk}", toko=toko,
              lama=cand.original_name, baru=up.original_name, upload_baru=up.pk)


def _persist_rows(rows, st, file_path, recon_date, account, flow, user, toko, provider, owner="", original_name=""):
    """Simpan hasil parse sebagai Upload + Transaction (atomic, dedup row_hash)."""
    with db_tx.atomic():
            up = Upload.objects.create(
                source_type=st,
                account=account,
                toko=toko,
                provider=provider,
                flow=flow or "",
                recon_date=recon_date,
                original_name=Path(original_name or file_path).name[:255],
                owner_name=(owner or "")[:100],
                status=Upload.PARSED,
                uploaded_by=user,
            )
            existing = set(
                Transaction.objects.filter(source_type=st, toko=toko).values_list("row_hash", flat=True)
            )
            objs, seen, dup, dup_tercatat = [], set(), 0, set()
            for row in rows:
                rh = row["row_hash"]
                if rh in existing or rh in seen:
                    dup += 1
                    # Baris yang sudah tercatat lewat UPLOAD TERDAHULU di-link ke
                    # upload ini agar "isi file" tetap bisa ditampilkan utuh
                    # (repeat DALAM file yang sama bukan isi file terdahulu).
                    if rh in existing:
                        dup_tercatat.add(rh)
                    continue
                seen.add(rh)
                objs.append(
                    Transaction(
                        upload=up,
                        source_type=st,
                        account=account,
                        toko=toko,
                        occurred_at=row["occurred_at"],
                        posted_date=row["posted_date"],
                        jenis=row["jenis"],
                        amount=row["amount"],
                        credit_delta=row["credit_delta"],
                        money_delta=row["money_delta"],
                        fee=row["fee"],
                        bonus=row["bonus"],
                        balance_after=row["balance_after"],
                        ticket_no=row["ticket_no"],
                        username=row["username"],
                        reference=row["reference"],
                        counterparty=row["counterparty"],
                        description=row["description"],
                        player_bank=row.get("player_bank", ""),
                        bank_title=row.get("bank_title", ""),
                        raw=row["raw"],
                        row_hash=rh,
                    )
                )
            Transaction.objects.bulk_create(objs, batch_size=1000)
            if dup_tercatat:
                up.duplicate_transactions.add(
                    *Transaction.objects.filter(
                        source_type=st, toko=toko, row_hash__in=dup_tercatat
                    ).values_list("id", flat=True)
                )
            up.rows_parsed = len(objs)
            up.rows_duplicate = dup
            up.save(update_fields=["rows_parsed", "rows_duplicate"])
            # `dup_tercatat | hash baris baru` = seluruh isi file ini. Hanya bila
            # file MENAMBAH baris (upload ulang identik: no-op). Di dalam atomic()
            # → penandaan ikut ter-rollback bila percobaan pertama gagal.
            if objs:
                _tandai_tiban(up, st, toko, dup_tercatat | {o.row_hash for o in objs}, user)
    return up, len(objs), dup
