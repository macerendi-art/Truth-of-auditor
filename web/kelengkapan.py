"""Status tiap sumber di kartu Kelengkapan Data — TAMPILAN saja.

`check_completeness` di engine menjawab satu pertanyaan: adakah baris AKTIF
untuk sumber ini? Jawabannya boolean, dan itu memang yang dibutuhkan mesin.
Untuk manusia, satu "tidak" itu menutupi tiga keadaan yang artinya jauh berbeda:

* filenya belum diupload,
* filenya sudah diupload dan barisnya sudah habis dipakai batch sebelumnya,
* sumber itu memang tak dipakai toko ini.

Keduanya tampil identik — abu-abu bertulis "opsional". Pada 6 Agustus 2026
seorang pemakai W25 menyimpulkan gateway UNOPAY "tidak terbaca" padahal 9.586
barisnya sudah masuk Batch #27; yang ia lihat cuma abu-abu itu. Modul ini
menyediakan angka yang membedakannya, TANPA menyentuh `check_completeness`
(nilainya ikut tersimpan di `ReconBatch.completeness` — bentuknya kontrak).

Biayanya tetap 3 query berapa pun jumlah sumbernya.
"""
from django.db.models import Count, Max

from reconciliation.engine import _date_filter, _toko_filter
from reconciliation.models import ReconBatch
from transactions.models import Transaction

#: Kunci kartu -> penyaring barisnya. Urutan & nama kunci mengikuti
#: `check_completeness` supaya keduanya tak pernah bicara soal hal berbeda.
SUMBER = {
    "panel_dp": ("panel", "depo"),
    "panel_wd": ("panel", "wd"),
    "bracket": ("bracket", None),
    "bank": ("bank", None),
    "gateway": ("gateway", None),
}


def _peta(qs, tambahan=None):
    nilai = qs.values("source_type__key", "jenis").annotate(n=Count("id"), **(tambahan or {}))
    return {(r["source_type__key"], r["jenis"]): r for r in nilai}


def status_sumber(toko, dari=None, sampai=None):
    """Per kunci sumber: berapa baris masih aktif, berapa sudah dipakai batch,
    dan batch terakhir yang memakainya (objek + nomor urut per-toko).

    Batch tanpa `recon_date` tetap dihitung — nomor urutnya ada, tanggalnya saja
    yang kosong; template menampilkan apa yang tersedia.
    """
    basis = _date_filter(
        _toko_filter(Transaction.objects.filter(is_duplicate=False), toko), dari, sampai
    )
    aktif = _peta(basis.filter(consumed_by_batch__isnull=True))
    terpakai = _peta(
        basis.filter(consumed_by_batch__isnull=False), {"batch": Max("consumed_by_batch")}
    )

    # Nomor urut batch per-toko = konvensi seluruh aplikasi (posisi menaik menurut id).
    urut, tanggal = {}, {}
    for i, (bid, tgl) in enumerate(
        ReconBatch.objects.filter(toko=toko).order_by("id").values_list("id", "recon_date"), 1
    ):
        urut[bid], tanggal[bid] = i, tgl

    hasil = {}
    for kunci, (sumber, jenis) in SUMBER.items():
        cocok = [
            (k, v) for k, v in aktif.items()
            if k[0] == sumber and (jenis is None or k[1] == jenis)
        ]
        n_aktif = sum(v["n"] for _, v in cocok)
        cocok_pakai = [
            (k, v) for k, v in terpakai.items()
            if k[0] == sumber and (jenis is None or k[1] == jenis)
        ]
        n_pakai = sum(v["n"] for _, v in cocok_pakai)
        bid = max((v["batch"] for _, v in cocok_pakai if v["batch"]), default=None)
        hasil[kunci] = {
            "aktif": n_aktif,
            "terpakai": n_pakai,
            "batch_no": urut.get(bid),
            "batch_tanggal": tanggal.get(bid),
        }
    return hasil
