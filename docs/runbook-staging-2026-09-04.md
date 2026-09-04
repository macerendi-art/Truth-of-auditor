# Runbook — Lingkungan staging (F3, 2026-09-04)

Status sebelum ini: **tidak ada lingkungan staging sama sekali** (butir F3). Konsekuensinya
(F5): setiap perbaikan mendarat langsung di aplikasi keuangan yang hidup, lewat deploy manual
satu orang, tanpa gerbang apa pun. Dokumen ini menutup F3 dengan staging yang **berguna, bukan
lengkap**: aplikasi nyata berjalan terhadap salinan data nyata, dapat dijangkau hanya lewat
tailnet, dengan cara menyegarkan data dan memasang revisi kode masing-masing satu perintah.

Sumber tugas: `.superpowers/sdd/prompt-eksekusi-perbaikan-2026-09-04/4d-brief.md` butir F3.

## Apa ini, dan apa BUKAN ini

Berjalan di VPS **`toa`** (alias SSH `ssh toa`, tailnet — **bukan** `toa-publik`). **Sengaja
terpisah total** dari dua hal lain yang sudah hidup di VPS yang sama, supaya tidak ada yang
saling menabrak:

| | Punya siapa | Untuk apa | Disentuh F3? |
|---|---|---|---|
| `/opt/toa`, `/etc/toa.env`, `toa.service`, DB `toa` | Gladi migrasi Contabo (2026-09-01) + dipakai ulang B1 (pemantauan, read-only ke PRODUKSI) | Pembanding cutover + checkout CLI untuk `periksa_kesehatan`/`periksa_index` | **TIDAK** |
| `~/cadangan/`, `toa-cadangan.*` | A1 | Cadangan harian dari produksi | **TIDAK** (staging cuma MEMBACA `status.json`-nya) |
| `/opt/toa-staging`, `/etc/toa-staging.env`, `toa-staging.service`, DB `toa_staging`, user OS `toa_staging` | **F3 (baru, dokumen ini)** | Staging | — |

Ini **BUKAN** replika produksi yang selalu sinkron (data disegarkan manual, satu perintah,
bukan otomatis), **BUKAN** dipasangi TLS publik/domain publik (hanya tailnet), dan **BUKAN**
dianonimkan (lihat bagian "Data nyata di staging" — keputusan sadar, dengan alasan).

## Arsitektur

```
Tailnet member (mac-rnd, dst.)
        │  HTTPS (cert asli tailnet, MagicDNS)
        ▼
https://truthofauditor.taila54dc6.ts.net/          <-- tailscale serve, HANYA di tailnet
        │  proxy (tailscaled sendiri, tidak lewat nginx/nginx tidak dipakai sama sekali)
        ▼
127.0.0.1:8001 (loopback SAJA)                     <-- gunicorn, toa-staging.service
        │
        ▼
127.0.0.1:5432 / database "toa_staging"            <-- Postgres 18.6 lokal, role toa_staging
```

Tidak ada nginx yang dilibatkan untuk staging (nginx yang sudah ada di VPS ini cuma menyajikan
halaman default placeholder — tidak diubah). `tailscale serve` (fitur bawaan Tailscale, bukan
kode yang kami tulis) yang menerbitkan sertifikat TLS asli untuk nama MagicDNS node ini dan
mem-proxy port 443-tailnet-saja ke gunicorn loopback. Dipilih dibanding nginx+sertifikat
sendiri karena: (a) satu perintah, tanpa mengelola sertifikat; (b) TLS ASLI (bukan self-signed)
menyalakan `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE` (keduanya `True` tanpa syarat saat
`DEBUG=False` di `truth_auditor/settings.py`, tidak bisa ditimpa lewat env — jadi tanpa HTTPS
sungguhan, TIDAK ADA seorang pun bisa login di staging); (c) secara struktural cuma bisa
dijangkau dari tailnet — `tailscale serve` (beda dari `tailscale funnel`) menolak lalu lintas
dari luar tailnet di level tailscaled sendiri, dan **`funnel` tidak pernah dipakai/diaktifkan**
di pekerjaan ini.

