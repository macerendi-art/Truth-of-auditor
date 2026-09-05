# Runbook — Pemantauan kesehatan produksi (B1) + alarm layanan mati (B6) + F6 (2026-09-04)

> **Menerima alarm dan tidak tahu harus berbuat apa?** Kartu triase per situasi ada di
> [`runbook-situasi-2026-09-05.md`](runbook-situasi-2026-09-05.md) — dokumen ini menjelaskan
> BAGAIMANA pemantauannya bekerja; yang itu menjawab APA yang harus dilakukan.

Sumber tugas: `docs/daftar-perbaikan-2026-09-03.md` butir B1, B6, F6.

Kalimat penutup daftar perbaikannya:

> Celah terbesarnya bukan mutu kodenya — melainkan otomasi di sekelilingnya. Tidak ada yang
> menjalankan tes, pemeriksaan index, atau pemeriksaan kesehatan selain manusia yang mengingatnya.

`core/management/commands/periksa_kesehatan.py` (469 baris) dan `periksa_index.py` (124 baris)
**sudah jadi dan bagus sebelum pekerjaan ini** — tidak ada yang menjalankannya. Dokumen ini
menutup itu: keduanya sekarang berjalan **harian, otomatis, lewat systemd timer**, plus satu
probe HTTP terpisah yang berjalan **tiap 5 menit** untuk mendeteksi layanan yang mati (B6).
F6 (index hilang/INVALID) terjawab sendiri oleh B1: `periksa_index` adalah penawarnya, dan B1
adalah yang akhirnya menjalankannya.

## Apa ini, dan apa BUKAN ini

Berjalan di VPS **`toa`** (alias SSH `ssh toa`, tailnet — sama seperti pekerjaan cadangan A1;
**bukan** `toa-publik`). Tiga systemd timer terpisah, tiga tujuan:

| Timer | Jadwal | Yang diperiksa | Butuh DB? |
|---|---|---|---|
| `toa-cadangan.timer` (A1, sudah ada) | 03:00 WIB harian | Cadangan basis data | Ya (dump) |
| `toa-kesehatan.timer` (baru) | 04:00 WIB harian | Kesehatan produksi (4 hal, lihat di bawah) | Ya (baca saja) |
| `toa-probe.timer` (baru) | tiap 5 menit | Layanan produksi hidup/mati (B6) | Tidak |

`toa-kesehatan.timer` dijadwalkan **sesudah** `toa-cadangan.timer` (04:00 vs 03:00 + jitter 5
menit) supaya saat dibaca, `~/cadangan/status.json` hari itu sudah pasti diperbarui.

Probe (B6) SENGAJA dipisah dari cek kesehatan (harian): butuh jadwal jauh lebih sering untuk
mendeteksi kematian layanan dalam hitungan menit, bukan jam, dan tidak butuh Django/DB sama
sekali — cuma `curl` ke domain publik. Menyatukannya dengan cek berat akan memaksa salah satu
jadi salah jadwal.

**Ini BUKAN pemantauan real-time/SLA.** Probe tiap 5 menit + ambang 3 kali gagal beruntun
(lihat di bawah) berarti downtime nyata baru terdeteksi ±15 menit setelah kejadian. Itu jauh
lebih baik daripada nol (keadaan sebelum B6), tapi bukan pager sungguhan — lihat bagian
"Yang tertahan pada pemilik" soal saluran pemberitahuan nyata.

## Keputusan: jalur (A) — Django `periksa_kesehatan` terhadap PRODUKSI dari VPS

Brief pekerjaan ini meminta pembuktian, bukan tebakan, di antara tiga jalur:

- **(A) VPS menjalankan `periksa_kesehatan` Django terhadap produksi.**
- (B) VPS menjalankan skrip SQL/psycopg mandiri yang meniru pemeriksaan tingkat-DB.
- (C) Railway cron service (butuh tindakan pemilik di dashboard).

**Dipilih: (A), dengan (B) sebagai pelengkap untuk SATU hal yang tidak bisa dijawab (A) dari
VPS (disk produksi, lihat di bawah).** Bukti sebelum memutuskan:

1. **App Django SUDAH terpasang** di `/opt/toa` di VPS ini — dari `~/migrasi/fase3-app.sh`
   (gladi migrasi Contabo, 2026-09-01). Diperiksa lebih dulu, bukan diasumsikan:
   `.venv/bin/python` ada, `/etc/toa.env` berisi `DATABASE_URL` dkk. Jadi jalur (A) **murah** —
   tepat seperti dugaan brief.
2. `core/management/commands/periksa_index.py` di checkout itu **identik byte-untuk-byte**
   dengan repo (dibandingkan lewat `diff` sebelum dipakai). `periksa_kesehatan.py` ada sebagai
   berkas belum ter-commit di checkout itu (sisa eksplorasi sebelumnya) — juga identik.
   **Koreksi 04-09-2026 (tinjauan akhir P2):** kalimat lama "checkout itu boleh basi" hanya
   **separuh benar**. `periksa_index` membandingkan `Transaction._meta.indexes` dari **kode yang
   berjalan** dengan `pg_index`: index **INVALID** terdeteksi dari kode mana pun (seluruh index
   tabel dibaca dari katalog), tapi index **HILANG** hanya bisa dilaporkan kode yang mengenal
   namanya — dari checkout `claude/test-fabbe0` (e414de5, 01-09-2026), `tx_hutang_piutang_idx`
   (migrasi 0012) yang tak pernah terbangun akan dilaporkan "Bersih". Karena itu: (a) memperbarui
   `/opt/toa` ke commit yang di-deploy adalah **langkah pasca-deploy wajib** (runbook rollback,
   "Urutan deploy wajib"); (b) skrip kesehatan kini mencatat revisi `/opt/toa` (commit + branch)
   di log dan `status.json` supaya drift-nya terlihat, dan menambah pemeriksaan index INVALID
   **DB-wide lewat SQL langsung** (bagian 2b, setara gerbang J4 cadangan) yang tidak bergantung
   pada checkout sama sekali. `/opt/toa` **sengaja belum diperbarui** saat ini ditulis: produksi
   belum menjalankan v1.25.0, jadi kode baru akan mengalarm `tx_hutang_piutang_idx` HILANG setiap
   pagi sebelum pemilik memutuskan deploy — perbarui setelah deploy, bukan sebelum.
