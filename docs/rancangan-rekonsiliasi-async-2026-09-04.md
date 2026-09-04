# Rancangan rekonsiliasi asinkron (E2) + pengukuran `run_batch` (E4)

Tanggal: 4 September 2026 · Status: **RANCANGAN — tidak diterapkan** (keputusan pemilik, prompt eksekusi §3). Nol perubahan kode produksi. Keputusan go/no-go ada di GERBANG 3.

Dokumen ini menjawab dua butir daftar perbaikan 03-09-2026: **E2** (rekonsiliasi berjalan sinkron di dalam request HTTP, tanpa antrian, tanpa retry) dan **E4** (`run_batch` belum pernah terukur ulang). Semua angka punya sumber; yang tidak terverifikasi ditandai **[belum diverifikasi]**. Angka lokal selalu disebut skalanya dan **bukan angka produksi**.

---

## 0. Ringkasan untuk pengambil keputusan

1. **`run_batch` terukur**: 2,8–2,9 detik per hari penuh (±7,9 rb baris panel, 3 ulangan, variansi ±2 %) pada DB lokal SQLite 71.584 baris, rezim **ber-kunci** (100 % panel ber-ticket). Produksi (dari `CLAUDE.md`, terukur 25-08-2026): 1,3 dtk pada hari ber-UUID, **22–29 dtk** pada hari QRIS ELITE tanpa kunci (g25, 9.623 baris).
2. **Batas kerasnya bukan gunicorn.** `--timeout 120` tidak membunuh request panjang pada worker `gthread` (heartbeat berjalan di loop utama, request di thread pool — dibaca dari sumber gunicorn 26.2.0). Batasnya adalah proxy di depan: Cloudflare (brief: 100 dtk; dokumentasi resmi hari ini: **125 dtk**) atau Railway edge (5 menit tanpa data / 15 menit maksimum) — tergantung pengguna masuk lewat domain mana.
3. **"524 tanpa jejak" tidak tepat.** Saat Cloudflare memutus, request di origin **tetap berjalan sampai selesai dan commit** — batch terbentuk, baris terkonsumsi, jejak audit tertulis. Yang hilang hanya *pandangan pengguna*; kebenaran data sudah dijaga `atomic()` + constraint unik. Celah nyatanya: pengguna tidak tahu apa yang terjadi, klik ulang menghasilkan pesan `IntegrityError` mentah, dan deploy di tengah run membatalkannya diam-diam.
4. **Pemicu realistis bukan pertumbuhan, melainkan tumpukan tanggal.** `run_batches_auto` memproses SEMUA tanggal panel dalam satu request. Empat hari ELITE g25 yang tertunda (libur, atau batch dihapus untuk diulang) = 4 × 29 = **116 dtk > 100 dtk — hari ini juga**, tanpa satu baris pun bertambah.
5. **Rekomendasi: bertahap.** Fase 0 (satu baris: rekam durasi tiap run) + Fase 1 (kunci per-toko, pesan ramah, batasi jumlah tanggal per klik — hasilnya terbukti identik dengan sekali-jalan) **sekarang**; worker antrean berbasis tabel Postgres (Fase 2, tanpa broker baru, ±4–5 hari kerja) **hanya bila** E1 (perbaikan data ELITE) tidak terwujud DAN durasi terekam mendekati 50 dtk. E1 sendiri mengembalikan g25 ke ±1,3 dtk — itu mitigasi E2 termurah.

---

## 1. Bentuk masalahnya, dengan angka

### 1.1 Apa yang sebenarnya terjadi hari ini saat run lambat

Jalur: browser → (Cloudflare bila lewat `auditor.wolfgang-77.com`) → Railway edge → gunicorn `gthread` (4 worker × 8 thread) → `web.views.reconcile` → `run_batches_auto` → `run_batch` per tanggal (masing-masing `@atomic`).

Lapisan batas waktu, dari luar ke dalam — **setiap klaim di sini dibaca dari sumber primer, bukan dari brief**:

| Lapisan | Batas | Sumber | Catatan |
|---|---|---|---|
| Cloudflare (domain ber-proxy) | brief: **100 dtk**; dokumentasi: **125 dtk** (Proxy Read Timeout) | developers.cloudflare.com, halaman Error 524, dibaca 04-09-2026: *"the origin did not provide an HTTP response before the default 125 seconds Proxy Read Timeout"*; hanya Enterprise yang bisa menaikkannya (sampai 6.000 dtk) | Dokumen ini memakai **100 dtk** sebagai batas rancangan karena itu persyaratan pemilik dan lebih konservatif; selisih 25 dtk dicatat, bukan diabaikan. Cloudflare sendiri menyarankan subdomain DNS-only untuk request >125 dtk |
| Railway edge (domain `*.up.railway.app`) | ditutup setelah **5 menit tanpa data**; maksimum **15 menit** bila data terus mengalir | docs.railway.com "Specs & Limits", dibaca 04-09-2026 | Pengguna yang masuk langsung ke domain Railway punya batas yang jauh lebih longgar dari pengguna Cloudflare |
| gunicorn `--timeout 120` | **BUKAN batas** untuk request panjang di `gthread` | `gunicorn/workers/gthread.py` 26.2.0: loop `run()` memanggil `self.notify()` tiap iterasi (≤1 dtk) sementara request dijalankan di `tpool`; `arbiter.murder_workers` hanya membunuh bila `last_update` lebih tua dari `timeout` | Menaikkan angka ini **tidak menyelesaikan apa pun**. Ia hanya relevan bila loop utama macet |
| gunicorn `graceful_timeout` | **30 dtk** (default, dibaca dari `gunicorn.config.GracefulTimeout.default`) | saat SIGTERM (deploy `railway up`), worker berhenti menerima koneksi dan menunggu in-flight paling lama 30 dtk lalu keluar; thread request mati bersama proses → Postgres rollback | Run 29 dtk yang sedang berjalan saat deploy **selamat tipis**; tumpukan 2 hari tidak. Rollback aman (atomic), tetapi pengguna hanya melihat halaman error |

