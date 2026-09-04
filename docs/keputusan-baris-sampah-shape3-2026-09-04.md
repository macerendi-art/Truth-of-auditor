# Keputusan: 6.118 baris sampah shape-3 QRIS Flyer di produksi — 2026-09-04

Dokumen keputusan untuk pemilik data. **Menghapus baris ini adalah keputusan
pemilik data — tidak ada satu baris pun yang dihapus dalam pengerjaan dokumen
ini.** Isinya: apa baris-baris itu, kenapa membiarkannya juga punya biaya,
bagaimana mengidentifikasinya dengan tepat, prosedur penghapusan yang aman
kalau pemilik memutuskan untuk menghapus, alternatif tanpa menghapus, dan satu
rekomendasi dengan syaratnya.

Sumber: `CLAUDE.md` bagian tentang penjaga header `_WAJIB` `QRFlyerParser`,
diverifikasi ulang terhadap kode di `sources/parsers/gateways.py`
(`QRFlyerParser`) dan `sources/management/commands/perbaiki_gateway_tanpa_tanggal.py`.

## Apa baris-baris itu, dan bagaimana lahirnya

Vendor QRIS Flyer sudah mengganti bentuk berkas ekspornya beberapa kali sejak
Agustus 2026. Sebelum ada penjaga header yang sekarang, bentuk ketiga
punya kolom `Client Reference` (sehingga baris tidak dianggap baris
footer/kosong dan tetap diproses) tetapi TIDAK punya kolom tiket maupun kolom
nominal yang dikenali parser saat itu. Akibatnya parser tetap menghasilkan
baris — bukan menolaknya — dengan `ticket_no=""`, `amount=0`, dan
`posted_date=NULL`. Ini terjadi pada **5 unggahan di 4 toko**, total
**6.118 baris**, menurut `CLAUDE.md`.

Baris-baris ini **inert**: nol yang pernah dikonsumsi batch, nol yang pernah
menghasilkan `MatchResult`, dan karena `posted_date` NULL, baris ini tidak
terlihat oleh jendela tanggal mana pun yang dipakai mesin pencocokan maupun
halaman laporan. `CLAUDE.md` sendiri menyebut sifat inert ini **"luck, not
design"** — bukan sesuatu yang dijamin kode, melainkan kebetulan karena
kebetulan tidak ada kolom yang membuatnya lolos jendela tanggal.

## Kenapa membiarkannya juga punya biaya

"Inert" tidak sama dengan "tidak berdampak sama sekali". Dua alasan konkret:

1. **Sifat inert-nya kebetulan, bukan dijamin.** Ini bukan klaim di atas kertas
   saja — saya menemukan setidaknya satu jalur kode yang SUDAH TIDAK terlindung
   oleh sifat inert itu: kartu dashboard **"Transaksi per Sumber"**
   (`web/views.py`, kueri `Transaction.objects.filter(toko=active)
   .values("source_type_id").annotate(n=Count("*"))`) TIDAK memfilter
   berdasarkan tanggal, `is_duplicate`, maupun status konsumsi — sengaja
   dirancang sebagai SATU agregat murah untuk seluruh riwayat toko (lihat
   catatan performa v1.18.0 di `CLAUDE.md`). Kueri ini menghitung baris apa
   adanya, sehingga 6.118 baris sampah ini **ikut terhitung** pada bar
   "gateway" kartu tersebut untuk keempat toko yang terdampak — permanen,
   diam-diam, tanpa satu pun tanda bahwa angkanya tercemar sampah.
2. **Mengaburkan audit.** Siapa pun yang kelak menyelidiki "kenapa jumlah
   baris gateway toko ini janggal" akan menghabiskan waktu menelusuri baris
   yang ternyata tidak pernah mewakili uang sungguhan.

Sebaliknya, biaya PENYIMPANANNYA sendiri kecil: 6.118 dari ±8,8 juta baris
produksi adalah ±0,07% — bukan soal ruang disk, murni soal kebenaran dan
kepercayaan pada angka.

## Bagaimana mengidentifikasinya dengan tepat

Kueri berikut (Django ORM) menyasar TEPAT populasi yang dijelaskan
`CLAUDE.md` — `ticket_no` kosong, `amount` nol, kedua kolom waktu NULL:

```python
from decimal import Decimal
from transactions.models import Transaction

kandidat = Transaction.objects.filter(
    source_type__key="gateway",
    ticket_no="",
    amount=Decimal("0"),
    posted_date__isnull=True,
    occurred_at__isnull=True,
)
```

