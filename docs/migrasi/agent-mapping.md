# Pemetaan Agen — Eksekusi Migrasi Railway → Contabo

**Pendamping** `docs/rencana-migrasi-contabo-2026-08-31.md` (v2.1) + `scripts/gerbang.{sh,sql}`.
**Pembaca:** satu sesi eksekutor Opus 5 effort *extra-high*, tanpa konteks selain repo ini.
**Aturan supremasi:** bila berkas ini berbeda dari rencana v2.1, **ikuti rencana** — penyimpangan
yang sudah diketahui ada di bagian terakhir.

## 1. Prinsip pemetaan — jujur, bukan aspirasional

**Tesis: FASE 0–5 dikerjakan INLINE oleh sesi eksekutor itu sendiri. Tidak didelegasikan.** Bukan
karena delegasi dilarang, tapi karena runbook ini **sekuensial dan stateful** — state-nya hidup di
dalam satu sesi shell, dan sebagian state itu **mati begitu sesinya tutup**. Bukti konkret, semuanya
dari rencana v2.1:

1. **Satu sesi `tmux new -s migrasi`.** FASE 2 bagian C menjalankan dua jendela di dalam sesi yang
   sama. Agen lain = attach baru, bukan pewarisan state.
2. **Transaksi MVCC `REPEATABLE READ` yang WAJIB tetap terbuka.** Jendela 1 menjalankan
   `BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ; SELECT pg_export_snapshot();` dan jendela 2
   memakai `pg_dump --snapshot='<ID>'`. Snapshot **hanya valid selama transaksi pengekspornya
   hidup**; begitu sesi itu tutup id-nya mati, jadi ia **tak bisa diserahkan ke proses/agen lain**.
   Patokan (`count`, `sum(amount|credit_delta|money_delta)`, sebaran bulanan) juga wajib dibaca dari
   transaksi yang sama sebelum `COMMIT` — di sesi lain = dunia yang sudah bergerak ±185 rb baris/hari.
3. **Konteks `sudo`.** FASE 1–3 berjalan sebagai `toa` lewat `sudo NOPASSWD` (J8), dan
   `Defaults env_reset` membuang variabel yang diekspor di luar batas sudo (lihat `toa_manage`).
   Konteks itu milik sesi shell, bukan milik dokumen.
4. **`~/.pgpass`** (umask 077, home `toa`) adalah satu-satunya jalur kredensial produksi — sengaja
   tidak di argv (J13 + FASE 1.4). Menyalinnya ke agen lain = menyebar rahasia yang sedang diputar.
5. **Variabel shell hidup lintas langkah:** `$DUMPDIR`, `$STAMP`, `$NEWPW`, `$PROD_URL` dipakai
   di C → D → E → F, dan `$NEWPW` menyeberang dari FASE 1.4 ke `/etc/toa.env` di FASE 3.
6. **Sesi root FASE 0 wajib terbuka sampai GERBANG 1 lulus.** Kalau `00-toa-hardening.conf` salah,
   sesi root itulah **satu-satunya jalan masuk** tersisa (`PermitRootLogin no` +
   `PasswordAuthentication no` sudah aktif) — dan sesi milik agen lain tak bisa dipakai manusia.

**Poin yang menentukan:** *sebuah gerbang yang dijalankan di sesi lain menguji mesin yang berbeda
dari yang baru saja disiapkan.* Ia bukan fungsi murni atas IP — ia membaca `ALTER SYSTEM` yang baru
di-restart, profil restore yang baru dikembalikan (G), peer-auth sebagai OS user `toa`, dan
`railway ssh -s Postgres` yang bergantung pada login CLI sesi pemanggil. Dari sesi/host lain ia
menguji kombinasi keadaan yang **belum tentu sama**; bila lulus, ia melatih orang mempercayai bukti
yang tidak menguji apa pun.

## 2. Tabel pemetaan tugas

