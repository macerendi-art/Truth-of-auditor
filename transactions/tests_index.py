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
from django.test.utils import CaptureQueriesContext

from sources.models import SourceType, Toko
from transactions.models import Transaction

# `web.hutang` di-import HANYA di tes (bukan di models.py) — bukti bahwa
# predikat index `tx_hutang_piutang_idx` (D2, di bawah) benar-benar
# byte-per-byte sama dengan filter kategori yang dipakai halaman
# `/hutang-piutang/` hari ini. Arah impor ini "terbalik" dari konvensi app
# biasa (transactions lebih rendah dari web) — sengaja, khusus tes ini,
# karena satu-satunya cara membuktikan dua sisi kode yang TIDAK saling
# mengimpor konstanta yang sama tetap identik adalah menjalankan keduanya
# dan membandingkan SQL asli.
from web.hutang import hutang_piutang


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


class D2KategoriIndexTests(TestCase):
    """Eskalasi D2 — index parsial `tx_hutang_piutang_idx` (migrasi 0012).

    Predikatnya (`raw->>'Kategori' ~* '^\\s*(hutang|piutang)\\s*$'`) HARUS
    identik byte-per-byte dengan filter kategori `web/hutang.py::
    hutang_piutang` (`KeyTextTransform("Kategori","raw").iregex`) — Postgres
    membuktikan kecocokan index parsial lewat `predicate_implied_by`, sebuah
    pembanding STRUKTURAL, bukan semantik. Satu karakter melenceng (spasi,
    escape, flag) berarti index diam-diam TIDAK PERNAH dipakai planner,
    tanpa error apa pun yang kelihatan. Tes ini menjalankan `hutang_piutang`
    SUNGGUHAN, menangkap SQL aslinya, dan membandingkan fragmen WHERE
    kategorinya dengan kompilasi kondisi index milik model — drift di SALAH
    SATU sisi (`transactions/models.py` atau `web/hutang.py`) memerahkan
    tes ini.
    """

    def setUp(self):
        self.toko = Toko.objects.create(key="tst-d2kat", name="Test D2 Kategori")
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"}
        )[0]

    def _index(self):
        return next(
            i for i in Transaction._meta.indexes if i.name == "tx_hutang_piutang_idx"
        )

    def _fragmen_kondisi_index(self):
        """Kompilasi kondisi index (`condition=Q(...)`) jadi teks SQL NYATA
        yang benar-benar dieksekusi (bukan `str(qs.query)` — representasi
        debug Django itu TIDAK selalu mengutip literal string dengan benar,
        beda dari SQL asli yang dikirim ke DB-API). Fragmen WHERE-nya HARUS
        jadi satu-satunya isi (tak ada filter lain di queryset ini)."""
        with CaptureQueriesContext(connection) as ctx:
            # `.values("pk")` (bukan `.exists()`) — TIDAK menambah `LIMIT 1`
            # yang akan ikut tertangkap sebagai bagian fragmen WHERE.
            list(Transaction.objects.filter(self._index().condition).values("pk"))
        sql = ctx.captured_queries[0]["sql"]
        return sql.split(" WHERE ", 1)[1]

    def test_index_ada_di_skema_dengan_kolom_benar(self):
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(
                cursor, Transaction._meta.db_table
            )
        self.assertIn("tx_hutang_piutang_idx", constraints)
        self.assertEqual(
            constraints["tx_hutang_piutang_idx"]["columns"],
            ["toko_id", "source_type_id", "posted_date"],
        )

    def test_skema_nyata_predikat_regex_ada(self):
        sql = _index_ddl("tx_hutang_piutang_idx")
        self.assertIsNotNone(sql)
        self.assertIn("WHERE", sql.upper())
        self.assertIn("hutang", sql.lower())
        self.assertIn("piutang", sql.lower())

    def test_predikat_index_identik_dengan_filter_hutang_piutang_asli(self):
        """Bukti nol-drift: panggil `hutang_piutang()` SUNGGUHAN (bukan
        salinan pola query), tangkap SQL fase-1-nya, dan pastikan fragmen
        kategori index ini muncul VERBATIM di dalamnya."""
        fragmen_index = self._fragmen_kondisi_index()
        with CaptureQueriesContext(connection) as ctx:
            hutang_piutang(self.toko)
        self.assertEqual(len(ctx.captured_queries), 1)
        sql_asli = ctx.captured_queries[0]["sql"]
        self.assertIn(fragmen_index, sql_asli)

    def test_predikat_tidak_menambah_is_duplicate(self):
        """`hutang_piutang()` TIDAK menyaring `is_duplicate` sama sekali —
        predikat index ini TIDAK BOLEH menambahnya (beda dari D4): syarat
        ekstra membuat index lebih sempit dari query, `predicate_implied_by`
        gagal membuktikan implikasi, dan index tak akan pernah dipakai."""
        self.assertNotIn("is_duplicate", self._fragmen_kondisi_index())


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
