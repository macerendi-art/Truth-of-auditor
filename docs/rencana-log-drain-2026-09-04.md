# Rencana B5: retensi log Railway (7–30 hari, tanpa drain) — 2026-09-04

Dokumen keputusan untuk pemilik. **Tidak ada kode yang berubah di sini** — ini
menjawab satu pertanyaan: apakah butuh (dan layak) memasang penyimpanan log
tambahan di luar retensi bawaan Railway, dan kalau ya, yang mana.

Ditulis **setelah** B3 (log akses gunicorn dinyalakan) dan sejalan dengan B4
(formatter+level logging) dan B2 (Sentry opsional) — ketiganya baru saja
mengubah premis butir B5 aslinya, jadi angka di bawah dihitung ulang, bukan
disalin dari draf awal.

## Ringkasan untuk yang buru-buru

- **Volume log kecil** — bahkan skenario tersibuk yang dihitung di bawah
  (±13 MB/hari) masih jauh di bawah tingkatan gratis/termurah semua vendor
  yang dibandingkan. Biaya opsi B5 **tidak digerakkan oleh volume**, tapi oleh
  harga minimum tiap vendor dan oleh risiko privasi.
- **Retensi yang benar-benar didukung bukti di repo ini: ~30 hari**, bukan
  90 hari, dan bukan sekadar "makin lama makin aman". Insiden nyata yang
  paling lambat ketahuan di `CLAUDE.md` berjarak **19 hari** dari kejadian ke
  penemuan; tidak ada satu pun yang melebihi itu. Tapi — dan ini penting —
  **insiden-insiden itu ketahuan lewat query ke database produksi, bukan
  lewat log Railway.** Kasus yang benar-benar bergantung pada log akses HTTP
  (bukan data aplikasi) adalah kelas yang berbeda: percobaan akses yang
  ditolak GeoBlock, yang **tidak** tercatat di mana pun selain baris log itu
  sendiri. Lihat Bagian 2.
- **Temuan privasi yang tak boleh dilewati:** format `--access-logformat` B3
  sengaja tidak mencatat query string permintaan saat ini — tapi field
  Referer (`%(f)s`) yang DICATAT bisa membawa query string dari **halaman
  sebelumnya**, dan halaman pencarian transaksi (`?q=`) menyaring persis
  `username`, `reference`, dan **`counterparty` (nama pemilik rekening
  bank)** — nama pemain/nomor rekening sungguhan. Ini celah yang belum
  tertutup oleh keputusan B3. Lihat Bagian 3.
- **Rekomendasi tunggal** (Bagian 5): pastikan/naikkan plan Railway ke
  tingkat yang memberi retensi 30 hari; **jangan** pasang drain ke pihak
  ketiga sebelum celah Referer di atas ditutup di kode. Opsi VPS `toa` disimpan
  sebagai langkah fase-2 opsional, bukan langkah sekarang.

---

## 1. Perkiraan volume log/hari

### 1.1 Format yang sekarang (sumber: `Procfile`)

```
--access-logformat '%(h)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)s'
```

`%(U)s` = path **tanpa** query string (keputusan B3, lihat commit
`65bc1c9`/`core/tests_access_log.py`). Field lain: `%(h)s` IP klien, `%(t)s`
timestamp, `%(s)s` status, `%(b)s` ukuran respons, `%(f)s` Referer, `%(a)s`
User-Agent, `%(L)s` waktu respons.

Cara menghitung volume: **volume/hari = (permintaan/hari) × (ukuran rata-rata
satu baris log)**. Dua bagian ini dihitung terpisah di bawah, keduanya
perkiraan berlabel — bukan diukur dari log produksi sungguhan (repo ini tidak
punya sampel log nyata untuk diaudit).

### 1.2 Ukuran satu baris log

Baris nyata memuat 3 field bervariasi panjang: path, Referer, User-Agent.
Tiga contoh representatif (dikonstruksi persis dari format Procfile di atas,
dihitung dengan `len(...encode('utf-8'))`):

