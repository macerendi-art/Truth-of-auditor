"""Operasi migrasi yang aman di produksi Postgres DAN di SQLite (tes & dev).

KENAPA MODUL INI ADA
====================

**1. `AddIndexConcurrently` bawaan mematikan seluruh suite tes.**
`django.contrib.postgres.operations.AddIndexConcurrently.database_forwards`
memanggil ``schema_editor.add_index(model, self.index, concurrently=True)``.
Argumen `concurrently` itu HANYA ada di schema editor PostgreSQL
(``django/db/backends/postgresql/schema.py``: ``add_index(self, model, index,
concurrently=False)``); tanda tangan basisnya — yang dipakai SQLite —
adalah ``add_index(self, model, index)`` (``django/db/backends/base/schema.py``).
Jadi memakai operasi bawaan apa adanya melempar ``TypeError`` saat PEMBUATAN DB
TES: bukan satu tes merah, melainkan seluruh suite mati sebelum tes pertama
jalan. `TambahIndexAman` menutup celah itu dengan mendelegasikan ke `AddIndex`
biasa di luar PostgreSQL. Dikunci oleh `core/tests_db_ops.py`.

**2. Index besar dibangun lebih dulu lewat psql, migrasi hanya menyusul.**
Start command Railway menjalankan ``migrate`` SEBELUM gunicorn membuka port.
Membangun index di atas tabel 6,1 juta baris di dalam ``migrate`` berarti boot
menggantung sampai index jadi — health check gagal, aplikasi tak pernah naik.
Alur produksinya karena itu terbalik: index dibangun manual lewat psql
(``CREATE INDEX CONCURRENTLY``, di luar jam sibuk, tanpa mengunci tabel),
BARU kode-nya di-deploy. Supaya alur itu sah, migrasinya wajib **idempoten** —
menemukan index yang sudah ada dan melewatinya, bukan meledak. Kalau index
ternyata belum ada (mis. DB staging yang baru dibuat), migrasi membangunnya
sendiri secara concurrent.

**3. Migrasi ini tidak boleh menggagalkan boot, apa pun yang terjadi —
dan harganya dibayar di sini.**
Index yang hilang membuat halaman lambat; angkanya tetap benar. Aplikasi yang
mati jauh lebih mahal daripada halaman lambat. Jadi kegagalan di jalur Postgres
dicatat sebagai `logger.warning` lalu boot diteruskan.

Konsekuensinya harus dikatakan terang-terangan, karena tidak kelihatan dari
berkas ini saja: `except` di bawah menulis satu `warning` lalu **kembali
normal**, dan `MigrationExecutor.apply_migration` memanggil
``record_migration()`` TANPA SYARAT begitu ``apply()`` tidak melempar. Artinya
migrasi yang gagal separuh tetap **TERCATAT selesai**; boot berikutnya
melewatinya sama sekali, dan index-nya **tidak akan pernah dibangun ulang
sendiri**. Yang tersisa adalah halaman yang lambat diam-diam — tanpa satu pun
keluhan, tanpa deteksi otomatis. Jangan menulis di sini bahwa boot berikutnya
akan menemukannya; tidak akan.

Cabang ``indisvalid = false`` di bawah **tetap ada dan tetap benar**, tapi
bukan untuk kasus itu: ia menangkap DB yang **belum pernah** menjalankan
migrasi ini (staging baru, restore) dan menemukan sisa ``CREATE INDEX
CONCURRENTLY`` manual yang gagal/terputus — index yang diabaikan planner tapi
namanya memblokir pembuatan ulang.

Karena tak ada deteksi otomatis, deteksinya **manual dan eksplisit**::

    python manage.py periksa_index

membandingkan `Transaction._meta.indexes` dengan `pg_index`, melaporkan yang
hilang/invalid beserta perintah pemulihannya, dan keluar dengan kode ≠ 0 bila
ada temuan. Jalankan setelah deploy yang menyentuh index, dan setiap kali ada
`warning` dari modul ini di log boot — kedua pesan `warning` itu menyebutkannya.

Karena mewarisi `AddIndex`, `state_forwards` tetap menyinkronkan model state,
jadi ``makemigrations --check`` tetap bersih tanpa `SeparateDatabaseAndState`.
"""

import logging

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db.migrations import AddIndex

logger = logging.getLogger(__name__)

