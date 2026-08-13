"""Penjaga operasi migrasi `TambahIndexAman`.

Tes terpenting di berkas ini adalah yang pertama: di SQLite (tes & dev) operasi
ini TIDAK BOLEH meneruskan `concurrently=True` ke schema editor. Django bawaan
melakukan persis itu — `AddIndexConcurrently.database_forwards` memanggil
`schema_editor.add_index(model, index, concurrently=True)`, sementara
`django/db/backends/base/schema.py` `add_index(self, model, index)` tidak punya
argumen tersebut (hanya backend postgresql yang punya). Akibatnya bukan satu
tes merah, melainkan `TypeError` saat PEMBUATAN DB TES → seluruh suite mati
sekaligus. Karena itu perilakunya dikunci di sini.

Catatan harness: memakai `SimpleTestCase` + `databases`, BUKAN `TestCase`.
`TestCase` membungkus tiap tes dalam `atomic()`, dan schema editor SQLite
menolak masuk di dalam transaksi ("cannot be used while foreign key constraint
checks are enabled"). `TransactionTestCase` juga bukan pilihan: flush-nya
menghapus data seed dari migrasi (SourceType/Toko/ToleranceProfile) untuk tes
berikutnya. Konsekuensinya DDL di sini tidak ikut rollback, jadi index uji coba
dibersihkan sendiri lewat `addCleanup`.
"""

from django.apps import apps
from django.db import connection, models
from django.db.migrations.state import ProjectState
from django.test import SimpleTestCase

from core.db_ops import TambahIndexAman

# Nama sengaja berbeda dari kedua index produksi: keduanya SUDAH ada di DB tes
# (migrasi 0008 jalan saat DB tes dibuat), jadi "index terbentuk" tak bisa
# dibuktikan dengan nama itu.
NAMA_UJI = "tx_tes_sementara_idx"


class TambahIndexAmanSQLiteTests(SimpleTestCase):
    databases = {"default"}

    def setUp(self):
        self.op = TambahIndexAman(
            model_name="transaction",
            index=models.Index(fields=["toko", "posted_date"], name=NAMA_UJI),
        )
        # Dua state, persis seperti yang dilakukan migration executor:
        # `state_forwards` menaruh index di state SEBELUM `database_forwards`.
        # `AddIndex.database_backwards` mencarinya lewat `from_state`, jadi
        # memakai satu state polos untuk kedua sisi tidak mewakili yang nyata.
        self.state_awal = ProjectState.from_apps(apps)
        self.state_akhir = self.state_awal.clone()
        self.op.state_forwards("transactions", self.state_akhir)
        self.addCleanup(self._buang_index_uji)

    # -- perkakas ---------------------------------------------------------
    def _buang_index_uji(self):
        with connection.cursor() as cur:
            cur.execute(f"DROP INDEX IF EXISTS {NAMA_UJI}")

    def _index_ada(self):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND name = %s",
                [NAMA_UJI],
            )
            return cur.fetchone() is not None

    def _maju(self):
        with connection.schema_editor() as editor:
            self.op.database_forwards(
                "transactions", editor, self.state_awal, self.state_akhir
            )

    def _mundur(self):
        with connection.schema_editor() as editor:
            self.op.database_backwards(
                "transactions", editor, self.state_akhir, self.state_awal
            )

    # -- tes --------------------------------------------------------------
    def test_di_sqlite_tidak_meneruskan_concurrently(self):
        """Maju di SQLite: tanpa TypeError, dan index-nya benar-benar terbentuk."""
        self.assertFalse(self._index_ada(), "prasyarat: index uji belum ada")
        self._maju()  # `AddIndexConcurrently` bawaan melempar TypeError di sini
        self.assertTrue(self._index_ada())

    def test_di_sqlite_mundur_juga_aman(self):
        """Mundur menempuh jalur non-Postgres yang sama — index hilang, tanpa error."""
        self._maju()
        self.assertTrue(self._index_ada())
        self._mundur()
        self.assertFalse(self._index_ada())

    def test_dijalankan_dua_kali_tidak_melempar(self):
        """Idempoten: index yang sudah ada dilewati, bukan dibangun ulang.

        Di produksi index besar dibangun lebih dulu lewat psql, jadi migrasi
        WAJIB boleh jalan di atas index yang sudah ada tanpa menggagalkan boot.
        """
        self._maju()
        self._maju()
        self.assertTrue(self._index_ada())

    def test_mundur_dua_kali_tidak_melempar(self):
        """Sisi sebaliknya: menghapus index yang sudah tak ada juga no-op."""
        self._maju()
        self._mundur()
        self._mundur()
        self.assertFalse(self._index_ada())