**Yang terjadi pada 524.** `gthread.handle_request` memanggil `self.wsgi(environ, start_response)` sampai view *selesai* sebelum menulis satu byte pun. Cloudflare memutus koneksi ke origin pada detik ke-100/125, tetapi thread Python tidak mengetahuinya sampai mencoba menulis respons. Jadi urutan nyata: `run_batches_auto` selesai → semua `run_batch` commit → `catat("reconcile")` tertulis → `messages.success` disimpan → *baru* penulisan respons gagal (broken pipe, tercatat di log gunicorn). **Batch ada, jejak audit ada.** Kalimat "524 tanpa jejak" di daftar perbaikan benar dari sudut pengguna, salah dari sudut data.

**Celah nyata, diurutkan dari yang sudah terjadi ke yang mungkin:**

1. **Tak terlihat.** Pengguna mendapat halaman Cloudflare, tidak tahu batch sudah jadi, tidak tahu tanggal mana yang selesai.
2. **Klik ulang saat run pertama masih berjalan.** Request kedua lolos `exists()` di awal `run_batch` (batch pertama belum commit), lalu `ReconBatch.objects.create` **memblokir** di index unik `uniq_reconbatch_toko_recon_date` sampai transaksi pertama commit (semantik index unik Postgres — pendatang kedua menunggu pemilik kunci yang belum commit; **[tidak diukur, semantik dokumentasi Postgres]**), lalu gagal `IntegrityError`. `run_batches_auto` menangkapnya per tanggal dan `reconcile` menampilkan `str(e)` mentah — pesan DB bahasa Inggris di layar pengguna. Kebenaran terjaga (tidak ada batch ganda), pengalamannya buruk. Catatan: `<form data-busy>` menonaktifkan tombol di tab yang sama; tab kedua atau klik setelah 524 tidak tercakup.
3. **Deploy di tengah run** (butir `graceful_timeout` di atas): rollback bersih, tetapi senyap.
4. **Klik ulang setelah 524 selesai** — aman: tanggal ber-batch dilewati (`skipped_existing`). Dibuktikan di §3.2.

Sepanjang run, request memegang **1 dari 32 thread** dan **1 koneksi DB** — bukan soal kapasitas.

### 1.2 Pengukuran `run_batch` (menutup E4)

**Metodologi.**
- DB: `db.sqlite3` worktree (**71.584** baris `Transaction`, 4 `ReconBatch` lama, 120.305 `MatchResult`) disalin ke scratchpad, di-`migrate` ke skema HEAD (`transactions/0011`, `core/0003` ikut). Berkas asli tak disentuh (md5 diverifikasi tak berubah).
- Lingkungan: macOS 26.6.1 arm64 (Apple Silicon, 10 core), Python 3.11.15, SQLite 3.53.1, Django 5.2.17. **Bukan Postgres, bukan Railway.**
- Tiap putaran: hapus semua batch lewat jalur resmi (`revert_late_settlements` + `delete` — `SET_NULL` membebaskan `consumed_by_batch`, diverifikasi 0 baris terkonsumsi), lalu `run_batches_auto(toko, Default, None, None, include=semua)` — persis argumen view `reconcile` saat semua sakelar dicentang. `run_batch` dan `run_match` dibungkus pengukur `perf_counter` lewat monkeypatch atribut modul (keduanya dipanggil lewat nama global, jadi bungkusnya kena; kode engine tak diubah). 3 putaran bersih, 1 putaran dengan `CaptureQueriesContext` (pemisah SQL/Python), 1 putaran `cProfile`.
- Skrip: `scratchpad/ukur_run_batch.py`, hasil mentah `ukur_run_batch.json`, profil `ukur_run_batch_profile.txt` (tidak di-commit).

**Data yang ada di DB lokal** — dua toko Nexus, data Juni 2026 (Fase-0 kalibrasi): `lbs` panel 27–28/06 (7.933 + 8.066 baris), `k25` panel 27/06 (7.932); gateway NXPay 6.633 baris **semua ber-ticket**; bank BCA/BRI rolling 01–28/06; bracket ±8,4 rb. **Panel 100 % ber-ticket; Panel↔Bracket berjalan mode ticket (7.915/7.933 cocok).** Ini rezim **ber-kunci** ("hari ber-UUID/ticket" dalam bahasa `CLAUDE.md` §Anomali). **Tidak ada satu pun hari rezim ELITE (tanpa kunci) di data lokal** — pengukuran ini tidak mewakili rezim yang justru menjadi masalah di produksi; untuk rezim itu dipakai angka produksi §1.3.

**Hasil per `run_batch` (detik, wall-clock, 3 putaran):**

| Toko · tanggal | Panel (left) | Uang (right) | Bracket | `run_batch` | Panel↔Bracket | Panel↔Bank | Sesama CM↔Bank | MatchResult | Terkonsumsi |
|---|---|---|---|---|---|---|---|---|---|
| lbs 26/06 | 1 | 109 | — | 0,72–0,78 | dilewati | 0,19–0,24 | dilewati | 110 | 272 |
| lbs 27/06 | 7.933 | 7.777 | 3 | **2,87–2,91** | 0,57–0,58 | 1,09–1,12 | 0,47–0,49 | 16.313 | 15.433 |
| lbs 28/06 | 8.066 | 9 | 8.066 | 2,02–2,03 | 0,68–0,71 | 0,60 | 0,15–0,17 | 16.348 | 8.402 |
| k25 26/06 | 1 | 109 | 3 | 0,83–0,86 | 0,14 | 0,15–0,16 | 0,16 | 277 | 275 |
| k25 27/06 | 7.932 | 7.652 | 7.934 | **2,80–2,84** | 0,68–0,73 | 0,95–0,99 | 0,41–0,43 | 16.306 | 23.644 |

