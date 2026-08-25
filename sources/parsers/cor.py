"""Parser operator COR (Gacor25). Panel terpisah 2 rail (bank & QRIS) + gateway QRIS.

Nominal dalam RUPIAH penuh (JANGAN x1000). File dari exporter non-standar -> dibaca
lewat read_xlsx_rows yang sudah tahan-styles. Kolom bank format "KODE - NOREK - NAMA".
"""
import re
from decimal import Decimal

from .base import (
    BaseParser,
    derive_bank_fields,
    parse_bank_triplet,
    parse_decimal,
    parse_dt,
    read_xlsx_rows,
    row_hash,
)

# Akun WD/DP situs sendiri (Vigor/TM Gaming) muncul di panel sebagai kode operator
# "OTH" -- bank aslinya "tersembunyi" di ekor nama pemilik, mis.
# "IGNATIUS IVAN / WITHDRAW BCA". Tanpa urai ini, chip filter Bank Title di
# run-detail menumpuk >1000 baris jadi satu "OTH" generik tak berguna.
_OTH_EMBED_RE = re.compile(r"/\s*(?:WITHDRAW|DEPOSIT)\s+([A-Z][A-Z0-9]+)\s*$", re.IGNORECASE)


def resolve_oth_bank(code, name):
    """Kode operator "OTH" -> bank asli hasil urai `name` ("... / WITHDRAW BCA" /
    "... / DEPOSIT BCA" -> "BCA"). Kode selain "OTH" dikembalikan apa adanya
    (fungsi ini murni penanganan kasus khusus OTH). Tanpa pola cocok -> "OTH"
    dipertahankan (dipakai juga oleh command backfill_oth_bank, harus idempoten)."""
    if (code or "").strip().upper() != "OTH":
        return code
    m = _OTH_EMBED_RE.search(str(name or ""))
    return m.group(1).upper() if m else code


def _cor_bank_title_chip(op_code_eff, op_name, bank_title_default):
    """Chip `bank_title` untuk rail bank COR / manual deposit.

    Destinasi QRIS ELITE diekspor sebagai ``QRIS - <norek> - QRISELITE``.
    ``derive_bank_fields`` hanya mengambil segmen pertama → ``QRIS``, sama
    dengan rail UNOPAY generik — kanal ELITE hilang di chip filter, channel
    guard, dan Control Bracket. Bila nama pemilik memuat ELITE, chip =
    ``QRISELITE`` (masih mengandung ``QR`` → kelas metode tetap QRIS).
    ``raw[\"Bank Title\"]`` tetap triplet penuh ``QRIS|QRISELITE|<norek>``.
    """
    code = (op_code_eff or "").strip().upper()
    name_u = (op_name or "").strip().upper()
    if code == "QRIS" and "ELITE" in name_u:
        return "QRISELITE"
    return bank_title_default


class CORPanelBankParser(BaseParser):
    """Panel rail bank COR klasik: Approved Date + Requested Date + From/Destination.

    Bukan ekspor manual deposit (kolom ``Date`` tunggal) — itu
    ``CORPanelManualDepositParser`` / ``cor_panel_manual_dp``.
    """

    source_key = "panel"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=1)
        is_wd = flow == "wd"
        out = []
        for r in rows:
            username = str(r.get("Username", "") or "").strip()
            if not username or str(r.get("Status", "") or "").strip().lower() != "approved":
                continue
            amt = parse_decimal(r.get("Amount"))
            if is_wd:
                jenis, credit_delta, money_delta = "wd", amt, -amt
                player_raw, oper_raw = r.get("Destination Bank"), r.get("From Bank")
            else:
                jenis, credit_delta, money_delta = "depo", -amt, amt
                player_raw, oper_raw = r.get("From Bank"), r.get("Destination Bank")
            pk_code, pk_acct, pk_name = parse_bank_triplet(player_raw)
            op_code, op_acct, op_name = parse_bank_triplet(oper_raw)
            op_code_eff = resolve_oth_bank(op_code, op_name)
            occurred = parse_dt(r.get("Requested Date"))
            posted = parse_dt(r.get("Approved Date"))
            raw = {k: ("" if v is None else str(v)) for k, v in r.items()}
            raw["Player Bank"] = f"{pk_code}|{pk_name}|{pk_acct}"
            raw["Bank Title"] = f"{op_code_eff}|{op_name}|{op_acct}"
            player_bank, bank_title = derive_bank_fields("panel", raw)
            bank_title = _cor_bank_title_chip(op_code_eff, op_name, bank_title)
            row = {
                "source_type": "panel",
                "occurred_at": occurred,
                "posted_date": posted.date() if posted else None,
                "jenis": jenis,
                "amount": amt,
                "credit_delta": credit_delta,
                "money_delta": money_delta,
                "fee": Decimal("0"),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": "",
                "username": username,
                "reference": "",
                "counterparty": pk_name,
                "description": f"{op_code} {op_name}".strip(),
                "player_bank": player_bank,
                "bank_title": bank_title,
                "raw": raw,
            }
            row["row_hash"] = row_hash("cor_panel_bank",
                                       [username, amt, occurred, pk_acct])
            out.append(row)
        return out


