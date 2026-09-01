"""Rincian Biaya admin — rekap fee bank per kanal, query-time & retroaktif.

Baris fee = `jenis="admin"` TERSIMPAN (parser era baru) ATAU cocok aturan
`is_admin_fee` saat baca (baris legacy ter-ingest sebelum aturannya lahir —
dedup membuat re-upload tak menandai ulang, jadi laporan yang menutupnya).
Kanal dari tarif tetap klien: 1.000 e-wallet · 2.500 BI Fast · 6.500 online.

BIAYA HALAMAN — kenapa berbentuk seperti ini
--------------------------------------------
Halaman ini pernah 2,4 dtk untuk rentang 30 hari, dan 2,26 dtk di antaranya
PYTHON, bukan SQL. Sebabnya dua, keduanya diperbaiki di sini:

1. **Kolom `raw` (JSONB besar) ikut terbaca padahal tak sekalipun dipakai.**
   Setiap baris di-detoast lalu di-`json.loads` oleh Django. Karena itu query
   ini memakai `.values()` berisi PERSIS kolom yang dibaca — `raw` tak pernah
   masuk daftar. Jangan menambahkannya "untuk berjaga-jaga".
2. **Seluruh mutasi keluar ditarik ke Python lalu 99%-nya dibuang.** Sekarang
   ada `PRAFILTER_FEE`: penyaring SQL yang merupakan **superset** aturan
   `is_admin_fee`, bukan penggantinya. Keputusan akhir tetap `is_admin_fee` di
   Python — prafilter hanya boleh salah dengan cara MELOLOSKAN baris yang lalu
   ditolak Python, tak pernah dengan membuang baris yang seharusnya masuk.

`PRAFILTER_FEE` **terkopel** ke `sources/parsers/fee_rules.is_admin_fee`:
menambah pola deskripsi baru di sana tanpa melebarkan prafilter di sini
membuat baris itu hilang dari laporan tanpa error. `web/tests_biaya.py`
menjaga sifat superset itu lewat tes properti — kalau tes itu merah, yang
salah adalah prafilter, bukan tesnya.

Sengaja `icontains`, bukan `Trim` + `istartswith`: `is_admin_fee` memakai
`str.strip()` Python yang membuang SEMUA whitespace (tab, newline), sedangkan
`TRIM()` SQL hanya spasi — deskripsi berawalan tab akan lolos Python tapi
tersaring SQL. `icontains` kebal terhadap seluruh kelas selisih itu.
"""
from datetime import date
from decimal import Decimal

from django.db.models import Q

from sources.models import Account, SourceType, Upload
from sources.parsers.fee_rules import is_admin_fee
from transactions.models import Transaction, provider_from_filename

NOL = Decimal("0")

_KANAL = {
    Decimal("1000"): "E-wallet",
    Decimal("2500"): "BI Fast",
    Decimal("6500"): "Transfer online",
}

# Superset SQL dari `is_admin_fee` (lihat docstring modul). Tiap cabang aturan
# terwakili: mandiri "BIAYA…" & BCA "…BIAYA TXN…" oleh satu `BIAYA`, BRI oleh
# tiga awalannya. Baris `jenis="admin"` lolos tanpa melihat deskripsi — persis
# seperti kode lama, termasuk baris berdeskripsi kosong/NULL.
PRAFILTER_FEE = (
    Q(jenis="admin")
    | Q(description__icontains="BIAYA")
    | Q(description__icontains="ATMSTRPRM")
    | Q(description__icontains="BFST")
    | Q(description__icontains="BRIVA")
)

_KOLOM = ("posted_date", "jenis", "description", "amount",
          "source_type_id", "account_id", "upload_id")


def _kanal(amount):
    return _KANAL.get(amount, "Lainnya")


def rincian_biaya(toko, dari=None, sampai=None):
    qs = Transaction.objects.filter(
        toko=toko, source_type__key="bank", money_delta__lt=0)
    if dari:
        qs = qs.filter(posted_date__gte=dari)
    if sampai:
        qs = qs.filter(posted_date__lte=sampai)

    baris = list(qs.filter(PRAFILTER_FEE).values(*_KOLOM))

    # Objek relasi diambil BORONGAN sesudah penyaringan: jumlah kombinasi di
    # sini ratusan, jumlah baris puluhan ribu, jadi `select_related` (yang ikut
    # menyeret setiap kolom relasi untuk SETIAP baris) adalah pilihan yang
    # salah. Tiga query tetap, tak bergantung jumlah baris.
    st_map = SourceType.objects.in_bulk(
        {r["source_type_id"] for r in baris if r["source_type_id"]})
    acc_map = Account.objects.in_bulk(
        {r["account_id"] for r in baris if r["account_id"]})
    up_map = Upload.objects.select_related("account").in_bulk(
        {r["upload_id"] for r in baris if r["upload_id"]})

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

    def label_baris(r):
        k = (r["source_type_id"], r["account_id"], r["upload_id"])
        if k not in _label:
            # Instance TAK TERSIMPAN semata-mata sebagai pembawa properti:
            # `source_label_full` tetap satu-satunya definisi label, jadi
            # aturannya mustahil menyimpang dari halaman lain. Dibuat per
            # KOMBINASI, bukan per baris.
            semu = Transaction(
                source_type=st_map.get(k[0]),
                account=acc_map.get(k[1]) if k[1] else None,
                upload=up_map.get(k[2]) if k[2] else None,
            )
            _label[k] = semu.source_label_full
        return _label[k]

    def bank_baris(r):
        # nama file cuma milik upload → kunci cukup upload_id
        uid = r["upload_id"]
        if uid not in _provider:
            up = up_map.get(uid) if uid else None
            _provider[uid] = provider_from_filename(
                up.original_name if up else "").lower()
        return _provider[uid]

    per = {}   # (tanggal, sumber) → {n, total, kanal:{}}
    ringkas = {"n": 0, "total": NOL, "kanal": {}}
    for r in baris:
        amount = r["amount"]
        if r["jenis"] != "admin":
            if not is_admin_fee(bank_baris(r), r["description"], amount):
                continue
        kanal = _kanal(amount)
        kunci = (r["posted_date"], label_baris(r))
        slot = per.setdefault(kunci, {"n": 0, "total": NOL, "kanal": {}})
        slot["n"] += 1
        slot["total"] += amount
        k = slot["kanal"].setdefault(kanal, {"n": 0, "total": NOL})
        k["n"] += 1
        k["total"] += amount
        ringkas["n"] += 1
        ringkas["total"] += amount
        rk = ringkas["kanal"].setdefault(kanal, {"n": 0, "total": NOL})
        rk["n"] += 1
        rk["total"] += amount

    rows = [
        {"tanggal": tgl, "sumber": sumber, **slot}
        for (tgl, sumber), slot in per.items()
    ]
    # tanggal None aman (date.min), terbaru dulu — pelajaran sort hutang.py
    rows.sort(key=lambda r: (r["tanggal"] or date.min, r["sumber"]), reverse=True)
    return {"rows": rows, "ringkas": ringkas}
