# Hasil eksekusi daftar perbaikan A–H — 4 September 2026

Sumber tugas: [`daftar-perbaikan-2026-09-03.md`](daftar-perbaikan-2026-09-03.md) ·
Rencana kerja: [`prompt-eksekusi-perbaikan-2026-09-04.md`](prompt-eksekusi-perbaikan-2026-09-04.md)
Rilis: **v1.25.0** · Cabang: `claude/prompt-eksekusi-perbaikan-1c3f75` → `origin/main`
Tes: **2.024 → 2.166 hijau** (+142, nol gagal) · 53 commit · 91+ berkas

> Daftar yang mengaku selesai padahal tidak jauh lebih merugikan daripada daftar yang jujur
> pendek. Kolom **Bukti** di bawah menyebut apa yang benar-benar diukur; yang belum terbukti
> ditulis belum terbukti.

## Status per butir

| # | Butir | Status | Bukti |
|---|---|---|---|
| A1 | Cadangan basis data | ✅ selesai | Timer 03:00 aktif; dump 1,6 GB/13m36d; TOC 448 entri; sha256 30 berkas cocok; **restore uji cocok byte-untuk-byte** dgn baseline produksi (count + 3 sum + sebaran bulanan); diverifikasi ulang independen oleh agen kedua |
| A2 | Berkas unggahan hilang tiap deploy | ⚠️ premis keliru; bagian kode selesai | `MEDIA_ROOT` bisa diatur env (4 tes baru). **`Upload.file` dead code sejak commit pertama** — lihat "Koreksi premis" |
| A3 | Rotasi `SECRET_KEY` + `DATABASE_URL` | ⏸ **tertahan pemilik** | Runbook siap: [`runbook-rotasi-kunci`](runbook-rotasi-kunci-2026-09-04.md). Butuh tanganmu — langkahnya menuntut menempel kredensial |
| B1 | Tidak ada satu alarm pun | ✅ selesai | `toa-kesehatan.timer` 04:00 aktif; gerbang pertama membaca verdict **dan umur** cadangan; jalur gagal dibuktikan berbunyi. **Jalan pertamanya menemukan BAHAYA nyata** (lihat bawah) |
| B2 | Tidak ada pelacak error | ✅ selesai | Sentry opsional (aktif hanya bila `SENTRY_DSN` ada); `max_request_body_size="never"` |
| B3 | Log akses mati | ✅ selesai | `--access-logfile -` di `Procfile` + `railway.json`; ⚠️ `%(f)s` dibuang (lihat "Celah yang kami buat sendiri") |
| B4 | Log tanpa format | ✅ selesai | Formatter + level ber-env |
| B5 | Tanpa log drain | ⏸ **keputusan pemilik** | [`rencana-log-drain`](rencana-log-drain-2026-09-04.md). Rekomendasi: naikkan retensi plan Railway; **tahan drain pihak ketiga** |
| B6 | Service diam setelah 3× restart | ✅ selesai | `toa-probe.timer` 5 menit; semua 5xx = mati; 403 hidup **hanya bila badan halaman memuat judul aplikasi**; anti-kedip 3× |
| C1 | HSTS mati | ✅ selesai | Default 1 tahun di produksi, tetap bisa ditimpa env |
| C2 | Tidak ada CSP | ✅ selesai, **sebagian** | `core/middleware.py`. ⚠️ Sengaja `'unsafe-inline'` — **bukan proteksi XSS penuh** |
| C3 | Sesi 2 minggu | ✅ selesai | 8 jam sejak penulisan sesi terakhir + expire saat browser tutup. ⚠️ Sempat melahirkan cacat Kritis, sudah dicabut |
| C4 | Tanpa pembatas login | ✅ selesai | App `loginguard`, kunci per (username, IP), 29 tes. ⚠️ Perotasi IP tak kena ambang — batas yang diterima sadar |
| C5 | Jejak audit tanpa IP | ✅ selesai | Migrasi `core/0003`; resolver IP dipakai ulang, tidak diduplikasi |
| C6 | Login/logout tak diaudit | ✅ selesai | Signal login/logout/gagal-login. ⛔ Ketikan kolom username tak pernah disimpan mentah |
| C7 | Tanpa pembaruan dependensi | ✅ selesai | `.github/dependabot.yml` mingguan |
| D1 | `/mutasi-bank/` 46 dtk | ✅ selesai | SQL literal **94–97 rb karakter → <3,2 rb**, datar sampai N=60.000 |
| D2 | `/hutang-piutang/` 13,4 dtk | ✅ selesai | Scan dipersempit + index `raw->>'Kategori'`. ⚠️ Sebab dominannya bukan yang diduga daftar |
| D3 | `/batch/<pk>/` 226 query | ✅ selesai | 47 (tumbuh/baris) → **datar 13** |
| D4 | Partial index `check_completeness` | ⚠️ **sudah selesai sejak migrasi 0009** | Backlog `CLAUDE.md` basi; ditambahkan tes penguncian saja |
| D5 | `/tinjau/` 94 query | ✅ selesai | 88 (tumbuh/baris) → **datar 16** |
| D6 | Toko pasif bayar mahal | ✅ riset | Hipotesis daftar **tidak reproduksi**; ditemukan cacat lain yang nyata & diperbaiki |
| E1 | COR/g25 22–29 dtk | 📄 di luar kendali kita | Draf permintaan siap dikirim: [`permintaan-data-panel-elite`](permintaan-data-panel-elite-2026-09-04.md) |
| E2 | Rekonsiliasi sinkron | 📄 rancangan saja | [`rancangan-rekonsiliasi-async`](rancangan-rekonsiliasi-async-2026-09-04.md) — **penerapan menunggu keputusanmu** |
| E3 | `_money_phones` panen ID palsu | 📄 lapor saja | Harness sidik-jari dibangun (`scripts/harness/`). Kandidat optimasi **setara tapi tidak mempercepat** |
| E4 | `run_batch` belum terukur | ✅ selesai | ≈2,8–2,9 dtk/hari penuh — **lokal SQLite 71 rb baris, rezim ber-ticket**; bukan angka produksi |
| F1 | Tidak ada CI | ✅ selesai | GitHub Actions; wajib `collectstatic` sebelum `test` |
| F2 | Tanpa uji anti-regresi performa | ✅ selesai | 4 halaman v1.23.0 dikunci; tiap tes **dibuktikan merah** saat optimasinya dibatalkan |
| F3 | Tidak ada staging | ✅ selesai | **HTTP 200** dari tailnet, halaman ter-render; isolasi dibuktikan struktural |
| F4 | Tidak ada coverage | ✅ selesai | `coverage` + `.coveragerc` |
| F5 | Ketergantungan satu orang | ✅ sebagian, ikut F1 | CI + staging mengurangi, tidak menghapus |
| F6 | `TambahIndexAman` menelan kegagalan | ✅ selesai, ikut B1 | `periksa_index` kini dijalankan terjadwal |
| G1 | Titik gagal tunggal | ❌ **tidak dikerjakan** | Soal biaya, bukan waktu — keputusanmu |
| G2 | Rollback tak terdokumentasi | ✅ selesai | [`runbook-rollback`](runbook-rollback-2026-09-04.md), termasuk bagian jujur "yang belum pernah diuji" |
| G3 | 3 setelan Postgres | ⏸ **GERBANG: butuh restart** | Prasyarat (A1 terbukti) **sudah terpenuhi** |
| G4 | `max_parallel_workers_per_gather` | ⏸ **GERBANG** | Bisa lewat `ALTER SYSTEM` + reload, tanpa restart |
| G5 | 719 MB index mati | ✅ selesai | Migrasi `transactions/0011`; pemakaian disisir ulang lebih dulu |
| H1 | `row_hash` Flyer bocor | 📄 dokumen keputusan | [`keputusan-row-hash-flyer`](keputusan-row-hash-flyer-2026-09-04.md) |
| H2 | 6.118 baris sampah | ⏸ **keputusan pemilik data** | [`keputusan-baris-sampah-shape3`](keputusan-baris-sampah-shape3-2026-09-04.md) |