class CORPanelManualDepositParser(BaseParser):
    """Panel manual deposit Vigor/TM Gaming (DP ELITE / deposit manual bank-rail).

    Bentuk header beda dari ``cor_panel_bank``:
    ``# | Date | Username | From Bank | Destination Bank | Amount | Status | By``
    — **satu** kolom ``Date`` (bukan Approved/Requested). Contoh destinasi
    ELITE: ``QRIS - 5615607894 - QRISELITE``.

    Selalu **deposit** (bukan WD): flow nama berkas diabaikan supaya
    ``… DP ELITE PANEL`` tidak bisa kebalik jadi wd. source_key tetap
    ``panel`` (ikut SourceType panel, tanpa migrasi).
    """

    source_key = "panel"
    MARKER = "cor_panel_manual_dp"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=1)
        out = []
        for r in rows:
            username = str(r.get("Username", "") or "").strip()
            if not username or str(r.get("Status", "") or "").strip().lower() != "approved":
                continue
            amt = parse_decimal(r.get("Amount"))
            # DP: pemain = From Bank, operator/tujuan = Destination Bank
            pk_code, pk_acct, pk_name = parse_bank_triplet(r.get("From Bank"))
            op_code, op_acct, op_name = parse_bank_triplet(r.get("Destination Bank"))
            op_code_eff = resolve_oth_bank(op_code, op_name)
            when = parse_dt(r.get("Date"))
            if not when:
                # Jangan emit baris dateless — guard ingest akan menolak seluruh
                # file; lebih jelas gagal di sini per-baris hanya jika SEMUA
                # gagal (kembalikan [] → zero-yield / bertanggal).
                continue
            raw = {k: ("" if v is None else str(v)) for k, v in r.items()}
            raw["Player Bank"] = f"{pk_code}|{pk_name}|{pk_acct}"
            raw["Bank Title"] = f"{op_code_eff}|{op_name}|{op_acct}"
            raw["Sumber"] = self.MARKER
            player_bank, bank_title = derive_bank_fields("panel", raw)
            bank_title = _cor_bank_title_chip(op_code_eff, op_name, bank_title)
            row = {
                "source_type": "panel",
                "occurred_at": when,
                "posted_date": when.date(),
                "jenis": "depo",
                "amount": amt,
                "credit_delta": -amt,
                "money_delta": amt,
                "fee": Decimal("0"),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": "",
                "username": username,
                "reference": "",
                "counterparty": pk_name,
                "description": f"{op_code} {op_name}".strip(),
                "player_bank": player_bank,
                "bank_title": bank_title,
                "raw": raw,
            }
            # Namespace hash terpisah dari cor_panel_bank — file yang sama
            # diurai dua parser tidak saling menimpa dedup.
            row["row_hash"] = row_hash(
                self.MARKER, [username, amt, when, pk_acct, op_acct]
            )
            out.append(row)
        if rows and not out:
            raise ValueError(
                "Panel manual deposit: berkas punya baris tetapi tidak satu pun "
                "lolos (Status=approved + Username + Date terbaca). Header yang "
                "dikenal: Date, Username, From Bank, Destination Bank, Amount, "
                "Status. Jangan samakan dengan cor_panel_bank (Approved/"
                "Requested Date)."
            )
        return out