| Jenis permintaan | Contoh path | Panjang baris |
|---|---|---|
| Halaman laporan | `GET /rekap-bulanan/` | 252 byte |
| Aset statis (cache hit 304) | `GET /static/web/css/app.a1b2c3d4.css` | 268 byte |
| Unggah berkas | `POST /toko/g25/unggah/` | 257 byte |

User-Agent Chrome desktop tipikal (±110 karakter) mendominasi ukuran baris.
**Perkiraan rata-rata dipakai: 260 byte/baris.** Baris dengan Referer panjang
(lihat Bagian 3 — inilah persisnya yang jadi masalah privasi) bisa lebih
besar; 260 byte adalah titik tengah yang wajar, bukan batas atas.

### 1.3 Jumlah permintaan/hari — JANGAN diturunkan dari ±500rb baris/hari

Pertumbuhan ±500rb baris `Transaction`/hari (diukur 04-09, lihat brief) adalah
baris **data** yang di-*bulk-create* di dalam satu transaksi atomic per
berkas diunggah (`sources/services.ingest`) — **satu file besar = satu baris
log HTTP**, bukan satu baris log per baris data. Menyamakan keduanya akan
melebih-lebihkan volume log **ribuan kali lipat**. Kontribusi unggahan ke
jumlah permintaan HTTP kecil: ±16+ toko (lihat `tokos_grouped`/daftar brand di
`CLAUDE.md`) × ±5 jenis sumber (panel DP, panel WD, bracket, bank, gateway) ×
1–3 unggahan/hari ≈ **80–250 permintaan POST/hari** — dan setiap satu berapa
pun baris di dalamnya tetap 1 baris log.

Pendorong volume yang sebenarnya adalah **trafik manusia** (tim auditor
internal membuka dashboard/laporan) ditambah **aset statis** (WhiteNoise
tetap jalan lewat proses gunicorn yang sama, jadi CSS/JS/gambar tetap kena
`--access-logfile`) ditambah lalu lintas non-manusia (health check, bot yang
mencoba path acak — relevan untuk Bagian 2). Tidak ada alat ukur permintaan
riil yang tersedia untuk tugas ini (metrik Railway sengaja tidak disentuh
sesuai batasan brief), jadi dipakai tiga skenario berlapis, ditandai jelas
sebagai **perkiraan**:

| Skenario | Asumsi | Permintaan/hari |
|---|---|---|
| Rendah | ±15 akun aktif × ±150 permintaan/hari (halaman+HTMX+aset belum ter-cache) | ~2.250 |
| Sedang | ±30 akun aktif × ±400 permintaan/hari | ~12.000 |
| Tinggi | termasuk hari unggah sibuk + percobaan akses dari luar (lihat Bagian 2) | ~50.000 |

Jumlah akun tidak punya sumber terukur di repo ini (tidak ada fixture/migrasi
seed yang mencatat jumlah user) — **perkiraan, minta pemilik konfirmasi
jumlah auditor/supervisor aktif sebelum mempercayai ujung atas tabel ini.**

### 1.4 Volume/hari dan perbandingan dengan jendela retensi Railway

`volume = permintaan/hari × 260 byte`, lalu dikalikan 7 dan 30 hari untuk
dibandingkan dengan jendela retensi Railway yang dinyatakan brief (7–30 hari
tergantung plan; per dokumentasi Railway: Hobby/Trial 7 hari, Pro 30 hari,
Enterprise hingga 90 hari — dicek ulang di Bagian 4, bukan sekadar disalin
dari brief):

| Skenario | Volume/hari | Volume 7 hari | Volume 30 hari |
|---|---|---|---|
| Rendah | ~585 KB | ~4,1 MB | ~17,6 MB |
| Sedang | ~3,1 MB | ~21,8 MB | ~93,6 MB |
| Tinggi | ~13,5 MB | ~94,5 MB | ~390 MB |

