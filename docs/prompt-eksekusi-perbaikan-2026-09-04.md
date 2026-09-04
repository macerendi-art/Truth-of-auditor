# Prompt Eksekusi — Perbaikan A–H Truth of Auditor

**Cara pakai:** salin SELURUH isi di bawah garis, tempel sebagai pesan pertama di sesi baru.
Prompt ini sengaja memuat fakta lapangan yang sudah diverifikasi 4 September 2026, supaya
sesi baru tidak menurunkan ulang hal yang sudah terbukti — itu juga yang membuatnya hemat.

---

Kerjakan seluruh daftar perbaikan di `docs/daftar-perbaikan-2026-09-03.md` sampai selesai.
Jangan berhenti untuk bertanya "lanjut?" — hanya lima gerbang di bagian **GERBANG** yang
boleh menghentikanmu.

## 0. Aturan yang tidak bisa ditawar

Ini aplikasi keuangan yang hidup dan dipakai orang setiap hari.

1. **Deploy hanya setelah izin eksplisit.** `railway up --ci` dijalankan dari checkout
   utama `/Users/macads/Truth-of-auditor` — BUKAN dari worktree (worktree mengirim pohon
   basi). Push ke `origin/main` ≠ deploy.
2. **Jangan pernah menghapus data produksi.**
3. **Aku tidak memasukkan kata sandi, kunci, atau token ke mana pun.** Kalau sebuah langkah
   butuh kredensial, aku berhenti dan menyerahkan perintahnya untuk kamu jalankan sendiri.
4. **`git fetch` lalu rebase sebelum tiap push.** Fast-forward saja, tidak pernah `--force`.
   Rekan tim (`sabian`) DAN kamu sendiri sama-sama mendarat di `main` — ini sudah dua kali
   menolak push di sesi lalu.
5. **Jangan commit** `db.sqlite3`, `staticfiles/`, atau berkas contoh xlsx asli (berisi nama
   pemain sungguhan).
6. **Jangan mengarang angka.** Kalau sebuah pengukuran gagal, laporkan gagal. Di sesi lalu
   satu agen pengukur melapor gagal alih-alih menebak — itu perilaku yang benar, pertahankan.
7. **Kontrak determinisme mesin pencocokan berlaku penuh.** Apa pun yang menyempitkan jendela
   pass 2, mengubah blocking, atau menggeser kunci sort **mengubah hasil rekonsiliasi** dan
   dilarang tanpa gerbang sidik-jari `(left_id, right_id, bucket, reason_code, score)` atas
   hari nyata. Baca bagian "Performa" dan "Anomali matcher 25-08-2026" di `CLAUDE.md`.

## 1. Disiplin hemat limit (baca sebelum memanggil agen pertama)

Batas pemakaianku terbatas. Empat aturan ini soal **cache hit**, bukan sekadar "jangan boros":

1. **`CLAUDE.md` disuntikkan ke system prompt. Menyuntingnya di tengah sesi membatalkan
   seluruh cache prefiks sesi itu.** Karena itu: **semua perubahan `CLAUDE.md`,
   `core/version.py`, dan `CHANGELOG.md` dikumpulkan dan ditulis SEKALI di paling akhir**,
   dalam satu commit. Hal yang sama berlaku untuk `.claude/settings.json`, menambah server
   MCP, atau mengaktifkan skill baru — jangan lakukan di tengah jalan.
2. **Tiap subagen mulai dari cache dingin.** Biayanya sebanding dengan apa yang kamu tempel
   ke dalam prompt-nya. Maka: **serahkan berkas lewat PATH, jangan tempel isinya**; jangan
   tempel ringkasan tugas-tugas sebelumnya ke prompt tugas berikutnya; dan **kelompokkan
   butir berdasarkan kedekatan berkas** supaya satu agen menyelesaikan beberapa butir
   sekaligus alih-alih lima agen memuat konteks yang sama lima kali.
3. **Satu sesi panjang lebih murah daripada banyak sesi pendek.** Jangan restart. Gabungkan
   panggilan tool yang tidak saling bergantung ke dalam SATU pesan. Jangan membaca ulang
   berkas yang sudah ada di konteks, dan jangan menjalankan ulang suite yang hasilnya sudah
   kamu pegang.
