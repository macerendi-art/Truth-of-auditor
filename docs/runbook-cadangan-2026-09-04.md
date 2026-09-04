# Runbook — Cadangan basis data produksi (A1, 2026-09-04)

Status sebelum ini: **produksi tidak punya cadangan sama sekali.** Dokumen ini menutup itu:
cadangan harian terjadwal, teruji lewat restore sungguhan, dan terpantau lewat berkas status.

Sumber tugas: `docs/daftar-perbaikan-2026-09-03.md` butir A1.

## Apa ini, dan apa BUKAN ini

Cadangan berjalan di VPS **`toa`** (alias SSH `ssh toa`, tailnet — bukan `toa-publik`/IP publik,
yang kena `ufw limit`+fail2ball dan bisa mengunci diri sendiri). VPS ini menarik dump **langsung
dari Railway produksi lewat proxy TCP publik** (host proxy ada di `~/.prod-url` pada VPS — lihat
larangan di bawah soal kredensial) dan menyimpannya di disk lokal VPS itu sendiri
(`/var/backups/toa/`).

> **Cadangan ini disimpan di VPS yang juga direncanakan menjadi produksi berikutnya
> (lihat `docs/rencana-migrasi-contabo-2026-08-31.md`). Itu bukan cadangan offsite: kalau mesin
> itu hilang, cadangan dan calon produksi hilang bersamaan. Keputusan ini diambil sadar oleh
> pemilik.**

Konsekuensi praktis: ini melindungi dari *kesalahan/korupsi data di Postgres Railway* (salah query,
migrasi salah, penghapusan tak sengaja lewat Django admin, dsb) dan dari *tidak adanya cadangan
sama sekali* (kondisi sebelum A1). Ini **tidak** melindungi dari hilangnya VPS `toa` itu sendiri
(disk mati, akun Contabo bermasalah, dsb). Cadangan offsite (mis. rclone+crypt ke Google Drive,
sudah didesain di `rencana-migrasi-contabo-2026-08-31.md` bagian "Cadangan") adalah pekerjaan
LANJUTAN, di luar cakupan A1 — catat sebagai risiko terbuka, bukan sesuatu yang diam-diam
dianggap sudah beres.

## Cara kerja

Satu skrip, `~/cadangan/backup-harian.sh` di VPS (salinan ter-versi:
[`scripts/cadangan/backup-harian.sh`](../scripts/cadangan/backup-harian.sh)), dijalankan harian
oleh systemd timer. Urutan kerjanya:

1. **Gerbang J4 — index INVALID.** `pg_dump` **MEMBUANG** index dengan `indisvalid = false`
   secara diam-diam (terverifikasi di sumber `pg_dump.c`, fungsi `getIndexes`, `REL_18_STABLE`),
   dan `migrate` tidak akan pernah membangunnya ulang karena migrasinya sudah tercatat selesai
   (`core/db_ops.TambahIndexAman` menelan kegagalan `CREATE INDEX CONCURRENTLY`). Jadi dump dari
   DB yang sedang punya index invalid kehilangan index itu SELAMANYA begitu direstore ke tempat
   baru — bukan cuma lambat, tapi diam-diam berbeda skema dari yang diklaim.
   Skrip menjalankan langsung ke produksi (lewat proxy):
   ```sql
   SELECT i.indexrelid::regclass AS idx, i.indrelid::regclass AS tbl
   FROM pg_index i WHERE NOT i.indisvalid;
   ```
   Ada baris → skrip **gagal dengan kode keluar bukan-nol, TIDAK menghasilkan dump**, dan nama
   index/tabelnya tercatat di log + berkas status. Ini dijalankan lewat SQL langsung (bukan
   `manage.py periksa_index`) karena Django tidak terpasang di VPS ini; logikanya setara —
   baca `core/management/commands/periksa_index.py` di repo kalau perlu bandingkan. Bedanya
   gerbang ini DB-wide (semua tabel), bukan hanya `transactions_transaction` — `pg_dump`
   membuang index invalid apa pun tabelnya.
