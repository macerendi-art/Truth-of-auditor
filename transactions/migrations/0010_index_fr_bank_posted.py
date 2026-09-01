"""Index ekspresi `(toko, source_type, raw->>'Bank', posted_date)` untuk carry FR.

Untuk `web/breakdown.py::_saldo_carry`. Versi lama mengagregasi
`Max(posted_date)` per akun atas SELURUH sejarah bracket toko sebelum `dari`
— biayanya tumbuh linier dengan umur data (utang struktural: ±11-12 ms per
hari sejarah, selamanya). Versi baru memakai loose index scan rekursif
(WITH RECURSIVE): enumerasi akun distinct + MAX(posted_date) per akun, tiap
langkah = satu index seek di index ini → biaya O(#akun x log N), TIDAK lagi
bergantung umur data.

Diukur di VPS salinan penuh produksi (8,85 juta baris), toko g25, panas
(tercepat dari 3; bersama perombakan agregasi web/breakdown.py yang memakai
index ini — angka SEBELUM = kode lama tanpa index, SESUDAH = kode baru):

    _saldo_carry sejarah 15/30/52/82 hari:
        608,4 / 1.038,5 / 1.605,5 / 1.530,0 ms   (tumbuh dgn umur data)
     ->  126,2 /   347,1 /   397,7 /   380,1 ms  (datar thd umur; loose
         scan-nya sendiri 0,77 ms EXPLAIN ANALYZE — sisanya kerja
         per-hari-penutup: agregat per-hari + fallback akun ber-rantai-
         putus di hari itu, bukan fungsi umur data)
    /bracket/ fungsi 1 hari : 1,503 -> 0,458 dtk    HTTP: 1,755 -> 0,627
    /bracket/ fungsi 1 bulan: 6,185 -> 2,654 dtk    HTTP: 6,116 -> 2,499

Nol regresi dibuktikan di data yang sama: 148 kasus (3 toko x semua tanggal
1-hari +- koreksi, tiap bulan kalender, rentang penuh) — seluruh sel
akun x kategori + saldo awal/akhir + Selisih Kontrol byte-identik.

`atomic = False` + `TambahIndexAman`: di produksi index dibangun lebih dulu
lewat psql (CREATE INDEX CONCURRENTLY) supaya migrasi tidak menahan boot;
di SQLite (tes & dev) turun ke AddIndex biasa. Lihat core/db_ops.py.
DDL runbook (kompilasi Django di Postgres, + kata CONCURRENTLY):

    CREATE INDEX CONCURRENTLY "tx_fr_bank_posted_idx"
        ON "transactions_transaction"
        ("toko_id", "source_type_id", (("raw" ->> 'Bank')), "posted_date");

Setelah deploy: `manage.py periksa_index`.
"""

from django.db import migrations, models
from django.db.models.fields.json import KeyTextTransform

from core.db_ops import TambahIndexAman


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("transactions", "0009_index_halaman_lambat"),
    ]

    operations = [
        TambahIndexAman(
            model_name="transaction",
            index=models.Index(
                models.F("toko"),
                models.F("source_type"),
                KeyTextTransform("Bank", "raw"),
                models.F("posted_date"),
                name="tx_fr_bank_posted_idx",
            ),
        ),
    ]
