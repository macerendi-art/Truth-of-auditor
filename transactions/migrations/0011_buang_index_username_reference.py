"""Buang index mati `username`/`reference` (719 MB, tabel 8,8 juta baris).

LATAR — BUKAN STATISTIK, BUKTI KODE
====================================
CLAUDE.md "Performa (v1.18.0)" mencatat backlog index mati ini, tapi juga
mencatat premisnya SUDAH RETAK: seluruh `pg_stat_*` produksi ter-reset saat
naik ke PG 18 (31-08-2026), jadi `idx_scan=0` hari ini cuma membuktikan
"tak dipakai ±31 jam" — bukan alasan yang cukup untuk membuang index tabel
inti rekonsiliasi. Migrasi ini TIDAK bersandar pada `idx_scan`.

Alasannya disisir ulang dari kode hari ini (04-09-2026), bukan dipercaya
begitu saja dari CLAUDE.md:

* `web/views.py::transactions` dan `transactions/admin.py.search_fields`
  (tanpa awalan `^`) adalah SATU-SATUNYA kueri DB atas dua kolom ini, dan
  keduanya `icontains` -> `UPPER(kolom) LIKE UPPER('%q%')`. Btree biasa mati
  karena kolomnya terbungkus fungsi `UPPER()`; `varchar_pattern_ops` (index
  `_like` yang otomatis menyertai `db_index=True` CharField di Postgres)
  cuma melayani `LIKE 'awalan%'` case-sensitive — pola yang tak pernah
  dipakai kedua pemanggil itu. `counterparty`/`description` sudah lama
  dicari dengan cara yang sama TANPA index apa pun, tak ada yang mengeluh.
* `reconciliation/engine.py` memakai `username`/`reference` sebagai kunci
  anchor (pass 0b reference-join gateway, mode username Panel<->Bracket),
  TAPI keduanya dibaca dari list Python yang sudah dimaterialisasi lewat
  `sides()` (`list(qs.order_by("id"))` di `PanelBracketMatcher.sides` dan
  `_MoneyMatcher.sides`) — join-nya dict/set murni di memori
  (`gw_ref[b.reference].append(b)`, `_kunci_username`), TIDAK PERNAH lewat
  `.filter(username=...)`/`.filter(reference=...)` pada queryset yang masih
  lazy. Diverifikasi dengan grep bertarget di seluruh `reconciliation/`,
  `sources/`, `web/`, `transactions/`, `core/` untuk `filter(`, `exclude(`,
  `get(`, `order_by(`, `values(`, `annotate(`, `distinct(`, `in_bulk`,
  `select_related`, raw SQL — nol lookup persis/`__in`/`__startswith` yang
  akan dilayani btree.
* `web/penjaga.py::_kunci` memanggil `.values_list("reference"/"username",
  flat=True)` — proyeksi kolom atas queryset yang SUDAH disaring toko/
  source_type/tanggal/jenis (dilayani index komposit lain), bukan filter
  atas kolom ini; index pada kolom yang diproyeksikan tidak menolong.
* `web/bonus.py`, `web/detail_fr.py`, `web/hutang.py`, `web/rekap.py`,
  `web/exports.py` hanya membaca `username` lewat `.values(...)`/atribut
  Python untuk ditampilkan — sama, proyeksi bukan filter.
* Kemunculan `username`/`reference` lain di kode (accounts.User.username,
  core.models.AuditLog.username, web/settlement.py `reference` = tanggal
  acuan settlement) adalah kolom/variabel LAIN yang tidak tersentuh migrasi
  ini.

Kalau ada pemakaian yang sebenarnya butuh lookup persis, migrasi ini semestinya
BATAL — hasil penyisiran di atas tidak menemukannya.

APA YANG DIBUANG
=================
`db_index=True` pada `Transaction.username` (base + `_like`) dan
`Transaction.reference` (base + `_like`) = 4 index Postgres, total 719 MB.
`ticket_no` TIDAK disentuh (tetap `db_index=True` — dipakai berbeda, di luar
cakupan ini).

KENAPA INI BUKAN `TambahIndexAman` (0008-0010) — KEPUTUSAN, BUKAN PENIRUAN
============================================================================
`transactions/migrations/0008`-`0010` memakai `atomic = False` +
`core/db_ops.TambahIndexAman` karena DUA masalah CREATE INDEX biasa yang
TIDAK berlaku untuk DROP:

1. `CREATE INDEX` (tanpa CONCURRENTLY) memegang lock yang memblokir TULIS
   selama seluruh proses scan+sort tabel — pada 8,8 juta baris itu bisa
   menit, dan start command Railway menjalankan `migrate` SEBELUM gunicorn
   membuka port, jadi boot menggantung sepanjang itu. `DROP INDEX` tidak
   men-scan apa pun — ia hanya menghapus baris katalog (`pg_class`/
   `pg_index`) lalu unlink berkas index. Kerja NYATA-nya sendiri berorde
   mikro-milidetik, bukan menit, tak peduli berapa besar tabelnya.
2. `AddIndexConcurrently`/`CREATE INDEX` biasa TIDAK idempoten — mengulang
   `migrate` pada index yang sudah ada meledak "already exists", makanya
   `TambahIndexAman` menambah pengecekan `pg_index` manual sebelum mencoba.
   `AlterField` yang menyalakan `db_index=False` TIDAK begini: dibaca dari
   sumber Django sendiri (`BaseDatabaseSchemaEditor._alter_field`,
   django/db/backends/base/schema.py), jalur pembuangan index memanggil
   `_constraint_names(model, [kolom], index=True, type_=Index.suffix)` —
   artinya ia bertanya ke KATALOG POSTGRES dulu index apa saja yang benar-
   benar ada di kolom itu, lalu membuang HANYA yang ditemukan. Kalau index
   itu sudah dibuang manual sebelumnya (mis. lewat psql `DROP INDEX
   CONCURRENTLY` di bawah), introspeksi ini menemukan nol baris dan migrasi
   jadi no-op dengan sendirinya — TANPA kelas Operation khusus. Ini
   idempotensi built-in Django, bukan sesuatu yang kami tambahkan.
   (Diverifikasi baris demi baris di
   `.venv/lib/python3.11/site-packages/django/db/backends/base/schema.py`
   sekitar baris 1015-1048 — komentar Django sendiri menulis "no strict
   check, as multiple indexes are possible" persis untuk kasus ini.)
   Bonus: introspeksi Postgres tidak membedakan opclass, jadi index `_like`
   (varchar_pattern_ops) IKUT TERBUANG oleh `AlterField` yang sama — tidak
   perlu ditangani terpisah seperti yang dilakukan schema editor Postgres
   untuk kasus UNIQUE->non-unique (`_alter_field` Postgres override, baris
   ~295-301 — kasus itu TIDAK relevan di sini karena `username`/`reference`
   tidak pernah `unique=True`).
   `sql_delete_index` Postgres sendiri juga `DROP INDEX IF EXISTS %(name)s`
   — lapis aman kedua di level SQL, di atas pengecekan katalog Django.

KESIMPULAN: pola CONCURRENTLY-dulu-lewat-psql-migrasi-jadi-no-op yang
dipakai 0008-0010 dibuat UNTUK masalah yang tidak dipunyai DROP (durasi scan
+ ketidak-idempotenan). Membungkusnya lagi di sini jadi meniru bentuk tanpa
alasan bawah — DILARANG oleh brief tugas ini, jadi migrasi ini memakai
`migrations.AlterField` polos, `atomic` default (True; `DROP INDEX` biasa,
BEDA dari `DROP INDEX CONCURRENTLY`, sah di dalam transaksi).

RISIKO YANG TERSISA — DIKOREKSI TINJAUAN AKHIR (P1, 04-09-2026)
================================================================
Analisis awal di bagian ini benar sampai satu titik dan MEREMEHKAN
durasinya. `DROP INDEX` (tanpa CONCURRENTLY) butuh `ACCESS EXCLUSIVE` pada
TABEL `transactions_transaction`. Yang tidak disebut: begitu permintaan lock
itu MENGANTRE di belakang transaksi yang sedang berjalan, SEMUA permintaan
lock baru pada tabel itu — termasuk `ACCESS SHARE` dari SELECT biasa — ikut
mengantre di belakangnya (semantik antrean lock Postgres). Jadi selama
`migrate` instance baru menunggu, instance LAMA yang masih melayani trafik
ikut MEMBEKU pada tabel inti. Durasinya = transaksi TERPANJANG yang sedang
memegang tabel saat itu, dan di aplikasi ini itu bukan "satu request biasa":

* `pg_dump` cadangan harian (scripts/cadangan/backup-harian.sh) memegang
  `ACCESS SHARE` pada semua tabel selama 13+ menit, 03:00–03:20 WIB.
  Deploy di jendela itu = aplikasi beku sampai dump selesai; boot Railway
  melewati batas health-check → restart ×3 (`restartPolicyMaxRetries`) →
  Railway menyerah: tidak ada instance yang naik, sementara dump tetap jalan.
* `run_batch` 22–29 dtk (hari ELITE) di dalam `transaction.atomic()`;
  ingest berkas besar di `_persist_rows` atomic.

Kerja nyata DROP-nya memang orde milidetik; yang mahal adalah MENUNGGU, dan
yang ikut menunggu adalah seluruh aplikasi.

LANGKAH WAJIB PRA-DEPLOY (bukan lagi "opsi manual")
====================================================
Jalankan keempat `DROP INDEX CONCURRENTLY` lewat psql SEBELUM `railway up`,
di LUAR 03:00–03:30 WIB dan tidak sedang ada rekonsiliasi/ingest besar.
`CONCURRENTLY` tidak pernah butuh `ACCESS EXCLUSIVE`, jadi tidak ada antrean
yang membekukan siapa pun; `migrate` saat boot kemudian menemukan katalog
sudah kosong → no-op (idempotensi bawaan Django yang dijelaskan di atas).

Nama index dihitung DETERMINISTIK dari algoritma penamaan Django
(`names_digest(table, kolom, length=8)` atas `transactions_transaction` +
nama kolom — stabil sejak migrasi 0001, kolom tak pernah berganti nama) —
BUKAN ditebak. Verifikasi lebih dulu lewat `\\d transactions_transaction`
di psql sebelum menjalankan:

    DROP INDEX CONCURRENTLY IF EXISTS transactions_transaction_username_6b02bd12;
    DROP INDEX CONCURRENTLY IF EXISTS transactions_transaction_username_6b02bd12_like;
    DROP INDEX CONCURRENTLY IF EXISTS transactions_transaction_reference_65ce6e73;
    DROP INDEX CONCURRENTLY IF EXISTS transactions_transaction_reference_65ce6e73_like;

Sesudahnya: `SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;`
harus KOSONG (`DROP INDEX CONCURRENTLY` yang terputus meninggalkan index
INVALID — gerbang J4 cadangan menolak dump bila ada), dan
`\\d transactions_transaction` tidak lagi menampilkan keempatnya.

Kalau langkah ini TERLEWAT, `migrate` tetap benar secara HASIL — hanya
harganya yang berbeda: pembekuan tabel inti selama transaksi terpanjang
saat itu. Urutan lengkap + jendela terlarang: docs/runbook-rollback-2026-09-04.md
bagian "Urutan deploy wajib".

JANGAN DIBALIK LEWAT `migrate` (P6)
====================================
`migrate transactions 0010` = AlterField kembali ke `db_index=True`, dan
Django menjalankannya sebagai `CREATE INDEX` POLOS — non-concurrent, TANPA
`IF NOT EXISTS` (`BaseDatabaseSchemaEditor._alter_field`,
django/db/backends/base/schema.py ~1223, plus `_like` dari schema editor
Postgres) — ×4 atas 10,3 juta baris, memegang lock yang memblokir semua
TULIS selama build (menit), dari koneksi psql/Django di workstation lewat
proxy publik yang bisa putus dan meninggalkan index INVALID. Dan bila index
itu sudah dibangun manual lebih dulu, migrasi mundur justru GAGAL "already
exists". Kalau index-nya benar-benar diperlukan lagi: bangun `CONCURRENTLY`
lewat psql dengan nama persis di atas dan BIARKAN kode tetap di 0011 —
index ekstra di DB yang tak dideklarasikan model tidak mengganggu apa pun
(itulah keadaan sebelum migrasi ini).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0010_index_fr_bank_posted'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transaction',
            name='reference',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='username',
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