**Kesimpulan Bagian 1:** bahkan skenario tersibuk (390 MB/30 hari) berorde
puluhan-ratusan MB — dua-tiga tingkat besaran di bawah tingkatan gratis vendor
manapun yang dibandingkan di Bagian 4. Log Django (error/warning, bukan akses)
jauh lebih kecil lagi — hanya menyala saat ada error 500 sungguhan (level
`ERROR` ke `console`+`mail_admins`, lihat `truth_auditor/settings.py`), realistis
puluhan baris/hari bahkan di hari buruk. **Volume bukan alasan untuk menahan
diri dari opsi mana pun di Bagian 4 — anggaran ditentukan variabel lain.**

---

## 2. Berapa lama retensi yang sebenarnya dibutuhkan

### 2.1 Metode: jeda kejadian→penemuan di histori nyata repo ini

`CLAUDE.md` dan riwayat commit-nya (`git log --follow -- CLAUDE.md`) adalah
sumber terbaik untuk ini — bukan kaidah retensi generik. Setiap baris di
bawah dicocokkan dengan **tanggal kejadian** (disebutkan di teks) dan
**tanggal commit yang mendokumentasikan pemahaman/perbaikannya** (dari `git
log`), lalu selisihnya dihitung.

| Insiden | Kejadian | Ketahuan/diperbaiki | Jeda | Cara ketahuan |
|---|---|---|---|---|
| QRIS Flyer shape-3: 1.519 baris sampah/unggahan, 6.118 baris total di produksi | mulai ±01-08-2026 (kalibrasi HKW) | commit `c3d2e612`, 10-08-2026 (gerbang header `_WAJIB`) | **s.d. 9 hari** | Query SQL langsung ke `Transaction` (`ticket_no=""`, `posted_date=NULL`) |
| QRIS Flyer shape-4: 339 baris LTN tanpa tanggal | 12-08-2026 | commit `c870971`/`7005fae`, 13-08-2026 | **~1 hari** | Query SQL serupa, dipicu kecurigaan dari insiden shape-3 |
| `row_hash` BSW ganda (1.366 baris, format desimal) | 12-08-2026 | dipahami commit `7005fae`, 13-08-2026 — **perbaikan resep masih DITUNDA sampai hari ini (04-09), 23 hari dan berjalan** | 1 hari (paham) / 23+ hari (belum tuntas) | Query SQL + penelusuran kode (`row_hash`), bukan log |
| `work_mem`/`shared_buffers` Postgres kembali ke default senyap pasca insiden `DiskFull /dev/shm` | 13-08-2026 | commit `6ccea90`, 01-09-2026 | **19 hari** | `pg_settings` (katalog Postgres, bukan log aplikasi) |
| Anomali matcher (COR QRIS ELITE kehilangan kunci UUID, rekonsiliasi 1,3 dtk→22–29 dtk) | mulai 25-08-2026, **masih berlangsung** | commit `51afbd4`, 01-09-2026 (didiagnosis, belum diperbaiki) | **7 hari s.d. dokumentasi, tak terbatas s.d. perbaikan** | `cProfile` + query langsung ke `MatchResult`/`Transaction` produksi |
| Index yang gagal terbangun (`AddIndexConcurrently` menelan galat di SQLite, migrasi tetap tercatat selesai) | sejak dibuat, tanpa batas waktu alami | terdeteksi hanya bila `periksa_index`/`periksa_kesehatan` dijalankan manual | **tidak terbatas** — bisa senyap selamanya | Command khusus yang membaca katalog Postgres (`pg_index`), bukan log |

### 2.2 Nuansa yang wajib disampaikan ke pemilik, bukan hanya angkanya

**Semua kejadian di tabel di atas ketahuan lewat query ke data aplikasi
(Postgres `Transaction`/`MatchResult`/katalog `pg_settings`/`pg_stat_*`) atau
lewat command diagnostik (`periksa_index`, `periksa_kesehatan`), BUKAN lewat
log akses HTTP atau log Django.** Data aplikasi di Postgres tidak punya batas
retensi (tersimpan selama tabelnya ada) — jadi retensi log Railway **tidak
pernah jadi penghalang** untuk insiden-insiden finansial/data-integritas di
atas, termasuk dua yang disebut brief (baris dateless QRIS Flyer, 1.366 baris
ganda BSW). Kerangka "bukti operasional menguap tepat saat dibutuhkan" di
pembuka brief **benar sebagai kekhawatiran umum, tapi tidak didukung oleh
insiden-insiden spesifik ini** — mereka justru bukti bahwa tim ini sudah
terbiasa menyelidiki lewat database, bukan lewat log.

