"""Penjaga `python manage.py periksa_index`.

Perintah ini adalah SATU-SATUNYA deteksi index hilang/invalid yang benar-benar
ada. `core/db_ops.TambahIndexAman` sengaja menelan kegagalannya jadi
`logger.warning`, dan karena `apply()` tak melempar, migrasinya tetap dicatat
selesai — tak ada boot berikutnya yang akan memperbaikinya sendiri. Jadi kalau
perintah ini diam-diam berhenti melapor, tak ada lapis kedua di belakangnya.

Fungsi `periksa` diuji tanpa DB (murni, pola sama dengan `web/penjaga.py`);
jalur Postgres diuji dengan koneksi palsu, karena suite ini berjalan di SQLite
dan `pg_index` memang tak ada di sana.
"""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from core.management.commands.periksa_index import periksa
from transactions.models import Transaction

WAJIB = ["tx_toko_src_posted_idx", "tx_toko_src_occurred_idx"]


class PeriksaMurniTests(SimpleTestCase):
    """Aturannya, tanpa DB dan tanpa Django."""

    def test_bersih(self):
        self.assertEqual(periksa(WAJIB, {n: True for n in WAJIB}), [])

    def test_index_hilang(self):
        temuan = periksa(WAJIB, {"tx_toko_src_posted_idx": True})
        self.assertEqual(
            temuan, [{"nama": "tx_toko_src_occurred_idx", "status": "hilang"}])

    def test_index_invalid(self):
        """ADA tapi `indisvalid = false` — planner mengabaikannya, jadi
        kueri tetap lambat. Dilaporkan "invalid", BUKAN "hilang": ia memang
        ada, dan namanya justru memblokir pembuatan ulang."""
        temuan = periksa(WAJIB, {"tx_toko_src_posted_idx": True,
                                 "tx_toko_src_occurred_idx": False})
        self.assertEqual(
            temuan, [{"nama": "tx_toko_src_occurred_idx", "status": "invalid"}])

    def test_invalid_di_luar_daftar_model_ikut_dilaporkan(self):
        """Index unique-constraint tak ada di `Meta.indexes`, tapi kalau ia
        invalid akibatnya sama saja — jadi validitas diperiksa untuk SELURUH
        index tabel, bukan hanya yang diwajibkan model."""
        temuan = periksa(WAJIB, {"tx_toko_src_posted_idx": True,
                                 "tx_toko_src_occurred_idx": True,
                                 "uniq_tx_source_toko_rowhash": False})
        self.assertEqual(
            temuan, [{"nama": "uniq_tx_source_toko_rowhash", "status": "invalid"}])

    def test_urutan_stabil(self):
        """Keluarannya dibandingkan antar-jalan (sebelum/sesudah perbaikan),
        jadi urutannya tak boleh mengikuti urutan dict katalog."""
        katalog = {"z_idx": False, "a_idx": False}
        self.assertEqual([t["nama"] for t in periksa(["m_idx"], katalog)],
                         ["a_idx", "m_idx", "z_idx"])

    def test_daftar_model_terbaca(self):
        """Kalau `Transaction._meta.indexes` berubah nama, tes di atas jadi
        fiksi. Ini yang menahannya tetap nyata."""
        nama = [i.name for i in Transaction._meta.indexes]
        for n in WAJIB:
            self.assertIn(n, nama)


class _KursorPalsu:
    def __init__(self, baris):
        self.baris = baris

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.sql, self.params = sql, params

    def fetchall(self):
        return self.baris


class _KoneksiPalsu:
    vendor = "postgresql"

    def __init__(self, baris):
        self.kursor = _KursorPalsu(baris)

    def cursor(self):
        return self.kursor


class PerintahTests(SimpleTestCase):
    MOD = "core.management.commands.periksa_index.connection"

    def jalankan(self, conn):
        out = StringIO()
        with patch(self.MOD, conn):
            call_command("periksa_index", stdout=out, stderr=out)
        return out.getvalue()

    def test_non_postgres_bilang_tidak_berlaku(self):
        """Di SQLite (tes & dev) perintah TIDAK boleh melapor "bersih" —
        itu jaminan palsu — dan tidak boleh galat."""
        out = StringIO()
        call_command("periksa_index", stdout=out)  # koneksi sqlite sungguhan
        teks = out.getvalue()
        self.assertIn("Tidak berlaku", teks)
        self.assertIn("sqlite", teks)
        self.assertNotIn("Bersih", teks)

    def test_semua_sehat_keluar_bersih(self):
        # katalog dibangun DARI model (bukan dari `WAJIB`): dua index
        # `Meta.indexes` dinamai otomatis oleh Django, dan mendaftarnya manual
        # akan membuat tes ini basi diam-diam begitu ada index baru.
        conn = _KoneksiPalsu(
            [(i.name, True) for i in Transaction._meta.indexes]
            + [("uniq_tx_source_toko_rowhash", True)]
        )
        teks = self.jalankan(conn)
        self.assertIn("Bersih", teks)
        # tabel yang diperiksa memang tabel Transaction
        self.assertEqual(conn.kursor.params, [Transaction._meta.db_table])

    def test_index_hilang_keluar_dengan_galat(self):
        """`CommandError` = keluar dengan kode ≠ 0. Itu inti perintah ini:
        bisa dipasang di runbook/CI dan gagal dengan sendirinya."""
        conn = _KoneksiPalsu([("tx_toko_src_posted_idx", True)])
        with self.assertRaises(CommandError) as cm:
            self.jalankan(conn)
        self.assertIn("index bermasalah", str(cm.exception))

    def test_index_invalid_keluar_dengan_galat_dan_perintah_pemulihan(self):
        conn = _KoneksiPalsu([("tx_toko_src_posted_idx", True),
                              ("tx_toko_src_occurred_idx", False)])
        out = StringIO()
        with patch(self.MOD, conn), self.assertRaises(CommandError):
            call_command("periksa_index", stdout=out, stderr=out)
        teks = out.getvalue()
        self.assertIn("INVALID", teks)
        # laporan tanpa jalan keluar cuma bikin panik
        self.assertIn("DROP INDEX CONCURRENTLY tx_toko_src_occurred_idx", teks)
