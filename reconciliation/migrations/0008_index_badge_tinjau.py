"""Index parsial untuk badge "Perlu Ditinjau" di sidebar.

`web/context_processors.py` menghitung antrean tinjau pada SETIAP render
halaman, untuk setiap pengguna. Pada 5,5 juta baris MatchResult, hitungan itu
menempuh tiga join dan memindai ratusan ribu baris untuk menghasilkan angka
yang isinya ratusan — terukur di VPS berisi salinan produksi:

    COUNT badge sidebar   360,5 ms -> 1,76 ms   (buffer 13.571 -> 476)

Efek halaman: /tinjau/ mxw 1,27 -> 0,24 detik. Yang paling terasa justru
halaman-halaman RINGAN, karena merekalah yang selama ini membayar 360 ms
untuk sesuatu yang tak ada hubungannya dengan isi halamannya.

Index sengaja PARSIAL: baris `perlu_tinjau` hanya ±0,02% dari tabel (968 dari
5.509.226 saat diukur), sehingga ukurannya puluhan kilobyte dan hitungannya
menjadi Index Only Scan.

`atomic = False` + `TambahIndexAman` mengikuti konvensi repo: di produksi
index dibangun lebih dulu lewat psql (CREATE INDEX CONCURRENTLY), di SQLite
turun ke AddIndex biasa. Lihat core/db_ops.py.
"""

from django.db import migrations, models

from core.db_ops import TambahIndexAman


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("reconciliation", "0007_alter_matchrun_relation_fr_bank"),
    ]

    operations = [
        TambahIndexAman(
            model_name="matchresult",
            index=models.Index(
                fields=["run"],
                name="mr_tinjau_run_idx",
                condition=models.Q(bucket="perlu_tinjau"),
            ),
        ),
    ]