4. **Jatah model.** `haiku` untuk kerja mekanis satu-dua berkas dengan spesifikasi lengkap.
   `sonnet` sebagai kuda beban dan untuk semua reviewer tugas. **`fable` MAKSIMAL 3 kali
   sepanjang seluruh pekerjaan** — jatahnya: (a) tinjauan akhir seluruh cabang, (b) rancangan
   D1, (c) rancangan E2. Jangan pakai di luar itu. **Selalu sebutkan model secara eksplisit**
   saat memanggil agen; kalau dikosongkan ia mewarisi model sesi (mahal).

## 2. Fakta lapangan yang SUDAH diverifikasi — jangan turunkan ulang

Diperiksa langsung 4 September 2026. Percayai ini; verifikasi ulang hanya kalau sebuah
perintah gagal dengan cara yang bertentangan.

**Repo & produksi**
- Cabang kerja `claude/test-fabbe0`, worktree `/Users/macads/Truth-of-auditor/.claude/worktrees/loving-joliot-2aa399`. HEAD `f33864b`. Bersih.
- v1.24.0 hidup di produksi. **1.996 tes.**
- `Procfile` dan `railway.json` memuat start command yang identik — `core/tests_start_command.py` menjaganya tetap sama. **Ubah keduanya bersamaan atau tes merah.**
- Basis data produksi **18 GB · 8.839.002 baris · tumbuh ±11 GB/bulan** (diukur 01-09, mengoreksi angka 14 GB yang lebih tua).

**Yang sudah ada dan tinggal dipakai — jangan bangun ulang**
- `commit 4121718` (Sabian, 5 Juli, hanya hidup di `pr4`, tidak pernah masuk `main`) sudah memuat **C1 + C2 + C3**: CSP di `core/middleware.py`, `truth_auditor/security.py` (SECRET_KEY fail-hard), HSTS default 1 tahun, sesi 8 jam rolling, cap upload 50MB/300MB, plus `web/tests_hardening.py` (88 baris). **Pungut, jangan tulis dari nol.** Lakukan `git show 4121718` dulu dan nilai tiap berkas terhadap kode hari ini — basisnya sudah 2 bulan bergerak.
- `docs/rencana-migrasi-contabo-2026-08-31.md` **baris ±1040–1065** sudah memuat skrip cadangan lengkap: `pg_dump --format=directory --jobs=4 --compress=zstd:3` → `pg_restore -l` (TOC terbaca = arsip tidak rusak) → `sha256sum` → unggah → retensi **`-mtime +1`, bukan +7** (alasannya ada di sana: 8 salinan × 0,4×DB menjebol disk di bulan ~6). **Pakai resep ini untuk A1.**
- `scripts/gerbang.sh` = alat **pembanding** produksi↔VPS (bukan alat dump; itu disengaja). Pakai untuk memverifikasi hasil restore. Konvensinya: user VPS `toa`, DB VPS `toa`, DB produksi `railway`.
- `core/management/commands/periksa_kesehatan.py` dan `periksa_index.py` sudah jadi — **tidak ada yang menjalankannya.** Itulah inti B1.

**Tiga jebakan cadangan yang sudah terbukti — langgar salah satu dan cadangannya diam-diam cacat**
- **J4:** `pg_dump` **MEMBUANG index yang `indisvalid=false`** (terverifikasi di sumber `pg_dump.c`, `getIndexes`, REL_18_STABLE), dan `migrate` tidak akan pernah membangunnya ulang karena migrasinya tercatat selesai. **Jalankan `periksa_index` SEBELUM tiap dump** dan gagalkan dump kalau ada yang INVALID.
- **Jangan** `railway ssh "pg_dump -Fc" > berkas`: kanal WebSocket-nya tidak terbukti 8-bit clean, tidak bisa dilanjutkan bila putus, dan `-Fc` ke pipe tidak seekable sehingga `-j` sia-sia. **Dump harus DITARIK OLEH VPS**, di dalam `tmux`.
- Kata sandi **tidak boleh masuk `argv`** (`pg_dump -d "$URL"` memperlihatkannya di `/proc/<pid>/cmdline`). Pakai `~/.pgpass` dengan `umask 077`.