| Tugas | Pelaksana | Model & effort | Alasan |
|---|---|---|---|
| FASE 0 provisioning, `sudoers.d/90-toa`, `sshd_config.d/00-toa-hardening.conf`, GERBANG 0/1, ufw + `tambah_cf` | **INLINE** | Opus 5 xhigh | Sesi root wajib terbuka sampai GERBANG 1; salah langkah = terkunci dari mesin |
| FASE 1 PG18 PGDG, Python 3.11 deadsnakes, `ALTER SYSTEM` paritas, `CREATE DATABASE toa` | **INLINE** | Opus 5 xhigh | `ALTER SYSTEM` tidak memvalidasi apa pun; nilai mustahil = Postgres menolak start dan psql tak ada lagi untuk membatalkan. Butuh baca-ulang `pg_settings` produksi di sesi yang sama |
| FASE 2 snapshot MVCC + `pg_dump --snapshot` + bukti utuh + `pg_restore` + `vacuumdb` + kembalikan profil | **INLINE** | Opus 5 xhigh | Snapshot mati bersama sesinya (§1.2); `$DUMPDIR`/`$STAMP` lintas langkah; restore wajib sebagai OS user `toa` |
| FASE 3 `/etc/toa.env`, systemd, nginx, `toa_manage`, suite ~1.700 tes | **INLINE** | Opus 5 xhigh | `/etc/toa.env` memuat `SECRET_KEY` + password DB baru; J1 hanya terbukti tertutup bila env dimuat DI DALAM batas sudo pada sesi yang menjalankan |
| FASE 4 cutover berwaktu, GATE A/B/C, R1–R5, rollback | **INLINE** | Opus 5 xhigh | Keputusan abort berbatas jam (08:45 dump, 11:00 GATE A). Tidak ada ruang untuk latensi delegasi, dan keputusan rollback butuh seluruh riwayat sesi |
| **Verifikasi silang ADVERSARIAL keluaran gerbang** | **subagent** | Opus 5 high | Murni baca; boleh paralel dengan langkah berikutnya; sudut pandang independen justru nilainya (lihat rincian di bawah) |
| Penulisan dokumen — runbook cutover cetak, catatan rilis, pembaruan CLAUDE.md, pengumuman operator (berkas **disjoint**) | **subagent paralel** | Opus 5 medium | Tidak menyentuh mesin; berkas tidak beririsan sehingga tidak ada konflik tulis |
| Riset insidental: rentang IP Cloudflare terbaru, kuirk nginx 1.24 (`http2` gabungan), opsi `pg_dump` PG18 (`--statistics`, `--snapshot`), harga/KB Contabo | **subagent** | model kecil (Haiku/Sonnet) | Pencarian fakta publik, hasilnya diverifikasi ulang inline sebelum dipakai |
| Diff `railway variables --json` ↔ `/etc/toa.env` di T-1 | **INLINE**, hasil **diverifikasi ulang subagent** | Opus 5 xhigh (inline) + high (verifikator) | Keluarannya memuat `SECRET_KEY` + `DATABASE_URL` produksi (J13) → tidak boleh keluar sesi. Subagent hanya menerima **daftar nama variabel + verdict beda/sama**, tanpa nilai |

### Rincian tugas subagent verifikasi silang adversarial

Diberi: path keluaran gerbang (`$KERJA/laporan-produksi-<mode>.txt`, `laporan-restore-<mode>.txt`,
`diff-<mode>.txt`; `KERJA` default `$HOME/toa-migrasi`) + akses **SELECT-only** ke DB hasil restore.
Bukan membaca ulang laporan lalu setuju, melainkan:

1. **Turunkan ULANG angka dari DB hasil restore** dengan query yang ditulis sendiri (bukan
   menjalankan `gerbang.sql`), lalu bandingkan dengan isi laporan. Laporan yang tidak bisa
   direproduksi = temuan.
2. **Berburu kerusakan yang LOLOS dari `SUM(amount)`** (J6) — alasan blok 08/12/13 ada:
   `occurred_at IS NULL` (mesin menyaring `occurred_at__date` → baris berhenti dicocokkan) ·
   `posted_date IS NULL` (baris lenyap dari semua laporan) · `raw` NULL/`'{}'::jsonb` (halaman
   laporan kosong) · `row_hash` kosong/rusak (idempotensi ingest hilang) · teks rusak encoding ·
   **nilai tertukar antar baris** (SUM tidak peduli urutan; hanya sidik jari
   `md5(string_agg(sig ORDER BY id))` blok 12 yang menangkapnya).
3. **Periksa apa yang TIDAK digerbang.** Mode `live` menyaring baris `~` dari `diff`; blok **17
   seluruhnya `~`**, jadi hanya tertangkap `grep 'analyzed=BELUM-PERNAH'` (`gerbang.sh` langkah 10).
   Blok **13 sengaja tanpa** `bucket`/`reason_code`/`reason_detail`/`resolved_by_batch_id` — hanya
   digerbang di **08b** (`\if :full`); blok 04 memberi `~` pada 14 tabel yang tumbuh. →
   **`banding <ip> live` bukan bukti kesetaraan penuh**; hanya `final` menggerbang semuanya.
4. **Larangan khusus: subagent tidak boleh menjalankan `gerbang.sh`.** Dua alasan struktural —
   (a) skrip mengambil `ceil`/`ceilmr` **baru** dari sisi restore, jadi perbandingannya bukan lagi
   perbandingan yang sedang diaudit; (b) nama berkas keluarannya tetap per-mode, jadi menjalankan
   ulang **menimpa bukti yang sedang diperiksa**.