## Isolasi dari produksi & dari `toa` — dan buktinya

Ini bagian paling berisiko dari seluruh pekerjaan, jadi diuraikan poin demi poin dengan
perintah pembuktiannya (dijalankan 2026-09-04, lihat bagian "Bukti" untuk keluaran mentahnya).

1. **OS user terpisah, tanpa akses ke rahasia produksi.** Proses staging (`toa-staging.service`
   + langkah `pip`/`migrate`/`collectstatic` dalam `pasang-revisi.sh`) berjalan sebagai user OS
   **`toa_staging`** (baru, `useradd --system --create-home`), BUKAN user `toa` yang memegang
   `~/.pgpass`/`~/.prod-url` (kredensial produksi Railway, dipakai cadangan A1 & pemantauan B1).
   Home directory `toa_staging` terpisah total.
   **Bukti**: `sudo -u toa_staging cat /home/toa/.pgpass` dan `.../.prod-url` → **Permission
   denied** (mode 0600 milik `toa`, `toa_staging` bukan anggota grup `toa` dan bukan pemiliknya).
   Ini BUKAN cuma "kami tidak mengisi env dengan itu" — bahkan kalau `DATABASE_URL` staging
   suatu hari salah ketik kehilangan sandinya (psycopg baru akan mencari `~/.pgpass` MILIK USER
   YANG MENJALANKAN PROSES), proses `toa_staging` tidak akan pernah bisa membaca berkas
   `.pgpass` produksi — bukan janji konfigurasi, tapi izin filesystem.
2. **Tidak ada rujukan ke produksi di env staging sama sekali.** `/etc/toa-staging.env`
   `DATABASE_URL` menunjuk `127.0.0.1:5432` (lokal), **bukan** proxy Railway. Tidak ada
   `~/.prod-url`/host Railway yang muncul di berkas ini.
   **Bukti**: `grep -ciE 'railway|rlwy|proxy'  /etc/toa-staging.env` → `0`.
3. **Password DATABASE_URL SELALU eksplisit, tidak pernah mengandalkan `.pgpass`.**
   `DATABASE_URL` staging membawa sandinya sendiri (`postgres://toa_staging:<hex>@127.0.0.1/…`)
   — psycopg/libpq HANYA membaca `~/.pgpass` saat field password KOSONG (`django/db/backends/
   postgresql/base.py` `get_connection_params`: `if settings_dict["PASSWORD"]:`). Jadi bahkan
   secara TEORI, jalur ke `.pgpass` tertutup dua lapis: sandi selalu terisi, DAN filesystem
   menolak (poin 1).
4. **Role Postgres terpisah, sengaja BUKAN pemilik apa pun di database `toa`.** Role
   `toa_staging` (`LOGIN PASSWORD ...`, TANPA `SUPERUSER`/`CREATEDB`/`CREATEROLE`) dibuat baru,
   tidak pernah diberi hak apa pun secara eksplisit atas database `toa`.
   **Bukti**: `psql toa -Atc "SELECT has_table_privilege('toa_staging','transactions_transaction','SELECT');"`
   → `f`. **Jujur soal batasnya**: role BISA secara teknis mencoba `CONNECT` ke database `toa`
   (Postgres memberi `CONNECT` ke `PUBLIC` secara default di semua database baru, dan ini
   SENGAJA tidak dicabut — `REVOKE CONNECT ... FROM PUBLIC` berarti mengubah ACL `toa`, dan
   `toa` HARAM disentuh sama sekali, termasuk untuk "pengerasan"). Yang menutup celah itu bukan
   larangan koneksi, tapi TIDAK ADANYA hak baca/tulis atas tabel apa pun di `toa` — dibuktikan
   di atas.