**VPS Contabo — tiga mesin berbeda. Target cadangan sudah bisa diakses.**

| Alias | IP | Hostname | Akses | Postgres |
|---|---|---|---|---|
| — | `217.216.39.105` — **target cadangan** | `vmi3547922` | ✅ **`ssh toa@…`**, `sudo` tanpa sandi | **PG 18.6**, DB `toa` ada |
| `contabo` | `217.15.162.131` | `vmi3504828` | ✅ `root@` | belum |
| `contabowa` | `100.86.226.20` (Tailscale) | `vmi3445746` | ✅ `root@` | belum |

Target cadangan diukur langsung 04-09: **262 GB kosong** dari 290 GB, RAM 23 GB (terpakai 7),
PostgreSQL **18.6** (PGDG Ubuntu 24.04) — versi yang sama persis dengan produksi, jadi restore
uji tidak akan tersandung beda versi. Pada laju produksi ±11 GB/bulan dan dump terpadatkan
±1,9 GB, ruang itu longgar; retensi `-mtime +1` tetap wajib demi alasan di dokumen migrasi.

> **⛔ Database `toa` di VPS SUDAH BERISI 29 tabel** — sisa gladi migrasi, jumlah yang sama
> dengan produksi. **Restore uji A1 dilarang menimpanya.** Buat database sekali-pakai
> terpisah (mis. `toa_ujicadangan`), verifikasi di sana, lalu jatuhkan. Menimpa `toa`
> menghapus hasil gladi yang jadi pembanding `scripts/gerbang.sh`.

> **`ssh root@217.216.39.105` DITOLAK, dan itu memang benar.** FASE 1 migrasi sengaja
> mematikan login root (`PermitRootLogin no`, dokumen baris 393–405, lengkap dengan
> checklist "dari mesin lain `ssh root@<IP>` harus DITOLAK"). **Selalu `toa@`, lalu `sudo`.**
> Jangan simpulkan kunci hilang saat root ditolak — itu pengamanannya bekerja.

> **⚠️ SSH ke mesin itu dibatasi laju, dan agen paralel bisa mengunci diri sendiri.**
> Dokumen baris 410–419: `fail2ban` aktif + `ufw limit 22/tcp` (sengaja `limit`, bukan
> `allow` polos, "di mesin berisi DB keuangan"). Beberapa percobaan auth yang GAGAL —
> termasuk sekadar mencoba username yang salah — memicu ban ±10 menit, yang muncul sebagai
> **`Connection refused`** (REJECT dari fail2ban), bukan timeout. Ini sudah terjadi sekali
> saat verifikasi 04-09.
> **Aturannya:** (a) hanya **SATU agen** yang boleh menyentuh VPS — jangan pernah beberapa
> agen ber-SSH sendiri-sendiri; (b) pakai multiplexing supaya banyak perintah berbagi satu
> koneksi:
> ```
> Host toa
>     HostName 100.102.118.125
>     User toa
>     ControlMaster auto
>     ControlPath ~/.ssh/cm-%r@%h:%p
>     ControlPersist 10m
> ```
> (c) jangan pernah menebak-nebak username. Break-glass bila terkunci: **konsol VNC Contabo**
> `194.233.66.221:63089` (dokumen baris 897 dan 1036) — itu perlu tangan pemilik.
>
> **✅ SUDAH DIBERESKAN 04-09: VPS ini kini ada di tailnet.** Pakai alias SSH **`toa`** (`ssh toa`; `toavps` masih jadi alias kedua)
> (sudah dipasang di `~/.ssh/config`) → `toa@100.102.118.125`, di tailnet bernama
> **`truthofauditor`** (`truthofauditor.taila54dc6.ts.net` — itu yang mengatur MagicDNS;
> hostname asli mesinnya tetap `vmi3547922`),
> Tailscale 1.102.3, `tailscaled` enabled saat boot, `ufw allow in on tailscale0` terpasang.
> Trafiknya **tidak** lewat port 22 publik, jadi `ufw limit` + fail2ban tidak ikut campur —
> peringatan kunci-diri-sendiri di atas **tidak lagi berlaku untuk jalur ini**. Dipasang
> **tanpa `--ssh`**: auth tetap kunci `toa` hasil FASE 1, MagicDNS tidak menyentuh
> `/etc/resolv.conf` (diperiksa), Postgres tetap `active`.
> Alias cadangan `toa-publik` (IP publik `217.216.39.105`) **masih kena rate-limit** —
> pakai hanya kalau tailnet mati, dan jangan paralel.
> Aturan "satu agen yang menyentuh VPS, satu koneksi ber-multiplexing" **tetap dipertahankan**
> — itu soal kewarasan operasional, bukan cuma rate limit.
>
> **✅ Kedaluwarsa node key sudah DIMATIKAN** (pemilik, 04-09; diverifikasi dari mesin —
> field `KeyExpiry` hilang dari `tailscale status --json`, bukan sekadar label di admin).
> Jalur tailnet tidak akan mati sendiri, jadi jangan menjadwalkan pekerjaan seputar itu.
> Tetap berlaku, dan ini yang penting: **pemeriksaan kesehatan B1 wajib memantau
> keberhasilan cadangan TERAKHIR**, bukan cuma keberadaan berkasnya — cadangan yang gagal
> diam-diam adalah mode kegagalan yang paling mahal di sini.

