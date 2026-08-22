"""Hutang/Piutang — daftar baris FR berkategori hutang/piutang, query-time.

Pola sama `web/breakdown.py`: baca `Transaction.raw` bracket tanpa migrasi,
berlaku retroaktif untuk data lama. Read-only murni terhadap Transaction.

Overlay opsional: `web.models.HutangManual` menimpa **total per bulan**
untuk toko tunggal. Satu bulan atau lintas bulan: tiap bulan yang punya
override memakai nilai manual; bulan tanpa override memakai Σ FR auto.
Baris FR di tabel tetap mentah.
"""
from calendar import monthrange
from collections import defaultdict
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


def _bulan_dalam_rentang(dari, sampai):
    """Daftar tanggal-1 tiap bulan yang bersinggungan [dari, sampai]."""
    if not dari or not sampai or dari > sampai:
        return []
    cur = date(dari.year, dari.month, 1)
    end = date(sampai.year, sampai.month, 1)
    out = []
    while cur <= end:
        out.append(cur)
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return out


def _auto_per_bulan(rows):
    """Σ money_delta FR per (periode=tgl1, kategori) dari baris yang sudah difilter."""
    by = defaultdict(lambda: {"hutang": NOL, "piutang": NOL})
    for r in rows:
        t = r.get("tanggal")
        if not t:
            continue
        periode = date(t.year, t.month, 1)
        slug = r.get("kategori") or ""
        if slug == "hutang":
            by[periode]["hutang"] += r.get("nominal") or NOL
        elif slug == "piutang":
            by[periode]["piutang"] += r.get("nominal") or NOL
    return by


def _overlay_total_bulanan(toko, dari, sampai, total_h, total_p, rows):
    """Timpa total per bulan bila ada HutangManual (satu atau multi bulan).

    Multi-toko (list) tidak di-overlay — form tulis single-toko saja.
    Tanpa dari/sampai: tidak di-overlay (tak ada kunci bulan).

    Per bulan M dalam rentang:
      - ada override field → pakai nilai manual (total bulan, tidak di-prorata)
      - tidak ada → pakai Σ FR auto baris di bulan itu (sudah ter-clip filter)
    Total = jumlah kontribusi semua bulan.
    """
    kosong = {
        "hutang": None, "piutang": None, "aktif": False,
        "periode": None, "periodes": [],
        "asli_hutang": total_h, "asli_piutang": total_p,
        "bulan_override": [],
    }
    if toko is None or isinstance(toko, (list, tuple, set, frozenset)):
        return total_h, total_p, kosong
    if not dari or not sampai:
        return total_h, total_p, kosong

    from web.models import HutangManual

    bulan = _bulan_dalam_rentang(dari, sampai)
    if not bulan:
        return total_h, total_p, kosong

    manuals = list(
        HutangManual.objects
        .filter(toko=toko, periode__in=bulan)
        .select_related("dibuat_oleh")
    )
    if not manuals:
        meta = dict(kosong)
        meta["periode"] = bulan[0] if len(bulan) == 1 else None
        meta["periodes"] = bulan
        return total_h, total_p, meta

    by_manual = {}
    for m in manuals:
        by_manual[(m.periode, m.field)] = m

    auto_by = _auto_per_bulan(rows)
    out_h, out_p = NOL, NOL
    bulan_override = []
    # Meta field: pakai manual terbaru (periode terbesar) yang ter-apply — UI badge.
    h_meta_obj = None
    p_meta_obj = None

    for periode in bulan:
        ah = auto_by.get(periode, {}).get("hutang", NOL)
        ap = auto_by.get(periode, {}).get("piutang", NOL)
        mh = by_manual.get((periode, HutangManual.FIELD_HUTANG))
        mp = by_manual.get((periode, HutangManual.FIELD_PIUTANG))
        used = False
        if mh is not None:
            out_h += mh.nilai
            h_meta_obj = mh
            used = True
        else:
            out_h += ah
        if mp is not None:
            out_p += mp.nilai
            p_meta_obj = mp
            used = True
        else:
            out_p += ap
        if used:
            bulan_override.append(periode)

    return out_h, out_p, {
        "hutang": _meta_manual(h_meta_obj),
        "piutang": _meta_manual(p_meta_obj),
        "aktif": True,
        "periode": bulan_override[-1] if len(bulan_override) == 1 else None,
        "periodes": bulan,
        "asli_hutang": total_h,
        "asli_piutang": total_p,
        "bulan_override": bulan_override,
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

    Bila toko tunggal + ada `HutangManual` pada bulan dalam rentang,
    `total_hutang` / `total_piutang` / `netto` memakai nilai override per bulan
    (bulan lain tetap auto). Baris FR tidak diubah. Metadata di kunci `manual`.
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
        toko, dari, sampai, total_h, total_p, rows)

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