3. `DATABASE_URL` di `/etc/toa.env` menunjuk basis data **gladi migrasi lokal `toa`** di VPS ini
   (pembanding cutover Contabo, beku di titik snapshotnya) — **bukan** produksi. Memeriksa
   kesehatan DB itu tidak berguna (tak mencerminkan insiden produksi nyata: batch, sequence,
   ukuran DB, semua beku). Jadi setiap pemanggilan `manage.py` di skrip pemantauan **menimpa**
   `DATABASE_URL` dengan `"$(cat ~/.prod-url)"` untuk SATU invokasi itu saja.
4. **`~/.prod-url` TERBUKTI tanpa sandi** sebelum dipakai (bukan diasumsikan dari namanya):
   `urlparse(open('~/.prod-url').read()).password is None` → `True`. Django/psycopg2 hanya
   mengisi `password` di parameter koneksi kalau `settings_dict["PASSWORD"]` truthy (diperiksa
   di sumber `django/db/backends/postgresql/base.py` `get_connection_params` — `if
   settings_dict["PASSWORD"]:`) — jadi `DATABASE_URL` tanpa sandi membuat psycopg/libpq
   **otomatis** mengambil sandinya dari `~/.pgpass`, PERSIS pola yang sudah dipakai
   `pg_dump`/`psql` di `scripts/cadangan/backup-harian.sh`. Sandi TIDAK PERNAH masuk argv/env
   secara eksplisit di skrip pemantauan ini. Dibuktikan bekerja: `manage.py periksa_index`
   terhadap produksi lewat proxy publik, sukses, sebelum skrip pemantauan ditulis.
5. **Kenapa BUKAN (B) untuk seluruh isi:** `periksa_kesehatan` sudah menjawab index F6, umur
   batch per toko, rasio sequence, tabel referensi, dan kueri patokan — menulis ulang semua itu
   di SQL mandiri persis **menduplikasi logika** yang brief eksplisit larang ("jangan
   menduplikasi logika `periksa_index`" — ini generalisasinya: jangan duplikasi
   `periksa_kesehatan` juga). Karena (A) terbukti murah dan bekerja, tidak ada alasan menempuh
   (B) untuk bagian itu.
6. **⚠️ DICABUT 04-09-2026 (VETO PEMILIK) — bagian ini mendokumentasikan keputusan yang
   TIDAK LAGI berlaku, dibiarkan utuh sebagai riwayat.** Keputusan ASLI: "Kenapa (B) TETAP
   dipakai untuk SATU hal — sisa disk produksi" — bagian "Ruang disk" `periksa_kesehatan`
   SENGAJA mengukur direktori tempat PERINTAH itu sendiri berjalan (lihat docstring-nya) — dari
   VPS ini itu berarti disk VPS, BUKAN volume Postgres produksi di Railway (dua mesin berbeda).
   Jadi bagian itu tetap dijalankan (informatif, disk VPS) dan disk PRODUKSI diukur terpisah
   lewat SQL murni: `current_user` di produksi lewat proxy TERBUKTI `rolsuper=true`, jadi
   `COPY dfout FROM PROGRAM 'df -kP <data_directory>'` bisa membaca disk NYATA tempat data
   Postgres produksi hidup — satu-satunya cara melakukan itu tanpa akses shell ke host Postgres
   itu sendiri.
   **Kenapa dicabut:** agen yang memasangnya sendiri mengajukannya sebagai keputusan yang bisa
   di-veto (lihat butir 6 di "Yang tertahan pada pemilik" di bawah, ditulis di sesi yang sama) —
   **pemilik memveto.** `COPY ... FROM PROGRAM` adalah primitif eksekusi-KODE permanen terhadap
   host database produksi (superuser bisa menjalankan perintah shell APA PUN), dipasang di dalam
   skrip yang berjalan HARIAN lewat systemd timer — permukaan yang tidak dapat diterima terlepas
   dari seberapa "baca-saja" isinya hari ini. Pengganti: `SELECT pg_database_size
   (current_database())`, satu SELECT biasa yang TIDAK butuh superuser dan TIDAK menjalankan apa
   pun di host — bukan disk NYATA (persen sisa), melainkan UKURAN basis data + laju tumbuh (yang
   sudah tersedia lewat bagian 4, `periksa_kesehatan` Django). Sisa disk produksi SESUNGGUHNYA
   kini harus dicek lewat metrik volume Postgres di dashboard Railway — presisi turun,
   dinyatakan terang-terangan, bukan dipura-purakan setara. Ukuran DB memang SUDAH dilaporkan
   ulang bagian 4 (`periksa_kesehatan` Django, `_ukuran_db`/laju tumbuh) — SATU `SELECT` tunggal
   di bagian 3 bukan duplikasi LOGIKA (tidak ada algoritma/ambang yang ditulis ulang, cuma satu
   fungsi bawaan Postgres), dan sengaja tetap dijalankan lewat SQL murni yang TIDAK bergantung
   app Django `/opt/toa` — kalau app itu rusak/belum ter-migrasi, bagian 3 tetap memberi angka
   ukuran DB walau bagian 4 gagal total; pola yang sama dengan alasan `periksa_index` (bagian 2)
   sengaja dijalankan terpisah dari `periksa_kesehatan` (bagian 4), lihat butir 2 di kepala
   `periksa-kesehatan-terjadwal.sh`.