**Catatan jujur yang harus tetap muncul di laporan akhir:** cadangan yang disimpan di VPS yang
juga direncanakan menjadi produksi berikutnya **bukan cadangan offsite**. Kalau mesin itu
hilang, dua-duanya hilang. Ini keputusan pemilik yang sudah diambil sadar — kerjakan, tapi
jangan laporkan sebagai "cadangan sudah aman" tanpa kalimat ini.

## 3. Keputusan yang sudah diambil pemilik

- **Target cadangan = VPS ToA `217.216.39.105`**, masuk sebagai `toa`. **Tidak tertahan apa
  pun** — A1 bisa dimulai di gelombang pertama.
- **E2 dan E3: rancang + ukur, JANGAN terapkan.** Hasilkan bukti dan rancangan, keputusan
  penerapan tetap di pemilik.
- **G3/G4 boleh menyentuh produksi**, dengan konfirmasi eksplisit tepat sebelum dijalankan,
  dan **hanya setelah A1 benar-benar menghasilkan cadangan yang terverifikasi.**

## 4. Orkestrasi

Pakai skill `superpowers:subagent-driven-development`. Aturan pembagian kerja:

> **Satu berkas hanya boleh ditulis oleh satu agen dalam satu gelombang.** Dua agen paralel
> yang menyunting berkas sama = konflik dan kerja terbuang. Gelombang dibagi berdasarkan
> kepemilikan berkas, bukan berdasarkan tema.

`truth_auditor/settings.py`, `requirements.txt`, `Procfile`, dan `railway.json` adalah
**titik sempit**: hampir semua butir B dan C menyentuhnya. Karena itu keempatnya dimiliki
**satu agen saja di Gelombang 1**, dan butir gelombang berikutnya yang butuh satu baris di
sana **mengantre** ke pemilik yang sama (Gelombang 1b), tidak menyuntingnya sendiri.

Tiap tugas: implementer → task reviewer (spec + kualitas) → perbaikan bila perlu. Catat
kemajuan di ledger `.superpowers/sdd/progress.md` supaya selamat dari compaction.

### Gelombang 0 — Preflight (sesi utama, tanpa agen)
`git fetch` + rebase. Jalankan suite penuh sekali, catat jumlah dan durasinya sebagai
garis dasar. Konfirmasi versi/deployment produksi. Buat ledger. Blok `Host toa` di `~/.ssh/config` **sudah terpasang** 04-09 (tailnet + multiplexing);
cukup verifikasi `ssh toa` tembus.

### Gelombang A — Cadangan (mulai bersamaan Gelombang 1, satu agen khusus, sonnet)
**A1.** Satu-satunya agen yang boleh ber-SSH ke VPS. Urutannya: `periksa_index` di produksi
(gagalkan bila ada index INVALID — jebakan J4) → `~/.pgpass` `umask 077` → dump **ditarik
oleh VPS** di dalam `tmux` dengan resep dokumen migrasi baris ±1040 → `pg_restore -l` +
`sha256sum` → retensi `-mtime +1` → jadwalkan harian → **buktikan dengan satu restore uji
ke DB sekali-pakai**, bukan sekadar "dump-nya jadi". Cadangan yang belum pernah di-restore
belum terbukti apa pun.
**A2** dikerjakan di Gelombang 4c.

