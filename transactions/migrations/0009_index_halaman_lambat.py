"""Tiga index dari profil halaman lambat pada data produksi (01-09-2026).

Diukur di VPS berisi salinan penuh produksi (8,85 juta baris), bukan
diperkirakan. Angka per query, cache panas:

    tx_toko_upload_id_idx        7.624 ms -> 18,5 ms   (buffer 2,12 jt -> 6,4 rb)
    tx_aktif_toko_src_jenis_idx    336 ms -> 0,11 ms   (jadi Index Only Scan)
    tx_toko_occurred_idx         1.578 ms -> 0,19 ms

Efek di tingkat halaman (dingin), tiga toko yang dikeluhkan operator:

    k25 /mutasi-bank/   44,6 dtk -> 3,3      g25 /mutasi-bank/  12,9 -> 6,3
    mxw / (dashboard)   24,9 dtk -> 1,4      g25 /bracket/      12,8 -> 2,7
    mxw /transactions/   7,6 dtk -> 0,85

`atomic = False` + `TambahIndexAman`: di produksi index dibangun lebih dulu
lewat psql (CREATE INDEX CONCURRENTLY) supaya migrasi tidak menahan boot;
di SQLite (tes & dev) turun ke AddIndex biasa. Lihat core/db_ops.py.

Biaya tulis: tiga index tambahan pada tabel yang menerima ~185 rb baris/hari.
Yang parsial nyaris gratis (hanya baris aktif). Dua lainnya berukuran wajar
karena berkolom sempit. Setelah deploy: `manage.py periksa_index`.
"""

from django.db import migrations, models

from core.db_ops import TambahIndexAman


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("transactions", "0008_index_performa"),
    ]

    operations = [
        TambahIndexAman(
            model_name="transaction",
            index=models.Index(
                fields=["toko", "upload", "id"],
                name="tx_toko_upload_id_idx",
            ),
        ),
        TambahIndexAman(
            model_name="transaction",
            index=models.Index(
                fields=["toko", "source_type", "jenis"],
                name="tx_aktif_toko_src_jenis_idx",
                condition=models.Q(consumed_by_batch__isnull=True, is_duplicate=False),
            ),
        ),
        TambahIndexAman(
            model_name="transaction",
            index=models.Index(
                fields=["toko", "occurred_at"],
                name="tx_toko_occurred_idx",
            ),
        ),
    ]