`run_batches_auto` utuh: lbs 5,69–5,76 dtk (3 tanggal), k25 3,71–3,75 dtk (2 tanggal). Lantai biaya tetap (hari dengan 1 baris panel): **0,7–0,9 dtk** — `check_completeness`, `verify_panel_anchor`, `_carried_results`, `_retro_homes`, `_aggregate_batch`, dan UPDATE konsumsi.

**Pemisahan SQL vs Python** (`CaptureQueriesContext`, satu putaran): lbs SQL 2,02 dari 5,72 dtk (**35 %**, 501 query ≈ 167/batch); k25 1,51 dari 3,77 dtk (**40 %**, 300 query). Query terlama 0,27–0,30 dtk = `SELECT DISTINCT` pool sisi uang; `UPDATE … consumed_by_batch_id` 0,13–0,17 dtk.

**Profil (`cProfile`, k25 2 tanggal, overhead profiler ≈2×: 7,66 dtk):**

| Fungsi | cumtime | ncalls | Arti |
|---|---|---|---|
| `run_match` (6×) | 5,38 | 6 | 72 % dari `run_batch` |
| `sides()` ×4 kelas matcher | 1,35 + 1,23 + 1,07 + 0,77 = **4,4** | 8 | **memuat** objek `Transaction` (bukan mencocokkan): 118.654 `Model.__init__`, 1,64 juta `typecast` SQLite |
| `_MoneyMatcher.match` | 0,75 | 2 | pencocokan uang seluruhnya |
| `_identity` | 0,383 | **62.751** | pasangan pass 1 → **6,1 µs/pasangan** |
| `_name_score` / `kandidat` / `_phone_match` | 0,26 / 0,09 / 0,08 | 62.025 / 65.450 / 62.751 | |
| `_aggregate_batch` | 0,80 | 2 | |
| `_retro_homes` / `check_completeness` / `verify_panel_anchor` / `_carried_results` | 0,30 / 0,10 / 0,09 / 0,03 | | biaya orkestrasi kecil |
| `panel_ticket_set` (B2, tanpa filter tanggal, tanpa `_active`) | 0,005 | 1 | 7.933 tiket lokal — **satu-satunya suku di `run_batch` yang tumbuh dengan UMUR toko** (semua tiket panel sepanjang masa); belum diukur di produksi |

**Apa yang bisa dan tidak bisa dipindahkan ke produksi dari angka ini:**
- **Bisa:** biaya per pasangan `_identity` **6,1 µs** lokal vs **5,88 µs** produksi (`CLAUDE.md`, 4.969.497 pasangan ↔ 29,2 dtk). Kesesuaian ini alasan ekstrapolasi §1.4 memakai konstanta produksi dengan tenang.
- **Tidak bisa:** rasio "memuat 4,4 dari 7,5 dtk" — SQLite mengubah tipe tanggal di Python (1,64 juta panggilan `typecast`); psycopg2 melakukannya di C. Rasio SQL 35–40 % juga milik SQLite, bukan Postgres.
- **Tidak ada:** rezim ELITE. Pasangan pass 1 lokal 62.751 vs produksi ELITE 4.969.497 — **79× lebih sedikit**; itulah perbedaan "hari ber-kunci" vs "hari tanpa kunci".

### 1.3 Angka produksi yang sudah ada (bukan dari sesi ini)

Dari `CLAUDE.md` §"Anomali matcher 25-08-2026", terukur di produksi:
- g25 sebelum 25-08 (QRIS UNO, UUID di kedua sisi, pass 0b melahap 78–88 % pool): **±1,3 dtk** pada 9.489 baris.
- g25 sesudah (QRIS ELITE, tanpa kunci): **22–29 dtk** (terukur 29.219 ms) pada 9.623 baris; 8.502 baris panel × bucket nominal = 4.969.497 pasangan × 5,88 µs. Mutu turun 95–97 % → 93,5 %.
- Sebarannya: hanya Vigor/TM Gaming yang kehilangan kunci — g25 (40.132 baris), w25 (3.137), cah (1.254). Dua belas brand Nexus tetap ber-ticket.

### 1.4 Jarak ke batas dan kapan tercapai — dengan ketidakpastiannya

**Model** (dari profil produksi): `t ≈ t_tetap + 5,88 µs × pasangan`; pasangan ∝ n² pada distribusi bucket nominal yang sama (matcher = "dinding kuadrat", kalibrasi 09-07-2026).

| Kasus | Waktu run tunggal | Jarak ke 100 dtk (brief) | Jarak ke 125 dtk (Cloudflare) |
|---|---|---|---|
| Brand Nexus / hari ber-kunci (produksi 1,3 dtk; lokal 2,8 dtk SQLite) | 1,3–3 dtk | **>30×** | >40× |
| g25 hari ELITE, 1 tanggal | 29 dtk | **3,4×** waktu → **≈1,85×** baris harian (√3,4) → ambang **≈15–16 rb baris panel/hari** (dari 8.502) | 4,3× → ≈2,1× baris |
| g25 hari ELITE, **tumpukan N tanggal dalam satu klik** | N × 29 dtk | **N = 4 sudah lewat (116 dtk)** | N = 5 (145 dtk) |

**Pemicu yang paling dekat adalah baris ketiga**, dan tidak butuh pertumbuhan: `run_batches_auto` mengulang semua tanggal panel aktif dalam satu request. Tumpukan 4 hari lahir dari libur panjang, dari `bulk_delete_batches` untuk mengulang seminggu, atau dari onboarding toko baru dengan ekspor sebulan. Ini bisa terjadi **besok**.