5. **Jendela paralel:** boleh jalan berbarengan dengan langkah berikutnya **sampai langkah 17**
   FASE 4; langkah **18** (`RESET default_transaction_read_only`) adalah batas split-brain, dan
   verdict verifikator wajib sudah masuk sebelum itu.

## 3. Aturan subagent (keras)

Salin apa adanya ke setiap prompt subagent:

- **READ-ONLY.** Boleh: `cat`, `grep`, `psql -c 'SELECT …'`, `ssh <host> "psql -tAc 'SELECT …'"`.
  Dilarang: `INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/TRUNCATE/REINDEX/VACUUM`, `pg_dump`,
  `pg_restore`, `systemctl`, `ufw`, `apt`.
- **Dilarang menyentuh** `/etc/toa.env` (baca maupun tulis), `ALTER SYSTEM`, `ALTER DATABASE`,
  dan **seluruh permukaan Cloudflare** (dashboard, API, DNS, WAF, mode SSL/TLS).
- **Dilarang mengeluarkan nilai rahasia** ke ringkasan/laporan/pesan balik mana pun: `SECRET_KEY`,
  password DB, isi `~/.pgpass`, `DATABASE_URL` lengkap, IP operator. Laporkan **nama variabel +
  verdict**, tidak pernah nilainya. (J13: dua rahasia produksi sudah pernah bocor lewat log sesi
  kerja — jangan tambah yang ketiga.)
- **Dilarang menulis** ke `samples/` dan ke checkout git mana pun (`/opt/toa`, worktree lokal);
  berkas kerja subagent hanya boleh di direktori scratch-nya sendiri. **Dilarang `git commit` /
  `git push` / `railway up` / `railway variables --set`.**
- Butuh sesuatu di luar daftar ini: **berhenti dan laporkan**, jangan improvisasi.

## 4. Template task-brief per FASE (siap salin)

````markdown
# FASE <N> — <judul>
**Status produksi:** <TIDAK TERSENTUH | DIBEKUKAN READ-ONLY | MENERIMA TULISAN>
**Reversibilitas:** <gratis sampai langkah X | berbiaya | titik tanpa balik>

## 1. Prasyarat — WAJIB terbukti SEBELUM perintah pertama
Checklist ini bukan formalitas; satu baris gagal = fase tidak dimulai.
- [ ] Fase sebelumnya lulus gerbangnya, keluaran mentahnya masih tersimpan
- [ ] **Nilai berikut dibaca ULANG HARI INI — jangan percaya dokumen:**
      - [ ] `pg_settings` produksi (`WHERE source NOT IN ('default','override')`)
      - [ ] `indisvalid` seluruh index `transactions_transaction` di **produksi** (J4)
      - [ ] IP operator: `curl -s https://api.ipify.org` ↔ `GEO_BLOCK_ALLOWLIST` + WAF Skip
      - [ ] rentang Cloudflare (`ips-v4`/`ips-v6`) bila fase menyentuh ufw
- [ ] `tmux -s migrasi` aktif; sesi root FASE 0 masih terbuka bila GERBANG 1 belum lulus
- [ ] Variabel sesi benar: `$STAMP`, `$DUMPDIR`, `$PROD_URL`, `$NEWPW` (sesuai fase)
- [ ] Jalan mundur fase ini sudah dibaca habis SEBELUM perintah pertama

## 2. Perintah berurut
Aturan: **satu blok = satu alasan.** Tiap blok didahului satu kalimat "kenapa" dan tidak digabung
dengan blok lain meski berurutan — blok gabungan menyembunyikan langkah mana yang gagal.

```bash
# Wrapper WAJIB untuk SETIAP manage.py — env dimuat DI DALAM batas sudo.
# `set -a; . /etc/toa.env; set +a` di shell pemanggil LALU `sudo -u toa …` TIDAK BEKERJA:
# `Defaults env_reset` membuang DATABASE_URL & DEBUG tepat sebelum Python berjalan,
# dan Django jatuh ke SQLite (J1 lahir kembali di dalam perbaikan J1-nya sendiri).
toa_manage() {
  sudo -u toa bash -c 'set -a; . /etc/toa.env; set +a; cd /opt/toa && exec .venv/bin/python manage.py "$@"' _ "$@"
}
```

## 3. Bukti-lulus (biner)
**Tempel keluaran MENTAH ke catatan fase — bukan ringkasan, bukan parafrasa, bukan "sesuai".**

| Perintah | Nilai yang WAJIB muncul |
|---|---|
| `<perintah verifikasi 1>` | `<string/angka persis>` |
| `<perintah verifikasi 2>` | `<string/angka persis>` |
| `test ! -f /opt/toa/db.sqlite3` | exit 0 — **tripwire J1** |
| `sudo -u toa git -C /opt/toa status --porcelain` | keluaran **kosong** — tripwire checkout |