## Enam premis daftar audit yang ternyata tidak berlaku

1. **A2** — "berkas unggahan hilang tiap deploy" hanya benar untuk berkas *staging yang transit*.
   `Upload.file` **tidak pernah diisi kode produksi mana pun sejak commit pertama**. Masalah
   sesungguhnya lebih besar dan tidak ada di daftar: **tidak pernah ada salinan permanen berkas
   sumber**, yang menjelaskan kenapa tiap parser salah (QRIS Flyer empat kali) pemulihannya harus
   lewat kolom `raw`.
2. **D4** — partial index `check_completeness` **sudah ada sejak migrasi 0009**.
3. **E2** — Cloudflare **125 dtk** (bukan 100); `gunicorn --timeout 120` **bukan** batas untuk
   `gthread`; dan **run yang kena 524 TETAP COMMIT** — pengguna melihat kegagalan padahal batch-nya
   jadi. Pemicu terdekat = menumpuk ≥4 tanggal per klik, bukan pertumbuhan data.
4. **D2** — sebab dominannya scan `raw->>'Kategori'` tanpa index, bukan materialisasi Python.
5. **Retensi cadangan `+1`** — bersandar perkiraan dump 0,4×DB (≈7,2 GB); nyatanya **1,6 GB**,
   jadi 7 hari hanya ±11 GB dari 262 GB kosong.