7. **(C) Railway cron** dicatat sebagai pelengkap yang TIDAK dikerjakan di sini — butuh tindakan
   pemilik di dashboard Railway, dan tugas ini eksplisit dilarang menjalankan `railway` apa pun.
   Lihat "Yang tertahan pada pemilik" di bawah.

## Isi pemantauan `toa-kesehatan.timer` (harian, `scripts/pemantauan/periksa-kesehatan-terjadwal.sh`)

Empat bagian, laporan **selalu utuh** (satu gerbang gagal tidak membungkam yang lain — prinsip
yang sama dengan aturan #1 di docstring `periksa_kesehatan.py`):

1. **Cadangan terakhir** — baca `~/cadangan/status.json` (A1). **Ini SATU hal yang brief minta
   jangan sampai terlewat**: bukan cuma "apakah berkasnya ada", tapi verdict run TERAKHIR **dan**
   umur `terakhir_ok`. BAHAYA kalau: verdict run terakhir bukan `"OK"`, ATAU `terakhir_ok`
   berumur ≥ 26 jam (field kosong pun BAHAYA) — jadi cadangan yang verdict-nya kebetulan `"OK"`
   tapi sudah beberapa hari basi (mis. timer cadangan sendiri berhenti) tetap tertangkap. Lihat
   bagian "Bukti" di bawah — ini teruji dengan sengaja, bukan cuma diklaim.
2. **Index F6** — `manage.py periksa_index` terhadap produksi (bersih hari ini: 24 index di DB,
   7 diwajibkan model, nol temuan).
3. **Ukuran basis data produksi** ⚠️ **REVISI 04-09-2026 (veto pemilik) — lihat keputusan #6 di
   atas untuk sejarahnya.** Awalnya "sisa disk produksi (persen)" lewat `COPY FROM PROGRAM df`;
   dicabut karena itu primitif eksekusi-shell permanen terhadap host database produksi. Sekarang:
   satu `SELECT pg_database_size(current_database())` — TANPA superuser, TANPA eksekusi apa pun
   di host. Selalu **INFO** (tanpa ambang BAHAYA/PERHATIAN sendiri — tak ada kapasitas volume
   yang bisa dipakai menilainya dari sini, pola yang sama dengan "laju tumbuh tak punya ambang"
   di `core/management/commands/periksa_kesehatan.py`), kecuali gagal dibaca sama sekali →
   PERHATIAN. Laju tumbuh dibaca dari bagian 4 (tidak diduplikasi). **Sisa disk produksi
   SESUNGGUHNYA (persen/GB) TIDAK BISA lagi dijawab bagian ini** — cek metrik volume Postgres di
   dashboard Railway. Presisi turun, dinyatakan apa adanya.
4. **`manage.py periksa_kesehatan`** terhadap produksi — mencakup lagi index F6 (redundan dengan
   #2 secara SENGAJA: `periksa_index` sendirian memberi status F6 yang bersih tanpa mengurai
   teks keluaran `periksa_kesehatan`, biayanya satu kueri SQL murah), plus umur batch per toko,
   rasio sequence, tabel referensi, kueri patokan, ukuran DB + laju tumbuh (potretnya DITULIS,
   `media/kesehatan.json` di VPS — bukan `--tanpa-simpan` — supaya laju tumbuh punya riwayat
   sejak sekarang, yang sebelum ini TIDAK PERNAH terkumpul karena perintahnya tak pernah
   berjalan).

Status keseluruhan naik monoton OK → PERHATIAN → BAHAYA dari keempat bagian (tak pernah turun
dalam satu jalan). BAHAYA → skrip keluar 1 → `OnFailure=toa-kesehatan-gagal.service`.

## Isi pemantauan `toa-probe.timer` (tiap 5 menit, `scripts/pemantauan/probe-layanan.sh`) — B6

`railway.json` memakai `restartPolicyType: ON_FAILURE` + `restartPolicyMaxRetries: 3` — sesudah
3x gagal restart, Railway diam dan **tak ada yang memberi tahu siapa pun**. B6 mendeteksi ini
dari luar lewat probe HTTP berkala ke `https://auditor.wolfgang-77.com/`.

**⚠️ Geo-block KH-only aktif di produksi.** VPS ini bukan di Kamboja, jadi respons NORMAL/SEHAT
dari sini adalah **HTTP 403** halaman "Trust No One"/"Akses Ditolak" (dibuktikan lewat curl
sungguhan sebelum skrip ditulis — judul halamannya persis "Akses Ditolak · Truth of Auditor").
**403 BUKAN tanda mati — justru bukti layanan hidup dan middleware geo bekerja.** Skrip ini
tidak pernah dan tidak boleh mencoba mem-bypass geo-block atau menambah IP VPS ke
`GEO_BLOCK_ALLOWLIST`.

Kategori respons (**direvisi P3, tinjauan akhir 04-09-2026** — versi awal hanya mengalarm
502/503/504 dan menganggap SETIAP 403 hidup):

| Kondisi | Kategori | Alarm? |
|---|---|---|
| curl gagal terhubung sama sekali (DNS/timeout/refused/TLS) | `mati` | Ya (lihat ambang beruntun) |
| HTTP 403 **dengan** judul `Akses Ditolak · Truth of Auditor` di badan | `hidup_tergerbang` | Tidak — ini yang NORMAL |
| HTTP 403 **tanpa** judul itu (WAF/edge Cloudflare yang menjawab, bukan aplikasi) | `mati` | Ya |
| HTTP **5xx apa pun**: 502/503/504 (edge Railway), 521–524 (Cloudflare tak mencapai origin), 500 (aplikasi, mis. Postgres jatuh) | `mati` | Ya |
| HTTP non-5xx lain (200/404/3xx/dst.) | `tak_terduga` | Tidak, tapi dicatat |

**Kenapa direvisi.** Domain probe berada di belakang Cloudflare. Saat Cloudflare tidak bisa
mencapai origin ia menjawab **521/522/523/524**, bukan 502/503/504 — versi awal memasukkannya ke
`tak_terduga` (tidak mengalarm), sehingga bentuk mati yang paling khas dilihat dari luar justru
tidak pernah menaikkan `gagal_beruntun`. Dan 403 hanya membuktikan hidup kalau **aplikasi itu
sendiri** yang menjawab (GeoBlockMiddleware); kalau aturan WAF Cloudflare berubah atau IP VPS
masuk daftar blokir WAF, 403 datang dari Cloudflare walau origin mati total — probe lama akan
melaporkan `hidup_tergerbang` selamanya. `docs/rencana-migrasi-contabo-2026-08-31.md` sudah
melarang persis pola itu (*"assert isi halaman, jangan 'bukan 5xx'"*). Judul yang diperiksa bisa
ditimpa env `JUDUL_TERGERBANG` bila halaman geo-block diubah **sadar** — ubah di skrip juga,
jangan biarkan probe mengalarm palsu. Cuplikan 200 byte badan kini dicatat untuk semua respons
HTTP selain `hidup_tergerbang` (termasuk 403 tanpa judul dan 5xx) — bukti pertama saat membaca
log insiden.

**Probe kedua ke domain Railway asli (`truth-of-auditor.up.railway.app`, tanpa Cloudflare) sudah
dipertimbangkan dan TIDAK layak:** dicek `curl` 04-09-2026, domain itu menjawab **404** dari edge
Railway — tidak lagi merutekan ke service ini, jadi tidak membuktikan apa pun. Jangan dipasang.

Diverifikasi sebelum dipasang: keenam cabang dijalankan terhadap server HTTP lokal palsu
(403+judul → `hidup_tergerbang`; 403 WAF, 522, 500, 503 → `mati`; 200 → `tak_terduga`), lalu
salinan VPS `/home/toa/probe/probe-layanan.sh` diganti (backup `.pre-p3-bak`, sha256 identik
dengan repo) dan dijalankan sekali lewat `bash` langsung: `hidup_tergerbang` dengan judul
terbaca, `verdict=OK`, `gagal_beruntun=0`.

**Anti-kedip:** satu kegagalan tunggal tidak langsung mengalarm — perlu **3 kali gagal
berturut-turut** (jadi ±15 menit downtime nyata pada jadwal 5 menit) baru verdict `GAGAL` dan
skrip keluar 1 → `OnFailure=toa-probe-gagal.service`. Field `terakhir_hidup` dipertahankan
LINTAS-RUN persis seperti `terakhir_ok` cadangan — lihat komentar di `backup-harian.sh` kalau
perlu banding, sengaja ditiru bukan dirancang ulang.

## Berkas status — cara membacanya

`~/kesehatan/status.json` (ditulis ulang tiap run, sukses maupun gagal):

```json
{
  "tanggal": "2026-09-04", "mulai": "…", "selesai": "…",
  "verdict": "BAHAYA",
  "cadangan": {"status": "OK", "pesan": "…", "verdict_run_terakhir": "OK",
               "terakhir_ok": "2026-09-04T17:28:38+07:00", "umur_jam": 0.5},
  "index_f6": {"status": "OK", "pesan": "Bersih — tak ada index hilang/invalid."},
  "ukuran_db_produksi": {"status": "INFO", "pesan": "ukuran basis data produksi: 1.40 GB …", "bytes": 1503238553},
  "periksa_kesehatan_django": {"status": "BAHAYA", "kode_keluar": 1, "ringkasan": "1 BAHAYA · 0 PERHATIAN · 34 OK · 9 INFO"},
  "log_file": "/home/toa/kesehatan/kesehatan.log"
}
```

⚠️ **Field berubah 04-09-2026**: bagian ini dulu bernama `disk_produksi` dengan `persen_bebas`
(lewat `COPY FROM PROGRAM`, lihat keputusan #6 di atas — DICABUT). Snapshot `status.json` yang
ditulis SEBELUM revisi ini masih memakai nama lama; itu bukan bug, cuma jejak sebelum rilis.

`verdict` di puncak = status TERBURUK dari keempat bagian. Rincian lengkap (termasuk daftar
toko/index/sequence per baris) ada di `log_file`, bukan di JSON ini — JSON sengaja ringkas untuk
dipantau cepat, log untuk investigasi.

`~/probe/status.json` (ditulis ulang tiap run, tiap 5 menit):

```json
{
  "waktu": "…", "url": "https://auditor.wolfgang-77.com/", "http_code": "403",
  "kategori": "hidup_tergerbang", "pesan": "…", "waktu_respons_detik": 0.29,
  "verdict": "OK", "gagal_beruntun": 0, "ambang_beruntun": 3,
  "terakhir_hidup": "2026-09-04T18:05:34+07:00"
}
```

`verdict: "GAGAL"` HANYA muncul setelah `gagal_beruntun >= ambang_beruntun` — satu kegagalan
tunggal tetap `verdict: "OK"` (tercatat di `gagal_beruntun` naik, tapi belum mengalarm). Kalau
`kategori` berturut-turut `"mati"` tapi `verdict` masih `"OK"`, itu tanda downtime BARU terjadi
dan belum cukup lama untuk dipastikan — jangan diabaikan, tapi juga jangan panik sebelum
`GAGAL` muncul.

Cek kedua yang independen dari isi berkas (kalau timer sendiri berhenti, berkas ini berhenti
diperbarui tapi isinya tetap terakhir "OK"): `systemctl list-timers toa-kesehatan.timer
toa-probe.timer` — kolom `NEXT`/`LAST` harus masuk akal.

**Cara memastikan alarm SUDAH/BELUM berbunyi: `journalctl -t toa-alarm`, bukan
`journalctl -u <nama>-gagal.service`.** Dibuktikan nyata saat membangun ini: `logger` yang
dipanggil dari unit oneshot yang cepat keluar kadang salah-atribusi ke journald (unit start/
finish normal tercatat, tapi baris `logger`-nya sendiri kadang TIDAK muncul di filter `-u`,
walau prosesnya benar-benar jalan dan pesannya ADA di journal lewat filter lain). `-t toa-alarm`
tidak bergantung atribusi unit — semua alarm dari `kirim-alarm.sh` (dari KEDUA unit
`*-gagal.service`) selalu tertangkap di situ. **Jangan pernah menyimpulkan "alarm tidak
berbunyi" hanya dari `journalctl -u toa-kesehatan-gagal.service`/`-u toa-probe-gagal.service`
kosong** — cek ulang dengan `-t toa-alarm` (atau `-p err` tanpa filter unit) sebelum percaya itu.

## Memasang saluran pemberitahuan nyata — TITIK TUNGGAL

> **Diperbarui 04-09-2026 — dua hal berubah di sini.**
>
> 1. **Jalur webhook sudah DIBUKTIKAN ujung-ke-ujung**, bukan cuma ditulis: `kirim-alarm.sh`
>    dijalankan terhadap penerima HTTP lokal sementara, dan badan JSON-nya benar-benar tiba
>    (`{"text": "ALARM toa: UJI SALURAN …"}`). Jadi yang tersisa untukmu **hanya menempel satu
>    baris `WEBHOOK_URL=…`** ke `alarm.env`. `jq` dan `curl` sudah terpasang di VPS (diperiksa).
> 2. **Ada mode uji mandiri:** `~/pemantauan/kirim-alarm.sh --uji` mengirim pesan percobaan lewat
>    SEMUA saluran yang terpasang tanpa merusak apa pun — kamu tidak perlu memalsukan kegagalan
>    pemantauan lebih dulu untuk membuktikan salurannya sampai.
>
> ⚠️ **`msmtp` BELUM terpasang di VPS** (diperiksa 04-09). Dulu blok SMTP dilewati **diam-diam**
> saat itu terjadi — kamu mengisi `ALARM_EMAIL_TO`, mengira email menyala, dan tidak pernah
> menerima apa pun. Sekarang ketiadaannya **berbunyi** di journal. Kalau memilih jalur email:
> `sudo apt install msmtp` + isi `~/.msmtprc` lebih dulu.

Repo ini tidak punya SMTP/Slack/webhook terkonfigurasi, dan memilih (apalagi membayar) layanan
semacam itu adalah **keputusan pemilik** — bukan sesuatu yang dipasang sendiri oleh pekerjaan
ini. Yang dibangun: mekanisme **gagal dengan berisik dan bisa dicolok** — `OnFailure` systemd +
journal (prioritas `user.err`) + berkas status + kode keluar ≠ 0, SEMUANYA sudah terbukti
berbunyi (lihat "Bukti" di bawah) — lalu **satu titik tunggal** tempat saluran nyata dipasang:
**`scripts/pemantauan/kirim-alarm.sh`** (dipanggil oleh KEDUA unit alarm,
`toa-kesehatan-gagal.service` dan `toa-probe-gagal.service`, lewat baris `ExecStart` mereka —
satu berkas, dua pemanggil).

Langkah konkret untuk pemilik (juga tertulis sebagai komentar di kepala berkas itu):

1. Pilih SATU (atau lebih): webhook generik (Slack incoming webhook/Discord/Telegram/PagerDuty/
   n8n/dst.) dan/atau SMTP lewat `msmtp`.
2. Simpan kredensialnya di `/home/toa/pemantauan/alarm.env` (mode **0600**, format `KUNCI=nilai`
   biasa) — **BUKAN** di unit systemd (0644, terbaca semua user lokal) dan **BUKAN** commit ke
   repo:
   ```
   WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ
   ALARM_EMAIL_TO=ops@contoh.com
   ```
3. `kirim-alarm.sh` SUDAH punya blok "AKTIFKAN DI SINI" untuk webhook dan untuk SMTP — keduanya
   otomatis aktif begitu env yang relevan terisi di `alarm.env`. Tidak perlu mengedit unit
   systemd atau skrip pemantauan lain sama sekali.
4. Uji dengan kegagalan yang SENGAJA dibuat (lihat "Menguji alarm" di bawah) sebelum
   mempercayainya di produksi.

Tanpa `alarm.env` terisi, `kirim-alarm.sh` HANYA mencatat ke journal — itu memang keadaan hari
ini, dan itu SENGAJA (bukan gagal senyap): journal + berkas status sudah cukup untuk siapa pun
yang AKTIF memeriksa, yang belum ada cuma saluran yang menghubungi seseorang secara aktif.

## Menguji alarm (pola yang dipakai saat B1/B6 ini dibangun — TIDAK PERNAH menyentuh produksi/state asli)

Jangan menguji dengan mematikan layanan produksi atau merusak cadangan asli. Pola yang dipakai
dan terbukti (lihat "Bukti" di bawah untuk keluarannya):

- **Cadangan basi (bukan cuma hilang):** salin `~/cadangan/status.json` ke berkas sementara,
  ubah `terakhir_ok` mundur >26 jam (`jq --arg t "$(date -d '40 hours ago' -Is)" '.terakhir_ok=$t'`),
  lalu jalankan skrip dengan env `CADANGAN_STATUS=<salinan>` **dan** `STATE_DIR=<direktori
  sementara>` (supaya `~/kesehatan/status.json` ASLI tidak ikut tertimpa):
  ```
  sudo -u toa env CADANGAN_STATUS=/tmp/x.json STATE_DIR=/tmp/y \
    /home/toa/kesehatan/periksa-kesehatan-terjadwal.sh
  ```
- **Layanan mati (B6), termasuk anti-kedip:** jalankan `probe-layanan.sh` dengan
  `URL=http://127.0.0.1:9/` (port tertutup, pasti gagal konek) dan `STATE_DIR` sementara,
  3 kali berturut-turut — verdict baru `GAGAL` di percobaan ke-3, dua percobaan pertama tetap
  `OK` (anti-kedip bekerja). 502/503/504 bisa disimulasikan dengan `nc -l` sekali pakai yang
  membalas `HTTP/1.1 502 Bad Gateway`.
- **Alarm sistemd sungguhan (bukan cuma skrip):** override sementara lewat `systemctl edit
  --runtime toa-probe.service` (menambah `Environment=URL=...`/`Environment=STATE_DIR=...`),
  `systemctl start` 3 kali, periksa `journalctl -p err`, lalu **WAJIB** hapus override
  (`rm /etc/systemd/system/toa-probe.service.d/override.conf; systemctl daemon-reload`) dan
  hapus direktori sementara sebelum selesai.
- Selalu tutup dengan satu jalan NYATA (tanpa override apa pun) untuk membuktikan pulih ke `OK`.

## Cara mematikan sementara

```
sudo systemctl stop toa-kesehatan.timer toa-probe.timer     # jeda (bukan disable — tetap di boot)
sudo systemctl start toa-kesehatan.service                   # jalankan manual sekali
```

`disable` (bukan `stop`) melepas dari boot — jangan dipakai untuk jeda singkat, sama seperti
cadangan A1.

## Bukti (dijalankan 2026-09-04, VPS `toa`, lewat `sudo systemctl start …` dan timer sungguhan)

- **Django app**: `/opt/toa` sudah terpasang dari gladi migrasi (`~/migrasi/fase3-app.sh`,
  2026-09-01). `periksa_index.py` identik byte-untuk-byte dengan repo; `periksa_kesehatan.py`
  juga identik (dibandingkan `diff` sebelum dipakai).
- **`~/.prod-url` terbukti tanpa sandi**: `urlparse(...).password is None` → `True` (python3,
  bukan diasumsikan dari nama berkas).
- **Jalan NYATA #1 — sukses murni**: `manage.py periksa_index` terhadap produksi lewat proxy →
  "transactions_transaction: 24 index di DB, 7 diwajibkan model. Bersih — tak ada index
  hilang/invalid." Kode keluar 0.
- **Jalan NYATA #2 — `toa-kesehatan.service` lewat `systemctl start` (real production data),
  DUA KALI (sebelum & sesudah memperbaiki bug parsing `df`, lihat di bawah)**: keduanya
  menemukan **1 BAHAYA sungguhan** — toko `mmk` batch terakhir **2026-08-26, 9 hari lalu**
  (ambang BAHAYA umur batch = 7 hari) — bukan temuan yang direkayasa. `status.json` akhir:
  `cadangan.status=OK` (0,5 jam), `index_f6.status=OK`, `disk_produksi.status=OK` (91,0% sisa,
  `/dev/zd7232 … 9% /var/lib/postgresql/data`), `periksa_kesehatan_django.status=BAHAYA`
  (`kode_keluar=1`, "1 BAHAYA · 0 PERHATIAN · 34 OK · 9 INFO"), `verdict` puncak = `BAHAYA`.
  Skrip keluar 1 → `systemctl start` melaporkan "failed" (BENAR, itu maksudnya) →
  `OnFailure=toa-kesehatan-gagal.service` **terbukti berbunyi**: `journalctl -p err` →
  `toa[…]: ALARM toa: kesehatan toa BAHAYA -- cek: …`. **Temuan ini nyata dan belum
  ditindaklanjuti** — lihat "Yang tertahan pada pemilik". (Baris `disk_produksi.status=OK` di
  atas mendahului revisi 04-09-2026 — lewat `COPY FROM PROGRAM`, sejak dicabut/veto pemilik.
  Dibiarkan apa adanya sebagai bukti historis; bagian yang sama sekarang bernama
  `ukuran_db_produksi` dan tidak lagi melaporkan persen sisa disk, lihat keputusan #6 & bukti
  jalan ulang di laporan `fix1-report.md`.)
  (Bug yang diperbaiki di antara dua jalan ini: `psql -Atc` dengan tiga pernyataan tergabung
  mencetak tag status `CREATE TABLE`/`COPY 1` ikut ke `$DF_LINE`, kebetulan masih terparse benar
  karena `awk` melompati whitespace di depan angka — bukan disengaja. Diganti `-qtAc`, dibuktikan
  keluarannya jadi satu baris bersih.)
- **Jalan NYATA #3 — `toa-probe.service`, manual DAN otomatis lewat timer sungguhan**: manual
  `systemctl start` → `403`/`hidup_tergerbang`/`verdict=OK`. Ditunggu ±3 menit sampai
  `toa-probe.timer` berbunyi SENDIRI (bukan dipicu manual) — `systemctl list-timers` sebelum:
  `NEXT=18:05:00 LEFT=2min 32s`; sesudah: `LAST=18:05:34 PASSED=13s ago`, `journalctl -u
  toa-probe.service` menunjukkan run itu, `status.json` `terakhir_hidup` ikut maju ke waktu yang
  sama.
- **Gagal SENGAJA #1 (cadangan basi, di SALINAN)**: `terakhir_ok` dimundurkan ke 40 jam
  (>ambang 26 jam) di salinan `status.json` (bukan berkas asli), `STATE_DIR` juga sementara →
  `cadangan.status="BAHAYA"`, pesan "terakhir_ok berumur 40.0 jam (>= ambang 26 jam) — CADANGAN
  SAH SUDAH BASI walau run terakhir kebetulan verdict OK", `verdict` puncak `BAHAYA`, kode
  keluar 1. **Ini pembuktian eksplisit kriteria (c): basi terdeteksi, bukan cuma hilang.** Uji
  kedua dengan `verdict="GAGAL"` di salinan → `cadangan.status="BAHAYA"` juga, pesan berbeda
  ("run cadangan TERAKHIR verdict='GAGAL'"). Berkas asli `~/cadangan/status.json` diperiksa
  SESUDAHNYA: `verdict=OK`, `terakhir_ok` tak berubah — tak tersentuh.
- **Gagal SENGAJA #2 (layanan mati + anti-kedip, di STATE_DIR sementara)**: `URL=http://127.0.0.1:9/`
  (port tertutup) 3x berturut-turut → percobaan 1: `gagal_beruntun=1, verdict=OK` (belum
  mengalarm); percobaan 2: `gagal_beruntun=2, verdict=OK`; percobaan 3: `gagal_beruntun=3,
  verdict=GAGAL`, kode keluar 1. **Anti-kedip terbukti bekerja** (2 kegagalan pertama tidak
  memicu alarm). Lanjutan: HTTP 502 palsu (`nc -l` sekali pakai membalas "HTTP/1.1 502 Bad
  Gateway") → `kategori="mati"` (disamakan dengan tanpa-respons, SESUAI desain), beruntun
  lanjut ke 4. Lalu jalan terhadap URL produksi asli (masih di STATE_DIR sementara) →
  `kategori="hidup_tergerbang", verdict=OK, gagal_beruntun=0` — **pulih terbukti**. STATE_DIR
  sementara dihapus; `~/probe/status.json` ASLI tak tersentuh sepanjang pengujian ini.
- **Gagal SENGAJA #3 (alarm systemd sungguhan, bukan cuma skrip, lewat override sementara)**:
  `systemctl edit --runtime toa-probe.service` menambah `Environment=URL=http://127.0.0.1:9/`
  + `Environment=STATE_DIR=/tmp/…` → `systemctl start` 3x → percobaan ke-3 systemd sendiri
  melaporkan "Job … failed" (kode keluar 1) → `journalctl -p err` menunjukkan
  `toa[…]: ALARM toa: PROBE toa: layanan produksi TIDAK MENJAWAB …`. Override dihapus
  (`rm .../override.conf; daemon-reload`), direktori sementara dihapus, lalu `systemctl start
  toa-probe.service` NORMAL sekali lagi → `403/hidup_tergerbang/OK/gagal_beruntun=0`. **Unit
  systemd kembali ke definisi aslinya** (diperiksa lewat `systemctl cat`).
- **Titik tunggal alarm (`kirim-alarm.sh`) dibuktikan menyalurkan KEDUA unit**: sesudah refactor
  (kedua `-gagal.service` dipindah dari `logger` inline ke memanggil `kirim-alarm.sh`), gagal
  sengaja #2 dan #3 diulang — `journalctl -p err` menunjukkan
  `toa[…]: ALARM toa: PROBE toa: …` (bukan lagi `root[…]`, karena unit alarm kini `User=toa`
  menjalankan skrip bersama, bukan `root` menjalankan `logger` langsung) — dan jalan nyata
  `toa-kesehatan.service` (BAHAYA `mmk`) diulang sesudah refactor juga →
  `toa[…]: ALARM toa: kesehatan toa BAHAYA …`. Keduanya lewat titik yang sama.
- **Tag stabil `-t toa-alarm` ditambah dan diverifikasi ULANG** sesudah ditemukan (nyata, bukan
  teori) bahwa `journalctl -u toa-probe-gagal.service` TIDAK SELALU menampilkan baris alarm
  walau alarmnya benar terkirim dan unitnya start/finish normal (journald salah-atribusi proses
  `logger` yang cepat keluar). Diulang: override sementara + 3x gagal beruntun → kali ini
  `-u toa-probe-gagal.service` menampilkan barisnya juga, TAPI `journalctl -t toa-alarm`
  menampilkannya di KEDUA percobaan, stabil — itu sebabnya bagian "Cara membaca `status.json`"
  di atas merekomendasikan `-t toa-alarm`, bukan `-u <nama>-gagal.service`, untuk memastikan
  alarm benar-benar tidak berbunyi.
- **Jadwal terbukti aktif** (`systemctl list-timers toa-kesehatan.timer toa-probe.timer
  toa-cadangan.timer`, akhir pekerjaan):
  ```
  NEXT                            LEFT LAST                         PASSED UNIT                ACTIVATES
  Fri 2026-09-04 18:10:00 WIB   …    Fri 2026-09-04 18:05:34 WIB     …      toa-probe.timer     toa-probe.service
  Sat 2026-09-05 03:00:18 WIB      8h -                                    toa-cadangan.timer  toa-cadangan.service
  Sat 2026-09-05 04:00:22 WIB      9h -                                    toa-kesehatan.timer toa-kesehatan.service
  ```
  `systemctl is-enabled`/`is-active` ketiganya → `enabled`/`active`.

## Yang tertahan pada pemilik (jangan dianggap sudah beres)

1. **Saluran pemberitahuan nyata (SMTP/webhook) belum terpasang.** `kirim-alarm.sh` adalah titik
   tunggalnya (lihat di atas) — mengisi `/home/toa/pemantauan/alarm.env` adalah SATU-SATUNYA
   langkah tersisa, tapi memilih layanan mana (dan menanggung biayanya kalau berbayar) adalah
   keputusan pemilik.
2. **(C) Railway cron service TIDAK dikerjakan** — pelengkap yang sah tapi butuh tindakan
   pemilik di dashboard Railway; tugas ini eksplisit dilarang menjalankan `railway` apa pun.
3. **VPS `toa` sendiri adalah TITIK TUNGGAL KEGAGALAN untuk SELURUH pemantauan** (cadangan,
   kesehatan, probe) — persis caveat yang sama dengan yang sudah ditulis di
   `docs/runbook-cadangan-2026-09-04.md` soal cadangan bukan offsite. Kalau VPS ini mati, TIDAK
   ADA yang memantau apa pun — termasuk tidak ada yang memantau bahwa pemantauannya sendiri
   mati (tak ada dead-man's-switch eksternal). Ini risiko terbuka, bukan sesuatu yang diam-diam
   dianggap sudah beres oleh pekerjaan ini.
4. **Temuan produksi NYATA yang belum ditindaklanjuti — DAN konsekuensinya pada alarm ini
   sendiri**: toko `mmk` belum punya batch rekonsiliasi bertanggal sejak **2026-08-26 (9 hari)**
   per saat runbook ini ditulis — muncul sebagai BAHAYA asli (bukan rekayasa pengujian) pada
   jalan pertama `toa-kesehatan.service`. Ini temuan operasional untuk pemilik/tim, bukan bug
   pemantauan — **tapi selama `mmk` belum dapat batch (atau dinonaktifkan), `toa-kesehatan.timer`
   akan BAHAYA setiap pagi, terus-menerus.** Begitu saluran nyata di atas terpasang, ini berarti
   alarm berbunyi SETIAP HARI sampai `mmk` selesai — dan temuan BAHAYA lain yang muncul
   BERSAMAAN (index invalid baru, disk menipis) akan mendarat di keadaan yang SUDAH merah,
   tidak kelihatan beda di level "alarm berbunyi atau tidak". Satu-satunya cara membedakannya
   hari itu adalah membuka `~/kesehatan/status.json` dan membandingkan bagian mana yang
   berubah — alarm sendirian tidak cukup begitu ada temuan berdiri lama yang belum
   ditindaklanjuti. Menindaklanjuti `mmk` bukan cuma soal data toko itu — itu yang membuat
   alarm ini kembali punya daya beda (discriminating) besok pagi.
5. **✅ RESOLVED 04-09-2026 sebagai efek samping butir 6 (di bawah).** Ketergantungan pada akses
   SUPERUSER Postgres lewat proxy publik dulu ada karena `COPY FROM PROGRAM` (butir 6) butuh
   `rolsuper=true`. Sejak `COPY FROM PROGRAM` dicabut, bagian 3 (`ukuran_db_produksi`) memakai
   `SELECT pg_database_size(current_database())` — fungsi biasa, tidak butuh hak superuser sama
   sekali. Risiko "kalau hak superuser dicabut pasca-migrasi, bagian disk gagal terbaca" **tidak
   lagi berlaku** untuk bagian ini. (Kredensial `~/.pgpass` itu sendiri tetap dipakai untuk
   koneksi produksi secara umum — itu bukan soal superuser, dan tetap perlu diperhatikan saat
   migrasi Contabo, lihat `docs/rencana-migrasi-contabo-2026-08-31.md`.)
6. **⚠️ DICABUT 04-09-2026 (VETO PEMILIK) — dibiarkan utuh sebagai riwayat butir yang memang
   ditulis untuk bisa di-veto.** Isi asli: "`COPY ... FROM PROGRAM 'df ...'` mengeksekusi
   perintah SHELL di host Postgres produksi lewat SQL superuser — ini LEBIH dari sekadar
   `SELECT`, walau efeknya sendiri tidak berbahaya (`df` baca-saja, tabelnya sementara-sesi) dan
   brief menyebut 'kamu hanya membaca'. Teknik ini dipakai secara sadar karena satu-satunya cara
   membaca disk NYATA produksi tanpa akses shell langsung ke host Postgres (lihat keputusan #6
   di bagian jalur di atas), tapi itu keputusan TEKNIS yang diambil pekerjaan ini, bukan sesuatu
   yang otomatis disetujui pemilik hanya karena 'membaca'." **Pemilik memveto persis seperti yang
   diantisipasi butir ini.** Dicabut di kode (`scripts/pemantauan/periksa-kesehatan-terjadwal.sh`
   DAN salinan VPS yang berjalan) dan diganti `pg_database_size` — lihat revisi keputusan #6 di
   bagian jalur di atas untuk rinciannya. Bukti eksekusi ulang (verdict tetap waras) ada di
   `.superpowers/sdd/prompt-eksekusi-perbaikan-2026-09-04/fix1-report.md`.