# `indisvalid` = false berarti index ada tapi tak terpakai planner (sisa
# CREATE INDEX CONCURRENTLY yang gagal/terputus). Nama index unik per skema,
# jadi kueri ini mengembalikan paling banyak satu baris.
SQL_STATUS_INDEX = """
SELECT i.indisvalid FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid
 WHERE c.relname = %s AND c.relkind = 'i'
"""


class TambahIndexAman(AddIndexConcurrently):
    """`AddIndexConcurrently` yang sadar vendor, idempoten, dan tak pernah fatal.

    - non-PostgreSQL (SQLite tes & dev) → delegasi ke `AddIndex` biasa,
      TANPA `concurrently` (lihat docstring modul, alasan #1);
    - PostgreSQL → lewati bila index sudah ada (alasan #2);
    - kegagalan apa pun di jalur Postgres → `warning`, boot lanjut (alasan #3).
    """

    atomic = False

    # -- perkakas ---------------------------------------------------------
    def _index_sudah_ada(self, schema_editor, model):
        """Cek keberadaan index lintas-vendor (dipakai jalur non-Postgres)."""
        with schema_editor.connection.cursor() as cursor:
            daftar = schema_editor.connection.introspection.get_constraints(
                cursor, model._meta.db_table
            )
        return self.index.name in daftar

    def _status_index_pg(self, schema_editor):
        """(ada, valid) menurut katalog PostgreSQL."""
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(SQL_STATUS_INDEX, [self.index.name])
            baris = cursor.fetchone()
        if baris is None:
            return False, False
        return True, bool(baris[0])

    # -- operasi ----------------------------------------------------------
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return

        if schema_editor.connection.vendor != "postgresql":
            # Penjaga keberadaan tetap dipasang (migrasi boleh jalan dua kali),
            # tapi DDL-nya tetap milik `AddIndex` — jangan bungkus dengan
            # try/except: "index sudah ada" yang ditelan diam-diam akan
            # menyembunyikan kegagalan nyata di dev/tes.
            if not self._index_sudah_ada(schema_editor, model):
                AddIndex.database_forwards(
                    self, app_label, schema_editor, from_state, to_state
                )
            return

        self._ensure_not_in_transaction(schema_editor)
        ada, valid = self._status_index_pg(schema_editor)
        if ada and valid:
            # Jalur normalnya: sudah dibangun manual lewat psql sebelum deploy.
            logger.info("Index %s sudah ada dan valid — migrasi no-op.", self.index.name)
            return
        if ada and not valid:
            logger.warning(
                "Index %s ADA tapi INVALID — sisa CREATE INDEX CONCURRENTLY yang "
                "gagal/terputus; planner mengabaikannya, jadi kueri tetap lambat. "
                "Pulihkan manual lewat psql: DROP INDEX CONCURRENTLY %s; lalu "
                "bangun ulang. Boot diteruskan. Migrasi ini akan TERCATAT SELESAI "
                "walau index-nya tak jadi — tak ada boot berikutnya yang akan "
                "memperbaikinya sendiri; pastikan lewat `python manage.py "
                "periksa_index`.",
                self.index.name,
                self.index.name,
            )
            return
        try:
            schema_editor.add_index(model, self.index, concurrently=True)
        except Exception:
            logger.warning(
                "Gagal membangun index %s secara concurrent — halaman akan lambat, "
                "angkanya tetap benar. Bangun manual lewat psql; bila tertinggal "
                "index invalid, DROP INDEX CONCURRENTLY %s; dulu. Boot diteruskan. "
                "PENTING: migrasi ini tetap TERCATAT SELESAI (record_migration "
                "dipanggil tanpa syarat karena apply() tidak melempar), jadi "
                "`migrate` berikutnya TIDAK akan mencobanya lagi — index ini tak "
                "akan pernah dibangun ulang sendiri. Verifikasi dengan `python "
                "manage.py periksa_index`.",
                self.index.name,
                self.index.name,
                exc_info=True,
            )

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        model = from_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return

        if schema_editor.connection.vendor != "postgresql":
            if self._index_sudah_ada(schema_editor, model):
                AddIndex.database_backwards(
                    self, app_label, schema_editor, from_state, to_state
                )
            return

        self._ensure_not_in_transaction(schema_editor)
        ada, _valid = self._status_index_pg(schema_editor)
        if not ada:
            return
        try:
            # Index invalid pun boleh (dan memang perlu) dibuang concurrent.
            schema_editor.remove_index(model, self.index, concurrently=True)
        except Exception:
            logger.warning(
                "Gagal membuang index %s secara concurrent. Boot diteruskan.",
                self.index.name,
                exc_info=True,
            )