**Ketidakpastian, terang-terangan:**
1. **Tidak ada deret waktu volume harian per toko.** Dua titik g25 (9.489 → 9.623) berasal dari jendela anomali beberapa hari dan bukan laju; angka "±185 rb baris/hari" dan "11 GB/bulan" adalah total 16 toko + bank + bracket. **Tanggal tercapainya tidak bisa diperkirakan dengan jujur** — yang bisa diberikan adalah ambang dalam baris (≈15–16 rb panel/hari untuk g25-ELITE), dan Fase 0 di §4 adalah cara mendapatkan deretnya.
2. Konstanta 5,88 µs milik CPU kontainer Railway. Migrasi ke VPS Contabo (`docs/rencana-migrasi-contabo-2026-08-31.md`) mengubahnya ke arah yang belum diketahui — ukur ulang di sana.
3. **E1 meruntuhkan seluruh baris kedua dan ketiga**: begitu panel/ELITE membawa kunci, pass 0/0b hidup lagi → ±1,3 dtk/hari (mekanismenya terbukti di hari UNO). E1 adalah mitigasi E2 yang paling murah dan satu-satunya yang juga memperbaiki mutu.
4. Batas Cloudflare 100 vs 125 dtk (§1.1). Rancangan memakai 100.
5. Bagian yang tumbuh dengan umur (`panel_ticket_set`) belum diukur di produksi; di skala 40 rb baris panel g25 hari ini masih puluhan milidetik, tetapi ia linier terhadap usia toko.

---

## 2. Pilihan arsitektur

Harga Railway (halaman pricing, dibaca 04-09-2026): CPU **$0,00000772/vCPU-detik ≈ $20/vCPU-bulan**, memori **$0,00000386/GB-detik ≈ $10/GB-bulan**, tidak ada biaya tetap per service — hanya pemakaian. Perkiraan bulanan di bawah **[perkiraan dari tarif, belum diverifikasi dengan tagihan]**: satu proses Django idle ±150–250 MB RSS (kontainer web dengan 2 worker terukur 283 MB, docstring `core/tests_start_command.py`), CPU idle mendekati nol, sibuk hanya puluhan detik per run.

Anggaran koneksi hari ini: web 4 × 8 = **32** persisten + 10 cadangan = 42 dari `max_connections=100` (dijaga `core/tests_start_command.py`). Setiap opsi di bawah menyebut tambahannya.

### Opsi A — Celery + Redis

- **Cara kerja:** service Redis di Railway sebagai broker; service worker `celery -A truth_auditor worker --pool solo --concurrency 1` menjalankan task `jalankan_rekonsiliasi(job_id)`. `acks_late=True` + `task_reject_on_worker_lost=True` supaya task tak hilang saat worker mati; `visibility_timeout` Redis harus > durasi task terpanjang atau task **dikirim ulang saat masih berjalan** (footgun yang sama dengan django-q2 di bawah).
- **Biaya:** Redis ±0,1–0,3 GB + worker ±0,25 GB + CPU kecil ≈ **$4–8/bulan** [perkiraan]. Dua dependensi baru (`celery`, `redis`) di `requirements.txt` yang sengaja dipatok dari `pip freeze` produksi.
- **Layanan baru yang harus dijaga:** Redis (persistensi, memori, versi) + worker. Dua hal yang bisa mati diam-diam, dua hal yang harus masuk pemantauan B1/B6.
- **Koneksi DB:** +1 (pool solo).
- **`Procfile`/`railway.json`:** `web:` tak berubah → tes identik tetap lolos; worker butuh start command sendiri (lihat §2.5).
- **Rollback:** flag `REKON_ASYNC=false` → view kembali ke jalur sinkron; Redis + worker bisa dibiarkan atau dihapus. Task yang sudah antre di Redis hilang bila Redis dihapus — kosongkan dulu.
- **Penilaian:** matang, tetapi membeli broker untuk beban **puluhan job per hari** (16 toko × 1–3 run). Semua kesulitan sebenarnya (§3) tetap harus dirancang sendiri — Celery tidak menyelesaikan satu pun dari empat batasan itu.

### Opsi B — `django-q2` (broker ORM) / `huey`

- **Cara kerja:** cluster `qcluster` dengan tabel `OrmQ` di Postgres yang sudah ada; `workers=1`.
- **Biaya:** worker ≈ **$2–4/bulan** [perkiraan]; satu dependensi baru.
- **Koneksi DB:** cluster = sentinel/scheduler + pusher + monitor + N worker; dengan broker ORM **masing-masing memegang koneksi sendiri** → ±4–5 untuk `workers=1`. Dokumentasi resminya bahkan menyarankan *DB terpisah* untuk broker — bertentangan dengan alasan memilih opsi ini.
- **Semantik retry (dokumentasi resmi `configure.html`, dibaca 04-09-2026):** `retry` = *"The number of seconds a broker will wait for a cluster to finish a task, before it's presented again."* dan *"The value must be bigger than the time it takes to complete longest task, i.e. timeout must be less than retry value."* Kalau tidak, *"Django-Q2 will start the task again"*. **Ini persis pertanyaan pembunuh di §3.2** — dan jawabannya di sini adalah "setel angkanya dengan benar", bukan mekanisme. `ack_failures` menandai task gagal sebagai terkirim; `max_attempts` default **0 = tak terbatas** — exception deterministik (mis. tanggal salah) akan diulang selamanya kecuali disetel.
- `huey`: broker bawaan Redis/SQLite/memori; Postgres hanya lewat `huey.contrib.sql_huey` (peewee) — menambah ORM kedua ke proses. Tidak dibahas lebih jauh.
- **Rollback:** sama dengan A (flag), tabel `OrmQ`/`Task` tinggal sebagai migrasi pihak ketiga di skema produksi.
- **Penilaian:** "tanpa broker" ternyata **4–5 koneksi dan satu proses supervisor pihak ketiga** yang perilaku gagalnya diatur konstanta. Untuk 1 worker, kerangka ini lebih berat daripada yang ia gantikan.

### Opsi C — Tetap di dalam request, geser batasnya

