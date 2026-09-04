"""Kunci kontrak index komposit `Transaction` ↔ DDL manual di produksi.

Index besar dibangun lewat psql (`CREATE INDEX CONCURRENTLY`) SEBELUM deploy,
memakai nama dan urutan kolom yang tertulis di runbook. Kalau model dan runbook
berbeda, Postgres akan punya index yang tak pernah dipakai planner sementara
migrasi diam-diam membangun index kedua yang mengunci tabel. Tes ini membuat
perbedaan itu merah di lokal, jauh sebelum produksi.
"""

from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase

from transactions.models import Transaction


class IndexKomposisiTests(SimpleTestCase):
    def test_nama_dan_urutan_kolom_index_terkunci(self):
        punya = {
            i.name: list(i.fields)
            for i in Transaction._meta.indexes
            if i.name.startswith("tx_toko_src_")
        }
        self.assertEqual(
            punya,
            {
                # Urutan kolom disengaja: toko & source_type selalu dipakai
                # sebagai kesetaraan, tanggal sebagai RENTANG di posisi akhir.
                "tx_toko_src_posted_idx": ["toko", "source_type", "posted_date"],
                "tx_toko_src_occurred_idx": ["toko", "source_type", "occurred_at"],
            },
        )


class MigrasiTertinggalTests(SimpleTestCase):
    # `makemigrations` membaca tabel django_migrations (check_consistent_history).
    databases = {"default"}

    def test_tidak_ada_migrasi_tertinggal(self):
        """`makemigrations --check` harus bersih.

        Perubahan `Meta.indexes` tanpa migrasi pasangannya lolos semua tes lain
        (model state saja yang berubah) tapi meledak saat deploy berikutnya.
        """
        keluaran = StringIO()
        try:
            call_command(
                "makemigrations", "--check", "--dry-run", verbosity=1, stdout=keluaran
            )
        except SystemExit:  # --check keluar dengan status non-nol bila ada beda
            self.fail(
                "Ada perubahan model tanpa migrasi:\n" + keluaran.getvalue()
            )