**Yang genuinely bergantung pada log HTTP (bukan data aplikasi):** percobaan
akses yang ditolak `GeoBlockMiddleware`. Middleware ini (`web/middleware.py`,
`class GeoBlockMiddleware`) mengembalikan `HttpResponseForbidden` langsung —
**tidak** melempar exception, **tidak** memanggil `catat()`/`AuditLog`, jadi
**tidak ada satupun jejak di database** untuk setiap 403 geo-block. Satu-
satunya bukti yang tersisa adalah baris log akses (`status=403`) itu sendiri,
dan itu lenyap begitu keluar dari jendela retensi Railway.
`IPAllowlistMiddleware` sedikit lebih baik — ia memanggil `catat(user,
"ip_blokir", ip, ...)` tapi **hanya sekali per sesi per IP** (lihat
`_SESSION_FLAG`), jadi frekuensi/pola percobaan berulang dalam satu sesi tetap
cuma ada di log mentah.

**Kesimpulan Bagian 2 — rekomendasi angka:** target retensi **≥30 hari**.
Alasan: (a) jeda terpanjang yang benar-benar terbukti di repo ini adalah 19
hari (insiden Postgres) dan 9 hari (QRIS Flyer shape-3) — 30 hari memberi
marjin di atas keduanya tanpa melompat ke 90 hari yang tak didukung bukti
apa pun di sini; (b) forensik keamanan (GeoBlock/IPAllowlist) — kelas insiden
yang PALING bergantung pada log — belum punya pola jeda terukur di repo ini
(fitur baru live sejak 22-07-2026, belum ada insiden nyata tercatat), jadi
30 hari adalah titik awal yang wajar, bukan angka yang diturunkan dari
kejadian spesifik. **Jika pemilik tahu siklus tinjau keamanan internal lebih
jarang dari bulanan, angka ini harus dinaikkan** — itu informasi yang tidak
ada di repo mana pun.

---

## 3. Privasi — jangan lewati bagian ini

### 3.1 Kenapa `%(U)s` (bukan `%(r)s`) dipilih di B3

Dikonfirmasi dari commit `65bc1c9` dan `core/tests_access_log.py`: `%(r)s`
gunicorn adalah request-line mentah (`"GET /path?query HTTP/1.1"` apa
adanya, termasuk query string). Aplikasi ini punya endpoint pencarian yang
menyaring lewat query string — `web/views.py` baris ~1287–1300, fungsi
`transactions`:

```python
q = request.GET.get("q", "").strip()
cond = (
    Q(username__icontains=q)
    | Q(ticket_no__icontains=q)
    | Q(reference__icontains=q)
    | Q(counterparty__icontains=q)   # nama pemilik rekening bank
)
```

Jadi pencarian nyata di aplikasi ini benar-benar berbentuk
`?q=<nama pemain>` atau `?q=<nama pemilik rekening>` — **`counterparty`
adalah nama orang sungguhan** (pengirim/penerima transfer bank). Kalau
`%(r)s` dipakai, setiap pencarian semacam ini menulis nama pemain/rekening
langsung ke log teks polos. `%(U)s` (path tanpa query) menutup celah ini
**untuk baris log permintaan itu sendiri** — keputusan B3 di titik ini benar
dan sudah diuji (`test_access_logformat_tidak_memuat_request_line_mentah`).

### 3.2 Celah yang BELUM tertutup: Referer (`%(f)s`)