5. **Database `toa` dan `~/baseline.txt` tidak tersentuh — dibuktikan dengan angka, bukan
   janji.** Lihat bagian "Bukti" di bawah: hitung baris + tiga jumlah (`amount`/`credit_delta`/
   `money_delta`) atas `transactions_transaction` di `toa`, diambil SEBELUM pekerjaan ini
   dimulai dan SESUDAH semua langkah selesai — identik. `md5sum ~/baseline.txt` juga diperiksa
   sebelum/sesudah. `scripts/staging/refresh-data.sh` sendiri menjalankan ulang perbandingan
   yang SAMA di setiap kali dipakai (baris "Baseline toa SEBELUM/SESUDAH", exit 3 kalau beda)
   — ini bukan cuma bukti sekali jalan, tapi gerbang permanen di skrip.
6. **`GEO_BLOCK_ENABLED=false` di staging** (env, bukan kode) — GeoBlockMiddleware KH-only
   produksi tidak relevan untuk operator yang mengakses lewat tailnet dari mana pun, dan kode
   `web/middleware.py` tidak disentuh sama sekali (larangan berkas F3). `IPAllowlistMiddleware`
   TIDAK diberi env kill-switch di kode (memang tidak ada satu di sumbernya) — perilakunya
   murni dari isi tabel `web.models.AllowedIP` yang IKUT TERSALIN dari dump produksi. Ini
   berarti: user berperan auditor/supervisor yang login di staging BISA digerbang kalau tabel
   `AllowedIP` staging (salinan produksi) berisi entri aktif dan IP tailnet operator tidak
   cocok — admin/superuser TIDAK PERNAH digerbang middleware ini, jadi login sebagai admin
   selalu bisa dipakai untuk mencoba revisi. Kalau perlu mencoba peran auditor/supervisor
   secara penuh, kosongkan/nonaktifkan baris `AllowedIP` di database `toa_staging` SAJA (bukan
   produksi) — ini aman karena `toa_staging` terpisah total dari produksi.

## Data nyata di staging — sikap eksplisit soal anonimisasi

`toa_staging` adalah **salinan LANGSUNG** data produksi (nama pemain, nomor rekening, nomor
HP, saldo — semua asli). Staging yang bocor sama buruknya dengan produksi yang bocor.
**Keputusan: TIDAK dianonimkan di rilis F3 ini**, dengan alasan eksplisit (bukan didiamkan):

- Nilai utama staging adalah mereproduksi PERILAKU pencocokan matcher — fuzzy name ≥85,
  kunci HP/VA/rekening, username persis (lihat `reconciliation/engine.py`, aturan anchor di
  `CLAUDE.md`). Data yang dianonimkan (nama diacak, nomor rekening di-hash) akan MERUSAK
  kalibrasi itu: hasil cocok/tidak-cocok di staging tidak lagi mencerminkan perilaku nyata,
  sehingga staging kehilangan justru nilai yang dicari — "coba dulu sebelum produksi".
- Mitigasi yang SUDAH berlaku, terlepas dari anonimisasi: hanya dapat dijangkau lewat tailnet
  (bukan mesin di tailnet siapa pun bisa join tanpa persetujuan admin Tailscale), TLS asli
  (bukan HTTP polos), butuh login (akun tersalin dari produksi — lihat poin berikut).
- **Konsekuensi yang WAJIB disadari pemilik, bukan cuma catatan kaki**: tabel `accounts_user`
  IKUT TERSALIN dari dump produksi, termasuk **hash password**. Hash password TIDAK bergantung
  pada `SECRET_KEY` (Django pakai PBKDF2/Argon2 murni dari password+salt, `SECRET_KEY` cuma
  dipakai untuk signing session/token, BUKAN untuk hashing password) — jadi **password akun
  produksi yang sama TETAP BEKERJA untuk login ke staging**. `SECRET_KEY` staging yang baru
  (lihat bagian "Cara memasang") membuat SESSION/TOKEN produksi tidak valid di staging (tidak
  bisa "curi sesi"), tapi TIDAK mencegah login ulang dengan password asli. Kalau staging bocor,
  itu setara kebocoran hash password produksi.