Tiga varian, semua **murah dan semua tidak memuaskan**:
1. **Streaming response** (heartbeat spasi tiap 10 dtk): lolos 524 Cloudflare, tetapi tetap mentok Railway 15 menit, tetap mati bersama tab browser/deploy, tetap tanpa retry, dan mengubah view menjadi generator (pesan `messages` dan `redirect` tak bisa dipakai lagi setelah byte pertama).
2. **Subdomain DNS-only** untuk endpoint rekonsiliasi (saran Cloudflare sendiri): kehilangan WAF/geo-block Cloudflare di jalur itu — `GeoBlockMiddleware` aplikasi masih menggerbang, tetapi lapisan luarnya hilang. Batas menjadi 5/15 menit Railway.
3. **Thread di dalam proses web + polling status**: view memulai `threading.Thread`, halaman status memantau tabel job. Tanpa proses baru, tanpa biaya. Tetapi thread hidup di worker gunicorn: mati saat worker di-recycle/deploy (rollback aman, job hilang), dan 4 worker web berarti 4 antrean yang saling tak melihat — serialisasi per toko hanya bisa lewat kunci DB.

**Kenapa tidak memuaskan:** semuanya memindahkan *tempat* batasnya, bukan menghapus *sebabnya*; tak satu pun memberi retry, status yang bertahan setelah crash, atau pemisahan dari siklus hidup proses web. Varian 3 layak sebagai **jembatan** bila Fase 2 diputuskan ditunda (§4).

### Opsi D — **Worker sendiri berbasis tabel `ReconJob` di Postgres** (direkomendasikan)

- **Cara kerja:** model `reconciliation.ReconJob` (toko, `tolerance`, `date_from`, `date_to`, `include` JSON, `user`, `ip`, `user_agent`, `status ∈ {antre, jalan, selesai, gagal, batal}`, `attempts`, `lease_until`, `worker_id`, `hasil` JSON, `error` teks, `mulai`, `selesai_pada`, `durasi_ms`). Management command `jalankan_antrean_rekonsiliasi`: loop tiap 2 dtk, `SELECT … WHERE status='antre' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1` → tandai `jalan` + `lease_until = now()+30 menit` (transaksi pendek) → panggil `run_batches_auto(**args)` → tandai `selesai`/`gagal` (transaksi pendek). Satu proses, satu thread, **satu koneksi DB**. Berjalan sebagai service Railway kedua dari repo yang sama, `restartPolicyType: ALWAYS` (bukan `ON_FAILURE` ×3 — worker yang menyerah setelah 3 crash = antrean mati senyap).
- **Biaya:** ≈ **$2–4/bulan** [perkiraan tarif], **nol dependensi baru**, semua kode di repo dan diuji suite yang ada (pola yang sudah dipakai repo: JS tanpa dependensi, seed lewat migrasi data, `TambahIndexAman` buatan sendiri).
- **Layanan baru yang harus dijaga:** satu proses worker. Pemantauan = satu query (`status='jalan' AND lease_until < now()` atau `status='antre'` lebih tua dari 10 menit) yang bisa masuk `periksa_kesehatan` (B1).
- **Koneksi DB:** +1 → 33 + 10 = 43 dari 100. `core/tests_start_command.py` harus diperluas supaya aritmetikanya tetap pagar yang dieksekusi, bukan komentar.
- **`Procfile`/`railway.json`:** lihat §2.5.
- **Rollback:** `REKON_ASYNC=false` → view sinkron seperti hari ini (**kode jalur sinkron tidak dihapus**, ia tetap dipanggil worker); worker dibiarkan hidup sampai antrean kosong lalu service dihapus; tabel `ReconJob` tinggal, tidak mengganggu apa pun.
- **Penilaian:** semua yang sulit (§3) harus dirancang sendiri di opsi mana pun; di opsi ini kodenya **terlihat, ±200 baris, dan diuji seperti kode repo lain**, bukan konstanta konfigurasi pustaka. Ini yang direkomendasikan.

### 2.5 Dampak ke `Procfile` / `railway.json` (semua opsi dengan worker)

- `core/tests_start_command.py` membaca **hanya** baris `web:` Procfile dan `deploy.startCommand` di `railway.json`. Menambah baris `worker:` di Procfile **tidak** memerahkan tes identik. Tetapi apakah Railway/Nixpacks menjalankan proses selain `web` dari Procfile **[belum diverifikasi]**.
- Yang terverifikasi (docs Railway "monorepo", 04-09-2026): tiap service bisa punya *start command* sendiri di Service Settings, dan bisa menunjuk berkas konfigurasi sendiri — *"You have to specify the absolute path for the railway.json or railway.toml file"*. Rekomendasi: `railway.worker.json` (start command = `python manage.py jalankan_antrean_rekonsiliasi`, `restartPolicyType: ALWAYS`) + baris `worker:` di Procfile + **tes kembar baru** yang menjaga keduanya identik — mengulang pola tes yang sudah ada.
- Worker **tidak** menjalankan `collectstatic`/`migrate` (milik web). Urutan boot antar-service tidak dijamin, jadi loop worker harus tahan skema tertinggal (query gagal → log → tidur → coba lagi; `ALWAYS` menangani crash).
- Deploy: worker menerima SIGTERM. Fase 2 minimal: tangkap SIGTERM → berhenti mengambil job baru, biarkan `run_batches_auto` yang sedang berjalan selesai bila masih di dalam masa tenggang Railway **[angka masa tenggang Railway belum diverifikasi]**; bila dibunuh: rollback atomic, lease kedaluwarsa, job diulang (§3.2).

### Ringkasan perbandingan

| | A Celery+Redis | B django-q2 | C in-request | D ReconJob+worker |
|---|---|---|---|---|
| Biaya/bulan [perkiraan] | $4–8 | $2–4 | $0 | $2–4 |
| Dependensi baru | 2 | 1 | 0 | **0** |
| Layanan baru dijaga | 2 | 1 | 0 | 1 |
| Koneksi DB tambahan | 1 | 4–5 | 0 | **1** |
| Retry + status bertahan crash | ya (setelan) | ya (setelan) | tidak | ya (kode sendiri) |
| Menjawab §3 | harus dirancang sendiri | harus dirancang sendiri | sebagian | dirancang di §3 |
| Rollback | flag | flag | — | flag |

