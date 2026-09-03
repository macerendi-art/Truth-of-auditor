# Daftar Perbaikan — Truth of Auditor

**Disusun 3 September 2026 · versi berjalan v1.24.0**

Semua butir di bawah punya bukti terukur atau kutipan kode, bukan saran umum.
Sumbernya: audit kelayakan enterprise 4 sudut + pengukuran waktu 23 halaman di
produksi + investigasi anomali matcher (8 agen, 2 September 2026).

Urutannya berdasarkan **kerugian kalau terjadi**, bukan kemudahan mengerjakan.

---

## A. Kehilangan data — kerjakan lebih dulu

| # | Masalah | Bukti | Usaha |
|---|---|---|---|
| A1 | **Tidak ada cadangan basis data sama sekali** | `pgbackrest info` → "No stanzas exist"; `archive_mode=off`; tanpa cron; tanpa `WAL_ARCHIVE_BUCKET` | ½–1 hari |
| A2 | **Berkas unggahan hilang tiap deploy** | service `web` → `volumeMounts: []`; `MEDIA_ROOT` di disk kontainer | 2 jam |
| A3 | **`SECRET_KEY` + `DATABASE_URL` bocor belum dirotasi** | Terekspos di log sesi 31-08-2026; riwayat 20 deployment tak menunjukkan perubahan variabel sesudahnya | 1 jam |

A1 dan A2 saling mengunci: tanpa cadangan **dan** tanpa berkas asli, kehilangan
basis data berarti kehilangan segalanya — bukan sebagian. Angka terukur: dump
terpadatkan **1,9 GB**, **4 menit 38 detik**, biaya penyimpanan ±$3/bulan.

---

## B. Kegagalan yang tidak terlihat

| # | Masalah | Bukti | Usaha |
|---|---|---|---|
| B1 | **Tidak ada satu alarm pun** | Tidak ada cron/scheduler di `railway.json` maupun `Procfile`; `periksa_kesehatan` sudah jadi tapi tak ada yang menjalankannya | 3 jam |
| B2 | **Tidak ada pelacak error** | Nol `sentry-sdk`/`rollbar`; `ADMINS`/`SERVER_EMAIL` tak didefinisikan; `LOGGING` membuang handler `mail_admins` | 3 jam |
| B3 | **Log akses mati total** | `Procfile` gunicorn tanpa `--access-logfile` — nol baris untuk request normal | 15 menit |
| B4 | **Log tanpa format** | `LOGGING` hanya `StreamHandler` tanpa `formatters`; root level `WARNING` menelan semua `logger.info` | 1 jam |
| B5 | **Retensi log terbatas plan, tanpa log drain** | Railway 7–30 hari tergantung plan; tak ada Vector/OTel | 2 jam |
| B6 | **Setelah 3× crash service diam** | `restartPolicyMaxRetries: 3` — tak ada yang memberi tahu siapa pun | ikut B1 |

---

## C. Keamanan

| # | Masalah | Bukti | Usaha |
|---|---|---|---|
| C1 | **HSTS mati di produksi** | `SECURE_HSTS_SECONDS` tak di-set → default `0`; dikonfirmasi lewat header live | 15 menit |
| C2 | **Tidak ada CSP** | Tidak ada `core/middleware.py`; header absen di `curl -I` | 2 jam |
| C3 | **Sesi login berlaku 2 minggu** | `SESSION_COOKIE_AGE` tak di-set → default Django, untuk data keuangan | 15 menit |
| C4 | **Tanpa pembatas percobaan login** | Nol `django-axes`/ratelimit/lockout/MFA; `AuditorLoginView` subclass polos | ½ hari |
| C5 | **Jejak audit tanpa IP** | `core/audit.py` `catat()` tak menerima `request` — 33 titik panggil, nol IP/user-agent | 2 jam |
| C6 | **Login/logout/gagal-login tak diaudit** | `web/signals.py` hanya set flag sesi; hanya `User.last_login` (satu field, bukan riwayat) | 2 jam |
| C7 | **Tanpa proses pembaruan dependensi** | Hari ini bersih (25/25 paket, 0 CVE, semua versi terbaru) — tapi tanpa CI/Dependabot, kepatokan menua diam-diam | 1 jam |