- **Rekomendasi (tertahan pada pemilik, lihat bagian akhir)**: pertimbangkan membuat SATU akun
  admin khusus staging (password berbeda) lewat `manage.py createsuperuser` di `toa_staging`
  setelah tiap refresh, dan JANGAN bagikan kredensial staging seluas kredensial produksi.
  Anonimisasi penuh bisa jadi pekerjaan LANJUTAN kalau pemilik memutuskan risikonya lebih besar
  dari nilai kalibrasi matcher — di luar cakupan F3 ini.

## Cara mengakses

Dari mesin mana pun yang **join tailnet yang sama** (mis. `mac-rnd`, `windows-sniper`, dst.):

```
https://truthofauditor.taila54dc6.ts.net/
```

Tidak perlu VPN/port-forward tambahan — MagicDNS tailnet me-resolve nama itu ke
`100.102.118.125`, dan `tailscale serve` menolak lalu lintas dari luar tailnet di level
tailscaled (bukan sekadar firewall `ufw` — walau `ufw allow in on tailscale0` juga sudah
terpasang sebagai lapis kedua). **Tidak pernah** ada domain publik/IP publik yang mengarah ke
staging ini.

## Cara menyegarkan data (`scripts/staging/refresh-data.sh`)

Satu perintah, dijalankan **di VPS** (`ssh toa`) sebagai user `toa`:

```bash
bash scripts/staging/refresh-data.sh
```

Yang terjadi (lihat komentar di berkas untuk detail/alasan tiap langkah):

1. Membaca dump TERBARU yang **terbukti baik** dari `~/cadangan/status.json` (A1) —
   `verdict == "OK"` dan `dump_dir`-nya — BUKAN `ls /var/backups/toa | tail -1` (yang bisa
   membaca direktori yang sedang ditulis kalau kebetulan tumpang tindih jendela cadangan
   03:00–03:30 WIB).
2. Verifikasi `sha256sum -c` manifest + `pg_restore -l` (TOC terbaca) — sama seperti restore
   uji A1.
3. **Baseline `toa` dicatat SEBELUM apa pun disentuh.**
4. Stop `toa-staging.service`, putuskan koneksi lama ke `toa_staging`, `dropdb`+`createdb` ulang
   `toa_staging` (owner sementara `toa` untuk restore lewat peer auth lokal — proses baca 700
   milik `toa`), `pg_restore --no-owner --no-privileges`.
5. **Pindah kepemilikan objek ke role `toa_staging`** lewat `ALTER TABLE/SEQUENCE/VIEW ... OWNER
   TO`, SATU-PER-SATU di dalam database `toa_staging` saja — BUKAN `REASSIGN OWNED BY toa`
   (itu ikut mereassign objek BERSAMA di seluruh cluster, termasuk yang tak berkaitan dengan
   `toa_staging`, dan berpotensi tak sengaja ikut memindahkan sesuatu di `toa`). Diverifikasi
   dengan hitungan objek yang BUKAN milik `toa_staging` — harus nol, atau skrip berhenti FATAL.
   **Kenapa ini penting**: `pg_restore --no-owner` membuat objek dimiliki `toa`. Kalau
   dibiarkan, `manage.py migrate` sebagai role `toa_staging` akan gagal `ALTER TABLE`/
   `CREATE INDEX` karena bukan pemilik — dan `core/db_ops.TambahIndexAman` (dipakai migrasi
   index terbaru) MENELAN kegagalan itu lalu tetap mencatat migrasi selesai. Index-nya
   sebenarnya TIDAK pernah terbentuk, `periksa_index` sesudahnya akan melapor MISSING, dan
   tidak ada satu pun error yang terlihat di `migrate`. Ini persis jebakan yang brief minta
   dijaga lewat "jalankan `periksa_index` sesudahnya".