2. **Dump.** `pg_dump --format=directory --jobs=4 --statistics --compress=zstd:3` dari
   `~/.prod-url` (kredensial dari `~/.pgpass`, **tidak pernah** di argv). **TIDAK memakai**
   `--snapshot=$SNAP`/`~/snap.out` — itu artefak koordinasi cutover migrasi (menahan satu
   transaksi terbuka supaya dump dan query pembanding membaca titik waktu yang persis sama).
   Cadangan harian berdiri sendiri tidak butuh itu: `pg_dump -j` sudah membuat snapshot
   sinkronnya sendiri untuk worker paralelnya, dan bergantung pada `~/snap.out` di sini hanya
   akan gagal karena berkas itu cuma diperbarui saat gladi migrasi berjalan.
3. **Bukti arsip tidak rusak.** `pg_restore -l "$DUMPDIR" > toc-$STAMP.txt` — TOC yang gagal
   dibaca berarti arsip dump rusak, ditandai GAGAL.
4. **Checksum.** `sha256sum` atas **seluruh isi** direktori dump (format `directory` = banyak
   berkas per tabel/blob, bukan satu berkas tunggal) → `dump-$STAMP.sha256`, bisa diverifikasi
   ulang dengan `sha256sum -c` dari dalam `/var/backups/toa`.
5. **Retensi `-mtime +1`** (BUKAN `+7`). Alasan: `docs/rencana-migrasi-contabo-2026-08-31.md`
   sekitar baris 1040–1065 — 8 salinan × ~0,4×ukuran DB menjebol disk sekitar bulan ke-6.
   Retensi pendek ini sengaja hanya menyisakan cadangan hari ini + kemarin di disk lokal.
   Kegagalan membersihkan salinan lama tidak menggagalkan cadangan hari itu (sudah terbukti
   valid lewat langkah 3–4 di atas).
6. **Berkas status** `~/cadangan/status.json` ditulis/diperbarui di SETIAP akhir jalan (sukses
   maupun gagal) — lihat bagian tersendiri di bawah.

Skrip berjalan dengan `set -euo pipefail` + `umask 077`, log ke `~/cadangan/backup.log` (dirotasi
mingguan oleh `/etc/logrotate.d/toa-cadangan`, 8 generasi, lihat
[`scripts/cadangan/toa-cadangan.logrotate`](../scripts/cadangan/toa-cadangan.logrotate)).

## Di mana berkasnya

| Apa | VPS (`ssh toa`) | Repo (ter-versi) |
|---|---|---|
| Skrip cadangan | `~/cadangan/backup-harian.sh` | `scripts/cadangan/backup-harian.sh` |
| Unit service | `/etc/systemd/system/toa-cadangan.service` | `scripts/cadangan/toa-cadangan.service` |
| Unit alarm gagal | `/etc/systemd/system/toa-cadangan-gagal.service` | `scripts/cadangan/toa-cadangan-gagal.service` |
| Timer | `/etc/systemd/system/toa-cadangan.timer` | `scripts/cadangan/toa-cadangan.timer` |
| Logrotate | `/etc/logrotate.d/toa-cadangan` | `scripts/cadangan/toa-cadangan.logrotate` |
| Dump harian | `/var/backups/toa/dump-YYYY-MM-DD/` (direktori) | — (tidak ter-versi, ini data) |
| TOC | `/var/backups/toa/toc-YYYY-MM-DD.txt` | — |
| Checksum | `/var/backups/toa/dump-YYYY-MM-DD.sha256` | — |
| Status terakhir | `~/cadangan/status.json` | — |
| Log | `~/cadangan/backup.log` | — |
| URL proxy produksi (tanpa sandi) | `~/.prod-url` | — (JANGAN commit) |
| Sandi DB produksi | `~/.pgpass` (mode 0600) | — (JANGAN commit, JANGAN cetak) |

Repo **tidak** menyimpan kredensial apa pun — skrip di repo membaca `~/.prod-url`/`~/.pgpass` dari
host tempat ia dijalankan, persis seperti salinan yang jalan di VPS.

