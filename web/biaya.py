"""Rincian Biaya admin — rekap fee bank per kanal, query-time & retroaktif.

Baris fee = `jenis="admin"` TERSIMPAN (parser era baru) ATAU cocok aturan
`is_admin_fee` saat baca (baris legacy ter-ingest sebelum aturannya lahir —
dedup membuat re-upload tak menandai ulang, jadi laporan yang menutupnya).
Kanal dari tarif tetap klien: 1.000 e-wallet · 2.500 BI Fast · 6.500 online.
"""
from datetime import date
from decimal import Decimal

from sources.parsers.fee_rules import is_admin_fee
from transactions.models import Transaction, provider_from_filename

NOL = Decimal("0")

_KANAL = {
    Decimal("1000"): "E-wallet",
    Decimal("2500"): "BI Fast",
    Decimal("6500"): "Transfer online",
}


def _kanal(amount):
    return _KANAL.get(amount, "Lainnya")


def rincian_biaya(toko, dari=None, sampai=None):
    qs = (
        Transaction.objects.filter(
            toko=toko, source_type__key="bank", money_delta__lt=0)
        .select_related("upload", "account", "source_type", "upload__account")
    )
    if dari:
        qs = qs.filter(posted_date__gte=dari)
    if sampai:
        qs = qs.filter(posted_date__lte=sampai)

    per = {}   # (tanggal, sumber) → {n, total, kanal:{}}
    ringkas = {"n": 0, "total": NOL, "kanal": {}}
    for t in qs.iterator():
        if t.jenis != "admin":
            bank = provider_from_filename(
                t.upload.original_name if t.upload_id else "").lower()
            if not is_admin_fee(bank, t.description, t.amount):
                continue
        kanal = _kanal(t.amount)
        kunci = (t.posted_date, t.source_label_full)
        slot = per.setdefault(kunci, {"n": 0, "total": NOL, "kanal": {}})
        slot["n"] += 1
        slot["total"] += t.amount
        k = slot["kanal"].setdefault(kanal, {"n": 0, "total": NOL})
        k["n"] += 1
        k["total"] += t.amount
        ringkas["n"] += 1
        ringkas["total"] += t.amount
        rk = ringkas["kanal"].setdefault(kanal, {"n": 0, "total": NOL})
        rk["n"] += 1
        rk["total"] += t.amount

    rows = [
        {"tanggal": tgl, "sumber": sumber, **slot}
        for (tgl, sumber), slot in per.items()
    ]
    # tanggal None aman (date.min), terbaru dulu — pelajaran sort hutang.py
    rows.sort(key=lambda r: (r["tanggal"] or date.min, r["sumber"]), reverse=True)
    return {"rows": rows, "ringkas": ringkas}