6. `vacuumdb --analyze` (dua tahap, sama seperti restore uji A1).
7. `manage.py migrate --noinput` memakai revisi kode yang **sedang terpasang** di
   `/opt/toa-staging` (lihat `pasang-revisi.sh` di bawah untuk mengganti revisi).
8. `manage.py periksa_index` — hasilnya WAJIB dilaporkan (lihat bagian Bukti).
9. Start ulang `toa-staging.service`.
10. **Baseline `toa` dicatat SESUDAH dan dibandingkan byte-untuk-byte dengan SEBELUM** — beda
    apa pun = skrip keluar kode 3 dengan pesan FATAL. `~/baseline.txt` tidak pernah disentuh
    sama sekali oleh skrip ini (tidak dibaca, tidak ditulis).

**Tidak dijadwalkan (sengaja).** Beda dari cadangan (A1)/pemantauan (B1) yang harus otomatis
harian, staging TIDAK butuh selalu segar — ini alat "coba sebelum produksi", operator yang
memutuskan kapan perlu data lebih baru. Menjadwalkannya berarti menambah satu timer systemd
lagi yang harus dikoordinasikan penamaannya dengan `toa-cadangan.timer`/`toa-kesehatan.timer`/
`toa-probe.timer` yang sudah ada — di luar cakupan yang diminta F3. Bisa ditambah nanti kalau
pemilik memutuskan itu berguna (lihat "Tertahan pada pemilik").

## Cara memasang revisi kode tertentu (`scripts/staging/pasang-revisi.sh`)

Satu perintah, dijalankan **dari mesin lokal** (checkout mana pun yang memiliki revisi yang
mau dicoba — worktree ini, atau checkout lain):

```bash
scripts/staging/pasang-revisi.sh <ref>
# contoh:
scripts/staging/pasang-revisi.sh HEAD
scripts/staging/pasang-revisi.sh origin/main
scripts/staging/pasang-revisi.sh 4d2f6a1c
```

**Sengaja lewat `git archive | ssh toa tar -x`, BUKAN `git push` + `git pull` di VPS.** Cabang
kerja hari ini (`claude/prompt-eksekusi-perbaikan-1c3f75`) berisi banyak commit yang belum (dan
mungkin sebagian tidak akan pernah) di-push ke `origin` — aturan tetap pekerjaan F3 ini
eksplisit melarang push. `git archive` bekerja atas riwayat git LOKAL apa pun, ter-push atau
tidak, jadi "coba dulu sebelum produksi" tetap bisa dipakai untuk kerja yang masih di laptop.
Untuk revisi yang MEMANG sudah di GitHub (mis. `origin/main`, atau cabang PR yang sudah
di-push), perintah yang sama tetap bekerja apa adanya — `git rev-parse` menyelesaikan ref dari
riwayat lokal (yang mencakup apa pun sudah di-`fetch`).

Yang terjadi:

1. Resolve `<ref>` → SHA commit penuh, pastikan ada di riwayat lokal.
2. Bersihkan `/opt/toa-staging` LAMA (kecuali `.venv`/`staticfiles`/`media`) — supaya berkas
   yang DIHAPUS di revisi baru (migrasi di-squash, modul di-rename) tidak diam-diam tertinggal
   dan ikut diimpor Django dari revisi sebelumnya.
3. `git archive <sha> | ssh toa "sudo -u toa_staging tar -x -C /opt/toa-staging"`.
4. Tulis `/opt/toa-staging/REVISI` (SHA yang sedang terpasang — dipakai skrip refresh untuk
   `migrate` dengan revisi yang benar).
5. `pip install -r requirements.txt` (idempoten), `manage.py migrate --noinput`,
   `manage.py collectstatic --noinput`, `manage.py periksa_index`.