---

## 3. Batasan yang mengikat rancangan apa pun

Bagian terpenting dokumen ini. Setiap opsi §2 yang mengabaikan salah satunya akan tampak berjalan **dan** merusak hasil tanpa pesan kesalahan.

### 3.1 ⛔ Kontrak determinisme

`CLAUDE.md` §Performa v1.18.0: `order_by("id")` di `sides()` dan pemecah seri `(-left.id, -right.id)` di pass 1 & 3 ada karena tanpanya hasil bergantung rencana eksekusi Postgres (bukti: `[P1,P2]` → cocok=1 vs `[P2,P1]` → cocok=2).

**Memindahkan eksekusi ke worker tidak menyentuh keduanya** — mereka hidup di dalam engine, bukan di pemanggil. Worker memakai modul settings yang sama (`USE_TZ=False`, opsi koneksi sama), jadi tidak ada perbedaan sesi DB. **Yang berubah bukan *di mana* run berjalan, melainkan *kapan*:** pool aktif dibaca saat run **mulai**, bukan saat tombol ditekan. Antrean melebarkan jendela antara keduanya, dan di jendela itu jalur tulis berikut mengubah pool — semuanya **sudah ada hari ini** antara dua pengguna, hanya lebih mungkin dengan antrean:

| Jalur tulis | Efek pada pool | Ada hari ini? |
|---|---|---|
| Ingest unggahan | menambah baris aktif | ya |
| Review manual (`_kunci_baris_override`) | mengonsumsi baris kredit | ya |
| Hapus batch (`delete_batch`/`bulk_delete_batches`) | membebaskan baris (`SET_NULL`) + `revert_late_settlements` | ya |
| Hapus unggahan | menghapus baris (kecuali `_locking_batches` menolak) | ya |

**Jaminan rancangan D:** (1) job menyimpan **argumen**, bukan potret data — persis seperti request hari ini; (2) `pg_advisory_xact_lock(toko_id)` diambil **di dalam** transaksi `run_batch` (Postgres saja; di SQLite/tes no-op lewat `connection.vendor`) sehingga dua run toko yang sama tidak pernah tumpang-tindih — juga bila kelak worker lebih dari satu (`SKIP LOCKED` saja **tidak** menyerialkan per toko); (3) **view hapus batch mengambil kunci yang sama** sebelum `revert_late_settlements` — jadi hapus dan run tidak pernah saling menyela (hari ini bisa); (4) halaman status menulis terang: *"Dijalankan pukul HH:MM memakai data yang ada saat mulai"*. Urutan masukan engine (`order_by("id")`) tidak berubah; yang dijamin rancangan adalah **himpunan** masukannya tidak berubah *di tengah* run.

### 3.2 ⛔ Atomisitas dan eksekusi ganda

`run_batch` = `@atomic`: gagal di tengah → tidak ada batch yatim, tidak ada baris terkonsumsi. Antrean + retry menambah satu pertanyaan yang membunuh implementasi naif:

> **Worker mati SETELAH transaksi `run_batch` commit tetapi SEBELUM job ditandai selesai. Apa yang terjadi?**

Jawaban konkret untuk rancangan D, lapis demi lapis:

1. **Yang tersimpan saat mati:** batch tanggal D1..Dk sudah commit (masing-masing transaksi sendiri), jejak audit untuk tiap batch ditulis di dalam loop (lihat butir 6), job masih `jalan` dengan `lease_until` ±30 menit ke depan.
2. **Pemulihan:** worker berikutnya (restart `ALWAYS`, atau kontainer baru saat deploy) mengambil job `jalan` yang `lease_until < now()` → `attempts += 1` → memanggil `run_batches_auto` **dengan argumen tersimpan yang sama**. Tanggal ber-batch masuk `skipped_existing`; tanggal berikutnya diproses. **Ini persis apa yang terjadi hari ini bila pengguna mengklik ulang** — bukan semantik baru.
3. **Bukti eksekusi, bukan argumen** (skrip `uji_resumable.py`, DB scratch, toko `lbs`): (A) reset → run sekali 26+27+28/06; (B) reset → run `date_to=27` (26+27) → run lagi tanpa batas (hanya 28 baru, 27 `skipped_existing`). Sidik jari `(relasi, left_id, right_id, bucket, reason_code, score)` seluruh 16.348 baris batch 28/06 **identik** (`c2e18f102330c5d9`), himpunan 8.402 baris terkonsumsi **identik** (`5857e6c941f7db94`); daftar `expired` sama (448 tx, dicek programatik). Yang berbeda hanya metadata `ReconBatch.date_from` (26 vs 27 — `lo` dihitung ulang dari panel aktif, dan tak ada lagi baris uang aktif sebelum 27) dan nomor pk batch. Klik ulang setelah selesai (C) tidak mengubah apa pun (B == C, 0 batch baru). Catat jujur: `date_from` yang tampil di halaman batch bisa berbeda antara "sekali jalan" dan "dilanjutkan" — kosmetik, dan **sudah begitu hari ini**.
4. **Eksekusi ganda yang benar-benar bersamaan** (lease kedaluwarsa padahal proses lama masih hidup — mis. run 35 menit, atau dua kontainer saat deploy): `pg_advisory_xact_lock(toko_id)` membuat pendatang kedua **menunggu** sampai transaksi pertama selesai, lalu ia menemukan batch sudah ada → `skipped_existing`. Tanpa kunci ini pun constraint unik menjaga (pendatang kedua memblokir di INSERT lalu `IntegrityError`) — tetapi ia sudah membaca pool dan membuang CPU; kunci membuatnya rapi. **Lease dipilih 30 menit tanpa thread heartbeat** — `run_batches_auto` tidak punya hook per tanggal, heartbeat berarti thread + koneksi kedua; harga yang dibayar adalah pemulihan lambat (≤30 menit) saat worker mati, yang ditangkap `periksa_kesehatan`. Kalau kelak durasi run mendekati lease, naikkan lease — jangan turunkan.
5. **`max_attempts = 2`** lalu `gagal` dengan traceback tersimpan: exception deterministik (tanggal salah, `IntegrityError` dari ras lain) tidak berputar selamanya — ini kelemahan default `max_attempts=0` django-q2.
6. **Jejak audit.** `catat()` hari ini dipanggil view **setelah** `run_batches_auto`, di luar transaksi run, dengan `request` untuk IP/UA. Di worker tidak ada `request`: job membawa `user_id`, `ip`, `user_agent` dari saat enqueue dan `catat` diberi parameter eksplisit `ip=`/`user_agent=` (perubahan kecil di `core/audit.py`). Jendela "commit lalu mati sebelum `catat`" **sudah ada hari ini** dan tidak diperburuk; bila ingin ditutup, `run_batch` menerima hook `on_batch` dan `catat` dipanggil di dalam `atomic`-nya — `reconciliation` boleh mengimpor `core`, **tidak boleh** `web`.
7. **Deploy di tengah run:** SIGTERM → rollback transaksi yang berjalan → lease kedaluwarsa → butir 2. Tanggal yang sudah commit tetap; hanya tanggal yang terputus diulang.