### Gelombang 1 — Titik sempit konfigurasi (SERIAL, 1 agen, sonnet)
Berkas: `truth_auditor/settings.py`, `truth_auditor/security.py`, `core/middleware.py`,
`web/tests_hardening.py`, `Procfile`, `railway.json`, `requirements.txt`.
Butir: **C1** (HSTS — catatan: `SECURE_HSTS_SECONDS` SUDAH ada di `settings.py:259`, membaca
env dengan default `'0'`; jadi ini soal default/env, bukan setelan yang hilang), **C2** (CSP),
**C3** (umur sesi), **B2** (pelacak error), **B3** (`--access-logfile -` di gunicorn — ubah
`Procfile` DAN `railway.json`), **B4** (formatter + level logging; `LOGGING` ada di
`settings.py:242`), **F4** (alat coverage).

### Gelombang 2 — Paralel, berkas terpisah
- **2a** (sonnet) — **C5** jejak audit ber-IP (`core/audit.py` `catat()` + 33 titik panggil + migrasi) & **C6** audit login/logout/gagal-login (`web/signals.py`).
- **2b** (sonnet) — **C4** pembatas percobaan login. Modul + tes sendiri; baris `settings.py`-nya diantrekan ke pemilik Gelombang 1.
- **2c** (haiku) — **F1** CI (`.github/workflows/`, berkas baru, tidak menyentuh apa pun).
- **2d** (sonnet) — **G5** buang 719 MB index mati (`reference` + `username`). **Lewat `db_index=False` di model + migrasi, BUKAN `DROP INDEX` di psql** — penyimpangan skema lahir justru saat index dibuang di belakang punggung Django. Alasan aman ada di `CLAUDE.md`: satu-satunya pemakaian kedua kolom itu adalah `icontains`, yang btree memang tak bisa layani.
- **2e** (haiku) — **G2** runbook rollback (dokumen) & **C7** Dependabot (`.github/dependabot.yml`).

### Gelombang 3 — Kecepatan (setelah Gelombang 2; sebagian menyentuh `web/views.py`)
- **3a** (sonnet; rancangan D1 boleh pakai jatah `fable`) — **D1** `/mutasi-bank/?upload=` 46/37 dtk, **D3** `/batch/<pk>/` 226 query, **D5** `/tinjau/` 94 query. Ketiganya di `web/views.py` → satu agen, serial di dalam. D1 tidak membaik saat dipanaskan, jadi polanya yang salah — agregat m2m `duplicate_transactions` di sekitar baris 2098.
- **3b** (sonnet) — **D2** `/hutang-piutang/` mode Semua Toko 13,4 dtk (`web/hutang.py`). Bukan N+1; jumlah query sudah konstan.
- **3c** (sonnet) — **D4** partial index untuk 5× EXISTS `check_completeness`. **Migrasinya WAJIB `atomic = False` + `core/db_ops.TambahIndexAman`** dan docstring-nya memuat DDL `CREATE INDEX CONCURRENTLY` untuk dijalankan lewat psql lebih dulu — presedennya migrasi `transactions/0008`–`0010`. Alasannya: start command Railway menjalankan `migrate` SEBELUM gunicorn membuka port.
- **3d** (sonnet) — **F2** uji anti-regresi performa untuk 4 halaman v1.23.0. Contoh polanya sudah ada di `web/tests_bracket_carry.py`. Kunci **bentuk** query (`assertNumQueries`, bentuk SQL), bukan angka milidetik.

### Gelombang 4 — Pemantauan & infrastruktur
- **4a** (sonnet) — **B1** penjadwal yang menjalankan `periksa_kesehatan` + `periksa_index`, **B6** pemberitahuan saat service mati setelah 3× restart, **F6** (terjawab sendiri oleh B1). Butuh `railway.json` → antre ke pemilik Gelombang 1.
- **4b** (haiku) — **B5** log drain (konfigurasi + dokumen).
- **4c** (sonnet) — **A2** volume permanen untuk berkas unggahan (`web` saat ini `volumeMounts: []`, `MEDIA_ROOT` di disk kontainer yang hilang tiap deploy). **Tidak tertahan apa pun — kerjakan lebih awal kalau ada slot.**
- **4d** (sonnet) — **F3** staging di VPS.