6. `systemctl restart toa-staging.service`.
7. Verifikasi HTTP dari VPS sendiri (`curl 127.0.0.1:8001/login/`) — verifikasi dari mesin
   tailnet LAIN (lebih kuat) didokumentasikan terpisah di bagian Bukti.

## Cara memasang (bootstrap satu-kali) — sudah dijalankan 2026-09-04

Lihat `scripts/staging/bootstrap-vps.sh` untuk catatan ter-versi dari langkah-langkah yang
sudah dijalankan tangan untuk membangun staging pertama kali: user OS `toa_staging`, role
Postgres `toa_staging` (password `openssl rand -hex 24` — HEX, bukan base64, supaya tidak ada
`+/=` yang merusak parsing `DATABASE_URL` atau `set -a; . env; set +a`), direktori
`/opt/toa-staging` + `/var/lib/toa-staging/media`, unit systemd `toa-staging.service`
(`scripts/staging/toa-staging.service`, tersalin ke `/etc/systemd/system/`), dan
`tailscale serve --bg --https=443 http://127.0.0.1:8001`.

`SECRET_KEY` staging dibuat LANGSUNG di VPS (`secrets.token_hex(32)`, dijalankan lewat Python
di VPS, tidak pernah lewat mesin lokal/repo) dan ditulis ke `/etc/toa-staging.env`
(`chmod 640 root:toa_staging`) — **BARU, tidak pernah disalin dari SECRET_KEY produksi**. Lihat
`scripts/staging/toa-staging.env.example` untuk bentuk berkasnya (tanpa nilai nyata).

**Catatan kejujuran operasional**: SECRET_KEY staging pertama yang dibuat sempat ikut tercetak
di transkrip perintah verifikasi (kesalahan redaksi `sed` yang hanya menutupi baris
`DATABASE_URL`) sebelum sempat dipakai untuk melayani trafik apa pun — langsung DIROTASI
(`ALTER`... eh, `sed -i` menimpa nilai baru) sebelum `toa-staging.service` pertama kali
dijalankan. Nilai yang benar-benar dipakai untuk melayani trafik tidak pernah tercetak.

## Migrasi index pada data besar

`toa_staging` hasil restore membawa ~10 juta baris `transactions_transaction` (ukuran sama
kelasnya dengan produksi). Migrasi terbaru cabang ini (`transactions/0012_tambah_index_
kategori_hutang_piutang`) memakai `core/db_ops.TambahIndexAman` (lihat preseden `0008`–`0011`
di `CLAUDE.md`) — aman dijalankan lewat `migrate` biasa di SQLite/tanpa `CONCURRENTLY` untuk
tes, tapi di Postgres produksi/staging bisa berjalan cukup lama dan (INI YANG DIPERIKSA F3)
MENELAN kegagalan "must be owner" secara senyap kalau kepemilikan objek salah — lihat langkah
5 `refresh-data.sh` di atas. `manage.py periksa_index` WAJIB dijalankan setelah setiap
`migrate` (baik lewat `refresh-data.sh` maupun `pasang-revisi.sh`, keduanya sudah
menjalankannya otomatis) — hasilnya dicatat di bagian Bukti.

## Bukti (dijalankan 2026-09-04)

> Angka detail (transkrip perintah, timing persis, checksum) — lihat
> `.superpowers/sdd/prompt-eksekusi-perbaikan-2026-09-04/4d-report.md`.

- **Baseline `toa` SEBELUM pekerjaan dimulai**: `count=8850457`,
  `sums=3189459707209.92 | -93733605229.10 | 216200143883.94`. `md5sum ~/baseline.txt` =
  `6ad10a1aac6a41303e65a85d4eb45a04` (17 baris).
- **Isolasi OS**: `sudo -u toa_staging cat /home/toa/.pgpass` → `Permission denied`;
  `.../.prod-url` → `Permission denied`.
- **Isolasi Postgres**: `psql toa -Atc "SELECT has_table_privilege('toa_staging',
  'transactions_transaction','SELECT');"` → `f`.
