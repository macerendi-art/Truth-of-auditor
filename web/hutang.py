"""Hutang/Piutang — daftar baris FR berkategori hutang/piutang, query-time.

Pola sama `web/breakdown.py`: baca `Transaction.raw` bracket tanpa migrasi,
berlaku retroaktif untuk data lama. Read-only murni terhadap Transaction.

Overlay opsional: `web.models.HutangManual` menimpa **total** hutang/piutang
bila rentang (dari, sampai) jatuh dalam satu bulan kalender yang sama dan
toko tunggal — baris FR tetap dari data mentah.
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.db.models.fields.json import KeyTextTransform

from transactions.models import Transaction
from web.breakdown import _slug_kategori

NOL = Decimal("0")


def _meta_manual(obj):
    """Snapshot metadata overlay untuk template/audit UI."""
    if obj is None:
        return None
    oleh = ""
    if obj.dibuat_oleh_id:
        oleh = getattr(obj.dibuat_oleh, "username", "") or ""
    return {
        "nilai": obj.nilai,
        "tanggal": obj.tanggal,
        "catatan": obj.catatan or "",
        "oleh": oleh,
        "periode": obj.periode,
        "updated_at": obj.updated_at,
    }


def _overlay_total_bulanan(toko, dari, sampai, total_h, total_p):
    """Timpa total bila rentang satu bulan + ada HutangManual.

    Multi-toko (list) tidak di-overlay di sini — form tulis single-toko saja.
    Mengembalikan (total_h, total_p, manual_meta dict).
    """
    kosong = {"hutang": None, "piutang": None, "aktif": False,
              "periode": None, "asli_hutang": total_h, "asli_piutang": total_p}
    if toko is None or isinstance(toko, (list, tuple, set, frozenset)):
        return total_h, total_p, kosong
    if not dari or not sampai:
        return total_h, total_p, kosong
    if dari.year != sampai.year or dari.month != sampai.month:
        return total_h, total_p, kosong

    # Impor lokal: hindari siklus models ↔ hutang saat app load.
    from web.models import HutangManual

    periode = date(dari.year, dari.month, 1)
    by_field = {
        m.field: m
        for m in HutangManual.objects
        .filter(toko=toko, periode=periode)
        .select_related("dibuat_oleh")
    }
    if not by_field:
        meta = dict(kosong)
        meta["periode"] = periode
        return total_h, total_p, meta

    h_obj = by_field.get(HutangManual.FIELD_HUTANG)
    p_obj = by_field.get(HutangManual.FIELD_PIUTANG)
    new_h = h_obj.nilai if h_obj is not None else total_h
    new_p = p_obj.nilai if p_obj is not None else total_p
    return new_h, new_p, {
        "hutang": _meta_manual(h_obj),
        "piutang": _meta_manual(p_obj),
        "aktif": True,
        "periode": periode,
        "asli_hutang": total_h,
        "asli_piutang": total_p,
    }


def hutang_piutang(toko, dari=None, sampai=None):
    """Baris bracket berkategori Hutang/Piutang + ringkasan total.

    `toko` boleh satu objek Toko ATAU list/tuple/set Toko (mode Semua Toko):
    daftar toko dijalankan lewat satu `toko__in`, bukan satu query per toko.
    Mode banyak-toko menambahkan kunci `"toko"` (nama) pada tiap baris; bentuk
    baris mode satu-toko sengaja dibiarkan PERSIS seperti semula supaya halaman
    lama tak perlu tahu apa-apa tentang mode ini.

    Filter kategori didorong ke DB (iregex pada key JSON) supaya scan tetap
    ringan di volume produksi; slug final tetap lewat `_slug_kategori` agar
    normalisasi varian ejaan satu pintu.

    Bila rentang satu bulan + toko tunggal + ada `HutangManual`, `total_hutang`
    / `total_piutang` / `netto` memakai nilai override; baris FR tidak diubah.
    Metadata di kunci `manual`.
    """
    banyak = isinstance(toko, (list, tuple, set, frozenset))
    lingkup = {"toko__in": list(toko)} if banyak else {"toko": toko}
    qs = Transaction.objects.filter(source_type__key="bracket", **lingkup)
    if dari:
        qs = qs.filter(posted_date__gte=dari)
    if sampai:
        qs = qs.filter(posted_date__lte=sampai)
    kolom = ["id", "posted_date", "money_delta", "fr_bank", "fr_kategori",
             "fr_jam", "fr_member", "fr_username", "fr_expense"]
    if banyak:
        kolom.append("toko__name")
    qs = (
        qs.annotate(
            fr_bank=KeyTextTransform("Bank", "raw"),
            fr_kategori=KeyTextTransform("Kategori", "raw"),
            fr_jam=KeyTextTransform("Jam", "raw"),
            fr_member=KeyTextTransform("Member", "raw"),
            fr_username=KeyTextTransform("Username", "raw"),
            fr_expense=KeyTextTransform("Expense", "raw"),
        )
        .filter(fr_kategori__iregex=r"^\s*(hutang|piutang)\s*$")
        .values_list(*kolom)
    )
    rows, total_h, total_p = [], NOL, NOL
    for nilai in qs:
        (pk, tanggal, delta, bank, kategori, jam, member, username,
         expense) = nilai[:9]
        slug = _slug_kategori(kategori)
        delta = delta or NOL
        baris = {
            "id": pk, "tanggal": tanggal, "jam": str(jam or ""),
            "account": str(bank or "").strip() or "(Tanpa Akun)",
            "kategori": slug,
            "member": str(member or "").strip() or str(username or "").strip(),
            "keterangan": str(expense or "").strip(),
            "nominal": delta,
        }
        if banyak:
            baris["toko"] = nilai[9]
        rows.append(baris)
        if slug == "hutang":
            total_h += delta
        else:
            total_p += delta
    rows.sort(key=lambda r: (r["tanggal"] or date.min, r["jam"], r["id"]), reverse=True)

    total_h_out, total_p_out, manual = _overlay_total_bulanan(
        toko, dari, sampai, total_h, total_p)

    return {
        "rows": rows,
        "total_hutang": total_h_out,
        "total_piutang": total_p_out,
        "netto": total_h_out + total_p_out,
        "count": len(rows),
        "manual": manual,
        # Total mentah FR (pra-overlay) — berguna UI admin & tes.
        "total_hutang_auto": total_h,
        "total_piutang_auto": total_p,
        "netto_auto": total_h + total_p,
    }


def periode_bulan(d):
    """Tanggal 1 bulan dari sebuah date (atau None)."""
    if d is None:
        return None
    return date(d.year, d.month, 1)


def akhir_bulan(d):
    """Hari terakhir bulan dari sebuah date."""
    return date(d.year, d.month, monthrange(d.year, d.month)[1])