Keduanya melengkapi, bukan menggantikan: `db.sqlite3`/`media/`/`staticfiles/` masuk `.gitignore`,
jadi `git status` **buta** terhadap SQLite yang diam-diam terbuat — dan `test -f` buta terhadap
berkas liar di checkout.

## 4. Jalan mundur
- **Pemicu:** <kondisi terukur, bukan firasat — mis. "08:45 dump belum selesai", "GATE A tidak lulus 11:00">
- **Langkah:** <urut, tiap langkah punya bukti keberhasilannya sendiri>
- **Biaya:** <waktu + apa yang hilang>
- **Titik setelah mana rollback TIDAK lagi gratis:** <mis. FASE 4 langkah 18 — begitu
  `default_transaction_read_only` dibuka, R4 berlaku: rollback DNS hanya bila watermark VPS belum
  bergerak, dan merge parsial tidak pernah diizinkan>

## 5. Yang TIDAK dikerjakan di fase ini (daftar godaan)
- <"menyetel `shared_buffers` di atas paritas produksi" — perlambatan jadi tak bisa dilacak>
- <"sekalian pasang worker latar / buang ~870 MB index mati" — backlog pasca-stabil; dua perubahan
  sekaligus membuat penyebab tak terlacak>
- <"pakai Let's Encrypt karena lebih familiar" — J10: mustahil di topologi oranye>
````

## 5. Catatan penutup untuk eksekutor

**Setiap angka di rencana v2.1 adalah pengukuran 31-08 / 01-09-2026, bukan konstanta.** Rencana itu
sendiri menulisnya: *"Sebelum FASE 1, baca ulang setelan produksi — jangan percaya tabel ini pun."*
Yang **wajib** dibaca ulang pada hari eksekusi, minimal:

- `pg_settings` produksi — v2.1 menemukan CLAUDE.md melenceng pada 5 dari 8 parameter, dan
  `work_mem=4MB` + `maintenance_work_mem=64MB` ternyata `source=default` (`ALTER SYSTEM` v1.18.0
  tidak seluruhnya selamat). Tulis setiap parameter **eksplisit**.
- `indisvalid` seluruh index `transactions_transaction` di produksi — `pg_dump` **membuang** index
  invalid, `TambahIndexAman` menelan kegagalan build, `django_migrations` ter-restore sebagai
  sudah-selesai; satu `false` yang lolos = index hilang permanen (J4).
- IP operator (`curl -s https://api.ipify.org`) terhadap `GEO_BLOCK_ALLOWLIST` **dan** WAF Skip — IP
  dinamis yang bergeser semalam mengunci operator keluar tepat saat cutover, dan J12 menutup pintu
  `GEO_BLOCK_BYPASS_STAFF` untuk permintaan anonim.
- Ukuran & laju DB — v2.1 mengoreksi "17 GB / 9,37 jt / +5 GB/bln" menjadi 18 GB / 8.839.002 baris /
  ±11 GB/bln. Angka lama tidak tereproduksi.

**Perlakukan selisih apa pun sebagai temuan yang harus DIJELASKAN sebelum melangkah, bukan
diabaikan.** Selisih tak terjelaskan adalah asumsi yang belum ketahuan salahnya, dan di FASE 4
harganya database keuangan. Persis aturan T-1 rencana: *"Beda tanpa penjelasan = cutover batal."*

---

## Catatan penyimpangan

1. **Tripwire `git status --porcelain` bukan milik rencana v2.1** (rencana hanya menetapkan
   `test ! -f /opt/toa/db.sqlite3`). Aman ditambahkan karena `.gitignore` memuat `db.sqlite3`,
   `media/`, `staticfiles/`, `.venv/` — symlink `media` dan hasil `collectstatic` tak mengotorinya.
   Kalau berisik di lapangan, yang gugur tripwire ini.
2. **"Paralel dengan langkah berikutnya" dibatasi rencana.** Instruksi pemetaan membolehkan paralel
   tanpa syarat; rencana menetapkan FASE 2 *"Satu saja meleset → BERHENTI"* dan abort 11:00 untuk
   GATE A. Kompromi §2: paralel sampai langkah 17, verdict masuk sebelum langkah 18. Rencana menang.
3. **Verifikasi silang subagent bukan pengganti gerbang.** Gerbang tetap dijalankan INLINE
   (`./scripts/gerbang.sh banding <IP-VPS> live|final`); subagent hanya mengaudit keluarannya.
4. **`gerbang.sh` tidak punya subperintah `dump`/`restore`** — keduanya sengaja dihapus dan keluar
   kode 2 sambil menunjuk FASE 2 bagian C–G. Jangan mencari otomatisasi yang memang tidak ada.