Format B3 tetap mencatat `%(f)s` (header `Referer`) — dan Referer bukan query
string permintaan **saat ini**, melainkan URL lengkap halaman **sebelumnya**,
**termasuk query string halaman itu**. Django tidak mengatur
`SECURE_REFERRER_POLICY` secara eksplisit di `truth_auditor/settings.py`
(dicek — tidak ditemukan), jadi berlaku default Django (`same-origin`) atau
default browser modern (`strict-origin-when-cross-origin`). **Keduanya sama-
sama mengirim path+query lengkap untuk navigasi SATU-ORIGIN** — dan hampir
semua navigasi di aplikasi internal ini memang satu-origin (auditor
berpindah antar halaman dalam `auditor.wolfgang-77.com` yang sama).

Rantai kebocorannya konkret: auditor mencari `?q=Budi Santoso` di halaman
Transaksi → tidak tercatat sebagai `%(U)s` request itu sendiri (aman) → tapi
begitu auditor klik tautan APA PUN dari halaman hasil pencarian itu (menuju
dashboard, halaman lain, bahkan permintaan aset statis di halaman tujuan),
browser mengirim `Referer: https://.../transaksi/?q=Budi+Santoso` pada
permintaan BERIKUTNYA — dan `%(f)s` **mencatatnya apa adanya**. Nama pemain
atau nama pemilik rekening jadi tercatat di baris log yang berbeda, beberapa
detik kemudian, dengan cara yang persis meniadakan maksud keputusan B3.