**Kenapa kueri ini TIDAK menyentuh 1.705 baris yang bisa dipulihkan.** Kedua
populasi ini lahir dari kegagalan penjaga header yang SAMA (kolom yang tidak
dikenali) tapi bentuknya berlawanan, dan pembeda pastinya ada langsung di kode
perbaikan yang sudah berjalan: `perbaiki_gateway_tanpa_tanggal.py` menyeleksi
baris gateway dengan kedua kolom waktu NULL, lalu secara eksplisit
`.exclude(ticket_no="")` — dengan komentar di kode itu sendiri: *"Ini yang
memisahkan baris yang bisa dipulihkan dari 6.118 baris sampah bentuk ketiga
(tiket '', Rp0) yang juga tak bertanggal. Sampah itu TIDAK disentuh."* Kueri
identifikasi di atas adalah **komplemen logis yang persis** dari populasi yang
sudah dipulihkan command tersebut, dalam populasi dasar yang sama
(`source_type=gateway`, kedua kolom waktu NULL): command memulihkan
`ticket_no != ""`, kueri ini menyasar `ticket_no == ""`. Keduanya tidak pernah
tumpang tindih secara struktural, bukan karena kebetulan nilai data. Syarat
`amount=0` ditambahkan sebagai pengaman kedua yang independen (juga sesuai
`CLAUDE.md`) — supaya kalau kelak ada baris gateway lain yang dateless dengan
tiket kosong TAPI nominal bukan nol (situasi yang tidak didokumentasikan
mana pun), kueri ini tidak ikut menyasarnya secara diam-diam.

**Verifikasi yang saya lakukan.** Saya menjalankan kueri di atas (dan kueri
komplemennya, meniru `perbaiki_gateway_tanpa_tanggal`) terhadap basis data
lokal (`db.sqlite3`, 71.584 baris — **jauh lebih kecil dari 8,8 juta baris
produksi dan bukan representasinya**). Keduanya mengembalikan 0 baris. Ini
**sesuai dugaan**, bukan bukti angka 6.118/1.705: insiden shape-3 dan shape-4
QRIS Flyer adalah kejadian produksi yang tidak tercermin di salinan data lokal
ini. Yang terbukti dari langkah ini hanyalah bahwa kueri di atas valid secara
sintaks dan berjalan tanpa galat terhadap skema yang sekarang — angka
6.118/1.705 itu sendiri tetap dikutip dari `CLAUDE.md`, TIDAK diverifikasi
ulang di sini karena produksi berada di luar jangkauan tugas ini.

## Prosedur penghapusan yang aman (kalau pemilik memutuskan menghapus)

1. **Hitung dulu.** Jalankan kueri identifikasi di atas terhadap produksi
   (read-only), catat jumlah total dan rincian per toko/upload. Bandingkan
   dengan 6.118 yang tercatat di `CLAUDE.md` — kalau angkanya berbeda,
   berhenti dan cari tahu kenapa sebelum lanjut. Sebagai pemeriksaan silang
   murah: hitung juga populasi yang sama DITAMBAH
   `description__startswith="QRFLYER "` — kalau jumlahnya beda dari langkah
   ini, ada baris di luar QRIS Flyer yang ikut tersaring dan itu tanda
   berhenti, bukan tanda lanjut.
2. **Cadangkan dulu.** Produksi sekarang punya cadangan harian terjadwal
   (lihat `docs/runbook-cadangan-2026-09-04.md`, butir A1) — pastikan dump
   HARI INI (sebelum penghapusan berjalan) sudah berhasil (status sukses, TOC
   terbaca, checksum cocok). Yang penting justru dump **sebelum** penghapusan
   ini, bukan dump sesudahnya — dump setelah baris terhapus sudah tidak berisi
   baris itu lagi, jadi tidak berguna sebagai jalan mundur. Retensi cadangan
   sengaja pendek (`-mtime +1`, cuma hari ini + kemarin di disk), sehingga
   kalau baru terasa ada masalah besok lusa, dump hari penghapusan ini sudah
   tidak ada lagi di disk kalau tidak disalin keluar lebih dulu.
2b. **Ekspor baris yang akan dihapus, terpisah dari dump harian.** Sebelum
   menghapus, simpan `id`, `toko`, `upload_id`, `row_hash`, dan `raw` dari
   seluruh baris kandidat (langkah 1) ke satu berkas di luar rotasi 2-hari
   cadangan harian (mis. disalin ke penyimpanan lain, bukan `/var/backups/toa/`
   yang ikut retensi `-mtime +1`). Ini murah (6.118 baris, bukan seluruh
   basis data) dan menutup argumen utama untuk TIDAK menghapus (kehilangan
   bukti forensik insiden) tanpa perlu migrasi skema — lihat bagian
   Alternatif di bawah.
3. **Hapus dalam transaksi.** Bungkus penghapusan dalam satu
   `transaction.atomic()`, memakai filter YANG PERSIS SAMA dengan langkah 1
   (hitung ulang di dalam transaksi yang sama untuk menghindari kondisi balap
   dengan proses ingest yang mungkin berjalan bersamaan). Catat jumlah dan
   rincian per toko yang benar-benar terhapus ke log yang bertahan lama
   (mis. `AuditLog`, mengikuti pola nama aksi yang sudah ada seperti
   `fr_koreksi_hapus`) — penghapusan `Transaction` lewat jalur ini tidak
   otomatis melewati jejak audit yang biasanya menyertai penghapusan batch.
