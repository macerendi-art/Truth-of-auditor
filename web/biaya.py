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

    # --- Memo label, HIDUP HANYA SELAMA PANGGILAN INI (jangan pernah global:
    # aplikasi keuangan, label harus ikut data terbaru tiap request). Halaman ini
    # menyentuh puluhan ribu baris tapi hanya ratusan upload; `source_label_full`
    # dan `provider_from_filename` sama-sama FUNGSI MURNI dari kunci di bawah,
    # jadi menghitungnya sekali per kombinasi = hasil identik, kerja jauh sedikit.
    #
    # Kuncinya BERTIGA (source_type, account, upload) karena ketiganya menentukan
    # label: `source_type` memilih jalur bank/gateway vs generik, `account.provider`
    # MENANG atas provider upload, dan upload menyumbang provider + nama file +
    # `owner_name`. Kalau kuncinya kurang — misalnya hanya `upload_id` — dua baris
    # dengan rekening berbeda dari satu file akan diberi label yang sama, dan di
    # laporan biaya itu berarti biaya bank tercatat di REKENING YANG SALAH.
    _label = {}    # (source_type_id, account_id, upload_id) → label sumber
    _provider = {}  # upload_id → token bank dari nama file (lower)

    def label_baris(t):
        k = (t.source_type_id, t.account_id, t.upload_id)
        if k not in _label:
            _label[k] = t.source_label_full
        return _label[k]

    def bank_baris(t):
        # nama file cuma milik upload → kunci cukup upload_id
        if t.upload_id not in _provider:
            _provider[t.upload_id] = provider_from_filename(
                t.upload.original_name if t.upload_id else "").lower()
        return _provider[t.upload_id]

    per = {}   # (tanggal, sumber) → {n, total, kanal:{}}
    ringkas = {"n": 0, "total": NOL, "kanal": {}}
    for t in qs.iterator():
        if t.jenis != "admin":
            if not is_admin_fee(bank_baris(t), t.description, t.amount):
                continue
        kanal = _kanal(t.amount)
        kunci = (t.posted_date, label_baris(t))
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