Ini bukan spekulasi teoretis — endpoint pencariannya nyata dan sudah
dipakai (dirujuk `CLAUDE.md` bagian performa v1.18.0: "`reference` +
`username` ... satu-satunya pemakaian ... `icontains` [pencarian]").

### 3.3 Implikasi untuk B5

- **Log yang ada SEKARANG (di Railway, dalam jendela 7–30 hari)** sudah
  berisiko memuat nama pemain/rekening lewat jalur Referer ini — ini bukan
  risiko baru yang diciptakan drain, tapi risiko yang SUDAH ADA sejak B3
  dinyalakan (04-09-2026) dan hanya makin lama bertahan kalau retensi
  diperpanjang atau disalin ke penyimpanan lain.
- **Mengirim log ke pihak ketiga (Bagian 4, Opsi C) memindahkan risiko ini ke
  luar** — vendor SaaS asing menyimpan salinan yang bisa memuat nama
  pemain/rekening sungguhan, tunduk pada kebijakan retensi/subprocessor
  mereka sendiri, bukan kontrol pemilik.
- **Rekomendasi:** perbaikan celah Referer ini (mis. `SECURE_REFERRER_POLICY
  = "strict-origin"` — mengirim origin saja tanpa path/query sama sekali
  untuk semua navigasi, atau menapis field Referer di lapisan
  forwarder/proxy sebelum dikirim keluar) **ada di luar wewenang tulis
  dokumen ini** (`truth_auditor/settings.py` sedang ditulis agen lain) —
  **dicatat sebagai eskalasi**, lihat Bagian 5. Sampai celah ini ditutup,
  opsi mengirim log ke vendor pihak ketiga (Opsi C) sebaiknya ditahan, atau
  minimal disaring (`Referer` dibuang/dipotong sebelum dikirim) di titik
  forwarder.

---

## 4. Opsi konkret dengan biaya bulanan

Catatan teknis yang mengoreksi asumsi umum: **Railway tidak punya tombol
"log drain" bawaan.** Dokumentasi Railway sendiri: *"Railway does not have a
log drain setting, but you can forward stdout using a log forwarder"*
(Vector/Fluent Bit/OpenTelemetry) — jadi Opsi B dan C di bawah SAMA-SAMA
butuh menambah forwarder yang membaca stdout gunicorn, yang berarti
menyentuh `Procfile`/`railway.json` (start command) — **di luar wewenang
tulis dokumen ini**, jadi langkah pemasangannya ditulis sebagai instruksi,
bukan dieksekusi.

Retensi bawaan Railway per plan (didokumentasikan): **Hobby/Trial 7 hari,
Pro 30 hari, Enterprise hingga 90 hari.** Catatan menarik dari dokumentasi
yang sama: menaikkan plan konon "immediately restore logs that were
previously outside of the retention period" — **jangan dipercaya begitu saja
untuk keputusan operasional**; ini kalimat marketing yang belum diverifikasi
lewat pengalaman nyata di proyek ini, konfirmasi ke Railway support kalau
mau mengandalkannya untuk pemulihan pasca-insiden.

### Opsi A — Naikkan plan Railway (Hobby → Pro)

| | |
|---|---|
| **Biaya** | Selisih plan dasar **Hobby $5/bulan → Pro $20/bulan** (+$15/bulan), **di luar** biaya pemakaian resource (compute/DB) yang sudah berjalan terpisah dan tak berubah oleh keputusan ini. **Perlu dikonfirmasi plan Railway proyek ini SEKARANG** — kalau sudah Pro, biaya tambahan = $0. |
| **Apa yang harus dijaga** | Tidak ada integrasi baru, tidak ada data keluar sistem — permukaan risiko privasi TIDAK bertambah. Satu-satunya hal yang perlu dipantau: retensi 30 hari tetap **terbatas** (bukan solusi permanen), dan klaim "upgrade memulihkan log lama" di atas belum terverifikasi. |
| **Siapa memasang** | Pemilik/admin akun Railway, lewat dashboard (ubah plan proyek) — **tidak butuh perubahan kode, tidak butuh akses `railway` CLI** (sengaja dihindari di tugas ini). |
| **Cara membatalkan** | Turunkan kembali ke plan sebelumnya kapan saja lewat dashboard yang sama; efeknya langsung (jendela retensi mengecil lagi ke 7 hari untuk data ke depan). |

### Opsi B — Self-host di VPS `toa` (yang sudah dipakai untuk cadangan)

VPS `toa` sudah punya pola operasional terpasang untuk pekerjaan berkala:
systemd `.service`+`.timer`, unit alarm-gagal (`OnFailure=`), dan
`logrotate.d` (lihat `docs/runbook-cadangan-2026-09-04.md`,
`scripts/cadangan/toa-cadangan.*`) — pola yang sama bisa dipakai ulang untuk
penerima log, bukan pola baru.

**Catatan jaringan penting, koreksi terhadap asumsi "tinggal pasang":** VPS
`toa` diakses lewat Tailscale (tailnet privat), **bukan** `toa-publik` (IP
publik, sudah dibatasi `ufw`+`fail2ban`, dan menurut catatan proyek "bisa
mengunci diri sendiri"). Pola cadangan yang sudah ada sengaja **menarik**
(pull) dari Railway lewat proxy TCP, bukan menerima (push) dari luar — ini
menghindari membuka port publik baru. Forwarder log yang PUSH dari Railway
(pola Vector standar) butuh `toa` menerima koneksi masuk dari internet publik
Railway, yang berarti membuka port publik baru di `toa-publik` — **menambah
permukaan serang yang selama ini sengaja dihindari desain cadangan.**
Alternatif yang lebih konsisten dengan pola yang ada: skrip **pull** berkala
(mis. lewat `railway logs`/API log Railway, dipanggil dari `toa` via cron/
timer, outbound saja, tanpa port baru) — ini perlu diriset lebih lanjut
sebelum diimplementasikan (di luar cakupan dokumen ini, lihat eskalasi).

| | |
|---|---|
| **Biaya** | Praktis **$0 tambahan** — VPS sudah disewa untuk cadangan, storage tambahan untuk log (puluhan-ratusan MB/bulan, lihat Bagian 1) dapat diabaikan dibanding kapasitas yang sudah dialokasikan untuk dump database. |
| **Apa yang harus dijaga** | (1) Jangan buka port publik baru di `toa-publik` tanpa penyaringan/otentikasi ketat — pertimbangkan pola pull, bukan push. (2) Tapis field Referer (Bagian 3) SEBELUM menyimpan, karena ini penyimpanan jangka panjang yang justru memperpanjang umur risiko privasi kalau tidak disaring. (3) Rotasi/hapus log lama (pola `logrotate` yang sama seperti cadangan) supaya tidak menumpuk tanpa batas — meski volumenya kecil, kebiasaan "simpan selamanya" bertentangan dengan poin privasi. (4) Siapa yang memantau kalau pipa berhenti mengalir diam-diam (alarm-gagal, seperti `toa-cadangan-gagal.service`). |
| **Siapa memasang** | Developer yang punya akses `ssh toa` DAN akses untuk mengubah `Procfile`/`railway.json` (start command perlu menambahkan forwarder atau memakai pendekatan pull terpisah) — **kedua perubahan itu di luar wewenang dokumen ini**, eskalasi ke pemilik/agen yang menulis berkas tersebut. |
| **Cara membatalkan** | Matikan unit systemd penerima (`systemctl stop`/`disable`), lepas wiring forwarder dari `Procfile`/`railway.json` (revert), hapus berkas log tersimpan di `toa` (`shred`/`rm` — ini data berisi PII, hapus dengan sengaja, bukan dibiarkan), tutup port yang sempat dibuka. |

### Opsi C — Drain ke layanan pihak ketiga

Dua vendor dicek harganya langsung (2026-09-04, harga bisa berubah — cek
ulang sebelum membeli):

| Vendor | Tingkatan gratis/termurah | Retensi | Cukup untuk volume Bagian 1? |
|---|---|---|---|
| **Axiom** | Personal: **gratis**, 500 GB/bulan ingest | 30 hari | Ya, headroom >1.000× dari skenario tertinggi |
| **Better Stack (Logtail)** | Gratis: 3 GB, **retensi hanya 3 hari** (lebih pendek dari Railway Hobby!); Nano berbayar **$30/bulan (region EU)** memberi 30 hari | 3 hari (gratis) / 30 hari (Nano+) | Ya di kedua tingkat, tapi tingkat gratis retensinya justru LEBIH PENDEK dari yang mau diperbaiki |

Volume di sini kecil sehingga secara nominal opsi Axiom bisa **$0/bulan** —
tapi biaya sebenarnya bukan uang, melainkan **memindahkan data (termasuk
kebocoran Referer di Bagian 3) ke infrastruktur pihak ketiga di luar
Indonesia/Kamboja**, dengan kebijakan retensi/subprocessor vendor sendiri.

| | |
|---|---|
| **Biaya** | $0–45/bulan tergantung vendor & tingkatan (lihat tabel) — nominal kecil, tapi lihat catatan privasi di atas. |
| **Apa yang harus dijaga** | (1) **Wajib**: tutup/tapis celah Referer (Bagian 3) sebelum data keluar sistem — mengirim ke vendor asing tanpa menyaring ini artinya secara aktif mengekspor nama pemain/rekening ke luar negeri. (2) Tinjau kebijakan retensi & penghapusan data vendor (bukan cuma harga) — data finansial nyata butuh kejelasan siapa lagi yang bisa mengaksesnya di sisi vendor. (3) Kredensial/API key forwarder harus dijaga seperti kredensial produksi lain. |
| **Siapa memasang** | Developer, lewat forwarder (Vector/Fluent Bit) yang dikonfigurasi vendor + perubahan `Procfile`/`railway.json` — **eskalasi**, sama seperti Opsi B. |
| **Cara membatalkan** | Hentikan/lepas forwarder dari `Procfile`/`railway.json` (revert), **secara eksplisit minta penghapusan data** di akun vendor (bukan sekadar berhenti bayar/downgrade — banyak vendor menyimpan data sampai diminta hapus), tutup/hapus akun vendor. |

---

## 5. Rekomendasi tunggal

**Konfirmasi plan Railway proyek ini sekarang, dan kalau belum, naikkan ke
tingkat yang memberi retensi 30 hari (Opsi A).** Ini opsi termurah dalam
kasus terburuk (+$15/bulan, $0 kalau ternyata sudah di plan itu),
**tidak menambah satu pun celah privasi baru** (tidak ada data yang pindah
ke sistem lain), dan 30 hari adalah angka yang didukung bukti nyata di
Bagian 2 (jeda kejadian→penemuan terpanjang yang terbukti = 19 hari).

**Jangan pasang drain ke pihak ketiga (Opsi C) sampai celah Referer (Bagian
3.2) ditutup di kode** — mengirim log yang berpotensi memuat nama pemain/
nama pemilik rekening ke vendor asing, sebelum menutup celah yang sudah
diketahui, adalah persis jenis keputusan yang brief minta jangan dilewati.

**Opsi B (VPS `toa`) disimpan sebagai langkah fase-2**, kalau pemilik
memutuskan 30 hari tidak cukup (mis. karena siklus tinjau keamanan internal
lebih jarang dari bulanan — informasi yang tidak ada di repo ini) atau ingin
riwayat GeoBlock/IPAllowlist yang bisa dicari lintas bulan. Kalau dipilih,
implementasikan pola **pull** (bukan push) supaya tidak membuka port publik
baru di `toa-publik`, dan tetap tapis Referer sebelum disimpan.

### Yang tertahan pada pemilik (tidak bisa diputuskan dokumen ini)

1. **Konfirmasi plan Railway saat ini** (Hobby/Pro/lainnya) — menentukan
   apakah Opsi A berbiaya $0 atau +$15/bulan, dan apakah retensi 30 hari
   sudah aktif hari ini tanpa tindakan apa pun.
2. **Konfirmasi apakah `SENTRY_DSN` sudah diset di Railway produksi** (B2).
   Kalau sudah, sebagian besar kebutuhan "kenapa 500 itu terjadi" sudah
   tertangani independen dari retensi log Railway (Sentry punya retensi
   sendiri) — mengurangi urgensi Opsi B/C untuk tujuan itu.
3. **Perbaikan celah Referer** (`SECURE_REFERRER_POLICY` atau penyaringan di
   forwarder) — di luar wewenang tulis dokumen ini (`truth_auditor/settings.py`
   sedang ditulis agen lain). **Eskalasi**: perlu task terpisah sebelum Opsi
   C layak dijalankan.
4. **Perubahan `Procfile`/`railway.json`** untuk memasang forwarder (Opsi B
   atau C) — di luar wewenang tulis dokumen ini, perlu dikoordinasikan dengan
   agen/task yang memegang berkas tersebut.
5. **Siklus tinjau keamanan yang diinginkan pemilik** (bulanan? triwulanan?
   tidak ada sama sekali saat ini) — menentukan apakah 30 hari benar-benar
   cukup atau harus dinaikkan ke Enterprise (90 hari)/Opsi B.

---

## Lampiran — sumber & cara verifikasi ulang

- Format log akses: `Procfile` baris 1; keputusan desain: commit `65bc1c9`
  (`sec(deploy): log akses gunicorn ke stdout, format tanpa query string
  (B3)`), diuji `core/tests_access_log.py`.
- Logging Django (B4) & Sentry opsional (B2): `truth_auditor/settings.py`
  baris ±285–355, `truth_auditor/security.py` (`configure_sentry`).
- Endpoint pencarian yang jadi dasar temuan Referer: `web/views.py`
  fungsi `transactions`, ±baris 1276–1300.
- Middleware GeoBlock/IPAllowlist: `web/middleware.py`
  (`class GeoBlockMiddleware`, `class IPAllowlistMiddleware`).
- Jeda kejadian→penemuan (Bagian 2): `git log --follow -p -- CLAUDE.md`
  dicocokkan dengan tanggal kejadian yang disebut teksnya; commit kunci:
  `c3d2e612` (10-08), `7005fae`/`c870971` (13-08), `6ccea90`/`51afbd4`
  (01-09).
- Pola operasional VPS `toa`: `docs/runbook-cadangan-2026-09-04.md`,
  `scripts/cadangan/toa-cadangan.*`.
- Harga & retensi Railway/Axiom/Better Stack: dicek langsung 04-09-2026 dari
  `docs.railway.com` (halaman panduan Logs & Pricing), `axiom.co/pricing`,
  `betterstack.com/logs/pricing` — **harga vendor berubah, cek ulang sebelum
  membeli.**