Berkas `~/migrasi/*` (dari gladi migrasi 2026-09-01: `dump-run.sh`, `restore-run.sh`, `fase1.sh`,
dst.) **tidak disentuh** oleh pekerjaan ini — itu perkakas gladi cutover Contabo, hidup
berdampingan dengan direktori `~/cadangan/` yang baru ini, tujuannya berbeda.

## Jadwal

Systemd timer (bukan cron) — dipilih karena `OnFailure=` (memicu unit alarm terpisah),
tercatat di journal, dan `Persistent=true` (jadwal yang terlewat karena mesin mati tetap
dijalankan begitu mesin hidup lagi; cron biasa tidak punya ini).

- **Jam:** `03:00 WIB` harian (`OnCalendar=*-*-* 03:00:00` — server sudah `Asia/Jakarta`),
  `RandomizedDelaySec=300` supaya tidak selalu presisi ke detik yang sama.
- Aktifkan: `sudo systemctl enable --now toa-cadangan.timer`
- **Buktikan jadwalnya nyata:** `systemctl list-timers toa-cadangan.timer` — kolom `NEXT` harus
  menunjukkan tanggal/jam nyata di masa depan.
- Jalankan manual sekali (di luar jadwal, mis. untuk uji coba): `sudo systemctl start
  toa-cadangan.service` (ini unit `Type=oneshot`, `systemctl start` menunggu sampai selesai).
- Matikan sementara: `sudo systemctl stop toa-cadangan.timer` (jangan `disable` kalau cuma mau
  jeda singkat — `disable` melepas dari boot).

## Cara membaca `status.json`

Contoh bentuk (angka ilustratif):

```json
{
  "tanggal": "2026-09-04",
  "mulai": "2026-09-04T17:14:41+07:00",
  "selesai": "2026-09-04T17:27:03+07:00",
  "verdict": "OK",
  "kode_keluar": 0,
  "pesan": "cadangan berhasil",
  "dump_dir": "/var/backups/toa/dump-2026-09-04",
  "ukuran_bytes": 1543210987,
  "toc_file": "/var/backups/toa/toc-2026-09-04.txt",
  "sha256_manifest": "/var/backups/toa/dump-2026-09-04.sha256",
  "sha256_manifest_hash": "…",
  "terakhir_ok": "2026-09-04T17:27:03+07:00"
}
```

Prinsip desainnya — **penting untuk B1 (pemantauan) yang akan membaca berkas ini**:

- Berkas ini **selalu ditulis ulang di akhir SETIAP percobaan**, sukses maupun gagal. Ia
  mencerminkan hasil percobaan **TERAKHIR**, bukan sekadar "apakah ada berkas dump" — dump yang
  ada di disk tapi TOC-nya tak terbaca, atau yang dibatalkan gerbang J4 sebelum sempat mulai,
  tetap menulis `"verdict": "GAGAL"` di sini.
- `terakhir_ok` **dipertahankan lintas-run** (dibawa dari status sebelumnya lewat `jq` kalau run
  ini gagal). Jadi kalau 3 hari berturut-turut gagal, `verdict` hari ini tetap `"GAGAL"` TAPI
  `terakhir_ok` tetap menunjuk ke kapan terakhir kali BENAR-BENAR berhasil — itu yang membedakan
  "baru saja gagal sekali" dari "sudah beberapa hari tak ada cadangan sah sama sekali".
- **Yang harus dipantau B1:** (a) `verdict != "OK"` pada run terakhir → alarm segera; (b) umur
  `terakhir_ok` (`now - terakhir_ok`) melewati ambang (mis. > 26 jam, memberi sedikit slack di
  atas jadwal harian) → alarm walau `verdict` run terakhir kebetulan `"OK"` untuk alasan lain
  (mis. `status.json` sendiri berhenti diperbarui karena timer mati — lihat juga
  `systemctl list-timers` sebagai pengecekan kedua yang independen dari isi berkas ini).
- `ukuran_bytes` dan `sha256_manifest_hash` (hash dari MANIFEST checksum, bukan hash satu berkas
  dump tunggal — formatnya `directory`, banyak berkas) berguna untuk mendeteksi dump yang
  "berhasil" tapi mencurigakan kecil (mis. gerbang J4 lolos tapi koneksi terputus di tengah — ini
  seharusnya sudah tertangkap sebagai GAGAL oleh langkah TOC, tapi ukuran adalah sinyal kedua).