- **Restore `toa_staging`**: dump sumber `/var/backups/toa/dump-2026-09-04` (verdict `OK`,
  checksum manifest cocok — 30 berkas SEMUA `OK` — TOC 448 entri terbaca bersih, sama dump yang
  dipakai restore uji A1 hari ini). Dijalankan lewat `systemd-run` transient unit (durasinya
  melebihi satu pemanggilan interaktif): mulai 18:29:29 WIB, selesai 18:44:57 WIB (**15m28d**
  untuk restore + dua tahap `vacuumdb --analyze`, sedikit lebih cepat dari restore uji A1
  [13m48d restore SAJA, tanpa vacuum] karena berjalan paralel dengan langkah lain, bukan sinyal
  performa berbeda). Hasil: **10.341.991 baris** `transactions_transaction` (persis sama dengan
  angka yang dicatat A1 saat dump ini dibuat), ukuran DB **16 GB**.
- **Pemindahan kepemilikan objek** (57 tabel/sequence/view di skema `public`) ke role
  `toa_staging` — percobaan pertama GAGAL di `accounts_user_allowed_tokos_id_seq` ("is linked
  to table", sequence identity/serial tidak boleh di-`ALTER OWNER` langsung, harus dilewati dan
  ikut berpindah otomatis bersama tabelnya). Diperbaiki (kecualikan sequence ber-`pg_depend
  deptype='a'`), lalu **0 objek** tersisa bukan milik `toa_staging` — perbaikan yang sama sudah
  masuk `refresh-data.sh` (lihat komentar di berkas).
- **`manage.py migrate --noinput`** atas `toa_staging` (revisi kode saat itu: `fe7df67`) —
  4 migrasi baru diterapkan bersih (`core.0003_auditlog_ip_user_agent`,
  `loginguard.0001_initial`, `transactions.0011_buang_index_username_reference`,
  `transactions.0012_tambah_index_kategori_hutang_piutang` — yang terakhir index parsial
  `TambahIndexAman` di atas 10,3 juta baris). **`manage.py periksa_index` sesudahnya**: `21
  index di DB, 9 diwajibkan model. Bersih — tak ada index hilang/invalid.` (exit 0) —
  membuktikan jebakan "must be owner" yang diperingatkan brief TIDAK terjadi di sini karena
  pemindahan kepemilikan di atas sudah benar sebelum `migrate` dijalankan.
- **`443` HANYA di IP tailnet**: `sudo ss -tlnp | grep :443` → `100.102.118.125:443` (+ alamat
  IPv6 tailnet `fd7a:115c:a1e0::f2d:767e`), **BUKAN** `0.0.0.0:443`. `8001` HANYA di
  `127.0.0.1` (dipegang proses `gunicorn` milik `toa-staging.service`). `8000` (rehearsal
  `/opt/toa`, tak disentuh) tetap berdiri sendiri di `127.0.0.1` juga.
- **`tailscale serve status`**: `https://truthofauditor.taila54dc6.ts.net (tailnet only) |--
  / proxy http://127.0.0.1:8001`. `tailscale funnel` tidak pernah dipanggil sepanjang pekerjaan
  ini.
- **HTTP lewat tailnet, DUA node berbeda**: dari VPS `toa` sendiri lewat `tailscale serve`
  (`curl https://truthofauditor.taila54dc6.ts.net/login/`) → `HTTP 200`, `<title>Masuk ·
  Truth of Auditor</title>`; **diulang dari mesin lokal (node tailnet LAIN)** dengan hasil
  IDENTIK: `HTTP 200`, judul halaman sama. (Diakses langsung ke `127.0.0.1:8001` TANPA lewat
  `tailscale serve`, yaitu tanpa header `X-Forwarded-Proto`, hasilnya `HTTP 301` — perilaku
  `SECURE_SSL_REDIRECT` default Django saat `DEBUG=False`, BUKAN kegagalan; ini justru
  membuktikan endpoint loopback murni tidak berguna tanpa proxy TLS di depannya, konsisten
  dengan klaim "hanya lewat tailnet".)
