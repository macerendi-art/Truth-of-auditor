"""Kunci kontrak index komposit `Transaction` ↔ DDL manual di produksi.

Index besar dibangun lewat psql (`CREATE INDEX CONCURRENTLY`) SEBELUM deploy,
memakai nama dan urutan kolom yang tertulis di runbook. Kalau model dan runbook
berbeda, Postgres akan punya index yang tak pernah dipakai planner sementara
migrasi diam-diam membangun index kedua yang mengunci tabel. Tes ini membuat
perbedaan itu merah di lokal, jauh sebelum produksi.
"""

from io import StringIO

from django.core.management import call_command
from django.db import connection, models
from django.test import SimpleTestCase, TestCase

from transactions.models import Transaction


def _index_ddl(name):
    """DDL `CREATE INDEX` mentah dari katalog — `get_constraints` lintas-vendor
    Django tidak mengekspos predikat `WHERE` index parsial, jadi predikatnya
    hanya bisa dibuktikan lewat katalog asli tiap vendor."""
    with connection.cursor() as cursor:
        if connection.vendor == "sqlite":
            cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name=%s", [name]
            )
        elif connection.vendor == "postgresql":
            cursor.execute("SELECT indexdef FROM pg_indexes WHERE indexname=%s", [name])
        else:
            return None
        row = cursor.fetchone()
    return row[0] if row else None


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


class IndexUsernameReferenceDibuangTests(TestCase):
    """G5 (04-09-2026): `username`/`reference` TANPA index — 719 MB dibuang.

    Satu-satunya pemakaian dua kolom ini sebagai KUERI di seluruh basis kode
    adalah `icontains` (`web/views.py::transactions`, `search_fields` di
    `transactions/admin.py` tanpa awalan `^`), yang tak pernah dilayani btree
    biasa maupun `_like`. `reconciliation/engine.py` memakainya sebagai kunci
    JOIN tapi selalu di atas list Python yang sudah dimuat (`sides()`), tak
    pernah lewat `.filter(username=...)`/`.filter(reference=...)` queryset.
    Lihat migrasi 0011 untuk penyisiran lengkapnya.

    Tes ini gagal SEBELUM migrasi 0011 (index masih ada di skema) dan lulus
    SESUDAHNYA — bukan cuma memeriksa `Meta`, tapi skema DB NYATA lewat
    introspeksi, supaya migrasi yang lupa dijalankan/lupa ditulis juga
    tertangkap (`MigrasiTertinggalTests` di bawah menjaga sisi migrasinya).
    """

    def _kolom_terindeks(self, kolom):
        """{indeks yang HANYA menyentuh satu `kolom`} dari skema DB nyata."""
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(
                cursor, Transaction._meta.db_table
            )
        return {
            nama for nama, info in constraints.items()
            if info.get("index") and info.get("columns") == [kolom]
        }

    def test_username_tidak_lagi_berindeks_di_skema(self):
        self.assertEqual(self._kolom_terindeks("username"), set())

    def test_reference_tidak_lagi_berindeks_di_skema(self):
        self.assertEqual(self._kolom_terindeks("reference"), set())

    def test_field_db_index_false(self):
        self.assertFalse(Transaction._meta.get_field("username").db_index)
        self.assertFalse(Transaction._meta.get_field("reference").db_index)

    def test_ticket_no_tetap_berindeks(self):
        """Guard: migrasi ini TIDAK boleh ikut membuang index `ticket_no`."""
        self.assertTrue(Transaction._meta.get_field("ticket_no").db_index)
        self.assertNotEqual(self._kolom_terindeks("ticket_no"), set())


class D4IndexAktifTests(TestCase):
    """D4 — `tx_aktif_toko_src_jenis_idx` (migrasi 0009), pemakai
    `reconciliation/engine.py::check_completeness` (5x EXISTS per render).

    Index ini SUDAH ADA sebelum tugas D4 ("3c") ditulis — bukan hasil tugas
    ini. Backlog CLAUDE.md v1.18.0 "partial index untuk 5x EXISTS" sudah
    STALE: migrasi 0009 mengukurnya di data produksi (336 ms -> 0,11 ms,
    jadi Index Only Scan) dan sudah ter-commit sebelum brief 3c ditulis. Tak
    satu pun index 0008-0011 (kecuali dua `tx_toko_src_*` lama) dikunci tes
    sebelum ini — tes ini menutup celah itu untuk index D4 secara spesifik.
    """

    def test_meta_index_kolom_dan_kondisi(self):
        idx = {i.name: i for i in Transaction._meta.indexes}
        self.assertIn("tx_aktif_toko_src_jenis_idx", idx)
        i = idx["tx_aktif_toko_src_jenis_idx"]
        self.assertEqual(list(i.fields), ["toko", "source_type", "jenis"])
        self.assertEqual(
            i.condition,
            models.Q(consumed_by_batch__isnull=True, is_duplicate=False),
        )

    def test_skema_nyata_kolom_benar(self):
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(
                cursor, Transaction._meta.db_table
            )
        self.assertIn("tx_aktif_toko_src_jenis_idx", constraints)
        self.assertEqual(
            constraints["tx_aktif_toko_src_jenis_idx"]["columns"],
            ["toko_id", "source_type_id", "jenis"],
        )

    def test_skema_nyata_predikat_ada(self):
        """DDL asli WAJIB mengandung predikat WHERE — bukan cuma tiga kolom
        biasa. Tanpa predikat ini, index-nya BUKAN yang diukur 336ms->0,11ms
        di docstring 0009 (index penuh atas tiga kolom itu jauh lebih besar
        dan tidak jadi Index Only Scan dengan cara yang sama)."""
        sql = _index_ddl("tx_aktif_toko_src_jenis_idx")
        self.assertIsNotNone(sql)
        self.assertIn("WHERE", sql.upper())
        self.assertIn("consumed_by_batch_id", sql)
        self.assertIn("is_duplicate", sql)


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
