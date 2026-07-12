"""Settlement Tertunda — baris kredit yang masih menunggu uangnya tiba (H+1).

Sumber kebenaran = `_carried_results(toko)` di engine (kriteria carry-over
persis yang dipakai rekonsiliasi harian). Untuk tiap baris dihitung:

- `umur`  = jarak hari dari tanggal kredit ke `reference` (frontier rekonsiliasi
            = recon_date batch terakhir toko; fallback hari ini)
- `batas` = tanggal kredit + window toleransi batch asal = run terakhir yang
            masih bisa men-settle baris ini (lihat `_can_still_settle`)
- `sisa`  = `batas − reference` (≤0 = harus segera dijalankan agar tidak
            kadaluarsa)
"""
from datetime import date as date_cls, timedelta

from reconciliation.engine import _carried_results
from reconciliation.models import ReconBatch


def _reference(toko):
    return ReconBatch.objects.filter(
        toko=toko, recon_date__isnull=False
    ).order_by("-recon_date").values_list("recon_date", flat=True).first() or date_cls.today()


def pending_settlement_rows(toko, reference=None):
    """List baris menunggu settlement, urut TERTUA dulu."""
    if reference is None:
        reference = _reference(toko)
    rows = []
    for tx_id, res in _carried_results(toko).items():
        tx = res.left
        home = res.run.batch
        window = home.tolerance.date_window_days if home and home.tolerance_id else 1
        d = tx.occurred_at.date() if tx.occurred_at else None
        batas = (d + timedelta(days=window)) if d else None
        rows.append({
            "tx_id": tx_id,
            "tanggal": d,
            "ticket": tx.ticket_no,
            "username": tx.username,
            "player_bank": tx.player_bank or tx.counterparty,
            "nominal": tx.amount,
            "jenis": tx.jenis,
            "umur": (reference - d).days if d else None,
            "batas": batas,
            "sisa": (batas - reference).days if batas else None,
            "home_batch_id": home.id if home else None,
            "home_date": home.recon_date if home else None,
        })
    rows.sort(key=lambda r: (r["tanggal"] or date_cls.max, r["tx_id"]))
    return rows