4. **Verifikasi sesudahnya.** Jalankan ulang kueri identifikasi (harus 0),
   jalankan ulang kueri komplemen `perbaiki_gateway_tanpa_tanggal` (jumlahnya
   harus TIDAK berubah — bukti 1.705 baris yang bisa dipulihkan tidak
   tersentuh), dan periksa kartu "Transaksi per Sumber" pada dashboard keempat
   toko yang terdampak — angka gateway-nya harus turun persis sejumlah baris
   yang dihapus untuk toko itu.

**Residu yang diketahui dan sengaja tidak ditutup di sini:** `CLAUDE.md`
(bagian performa v1.18.0) mencatat bahwa agregat `Upload.rows_parsed` TIDAK
pernah diperbarui saat transaksi dihapus lewat Django admin — hal yang sama
berlaku untuk penghapusan lewat prosedur ini. Kelima `Upload` yang menjadi
sumber 6.118 baris ini akan tetap melaporkan jumlah baris asalnya (termasuk
sampah yang sudah terhapus) pada catatan `rows_parsed`-nya, dan
`web/penjaga.py` memakai `rows_parsed + rows_duplicate` untuk kolam kebiasaan
per-stream. Ini residu yang murni kosmetik pada riwayat upload (tidak
menyentuh uang, tidak menyentuh rekonsiliasi) — dicatat di sini supaya tidak
ada yang terkejut menemukan selisih itu belakangan, bukan sesuatu yang perlu
diperbaiki sebagai syarat penghapusan.

Dokumen ini berhenti di prosedur — **eksekusinya sendiri di luar cakupan
tugas ini** (tidak boleh menyentuh produksi).

## Alternatif tanpa menghapus: menandai

Daripada menghapus, baris bisa ditandai sebagai sampah (mis. kolom/penanda
baru) alih-alih dihapus fisik.

**Untung:** dapat dibatalkan; menyimpan bukti forensik insiden ini (berapa
banyak baris rusak yang sempat terlanjur masuk, kalau kelak diperlukan mis.
untuk keperluan audit atau perselisihan dengan vendor); nol risiko
"menghapus sesuatu yang ternyata masih diperlukan". **Catatan:** manfaat
forensik ini sudah didapat dengan biaya jauh lebih rendah lewat langkah 2b
pada prosedur di atas (ekspor `id`/`toko`/`upload_id`/`row_hash`/`raw` ke
berkas terpisah sebelum menghapus) — tanpa migrasi skema, tanpa perubahan
kode. Ini melemahkan alasan utama untuk memilih menandai.

**Rugi:** ini SENDIRI adalah pekerjaan kode (migrasi skema untuk kolom
penanda baru + perubahan logika penulisan/pembacaan) — bukan solusi
"dokumen saja", dan berlawanan dengan pembatasan tugas ini yang tidak boleh
mengubah kode. Menandai juga tidak menutup risiko yang dijelaskan di atas
secara otomatis: kartu "Transaksi per Sumber" (dan kueri lain yang mungkin
serupa di masa depan) tetap perlu diperbarui SATU PER SATU untuk menghormati
penanda baru itu — kalau ada satu yang lupa, sampahnya muncul lagi di tempat
lain, persis pola yang membuatnya "kebetulan aman" sekarang. Menghapus
menutup risiko itu di semua tempat sekaligus, satu kali.

## Rekomendasi

**Hapus**, dengan syarat berikut dipenuhi lebih dulu:

1. Cadangan hari-H sudah diverifikasi berhasil (langkah 2 di atas) — bukan
   sekadar "ada jadwal cadangan", tapi hasil dump hari itu benar-benar sukses.
2. Kueri identifikasi dijalankan dulu di produksi (read-only) dan angkanya
   dikonfirmasi pemilik SEBELUM penghapusan berjalan — dokumen ini memberi
   kueri dan prosedurnya, bukan otorisasi untuk menjalankannya.
3. Penghapusan dan verifikasi memakai prosedur atomik + audit log di atas,
   bukan `DELETE` manual tanpa jejak.
4. Ekspor forensik (langkah 2b) sudah dijalankan sebelum penghapusan —
   syarat murah yang menutup risiko utama satu-satunya dari menghapus
   (kehilangan bukti insiden ini kalau kelak dibutuhkan).

Alasan memilih hapus di atas menandai: baris-baris ini tidak membawa informasi
sah apa pun (bukan transaksi, bukan duplikat yang perlu direkonsiliasi — betul-
betul kosong: tanpa tiket, tanpa nominal, tanpa tanggal), sehingga tidak ada
nilai masa depan dari menyimpannya di dalam tabel produksi; menandai tetap
membutuhkan pekerjaan kode dan migrasi (di luar cakupan dokumen ini) sementara
tidak menutup risiko "kueri baru lupa memfilter" di semua tempat sekaligus
seperti yang dilakukan penghapusan — dan dengan langkah 2b, nilai forensiknya
tetap tersimpan tanpa perlu menandai. Kalau pemilik menilai nilai forensik
insiden ini perlu disimpan DI DALAM basis data produksi itu sendiri (bukan
berkas ekspor terpisah), alternatif menandai tetap tersedia sebagai catatan
lanjutan — bukan sesuatu yang diputuskan lewat dokumen ini.