Alarm kegagalan JUGA masuk journal lewat `OnFailure=toa-cadangan-gagal.service` (prioritas
`user.err`, cari dengan `journalctl -p err -u toa-cadangan-gagal.service`) — ini pelengkap, bukan
pengganti pemantauan `status.json`, karena journal butuh seseorang/sesuatu yang aktif membacanya.

## Kalau gagal

1. Baca `pesan` di `~/cadangan/status.json` dan tail `~/cadangan/backup.log` — pesan gagal selalu
   menyebut penyebabnya (gerbang J4 + nama index, `pg_dump`, TOC, atau checksum).
2. **Gerbang J4 menolak (index invalid ditemukan):** ini SATU-SATUNYA kegagalan yang butuh
   tindakan di sisi produksi, bukan di VPS cadangan. Index invalid diperbaiki lewat psql di
   produksi di luar jam sibuk: `DROP INDEX CONCURRENTLY <nama>;` lalu bangun ulang
   `CREATE INDEX CONCURRENTLY …` (definisi index ada di migrasi Django terkait/`periksa_index.py`
   `PEMULIHAN`). Setelah index sehat kembali (`indisvalid = true` untuk semuanya), jalankan ulang
   manual: `sudo systemctl start toa-cadangan.service`.
3. **`pg_dump` gagal (jaringan/proxy Railway putus, dsb):** cek `~/.pgpass` masih ada & mode 0600,
   `~/.prod-url` masih benar, dan konektivitas ke proxy (`psql "$(cat ~/.prod-url)" -c 'select 1'`
   — JANGAN pernah tempel isi `.pgpass`/URL bersandi ke tempat manapun; kalau perlu menunjukkan
   bentuknya, sensor `cut -d: -f1,2,3,4`). Coba jalankan ulang manual.
4. **TOC gagal terbaca / checksum gagal:** arsip dump yang baru saja dibuat rusak — jangan
   percaya dump hari itu. Jalankan ulang manual; kalau berulang, itu bukan masalah sesaat (disk
   VPS penuh? proses `pg_dump` yang lain bentrok?) — cek `df -h /` dan proses lain yang menyentuh
   `/var/backups/toa`.
5. Timer sendiri tidak jalan sama sekali (tidak ada entri baru di log/status berhari-hari,
   `terakhir_ok` makin tua): cek `systemctl list-timers toa-cadangan.timer` (harus aktif, ada
   `NEXT`) dan `systemctl status toa-cadangan.timer`.
6. Setiap kegagalan otomatis menulis `"verdict": "GAGAL"` — **jangan** menganggap "besok pasti
   jalan sendiri" tanpa memeriksa penyebabnya; gerbang J4 khususnya TIDAK akan sembuh sendiri
   (index invalid tidak hilang kecuali diperbaiki manual di produksi).

## Cara memulihkan (restore)

### Restore uji (sekali-pakai, TIDAK menyentuh apa pun yang sudah ada)

Ini persis prosedur yang dipakai untuk membuktikan cadangan 2026-09-04 (lihat hasil di bawah).
Jalankan di VPS `toa`:

```bash
D=/var/backups/toa/dump-<STAMP>            # ganti <STAMP> dengan tanggal dump yang mau diuji
createdb toa_ujicadangan
pg_restore --dbname=toa_ujicadangan --jobs=4 --no-owner --no-privileges \
  --exit-on-error "$D"
psql toa_ujicadangan -Atc "SELECT 'count='||count(*) FROM transactions_transaction;"
psql toa_ujicadangan -Atc "SELECT 'sums='||sum(amount)||' | '||sum(credit_delta)||' | '||sum(money_delta) FROM transactions_transaction;"
# lalu BANDINGKAN dengan query yang sama terhadap produksi (lewat ~/.prod-url) —
# BUKAN dengan ~/baseline.txt lama, yang terikat pada snapshot gladi migrasi 2026-09-01
# dan sudah kedaluwarsa (produksi terus tumbuh, ratusan ribu baris/hari).
dropdb toa_ujicadangan
```