6. **Laju tumbuh** — **±500 rb baris/hari** (10.345.543 pada 04-09 vs 8.850.457 pada 01-09), bukan
   ±185 rb yang tercatat. Ini menggeser aritmetika disk, retensi, dan proyeksi ambang timeout.

## Celah yang kami buat sendiri hari ini, dan sudah ditutup

Tiga-tiganya lahir dari pekerjaan hari ini dan ditemukan sebelum deploy — cabang ini belum pernah
menyentuh produksi.

1. **Kritis — pergantian toko bisa dibatalkan diam-diam.** `SESSION_SAVE_EVERY_REQUEST` (dari C3)
   membuat request lambat menulis balik sesi basi dan membatalkan `set_toko`; POST berikutnya
   mendarat di **toko yang salah tanpa error**. Dicabut, dikunci komentar larangan.
2. **Privasi — nama pemain bocor ke log akses.** `%(f)s` (Referer) membawa `?q=` dari pencarian
   yang menyaring `username`/`ticket_no`/`reference`/`counterparty`. Dibuang.
3. **Eksekusi shell di mesin basis data produksi.** `COPY FROM PROGRAM df` di pemantauan —
   dicabut atas keputusanmu, dikunci `core/tests_pemantauan_program.py`.

## Temuan operasional yang butuh tindakan

- 🔴 **Toko `mmk` tidak menghasilkan batch bertanggal sejak 26-08-2026** (9 hari). Ditemukan
  pemantauan B1 pada jalan pertamanya. Entah memang tidak ada aktivitas, entah ingest berhenti.
  ⚠️ Selama belum diselesaikan, alarm kesehatan **merah tiap pagi** dan akan mengaburkan temuan
  lain — selesaikan, atau bisukan sadar dengan tanggal kedaluwarsa.
- ⚠️ **`/opt/toa` di VPS adalah checkout cabang basi** dan itulah yang menjalankan pemeriksaan
  harian terhadap produksi. Index INVALID tetap terdeteksi; index yang **hilang** buta dari sana.
- ⚠️ **Data staging tidak dianonimkan** dan hash sandi produksi ikut tersalin serta tetap bekerja.
  Butuh ratifikasimu.
- ⚠️ **Cadangan ini bukan offsite.** Ia duduk di VPS yang juga direncanakan menjadi produksi
  berikutnya, dan VPS itu kini titik gagal tunggal untuk cadangan **dan** pemantauan sekaligus.

## Yang menunggu keputusanmu

| Gerbang | Isi | Prasyarat |
|---|---|---|
| 1 | **A3 rotasi kunci** — runbook siap, langkahnya menuntut kredensial | ⚠️ Wajib memperbarui `~/.pgpass` VPS, atau cadangan mati senyap |
| 2 | **G3 restart Postgres** / **G4 tanpa restart** | A1 terbukti — **sudah terpenuhi** |
| 3 | **Go/no-go E2 dan E3** | Rancangan + pengukuran siap |
| 4 | **H2 hapus 6.118 baris sampah** | Dokumen keputusan siap; kini ada cadangan |
| 5 | **Deploy** | ⚠️ Urutan migrasi index WAJIB lewat psql lebih dulu; **jendela 03:00–03:30 terlarang** |
