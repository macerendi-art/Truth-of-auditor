"""Dua index komposit performa untuk `Transaction`.

`atomic = False` + `TambahIndexAman`: di produksi index dibangun lebih dulu
manual lewat psql (CREATE INDEX CONCURRENTLY, tabel 6,1 juta baris), jadi
migrasi ini normalnya no-op yang tidak menahan boot; di SQLite (tes & dev) ia
turun ke `AddIndex` biasa. Lihat core/db_ops.py untuk alasan lengkapnya.
"""

from django.db import migrations, models

from core.db_ops import TambahIndexAman


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("transactions", "0007_transaction_uniq_tx_source_rowhash_toko_null"),
    ]

    operations = [
        TambahIndexAman(
            model_name="transaction",
            index=models.Index(
                fields=["toko", "source_type", "posted_date"],
                name="tx_toko_src_posted_idx",
            ),
        ),
        TambahIndexAman(
            model_name="transaction",
            index=models.Index(
                fields=["toko", "source_type", "occurred_at"],
                name="tx_toko_src_occurred_idx",
            ),
        ),
    ]