Verifikasi arsip SEBELUM restore (opsional tapi murah): `pg_restore -l "$D" | head` dan
`cd /var/backups/toa && sha256sum -c dump-<STAMP>.sha256`.

**Jangan pernah** restore uji ke database `toa` yang sudah ada — itu hasil gladi migrasi dan jadi
pembanding `scripts/gerbang.sh` proyek migrasi Contabo. Selalu ke database sekali-pakai
(`toa_ujicadangan` atau nama serupa), lalu `DROP DATABASE` setelah selesai diverifikasi.

### Restore sungguhan (skenario darurat: produksi Railway rusak/hilang)

1. Pastikan dump yang dipakai TERBUKTI baik: `verdict: "OK"` di `status.json` untuk tanggal itu,
   dan `sha256sum -c` atas manifestnya lolos.
2. Siapkan target restore (Postgres 18 baru — di VPS ini kalau memang skenarionya cutover ke
   Contabo, atau instance Railway/Postgres baru kalau cuma perbaikan data):
   `createdb <db_baru> [--owner=...]`.
3. `pg_restore --dbname=<db_baru> --jobs=4 --no-owner --no-privileges --exit-on-error
   /var/backups/toa/dump-<STAMP>`
4. `vacuumdb -d <db_baru> --analyze-in-stages --jobs=4` lalu `vacuumdb -d <db_baru> --analyze
   --jobs=4` (statistik planner segar; dump dibuat dengan `--statistics` jadi sebagian sudah
   terbawa, tapi analyze tetap dianjurkan setelah restore besar).
5. Jalankan `python manage.py periksa_index` (di lingkungan Django yang menunjuk ke `<db_baru>`)
   sebelum melayani trafik nyata — restore TIDAK membangun ulang index yang tadinya invalid di
   sumber (gerbang J4 seharusnya sudah mencegah dump semacam itu terjadi, tapi ini lapis
   pertahanan kedua yang murah).
6. Arahkan `DATABASE_URL` aplikasi ke `<db_baru>` dan restart service.

## Larangan yang tetap berlaku (diwarisi dari gladi migrasi, jangan dilonggarkan)

1. DB `toa` di VPS ini HARAM ditimpa/di-drop — itu pembanding gladi migrasi Contabo.
2. Restore uji SELALU ke database sekali-pakai, lalu `DROP DATABASE` setelah diverifikasi.
3. Tidak pernah menghapus apa pun di produksi Railway — pekerjaan cadangan ini murni MEMBACA.
4. Sandi tidak boleh masuk argv (`pg_dump -d "postgres://user:pass@…"` bocor lewat
   `/proc/<pid>/cmdline`) — selalu andalkan `~/.pgpass`.
5. Jangan mencetak isi `~/.pgpass`/sandi apa pun; kalau perlu menunjukkan bentuknya, sensor
   `cut -d: -f1,2,3,4`.
6. Jangan commit apa pun ke `docs/`/`scripts/` yang memuat host/port/kredensial produksi mentah —
   rujuk saja "`~/.prod-url` pada VPS `toa`".
7. Gunakan alias SSH **`toa`** (tailnet), bukan **`toa-publik`** (IP publik — kena `ufw limit`+
   fail2ban, bisa mengunci diri sendiri ±10 menit).

## Bukti (dijalankan 2026-09-04, lewat `sudo systemctl start toa-cadangan.service` — jalur produksi
sungguhan, bukan skrip dijalankan tangan)

- **Gerbang J4**: dijalankan terhadap produksi jam 17:15 WIB — **tidak ada index invalid**, dump
  dilanjutkan.
- **Dump baru** (`dump-2026-09-04`): mulai 17:14:59, selesai 17:28:38 WIB (≈13m39d, produksi sudah
  tumbuh dari 8,85 juta baris [gladi 01-09] ke ~10,34 juta baris, jadi lebih lama dari 11m51d
  gladi migrasi). Ukuran 1,6 GB (1.702.624.037 byte). TOC 448 entri, `pg_restore -l` terbaca
  bersih. `sha256sum -c dump-2026-09-04.sha256` (30 berkas dalam manifest) → **SEMUA COCOK**.
  `status.json` → `"verdict": "OK"`, `"kode_keluar": 0`.