> C1–C3 sebenarnya pernah ditulis rekan tim pada commit `4121718` (5 Juli 2026)
> tapi commit itu **tidak pernah masuk `main`** — hanya hidup di `pr4`. Tinggal
> dipungut, bukan dibuat dari nol.

---

## D. Kecepatan — yang benar-benar terukur lambat

Dari 23 halaman utama, semuanya di bawah 2 detik **kecuali** yang di bawah ini.

| # | Halaman | Terukur | Sebab | Usaha |
|---|---|---|---|---|
| D1 | `/mutasi-bank/?upload=<id>` | **46 dtk dingin / 37 dtk panas** | Agregat m2m `duplicate_transactions` (`web/views.py` ±2098). **Tidak membaik saat dipanaskan** → polanya yang salah, bukan cache | ½ hari |
| D2 | `/hutang-piutang/` mode Semua Toko | 13,4 dtk dingin | Menyapu 29 toko dalam 6 query berat; jumlah query tetap konstan (bukan N+1) | ½ hari |
| D3 | `/batch/<pk>/` | 0,9 dtk tapi **226 query** | Pola N+1; belum menyakitkan, akan tumbuh | 2 jam |
| D4 | `/reconcile/` | 1,9 dtk | `check_completeness` 5× EXISTS tanpa partial index — sudah tercatat di backlog v1.18.0 | 3 jam |
| D5 | `/tinjau/` | 0,3 dtk tapi **94 query** | Tak berkorelasi jumlah baris toko; diduga N+1 per item antrian | 2 jam |
| D6 | Toko pasif bayar mahal | k25 `/rekening/` 3,0 dtk vs mxw 1,2 dtk — padahal k25 6× lebih kecil | Datanya dingin di cache karena tak disentuh trafik | riset dulu |

---

## E. Rekonsiliasi

| # | Masalah | Bukti | Catatan |
|---|---|---|---|
| E1 | **COR/g25 22–29 dtk, ketepatan turun ke 93,5%** | Panel DP QRIS ELITE tak punya kolom `Transaction ID`; ID milik ELITE nol kecocokan di panel (400 ID × 2.000 baris) | **Perbaikannya di DATA, bukan kode.** Butuh pihak panel atau ELITE |
| E2 | **Rekonsiliasi jalan sinkron di dalam request** | `web/views.py` memanggil `run_batches_auto` langsung; Cloudflare timeout 100 dtk, gunicorn 120 dtk, tanpa antrian & tanpa retry | Run lambat → 524 tanpa jejak |
| E3 | **`_money_phones` memanen ID vendor sebagai nomor HP** | 7.775 dari 8.284 baris uang ELITE punya 2 "phones" palsu | Belum menghasilkan pasangan salah (19 diperiksa satu-satu) — biaya + risiko laten |
| E4 | **`run_batch` belum terukur ulang** | Agen pengukur gagal (VPS mati 49 menit) dan melaporkan gagal, bukan mengarang angka | Satu-satunya lubang di data pengukuran |

---

## F. Praktik rekayasa