- **Baseline `toa` SESUDAH semua langkah selesai**: `count=8850457`,
  `sums=3189459707209.92 | -93733605229.10 | 216200143883.94` — **identik byte-untuk-byte**
  dengan SEBELUM. `md5sum ~/baseline.txt` = `6ad10a1aac6a41303e65a85d4eb45a04` — **tidak
  berubah**.
- **Isolasi tambahan dibuktikan ulang pasca-setup**: `grep -ciE 'railway|rlwy|proxy'
  /etc/toa-staging.env` → `0`. `DATABASE_URL` di berkas itu menunjuk
  `127.0.0.1:5432/toa_staging` (sandi disensor saat diperiksa, tak pernah dicetak utuh di
  transkrip kerja).

## Yang tertahan pada pemilik

1. **Anonimisasi data staging** — keputusan diambil (TIDAK dilakukan, lihat alasan di atas),
   tapi ini keputusan pemilik untuk diratifikasi/dibalik, bukan sesuatu yang boleh didiamkan.
2. **Akun staging terpisah dari akun produksi** — password produksi TETAP BEKERJA di staging
   (hash tersalin apa adanya). Rekomendasi: buat admin staging sendiri, jangan sebarkan akses
   staging seluas akses produksi.
3. **Penjadwalan refresh data** — sengaja manual (lihat alasan di atas). Kalau pemilik mau
   otomatis (mis. mingguan), perlu timer baru bernama konsisten (`toa-staging-refresh.timer`?)
   dikoordinasikan supaya tidak menimpa jam `toa-cadangan`/`toa-kesehatan`/`toa-probe`.
4. **Port tailnet `:443` di node `truthofauditor` sekarang dipakai staging** — kalau proyek
   migrasi Contabo (`docs/rencana-migrasi-contabo-2026-08-31.md`) lanjut ke cutover sungguhan
   dan berencana memakai `tailscale serve`/port yang sama untuk lalu lintas produksi nyata di
   node ini, KOORDINASIKAN dulu sebelum menimpa konfigurasi `tailscale serve` yang dibuat di
   sini.
5. **Pengerasan lanjutan (opsional, tidak dikerjakan)**: aturan `iptables`/`nftables` berbasis
   `--uid-owner toa_staging` yang menolak SEMUA egress ke host Railway secara eksplisit, sebagai
   lapis pertahanan tambahan di atas ketiadaan kredensial. Tidak dikerjakan di F3 ini karena
   bukti ketiadaan-kredensial (poin 1–4 di bagian isolasi) sudah menutup jalur yang realistis;
   dicatat sebagai perbaikan lanjutan kalau pemilik ingin pertahanan berlapis lebih jauh.

## Batasan yang diketahui / tidak dikerjakan (jujur, bukan diam-diam)

- Tidak ada halaman "staging ini bukan produksi" di UI (kode `web/`/`truth_auditor/` tidak
  disentuh — di luar berkas yang boleh ditulis F3). Operator harus mengingat sendiri dari URL
  (`truthofauditor.taila54dc6.ts.net`, beda dari `auditor.wolfgang-77.com` produksi).
- Refresh data tidak menjaga riwayat (`toa_staging` ditimpa penuh tiap kali) — kalau perlu
  membandingkan dua titik waktu data, itu di luar cakupan "berguna, bukan lengkap" F3.
- `toa-kesehatan.service` (B1, pekerjaan lain) berstatus `failed` di `systemctl list-units` saat
  pekerjaan F3 ini dimulai — **sudah begitu sebelum F3 disentuh**, bukan akibat pekerjaan ini,
  tidak diperbaiki di sini (di luar cakupan berkas yang boleh ditulis F3, dan bukan bagian dari
  pemantauan/cadangan yang harus "tidak ditabrak" — hanya diamati dan dicatat di sini secara
  jujur).