### 3.3 ⛔ Satu batch per `(toko, recon_date)`

Tiga lapis, dari luar ke dalam:
1. **Dedupe saat enqueue:** index unik parsial `ReconJob(toko) WHERE status IN ('antre','jalan')`. Klik kedua untuk toko yang sama → `IntegrityError` ditangkap → **redirect ke halaman status job yang sudah ada** (bukan job baru, bukan pesan error).
2. **Kunci per toko** (`pg_advisory_xact_lock`) selama run — mencegah dua run toko yang sama tumpang-tindih walau job-nya lolos lapis 1 (lease kedaluwarsa, dua kontainer).
3. **Constraint unik DB** `uniq_reconbatch_toko_recon_date` — garis terakhir, tidak berubah, tetap dijaga tes yang ada.

Tidak ada lapis yang bergantung pada broker.

### 3.4 Settlement tertunda & retro write-back

`late_settlement` (flip hasil `no_money` di batch asal), `_add_retro_gross`/`_writeback_retro` (baris susulan ditulis ke batch tanggalnya), dan `revert_late_settlements` (saat hapus batch) semuanya mengandaikan **batch tanggal D+1 dijalankan setelah D, dan hapus tidak menyela run**. Konsekuensi untuk rancangan:
- **Satu worker, FIFO global** memberi urutan itu gratis; di dalam satu job `run_batches_auto` sudah menaik (`for d in panel_dates` — "MENAIK — prasyarat kebenaran carry-over").
- **Hapus batch saat run toko yang sama berjalan** — hari ini bisa terjadi antara dua pengguna: run menulis retro ke `MatchRun` batch yang sedang dihapus → cek FK menunggu kunci baris → salah satu menang: bila hapus commit dulu, INSERT gagal FK → run rollback penuh (aman, membingungkan); bila run commit dulu, hasil retro ikut terhapus bersama batch (baris kredit `SET_NULL` → aktif lagi, sama seperti hari ini). Rancangan menutupnya dengan kunci yang sama di view hapus (§3.1 butir 3): hapus **menunggu** run selesai, atau UI menolak hapus selama ada job `jalan` untuk toko itu.
- **Job yang mulai belakangan melihat lebih banyak baris carried** (unggahan di antara klik dan mulai) — sama dengan pengguna yang mengklik lebih lambat hari ini; bukan defek baru, tetapi harus disebut di halaman status.

### 3.5 Pengalaman pengguna — dirancang, bukan detail

Hari ini: tekan → tunggu → redirect ke batch (1 tanggal) atau flash "N batch dibuat". Dengan antrean:

- **Tekan "Jalankan"** → job dibuat (validasi tanggal/`verify_panel_anchor` **tetap dijalankan sinkron di view** supaya penolakan panel-anchor tetap instan seperti sekarang — itu query murah) → redirect ke `/rekonsiliasi/antrean/<id>/`.
- **Halaman status** memakai HTMX yang sudah ada di `app_base.html` (`hx-trigger="every 3s"` pada satu partial): `antre` (posisi antrean, "di depan: toko X"), `jalan` (mulai pukul, "tanggal yang sudah selesai: 26/06, 27/06 · sedang: 28/06" — dari `ReconBatch` yang commit, tanpa hook engine), `selesai` (ringkasan seperti flash hari ini + tombol ke batch; bila tepat 1 batch, **redirect otomatis ke `batch_detail`** — perilaku sekarang dipertahankan), `gagal` (pesan manusiawi + "tidak ada batch setengah jadi; tanggal 26/06 dan 27/06 sudah selesai" + traceback untuk admin), `batal` (hanya dari `antre`).
- **Chip sidebar** "Rekonsiliasi berjalan · g25" lewat `web.context_processors` — satu query murah di index parsial, mengikuti pola `pending_review_count`. Ini juga pengganti notifikasi: pengguna yang menutup tab tetap melihatnya di halaman mana pun. Email/Telegram **tidak** dirancang (satu tim, satu layar).
- **Panel "Kerjakan hari ini"** dashboard menampilkan job aktif toko itu alih-alih tombol run.
- **Riwayat** job (siapa, kapan, berapa lama, hasil) di halaman Rekonsiliasi di bawah Riwayat Batch — dan `durasi_ms` di sana adalah **instrumen E4 permanen**.
- **Kegagalan worker** (bukan job): `periksa_kesehatan` melapor job `antre` >10 menit atau `jalan` melewati lease → B1/B6.

---

## 4. Rekomendasi tunggal, usaha, jalur bertahap

**Rekomendasi: Opsi D, dikerjakan bertahap, dan Fase 2 digerbangi angka — bukan dijadwalkan.**