### Gelombang 5 — Analisis saja, TIDAK menulis kode produksi
- **E4** ukur `run_batch` (lubang satu-satunya di data pengukuran sesi lalu).
- **E3** bangun harness sidik-jari, ukur dampak `_money_phones`, **laporkan** — jangan terapkan.
- **E2** rancangan rekonsiliasi async + biayanya (boleh pakai jatah `fable`) — jangan terapkan.
- **D6** riset kenapa toko pasif membayar mahal (k25 3,0 dtk vs mxw 1,2 dtk padahal 6× lebih kecil).
- **H1** + **H2** laporan keputusan. **H1 jangan "diperbaiki begitu saja"**: semua baris lama memakai resep `row_hash` sekarang, mengganti resepnya membuat unggah ulang berkas lama menggandakan massal. **H2** penghapusan 6.118 baris sampah adalah keputusan pemilik data.
- **E1** di luar kendali kita: butuh pihak panel mengekspor kolom `Transaction ID` di DP QRIS ELITE, atau ELITE menulis tiket panel di kolom `TICKET` seperti yang sudah dilakukannya untuk 12 brand Nexus. **Siapkan draf permintaannya**, jangan tunggu.

### Penutup
1. Tinjauan akhir seluruh cabang — **`fable`**, satu kali, satu paket diff.
2. Kalau ada temuan: **SATU** agen perbaikan dengan seluruh daftar temuan, bukan satu agen per temuan.
3. Baru setelah itu, dalam **satu commit terakhir**: `CLAUDE.md` + `core/version.py` + `python manage.py changelog`. Versinya **MINOR** (v1.25.0) — aturan penomoran di `core/version.py` menegaskan bank/gateway/brand baru, halaman laporan baru, dan pengetatan akses tetap MINOR berapa pun jumlahnya.
4. Suite penuh hijau. `git fetch` + rebase. Push.
5. **GERBANG 5** (deploy).

## 5. GERBANG — hanya lima ini yang boleh menghentikanmu

1. **A3 rotasi `SECRET_KEY` + `DATABASE_URL`** (bocor 31-08). Aku siapkan langkahnya, pemilik
   yang menjalankan. **Keduanya harus dibuat BARU, tidak pernah disalin**, dan
   `SECRET_KEY_FALLBACKS` berisi kunci lama **dilarang**.
2. **Restart Postgres produksi** untuk G3 (`dynamic_shared_memory_type` mmap→posix,
   `max_worker_processes` 8→16, `wal_buffers` 16MB→64MB). Hanya setelah A1 terbukti jalan
   **dan restore ujinya berhasil**. G4 (`max_parallel_workers_per_gather` 2→4, terukur
   15,1→5,9 dtk) bisa lewat `ALTER SYSTEM` + reload tanpa restart — pisahkan keduanya.
3. **Go/no-go E2 dan E3** setelah laporan Gelombang 5.
4. **Penghapusan 6.118 baris sampah H2** — data pemilik.
5. **Deploy.**

Di luar lima ini: jalan terus. Kalau VPS terkunci fail2ban, **tunggu 10 menit, jangan
mencoba lagi berulang-ulang** — mencoba terus justru memperpanjang ban; sementara itu
kerjakan gelombang lain.

## 6. Definisi selesai

Satu butir **selesai** hanya bila ketiganya benar: (a) ada tes yang gagal tanpa perubahan itu
dan lulus dengannya, (b) suite penuh tetap hijau, (c) untuk butir kecepatan, ada **angka
sebelum dan sesudah yang diukur**, bukan diperkirakan.

Laporan akhirnya satu tabel: butir · status (selesai / tertahan / diputuskan tidak dikerjakan)
· bukti. Butir yang tertahan disebut tertahan, beserta apa persisnya yang menahannya. Daftar
yang mengaku selesai padahal tidak jauh lebih merugikan daripada daftar yang jujur pendek.
