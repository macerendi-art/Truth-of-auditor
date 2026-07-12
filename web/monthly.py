"""Ringkasan Bulanan — rekap batch harian satu toko dalam satu bulan.

Angka diambil apa adanya dari `ReconBatch.summary` (yang dihitung engine saat
run) — TIDAK menghitung ulang, jadi tiap baris identik dengan halaman batch
hariannya. `selisih` = versi MATCHED (panel − uang berpasangan), konsisten
dengan kartu batch.
"""
from reconciliation.models import ReconBatch


def _num(d, *keys):
    """Ambil angka bersarang dari dict summary; None/hilang → 0."""
    for k in keys:
        d = (d or {}).get(k)
    return d or 0


def _row(batch):
    s = batch.summary or {}
    dp, wd, buckets = s.get("dp") or {}, s.get("wd") or {}, s.get("buckets") or {}
    return {
        "date": batch.recon_date,
        "batch_id": batch.id,
        "dp_panel": _num(dp, "panel"),
        "dp_gross": _num(dp, "money_gross"),
        "dp_selisih": _num(dp, "selisih"),
        "wd_panel": _num(wd, "panel"),
        "wd_gross": _num(wd, "money_gross"),
        "wd_selisih": _num(wd, "selisih"),
        "cocok": _num(buckets, "cocok"),
        "tinjau": _num(buckets, "perlu_tinjau"),
        "tidak": _num(buckets, "tidak_cocok"),
    }


_SUM_KEYS = (
    "dp_panel", "dp_gross", "dp_selisih", "wd_panel", "wd_gross", "wd_selisih",
    "cocok", "tinjau", "tidak",
)


def monthly_summary(toko, year, month):
    """{"rows": [per tanggal, menaik], "total": agregat bulan}."""
    batches = (
        ReconBatch.objects.filter(
            toko=toko, recon_date__isnull=False,
            recon_date__year=year, recon_date__month=month,
        )
        .order_by("recon_date")
    )
    rows = [_row(b) for b in batches]
    total = {k: 0 for k in _SUM_KEYS}
    for r in rows:
        for k in _SUM_KEYS:
            total[k] += r[k]
    return {"rows": rows, "total": total}
