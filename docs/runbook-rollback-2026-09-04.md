# Runbook — Rollback aplikasi dan basis data produksi (G2, 2026-09-04)

Status sebelum ini: **prosedur rollback tak terdokumentasi.** Aplikasi hidup di Railway dengan
migrasi basis data yang berjalan otomatis di setiap deploy. Riwayat migrasnya dulu aditif saja
(nol `RemoveField`/`DeleteModel`), jadi rollback aman **secara kebetulan, bukan karena tooling** —
dan kebetulan itu hanya berlaku sementara data terus bertumbuh. Dokumen ini menutup celah itu:
prosedur yang jelas, bisa dieksekusi, dan jujur tentang apa yang sudah/belum pernah diuji.

> ⚠️ **Amandemen 04-09-2026 (tinjauan akhir P1/P2/P6).** Sejak `transactions/0011` klaim "semua
> migrasi aditif" **tidak lagi benar**: 0011 MEMBUANG empat index. Bagian baru
> [Urutan deploy wajib & jendela terlarang](#urutan-deploy-wajib--jendela-terlarang-p1p2-04-09-2026)
> dan [Migrasi yang tidak boleh dibalik](#migrasi-yang-tidak-boleh-dibalik-lewat-migrate-p6)
> mengoreksi contoh `migrate transactions 0009` yang dulu ada di dokumen ini.

Sumber tugas: `docs/daftar-perbaikan-2026-09-03.md` butir G2.

---

## Pohon keputusan ringkas

Aplikasi jatuh atau menunjukkan perilaku aneh → tanya diri sendiri:

1. **Apakah data terlihat rusak atau hilang?**
   - Ya → keputusan mungkin sudah dimulai sebelum gejala terlihat (data lama yang salah
     di-overwrite, query yang menyembunyikan baris, dsb) → [Restore dari cadangan](#restore-dari-cadangan)
     adalah satu-satunya perbaikan nyata; rollback aplikasi saja cuma membuang ciri tetapi data
     tetap rusak.
   - Tidak, tapi halaman lambat atau ada error transien → cek kesehatan dulu sebelum rollback:
     [Pemeriksaan kesehatan cepat](#pemeriksaan-kesehatan-cepat).

2. **Aplikasi tak naik (deployment gagal) atau HTTP 500 seketika setelah deploy?**
   - Rollback deploy aplikasi, lalu isolasi penyebabnya di workstation lokal.

3. **Semuanya terlihat baik tapi ada indikasi index hilang/invalid?**
   - Rollback deploy, periksa index di produksi dengan `periksa_index`, perbaiki index,
     lalu redeploy.

4. **Kalau salah, cara recovery?**
   - [Restore dari cadangan](#restore-dari-cadangan).

---

## Pemeriksaan kesehatan cepat

Sebelum memulai rollback apa pun, jalankan di produksi Railway (via `railway ssh`):

```bash
python manage.py periksa_kesehatan     # OK / PERHATIAN / BAHAYA
python manage.py periksa_index          # bersih / ada temuan (+ kode ≠ 0 jika ada)
```

Keduanya adalah read-only:
- `periksa_kesehatan` melaporkan status disk, umur batch per toko, tabel referensi (SourceType,
  Toko, ToleranceProfile), sequence, dan index.
- `periksa_index` khusus index `transactions_transaction` — hilang atau invalid (`indisvalid =
  false`).

Angka dan status apa pun yang terlihat, catat untuk laporan insiden.

---

## Urutan deploy wajib & jendela terlarang (P1/P2, 04-09-2026)

Start command Railway menjalankan `migrate` **sebelum** gunicorn membuka port, dan instance lama
masih melayani trafik selama itu. Dua migrasi di cabang v1.25.0 membuat urutan ini **wajib**, bukan
opsional — rinciannya ada di docstring masing-masing migrasi, ini ringkasannya yang dieksekusi:

**Jendela terlarang: 03:00–03:30 WIB** (jangan `railway up`, jangan DDL psql). `pg_dump` cadangan
harian (`scripts/cadangan/backup-harian.sh`, `toa-cadangan.timer` 03:00 + jitter 5 menit) memegang
transaksi 13+ menit. Dua akibatnya:
- `DROP INDEX` non-concurrent (0011 lewat `migrate`) minta `ACCESS EXCLUSIVE` pada
  `transactions_transaction`; begitu permintaan itu **mengantre** di belakang `pg_dump`, semua lock
  baru pada tabel itu — termasuk `ACCESS SHARE` dari SELECT biasa — ikut mengantre. Instance lama
  **membeku** pada tabel inti sampai dump selesai; boot baru melewati health-check → restart ×3 →
  Railway menyerah, tidak ada instance yang naik.
- `CREATE INDEX CONCURRENTLY` (0012 di boot bila psql terlewat) **menunggu** semua transaksi yang
  lebih tua selesai sebelum fase keduanya — tertahan selama dump walau tanpa lock eksklusif.
Jam sepi *terasa* aman; justru itu jam cadangan.

**Sebelum `railway up`** (psql produksi, di luar jendela di atas, tidak sedang ada rekonsiliasi/ingest besar):

```sql
-- P1: 0011 -- nama dihitung dari names_digest Django, verifikasi dulu lewat \d transactions_transaction
DROP INDEX CONCURRENTLY IF EXISTS transactions_transaction_username_6b02bd12;
DROP INDEX CONCURRENTLY IF EXISTS transactions_transaction_username_6b02bd12_like;
DROP INDEX CONCURRENTLY IF EXISTS transactions_transaction_reference_65ce6e73;
DROP INDEX CONCURRENTLY IF EXISTS transactions_transaction_reference_65ce6e73_like;
-- P2: 0012 -- DDL persis dari docstring migrasi
CREATE INDEX CONCURRENTLY "tx_hutang_piutang_idx"
    ON "transactions_transaction" ("toko_id", "source_type_id", "posted_date")
    WHERE ("raw" ->> 'Kategori') ~* '^\s*(hutang|piutang)\s*$';
-- gerbang: HARUS kosong (CONCURRENTLY yang terputus meninggalkan index INVALID;
-- gerbang J4 cadangan menolak dump bila ada satu pun)
SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;
```

Dengan itu `migrate` saat boot menemukan katalog sudah sesuai dan **no-op** untuk keduanya (0011:
introspeksi Django tidak menemukan index untuk dibuang; 0012: `TambahIndexAman` melihat index ada &
valid).

**Sesudah naik**, dari **kode baru** (`railway ssh`):
1. `python manage.py periksa_index` — harus "Bersih".
2. `EXPLAIN (ANALYZE, BUFFERS)` fase-1 `/hutang-piutang/` (query di docstring 0012) — index parsial
   harus dipakai; `predicate_implied_by` belum pernah dibuktikan di Postgres nyata.
3. Buka `/kelola/log/`, pastikan baris `login` muncul dengan IP.
4. **Perbarui `/opt/toa` di VPS ke commit yang di-deploy** (`git -C /opt/toa fetch origin && git -C
   /opt/toa checkout <commit>`). Pemantauan harian (`toa-kesehatan.timer`) menjalankan
   `periksa_index` dari checkout itu: index **INVALID** terdeteksi dari kode mana pun (seluruh
   `pg_index` tabel dibaca), tapi index **HILANG** hanya bisa dilaporkan kode yang mengenal namanya.
   Skrip kesehatan kini mencatat revisi `/opt/toa` di log dan `status.json` supaya drift terlihat.

Kalau langkah psql **terlewat**, hasil akhirnya tetap benar — hanya harganya yang berbeda: 0011
membekukan tabel inti selama transaksi terpanjang saat itu, 0012 membangun index di boot dan bisa
terbunuh health-check (→ INVALID → cadangan berhenti, lihat P2 di docstring 0012).

---

## Rollback deploy aplikasi

Deploy produksi di Railway berjalan **manual** dari checkout utama, BUKAN dari git worktree:

```bash
cd /Users/macads/Truth-of-auditor           # BUKAN worktree!
git fetch origin
git rebase origin/main                      # fast-forward, tak pernah force
railway up --ci --detach --project <PROJECT_ID> --environment production --service web
```

Untuk **rollback** ke deployment sebelumnya (tanpa mengubah `DATABASE_URL` atau `migrate`):

1. **Catat hash deployment terbaru yang hendak dibatalkan** (lihat di Railway console atau
   `railway deployments list --service web`).

2. **Kembali ke commit git terdahulu yang diinginkan:**
   ```bash
   cd /Users/macads/Truth-of-auditor
   git log --oneline | head         # cari hash commit yang stabil
   git reset --hard <HASH_LAMA>
   ```

3. **Redeploy dari commit lama itu:**
   ```bash
   railway up --ci --detach --project <PROJECT_ID> --environment production --service web
   ```

   Railway akan membaca `Procfile`/`railway.json` dari HEAD lokal, menjalankan `migrate`
   (idempoten, kolom/index yang ada akan dilalui), lalu naik dengan kode versi lama.

4. **Setelah naik:** cek `periksa_kesehatan` dan `periksa_index` lagi.

### Kapan rollback deploy saja sudah cukup

- Aplikasi tak naik (500 startup, import error, syntax error di kode baru).
- Halaman error tapi query/data terlihat valid (mis. typo di template, bug di view logic yang
  tidak menyentuh DB).
- Perilaku aneh yang berubah persis saat deploy, TAPI tidak ada bukti data yang berubah.

### Kapan rollback deploy TIDAK cukup

- Migrasi sudah berjalan dan mengubah skema; rollback aplikasi saja meninggalkan DB dalam keadaan
  tidak sesuai dengan kode lama.
- Index hilang atau invalid — aplikasi lama juga akan lambat kecuali index diperbaiki.
- Data terlihat hilang atau rusak — data tidak akan hilang karena rollback aplikasi.

---

## Rollback migrasi basis data

**Fundamental:** Start command Railway menjalankan `migrate` SEBELUM gunicorn membuka port.
Jika migrasi gagal, port TIDAK akan terbuka dan aplikasi TIDAK akan naik. Migrasi yang berhasil
tidak boleh dibatalkan begitu saja tanpa pemahaman penuh tentang apa yang dihapus.

### Peringatan penting

**Tidak ada satu pun migrasi proyek ini yang pernah diuji untuk mundur.** Sampai 03-09-2026
semuanya aditif (nol `RemoveField`/`DeleteModel`); sejak `transactions/0011` (04-09-2026) ada satu
yang **membuang** index — dan justru yang itu **tidak boleh dibalik lewat `migrate`** (lihat bagian
khusus di bawah). Jika mundur diperlukan, hal itu adalah situasi luar biasa (data corruption yang
diperkenalkan migrasi, atau migrasi yang mengeksekusi DML yang tidak dapat dipulihkan) — bukan
operasi rutin.

Urutan mundur migrasi (untuk migrasi yang memang aman dibalik):

```bash
# Dari workstation lokal (dengan DATABASE_URL menunjuk ke produksi atau staging):
python manage.py migrate <APP> <NOMOR_SEBELUMNYA>

# Contoh yang AMAN: membalik 0012 (index parsial) — database_backwards-nya
# remove_index(concurrently=True), tidak memblokir apa pun:
python manage.py migrate transactions 0011

# JANGAN: `migrate transactions 0010` atau lebih rendah — itu MEMBALIK 0011 (lihat bagian
# "Migrasi yang tidak boleh dibalik").

# Setelah itu, langsung redeploy dari commit lama (lihat di atas).
```

### Migrasi yang tidak boleh dibalik lewat `migrate` (P6)

**`transactions/0011_buang_index_username_reference`.** Membaliknya = `AlterField` kembali ke
`db_index=True`, dan Django menjalankannya sebagai `CREATE INDEX` **polos** — non-concurrent, tanpa
`IF NOT EXISTS` (`django/db/backends/base/schema.py` `_alter_field`, plus `_like` dari schema editor
Postgres) — ×4 atas 10,3 juta baris (719 MB), memegang lock yang memblokir **semua tulis** ke
`transactions_transaction` selama build (menit), dari koneksi psql/Django di laptop lewat proxy
publik yang bisa putus di tengah dan meninggalkan index INVALID (→ gerbang J4 menghentikan cadangan).
Bila index itu sudah dibangun manual lebih dulu, migrasi mundurnya malah **gagal "already exists"**.

Kalau keempat index itu benar-benar diperlukan lagi: bangun `CONCURRENTLY` lewat psql dengan nama
persis di docstring 0011, dan **biarkan kode tetap di 0011** — index ekstra di DB yang tidak
dideklarasikan model tidak mengganggu apa pun (itulah keadaan sebelum 0011).

### Kapan mundur migrasi boleh dipertimbangkan

1. **Migrasi mengubah struktur data yang tidak bisa dipulihkan.**
   - Contoh: `RemoveField` yang menghapus kolom (dalam proyek ini, ini belum pernah terjadi).
   - Contoh: `RunPython` yang meng-update jutaan baris berdasarkan logika yang berubah.
   - Apa yang perlu dilakukan: verifikasi dengan `periksa_index` / `periksa_kesehatan` SEBELUM
     mundur; jika index sudah invalid (lihat bagian khusus di bawah), migrasi mundur bisa
     membuat situasi lebih buruk.

2. **Migrasi index (TambahIndexAman) gagal membangun index.**
   - Jangan mundur — lihat bagian khusus di bawah; mundur hanya melepas nama index dari
     `Transaction._meta.indexes` (kode), tapi `pg_index` di DB tetap memiliki sisa index
     yang invalid.

### Kapan mundur migrasi TIDAK boleh dilakukan

1. **Index invalid ditemukan sebelumnya (`periksa_index` menunjukkan `INVALID`).**
   - Tidak boleh mundur; index sudah tidak bisa direferensikan. Perbaiki index manual lewat psql
     (lihat bagian khusus di bawah) DULU.

2. **Tidak ada bukti bahwa migrasi menyebabkan masalah.**
   - Mundur secara spekulatif meninggalkan aplikasi dan DB di keadaan tidak sesuai.

3. **Data sudah dikonsumsi/dimodifikasi oleh batch rekonsiliasi setelah migrasi.**
   - Mundur menghapus kolom yang sekarang menyimpan data; batch yang dibuat setelah migrasi
     akan kehilangan data itu selamanya. Restore dari cadangan adalah pilihan yang lebih aman.

---

## Kasus khusus: Migrasi index (TambahIndexAman)

Operasi index di produksi dijalankan **manual lewat psql**, di luar jadwal deploy:

```bash
# Di VPS atau via cloud DB admin panel:
CREATE INDEX CONCURRENTLY idx_name ON transactions_transaction (...);
```

Migrasi Django hanya mencatat bahwa index sudah ada — ia TIDAK membangun index di dalam `migrate`
(yang would hang boot).

### Gerbang otomatis yang rusak (index hilang atau invalid)

Perintah `core/db_ops.TambahIndexAman` memiliki penjaga: jika index sudah ada dan valid, migrasi
cukup log INFO dan selesai. Jika index tidak ada, migrasi MENCOBA membangun concurrent
(tapi tanpa menggantung boot). **Kegagalannya cuma `logger.warning`, dan migrasi TETAP TERCATAT
SELESAI** — itu desain intentional. Konsekuensinya:

- Boot berikutnya akan melewati migrasi (sudah tercatat).
- Index tidak akan pernah dibangun ulang sendiri.
- Halaman akan lambat, selamanya, sampai index dibangun manual.

### Cara mendeteksi

```bash
python manage.py periksa_index
# Atau di VPS (tanpa Django):
psql <produksi> -Atc "
  SELECT i.indexrelid::regclass AS idx
    FROM pg_index i WHERE NOT i.indisvalid;
"
```

Kode keluar bukan 0 = ada index bermasalah.

### Cara memperbaiki

1. **Index HILANG** (ada di `Transaction._meta.indexes` tapi tidak di DB):
   Buat manual lewat psql:
   ```sql
   -- Definisi index ada di migrasi Django terkait (transactions/migrations/NNNNN.py)
   -- atau di komentar periksa_index.py
   CREATE INDEX CONCURRENTLY idx_name ON transactions_transaction (...);
   ```

2. **Index INVALID** (ada tapi `pg_index.indisvalid = false`):
   ```sql
   DROP INDEX CONCURRENTLY idx_name;
   -- Tunggu sampai selesai (bisa lama kalau tabel besar)
   -- Lalu buat ulang:
   CREATE INDEX CONCURRENTLY idx_name ON transactions_transaction (...);
   ```

3. **Setelah perbaikan manual:**
   ```bash
   python manage.py periksa_index     # harus bersih
   ```

### Dampak rollback migrasi index (TIDAK disarankan)

Jika migrasi index di-rollback (mundur dari 0010 ke 0009), maka:
- Kode akan berhenti meng-claim index itu di `Transaction._meta.indexes`.
- Tapi `pg_index` di DB tetap memiliki nama index yang sama (kalau ada).
- Redeploy dengan migrasi baru akan mencoba membuat index dengan nama yang sama → konflik.

**Jangan mundur migrasi index.** Jika index sudah invalid atau hilang, perbaiki lewat psql
lalu tetap di migrasi terbaru.

---

## Restore dari cadangan

Prosedur lengkap untuk memulihkan data dari dump terjadwal ada di:
[`docs/runbook-cadangan-2026-09-04.md`](./runbook-cadangan-2026-09-04.md)

Ringkasnya (untuk skenario darurat):

1. **Verifikasi bahwa dump tersedia dan baik:**
   ```bash
   ssh toa
   cat ~/cadangan/status.json | jq '.verdict'
   sha256sum -c /var/backups/toa/dump-<YYYY-MM-DD>.sha256
   ```

2. **Jalankan restore uji (tidak menimpa database manapun):**
   ```bash
   D=/var/backups/toa/dump-2026-09-XX
   createdb restore_uji
   pg_restore --dbname=restore_uji --jobs=4 --no-owner --exit-on-error "$D"
   # Bandingkan count / sums dengan produksi untuk memastikan data masuk lengkap
   dropdb restore_uji
   ```

3. **Jika uji lolos, lakukan restore ke target nyata:**
   - Lokasi target tergantung skenario (Railway database baru, VPS yang akan jadi produksi baru,
     dsb). Lihat bagian "Restore sungguhan" di `docs/runbook-cadangan-2026-09-04.md`.

4. **Setelah restore:**
   ```bash
   python manage.py periksa_index          # harus bersih, atau perbaiki index dulu
   python manage.py migrate --noinput      # pastikan skema match kode terbaru
   ```

5. **Redirect aplikasi ke database baru dan test.**

---

## Urutan keputusan yang aman (ringkas)

```
Gejala timbul
  ├─ Data terlihat rusak/hilang?
  │   └─ Ya → Restore dari cadangan (baca runbook-cadangan-2026-09-04.md)
  │
  ├─ Aplikasi tidak naik (HTTP error saat startup)?
  │   └─ Ya → Rollback deploy, debug lokal
  │
  ├─ Halaman 500 atau lambat setelah deploy?
  │   ├─ Jalankan periksa_kesehatan + periksa_index
  │   ├─ Index invalid/hilang?
  │   │   └─ Ya → Perbaiki index manual, kemudian:
  │   │       ├─ Jika rollback diperlukan, lihat "Rollback deploy aplikasi"
  │   │       └─ Kalau hanya index yang bermasalah, perbaiki terus redeploy sama
  │   │
  │   └─ Tidak ada masalah infrastruktur → Rollback deploy, debug logic
  │
  └─ Tidak ada gejala jelas?
      └─ Cek log aplikasi / database query plan (EXPLAIN)
```

---

## Apa yang BELUM pernah diuji

Dokumentasi ini didasarkan pada desain sistem dan kode, tapi beberapa jalur belum pernah
dieksekusi di produksi nyata. Catat ini sebelum mengandalkan prosedur ini di situasi darurat:

### Tidak diuji

1. **Rollback migrasi basis data** (`python manage.py migrate <APP> <NOMOR>`)
   - Kode yang mendukung itu ada dan seharusnya berfungsi, tapi tidak pernah ada alasan nyata
     untuk mundur — dan 0011 **tidak boleh** dibalik lewat jalur ini sama sekali (lihat bagian
     "Migrasi yang tidak boleh dibalik").
   - **Kalau perlu dijalankan:** siapkan staging (`docs/runbook-staging-2026-09-04.md`,
     `toa_staging` di VPS) dengan dump backup yang sama, uji mundur di sana DULU sebelum produksi.

2. **Mundur migrasi yang memodifikasi data (RunPython dengan logika DML)**
   - Beberapa migrasi memiliki operasi forward-only yang memodifikasi data. Mundur tidak akan
     membatalkan modifikasi itu — data tetap berubah.
   - **Jika diperlukan:** restore dari cadangan adalah satu-satunya cara membatalkan modifikasi.

3. **Recovery index invalid dengan DROP INDEX CONCURRENTLY**
   - Prosedur tertulis di sini, tapi belum pernah dijalankan di produksi nyata.
   - **Cara uji:** buat index dummy yang invalid di staging, jalankan DROP CONCURRENTLY.

4. **Restore dari cadangan dengan migrasi schema yang berbeda**
   - Skenarionya: dump dibuat sebelum migrasi X, tetapi aplikasi sekarang menuntut migrasi X.
   - Runbook cadangan menyebut `python manage.py migrate --noinput` setelah restore untuk
     menjaga skema tetap sinkron, tapi belum pernah dieksekusi di bawah kondisi skema yang sangat
     berbeda.

### Hasil jika prosedur gagal

- **Rollback deploy gagal:** Aplikasi tetap di versi baru atau tidak naik sama sekali. Isolasi
  penyebab lewat `railway logs --service web`.
- **Mundur migrasi gagal:** Database dalam keadaan terputus skemanya dari kode aplikasi. Restore
  dari cadangan diperlukan.
- **Perbaikan index invalid gagal:** Index tetap tidak dipakai, halaman tetap lambat. Cek
  permission DB (apakah user Postgres punya `SUPERUSER`/`CREATEDB` untuk `CONCURRENTLY`?).
- **Restore gagal:** Data tetap rusak di target. Cek koneksi database, space disk, dan format
  dump (apakah checksumnya cocok?).

### Yang perlu diteskan di depan (sebelum keadaan darurat nyata)

1. Di VPS `toa`: jalankan `sudo systemctl start toa-cadangan.service` (uji backup sekali secara
   manual).
2. Restore uji dari backup terakhir ke database sekali-pakai di `toa`, verifikasi count/sums.
3. Di staging Railway: deploy versi commit lama tujuan rollback, verifikasi aplikasi naik.
4. Jalankan migrasi mundur yang **aman** — `python manage.py migrate transactions 0011` (membalik
   0012, `remove_index(concurrently=True)`) — di **staging** `toa_staging` dengan dump backup,
   pastikan lolos tanpa error dan `periksa_index` sesudahnya bersih. **Jangan** menguji
   `migrate transactions 0010`/`0009`: itu membalik 0011 (`CREATE INDEX` blokir-tulis ×4).

---

## Lihat juga

- [`docs/runbook-cadangan-2026-09-04.md`](./runbook-cadangan-2026-09-04.md) — Cadangan basis data
  dan restore.
- `core/db_ops.py` — Penjelasan `TambahIndexAman`, penjaga otomatis, dan alasan design.
- `core/management/commands/periksa_index.py` — Logika pemeriksaan index.
- `core/management/commands/periksa_kesehatan.py` — Logika pemeriksaan kesehatan sistem.
- `railway.json` — Start command yang menjalankan `migrate` sebelum gunicorn.
- `CLAUDE.md` (bagian Deployment, Performa) — Filosofi dan trade-off infrastruktur.