| Fase | Isi | Risiko | Usaha | Syarat mulai |
|---|---|---|---|---|
| **0 — Ukur** | `run_batch` menulis `summary["durasi_ms"]` (+ per relasi dari `run_match`). Nol perubahan perilaku; menjadikan tiap run produksi pengukuran E4 dan memberi deret waktu yang §1.4 tidak punya | nihil | ≤ ½ hari termasuk tes | sekarang |
| **1 — Perkuat jalur sinkron** | (a) `pg_advisory_xact_lock(toko_id)` di `run_batch` + view hapus batch (no-op di SQLite); (b) `IntegrityError` batch ganda → pesan "sedang dijalankan pengguna lain / sudah ada"; (c) **batasi tanggal per klik** (mis. 3) dengan flash "3 dari 7 tanggal selesai — tekan lagi untuk melanjutkan": memotong pemicu tumpukan (§1.4 baris 3) tanpa proses baru, dan **terbukti tidak mengubah hasil** (§3.2 butir 3); (d) tombol `data-busy` diperluas lintas-tab lewat cek job/kunci | rendah — tanpa layanan baru, tanpa migrasi kecuali (c) tidak butuh apa pun | 1–2 hari | sekarang; **rilis PATCH/MINOR biasa** |
| **2 — Worker `ReconJob`** | model + migrasi, command worker, flag `REKON_ASYNC`, halaman status HTMX + chip sidebar, `catat(ip=, user_agent=)`, `railway.worker.json` + Procfile `worker:` + tes kembar + perluasan aritmetika koneksi, pemeriksaan di `periksa_kesehatan`, SIGTERM | sedang — layanan baru, deploy dua service | **4–5 hari kerja** + 1 hari pengamatan di produksi dengan flag mati dulu (worker hidup, view masih sinkron) | **hanya bila** E1 tidak terwujud DAN `durasi_ms` menunjukkan run tunggal > 50 dtk, ATAU satu 524 nyata terjadi |
| **3 — opsional** | batalkan job `jalan` (butuh hook engine), notifikasi, worker >1 (kunci per toko sudah siap) | sedang | sesuai kebutuhan | permintaan pengguna |

Kalau Fase 2 ditunda lama dan 524 terjadi, **jembatan** yang sah adalah Opsi C varian 3 (thread + tabel job yang sama) — tabel `ReconJob` dan halaman statusnya dirancang identik supaya jembatan itu tidak dibuang saat worker datang.

Rollback tiap fase: 0 dan 1 = revert commit biasa (tak ada skema kecuali kolom JSON yang sudah ada); 2 = `REKON_ASYNC=false` (jalur sinkron tidak pernah dihapus), worker dihentikan setelah antrean kosong.

---

## 5. Kapan ini belum perlu dikerjakan

Jujur, dari angkanya sendiri:

- **Untuk 12 brand Nexus** (dan Vigor/TMG pada hari ber-UUID): run tunggal 1,3 dtk produksi / 2,8 dtk SQLite lokal terhadap batas 100 dtk — jarak **>30×**. Tumpukan pun harus ±70 hari untuk mendekati batas. **Tidak perlu**, dan tidak akan perlu dalam horizon yang bisa diperkirakan.
- **Untuk g25/w25/cah pada hari ELITE**: run tunggal 29 dtk, jarak 3,4× waktu ≈ 1,85× volume harian; **pemicu terdekat adalah tumpukan ≥4 tanggal dalam satu klik**, bukan pertumbuhan. Fase 1(c) menutup pemicu itu tanpa arsitektur baru, dan **E1 menutup sebabnya** (kembali ±1,3 dtk dan mutu 95–97 %).
- **Kesimpulan:** Fase 0 + 1 layak sekarang karena murah dan memperbaiki hal yang sudah salah hari ini (pesan mentah, ras hapus-vs-run, tumpukan). **Fase 2 belum perlu** selama (a) permintaan E1 masih berjalan dan (b) `durasi_ms` belum pernah menyentuh 50 dtk untuk satu tanggal. Membeli worker + service kedua sekarang berarti membeli kompleksitas untuk masalah yang mungkin hilang bersama E1 — mencegah itu adalah hasil sah rancangan ini.
- **Yang harus mengubah kesimpulan ini:** E1 ditolak vendor; brand Vigor/TMG baru dengan volume ≥ g25; atau migrasi ke VPS Contabo terukur lebih lambat per pasangan. Semua terbaca dari Fase 0.

---

## Lampiran

**A. Sumber angka**
- `run_batch` lokal: `scratchpad/ukur_run_batch.{py,json,log}`, `ukur_run_batch_profile.txt`, `uji_resumable.py` (tidak di-commit; scratchpad sesi).
- Produksi: `CLAUDE.md` §"Anomali matcher 25-08-2026" (29.219 ms; 4.969.497 pasangan; 5,88 µs), §"Performa v1.18.0" (koneksi 32/100), `core/tests_start_command.py` (283 MB, aritmetika).
- gunicorn 26.2.0: `workers/gthread.py` (`run`, `handle_request`), `arbiter.py` (`murder_workers`), `config.GracefulTimeout.default = 30`.
- Cloudflare: developers.cloudflare.com Error 524 (125 dtk; Enterprise 6.000 dtk; saran DNS-only).
- Railway: pricing (tarif per detik), "Specs & Limits" (5/15 menit), "monorepo" (start command & config path per service).
- django-q2: `configure.html` (`retry`, `timeout`, `ack_failures`, `max_attempts`).

**B. Yang sengaja tidak dirancang**
- Paralelisasi di dalam satu run (memecah pool per bucket ke beberapa proses): mengubah urutan pemecah seri → dilarang kontrak determinisme tanpa harness sidik jari (E3).
- Menyempitkan `_money_phones`/blocking untuk mempercepat hari ELITE: **mengubah hasil**; itu E3, bukan E2.
- Broker terpisah untuk beban puluhan job/hari.