class CORPanelQRISParser(BaseParser):
    source_key = "panel"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=1)
        is_wd = flow == "wd"
        out = []
        for r in rows:
            username = str(r.get("Username", "") or "").strip()
            txid = str(r.get("Transaction ID", "") or "").strip()
            status = str(r.get("Status", "") or "").strip().lower()
            if not txid or not username or status not in ("success", ""):
                continue
            amt = parse_decimal(r.get("Amount"))
            raw = {k: ("" if v is None else str(v)) for k, v in r.items()}
            if is_wd:
                jenis, credit_delta, money_delta = "wd", amt, -amt
                pk_code, pk_acct, pk_name = parse_bank_triplet(r.get("Destination Bank"))
                raw["Player Bank"] = f"{pk_code}|{pk_name}|{pk_acct}"
                counterparty = pk_name
            else:
                jenis, credit_delta, money_delta = "depo", -amt, amt
                counterparty = ""
            occurred = parse_dt(r.get("Requested Date"))
            posted = parse_dt(r.get("Approved Date"))
            # Rail QRIS tak punya kolom bank tujuan di ekspor — sintesis
            # labelnya supaya chip filter, sel tabel, ekspor, dan kelas metode
            # dashboard tak lagi kosong. (raw sintetis = praktik mapan parser
            # COR, lihat raw["Player Bank"] di atas.)
            # Bentuknya triplet panel "KODE|NAMA|NOREK" seperti nilai asli
            # ("BCA|HENDI|7126201591"); NAMA & NOREK kosong karena rail QRIS
            # memang tak punya pemilik maupun nomor rekening tujuan. Itu bukan
            # kosmetik: engine `_expected_owner` mengambil segmen TENGAH dan
            # jatuh ke seluruh string bila tak ada "|" — label telanjang "QRIS"
            # akan dibaca sebagai NAMA pemilik rekening dan menyalakan
            # `_route_ok` (kunci sort sekunder) untuk seluruh populasi COR QRIS.
            # Kolom `bank_title` tetap "QRIS": derive mengambil segmen pertama.
            raw["Bank Title"] = "QRIS||"
            player_bank, bank_title = derive_bank_fields("panel", raw)
            row = {
                "source_type": "panel",
                "occurred_at": occurred,
                "posted_date": posted.date() if posted else None,
                "jenis": jenis,
                "amount": amt,
                "credit_delta": credit_delta,
                "money_delta": money_delta,
                "fee": Decimal("0"),
                "bonus": parse_decimal(r.get("Bonus")),
                "balance_after": None,
                "ticket_no": "",
                "username": username,
                "reference": txid,
                "counterparty": counterparty,
                "description": f"QRIS {txid}".strip(),
                "player_bank": player_bank,
                "bank_title": bank_title,
                "raw": raw,
            }
            row["row_hash"] = row_hash("cor_panel_qris", [txid, username, amt])
            out.append(row)
        return out


class CORQRISWDGatewayParser(BaseParser):
    """Mutasi WD gateway QR UNO — sisi uang QRIS withdrawal keluarga panel
    TM Gaming/Vigor (SLO/COR/WN25).

    Kunci exact: `Order ID (Merchant)` (UUID penuh) == `Transaction ID` panel
    QRIS WD -> reference-join pass 0b. Baris REFUND dilewati (payout gagal,
    uang kembali). Baris SUCCESS ber-order non-UUID (transfer manual operator)
    tetap diambil supaya muncul sebagai uang-tanpa-panel.
    """

    source_key = "gateway"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=1)
        out = []
        for r in rows:
            order = str(r.get("Order ID (Merchant)", "") or "").strip()
            status = str(r.get("Status", "") or "").strip().lower()
            if not order or status != "success":
                continue
            amt = parse_decimal(r.get("Amount"))  # nett = angka yang dilihat panel
            occurred = parse_dt(r.get("TransactionTime"))
            acct = str(r.get("AccountNumber", "") or "").strip()
            recipient = str(r.get("RecipientName", "") or "").strip()
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "wd",
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": -amt,
                "fee": parse_decimal(r.get("Fee")),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": "",
                "username": "",
                "reference": order,
                "counterparty": "" if recipient == acct else recipient,
                "description": f"QRIS WD {r.get('Merchant Name', '')}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items()},
            }
            row["row_hash"] = row_hash("cor_qris_wd_gw", [order, amt, occurred])
            out.append(row)
        return out


class CORQRISGatewayParser(BaseParser):
    source_key = "gateway"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=1)
        out = []
        for r in rows:
            order = str(r.get("OrderId", "") or "").strip()
            if not order:
                continue
            gross = parse_decimal(r.get("GrandTotal"))
            net = parse_decimal(r.get("BranchNominal"))
            occurred = parse_dt(r.get("TransactionTime"))
            # Bentuk kolom berasal dari vendor, sedangkan nama berkas (dan
            # `flow`) diketik manusia; bentuk harus menang. Di produksi seluruh
            # 2.067 baris bentuk-DP yang sempat berjenis WD adalah korban salah
            # deteksi pada satu toko (w25), hanya 14-07-2026 sebanyak 1.471 dan
            # 13-08-2026 sebanyak 596 — bukan bukti bentuk ini pernah menjadi WD.
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "depo",
                "amount": gross,
                "credit_delta": Decimal("0"),
                "money_delta": gross,
                "fee": gross - net,
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": "",
                "username": "",
                "reference": order,
                "counterparty": "",
                "description": f"QRIS COR {r.get('RRN','')}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items()},
            }
            row["row_hash"] = row_hash("cor_qris_gw", [order, gross])
            out.append(row)
        return out