- **Timer**: `systemctl enable --now toa-cadangan.timer` → `enabled`/`active`.
  `systemctl list-timers toa-cadangan.timer` → `NEXT = Sat 2026-09-05 03:04:56 WIB` (nyata, sesuai
  jadwal `03:00 WIB` + jitter `RandomizedDelaySec`).
- **Restore uji**: baseline produksi diambil LANGSUNG lewat psql pukul 17:14:34 WIB (beberapa detik
  sebelum dump dipicu) — `count=10341991`,
  `sums=3596865558308.80 | -109008844489.98 | 243692437798.96`,
  per bulan `2026-06=192 | 2026-07=4018660 | 2026-08=5728336 | 2026-09=588684`.
  `createdb toa_ujicadangan` → `pg_restore --dbname=toa_ujicadangan --jobs=4 --no-owner
  --no-privileges --exit-on-error dump-2026-09-04` (13m48d, kode keluar 0) → query yang SAMA
  terhadap `toa_ujicadangan` menghasilkan **angka yang PERSIS SAMA, byte-untuk-byte**: count,
  ketiga sum, dan keempat baris per-bulan cocok seluruhnya, nol selisih. (Produksi sendiri sudah
  bertambah ke `count=10345543` pada saat verifikasi ~29 menit kemudian — pertumbuhan normal
  sistem yang terus menyala, BUKAN indikasi restore tidak lengkap; pembandingnya memang baseline
  yang diambil tepat sebelum dump, bukan angka produksi saat itu juga.)
  `DROP DATABASE toa_ujicadangan` dijalankan setelah verifikasi.
- **Tak tersentuh**: `DB toa` tetap ada (dicek lewat `pg_database`), `~/baseline.txt` tetap 17
  baris dengan md5 tak berubah dari sebelum pekerjaan ini dimulai.
- **Retensi terbukti bekerja pada percobaan pertama**: dump gladi migrasi lama (`dump-2026-09-01`,
  3 hari) otomatis terhapus oleh langkah retensi `-mtime +1` pada run ini — bukti retensi bukan
  cuma kode mati.
- **Jalur `OnFailure` diuji sungguhan** (bukan dengan merusak unit asli): unit sekali-pakai
  `toa-cadangan-uji-gagal.service` dipasang sementara (`ExecStart=/bin/false`,
  `OnFailure=toa-cadangan-gagal.service` — sama seperti unit asli), dijalankan lewat
  `sudo systemctl start` → gagal seperti yang diharapkan (`Active: failed (Result: exit-code)`).
  Journal membuktikan alarm benar-benar terpicu, bukan cuma terpasang: `toa-cadangan-gagal.service`
  tercatat `Starting…`/`Finished…` pada detik yang sama, dan pesan aslinya muncul di journal —
  `root[...]: cadangan toa GAGAL -- cek: journalctl -u toa-cadangan.service -n 100 | cat
  /home/toa/cadangan/status.json`. Unit uji dihapus + `daemon-reload` sesudahnya; `toa-cadangan.service`
  (asli) tetap `inactive (dead)` (bukan `failed`), dan `toa-cadangan.timer` tetap `active`/`enabled`
  dengan `NEXT` nyata (`Sat 2026-09-05 03:03:22 WIB` — bergeser sedikit dari jitter
  `RandomizedDelaySec` karena `daemon-reload`, bukan indikasi masalah). Tidak ada unit lain yang
  masuk status `failed` akibat pengujian ini (`systemctl --failed` hanya menunjukkan dua unit boot
  bawaan VPS yang tak berkaitan, `cloud-init.service` dan `systemd-networkd-wait-online.service`).

Detail lengkap (transkrip perintah, angka mentah): lihat
`.superpowers/sdd/prompt-eksekusi-perbaikan-2026-09-04/A1-report.md`.