| # | Masalah | Bukti | Usaha |
|---|---|---|---|
| F1 | **Tidak ada CI** | Tidak ada `.github/workflows/`; tak ada langkah tes di jalur deploy | 3 jam |
| F2 | **Tidak ada uji anti-regresi performa** untuk 4 halaman v1.23.0 | Nol `assertNumQueries` di `tests_rekening/biaya/breakdown/detail_fr` — polanya sudah ada di `tests_bracket_carry.py` untuk dicontoh | 1 hari |
| F3 | **Tidak ada staging** | VPS Contabo punya salinan penuh tapi FASE 3+ belum dijalankan | 1–2 hari |
| F4 | **Tidak ada alat coverage** | `coverage`/`pytest-cov` tak terpasang; klaim cakupan bersandar rasio baris | 1 jam |
| F5 | **Ketergantungan satu orang** | Deploy manual dari satu checkout oleh satu orang; tanpa gerbang otomatis | ikut F1 |
| F6 | **`TambahIndexAman` menelan kegagalan build** | Migrasi tercatat selesai walau index gagal dibangun → halaman lambat diam-diam. `periksa_index` ada sebagai penawar tapi harus dijalankan manual | ikut B1 |

---

## G. Infrastruktur

| # | Masalah | Bukti | Usaha |
|---|---|---|---|
| G1 | **Titik gagal tunggal di kedua sisi** | web `numReplicas: 1`, Postgres `numReplicas: 1`, `pg_stat_replication` kosong | biaya, bukan waktu |
| G2 | **Prosedur rollback tak terdokumentasi & belum pernah diuji** | Migrasi aditif-saja (nol `RemoveField`/`DeleteModel`) jadi aman secara kebetulan, bukan karena tooling | ½ hari |
| G3 | **Tiga setelan Postgres menunggu restart** | `dynamic_shared_memory_type` mmap→posix, `max_worker_processes` 8→16, `wal_buffers` 16MB→64MB | 30 menit |
| G4 | **`max_parallel_workers_per_gather` 2→4 belum diterapkan** | Terukur 15,1 dtk → 5,9 dtk pada agregat tabel penuh | 15 menit |
| G5 | **719 MB index mati aman dibuang** | `reference` + `username` (base + `_like`) — satu-satunya pemakaian di seluruh kode adalah `icontains`, yang tak bisa dilayani btree | 2 jam |

---

## H. Cacat data yang diketahui dan belum dibereskan

| # | Masalah | Bukti |
|---|---|---|
| H1 | **`row_hash` QRIS Flyer bocor lewat format desimal** | Satu transaksi bisa menghasilkan dua hash beda antar bentuk berkas. Terbukti: BSW 12-08 diunggah dua kali → 1.366 baris ganda. Sudah ditandai `is_duplicate`, tapi resepnya belum diperbaiki — **jangan diganti begitu saja**, semua baris lama memakai resep sekarang |
| H2 | **6.118 baris sampah shape-3 di produksi** | Baris ber-`ticket_no=""`, `amount=0`, `posted_date=NULL` dari 5 unggahan di 4 toko. Inert (nol dikonsumsi, nol MatchResult) — menghapusnya keputusan pemilik data |

---

## Yang sudah baik, dan sebaiknya tidak dibongkar

Supaya daftar di atas tidak terbaca sebagai "semuanya rusak":

- **Otorisasi per toko** — 47 rute ditelusuri satu per satu, nol yang lolos.
- **Dependensi** — 25/25 paket, **0 CVE**, semuanya di versi terbaru hari ini.
- **Tes** — 1.988 tes; baris tes **melebihi** baris kode di semua area, termasuk
  matcher dan ingest. Dikalibrasi terhadap data produksi nyata, bukan sintetik.
- **Disiplin migrasi** — aditif saja, nol operasi destruktif sepanjang riwayat.
- **Disiplin performa** — mengunci *bentuk* query (`assertNumQueries`, bentuk SQL),
  bukan angka milidetik yang rapuh.
- **Dokumentasi kausal** — keputusan non-jelas menjelaskan *mengapa* dan *apa
  konsekuensinya*, sehingga tidak dibongkar orang berikutnya karena tidak tahu.

**Celah terbesarnya bukan mutu kodenya — melainkan otomasi di sekelilingnya.**
Tidak ada yang menjalankan tes, pemeriksaan index, atau pemeriksaan kesehatan
selain manusia yang mengingatnya.
