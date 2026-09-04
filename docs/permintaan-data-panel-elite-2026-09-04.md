# Permintaan Data ke Panel Vigor/TM Gaming / Vendor QRIS ELITE — 2026-09-04

Draf permintaan yang bisa diteruskan pemilik ke pihak luar (panel Vigor/TM Gaming
dan/atau vendor gateway QRIS ELITE). Bagian A ditulis untuk dikirim apa adanya —
tidak menyebut nama modul kode, nama berkas, atau struktur basis data internal.
Bagian B adalah pegangan internal (sumber angka, rincian per brand) — **jangan
ikut diteruskan**.

Ini butir dengan dampak terbesar di seluruh daftar perbaikan berjalan, dan
perbaikannya **ada di data, bukan di kode kami** — karena itu bentuknya
permintaan, bukan pekerjaan teknis.

---

## A. Naskah siap kirim

### Versi ringkas (5 kalimat, untuk chat)

> Sejak 25 Agustus 2026, proses pencocokan transaksi otomatis untuk brand
> Vigor/TM Gaming melambat tajam — dari sekitar 1,3 detik menjadi 22–29 detik
> per hari — dan tingkat kecocokannya turun dari kisaran normal 95–97% menjadi
> 93,5%. Penyebabnya: laporan deposit QRIS dari gateway ELITE untuk brand ini
> tidak membawa satu pun nomor identitas transaksi yang bisa langsung
> dipasangkan ke catatan panel, sehingga sistem terpaksa membandingkan hampir
> 5 juta kombinasi baris per hari satu per satu alih-alih langsung mengenali
> pasangannya. Kabar baiknya, laporan **withdraw** QRIS ELITE untuk brand yang
> sama **sudah** membawa nomor ini, dan **12 brand lain** di jaringan yang sama
> juga sudah menerimanya untuk sisi deposit — jadi ini bukan permintaan fitur
> baru, hanya perluasan sesuatu yang sudah berjalan di tempat lain. Kami mohon
> salah satu saja dari dua hal: laporan deposit QRIS panel menyertakan nomor
> transaksi per baris (seperti laporan withdraw-nya), **atau** pihak ELITE
> mengisi kolom tiket dengan nomor tiket panel untuk brand ini (seperti sudah
> berlaku untuk 12 brand lain). Bila salah satu terpenuhi, waktu proses kembali
> ke ±1,3 detik dan tingkat kecocokan kembali ke 95–97%; bila tidak, beban
> proses akan terus membesar seiring pertumbuhan transaksi dan tingkat
> kecocokan tetap tertahan di bawah standar biasanya.

### Surat/pesan lengkap

**Perihal: Permintaan penyesuaian data kecil — laporan deposit QRIS (Vigor/TM
Gaming)**

Yth. Bapak/Ibu,

Kami ingin menyampaikan satu kendala teknis pada sistem rekonsiliasi transaksi
kami, khusus untuk brand yang menggunakan panel Vigor/TM Gaming, dan mengajukan
permintaan kecil yang kami yakini bisa menyelesaikannya.

**Apa yang terjadi.** Sejak 25 Agustus 2026, proses pencocokan otomatis antara
catatan transaksi panel dan catatan uang masuk untuk brand-brand ini melambat
signifikan — dari hitungan detik menjadi puluhan detik per hari — dan tingkat
akurasi pencocokannya ikut turun dari kisaran normal (95–97%) menjadi 93,5%.
Setelah ditelusuri, sebabnya bukan pada sistem kami, melainkan pada satu
perubahan data sejak brand-brand ini pindah menggunakan gateway QRIS ELITE:
laporan deposit QRIS dari panel untuk transaksi ini tidak menyertakan nomor
identitas transaksi (nomor unik per baris) yang bisa dipasangkan langsung ke
catatan gateway. Tanpa nomor itu, sistem kami harus membandingkan setiap baris
transaksi satu per satu berdasarkan nama pengguna dan nominal saja — jauh lebih
lambat, dan sebagian transaksi jadi tidak terpasangkan otomatis sama sekali
sehingga harus ditinjau manual satu per satu.

**Yang membuat kami yakin ini bisa diselesaikan tanpa pekerjaan besar:**
nomor identitas transaksi ini **sudah tersedia** pada dua tempat lain yang
setara persis:

1. Laporan **withdraw** QRIS ELITE untuk brand yang sama sudah menyertakan
   nomor transaksi per baris — hanya sisi **deposit**-nya yang belum.
2. **12 brand lain** dalam jaringan yang sama (di luar Vigor/TM Gaming) sudah
   menerima nomor tiket panel pada laporan deposit QRIS ELITE mereka.

Karena itu, kami mengajukan **dua alternatif** — cukup salah satu saja untuk
menyelesaikan masalah ini:

| # | Ditujukan ke | Permintaan |
|---|---|---|
| 1 | Panel Vigor/TM Gaming | Ekspor laporan **deposit** QRIS ELITE menyertakan kolom nomor transaksi/tiket per baris — persis seperti yang sudah ada pada ekspor **withdraw** QRIS mereka saat ini. |
| 2 | Vendor QRIS ELITE | Kolom **TICKET** pada laporan mutasi ELITE untuk brand Vigor/TM Gaming diisi dengan nomor tiket panel per transaksi — persis seperti yang sudah dilakukan ELITE untuk 12 brand lain di jaringan yang sama. |

Contoh konkret kolom yang kami maksud:

| Kolom | Isi saat ini (Vigor/TM Gaming, sisi deposit) | Isi yang diminta | Sudah berlaku di |
|---|---|---|---|
| Nomor transaksi (ekspor deposit QRIS panel) — pada ekspor withdraw kolom ini bernama `Transaction ID` | Tidak ada kolom ini sama sekali | Kolom `Transaction ID` (atau nama setara), berisi nomor transaksi/tiket unik per baris | Ekspor withdraw QRIS panel yang sama |
| TICKET (laporan mutasi ELITE) | Berisi kata "Done" untuk semua baris | Nomor tiket panel per transaksi | 12 brand lain di jaringan yang sama |

**Kalau permintaan ini dipenuhi:** waktu proses pencocokan kembali ke ±1,3
detik per hari, dan tingkat kecocokan kembali ke kisaran normal 95–97%. Ini
satu-satunya perbaikan yang memulihkan **akurasi**, bukan sekadar kecepatan —
selama nomor identitas ini tidak ada, sistem kami hanya bisa menebak
berdasarkan nama dan nominal, dan sebagian kecil transaksi akan selalu perlu
ditinjau manual karena tidak terpasangkan otomatis dengan pasti.

**Kalau belum bisa dipenuhi dalam waktu dekat:** kami akan tetap bisa
memprosesnya, hanya saja waktu prosesnya akan terus bertambah seiring
pertambahan volume transaksi brand ini, dan sebagian kecil transaksi perlu
ditinjau manual karena sistem tidak punya cara pasti membedakannya hanya dari
nama dan nominal.

Mohon informasinya, dan kami sangat terbuka untuk mendiskusikan mana dari dua
opsi di atas yang lebih mudah dilaksanakan di sisi Bapak/Ibu.

Terima kasih.

---

## B. Catatan internal (jangan ikut diteruskan)

**Sumber angka.** Seluruh angka pada bagian A dikutip dari `CLAUDE.md` bagian
*"Anomali matcher 25-08-2026"* di repo ini, diverifikasi ulang kata demi kata
terhadap isi berkas tersebut (bukan disalin buta dari brief tugas):

- Waktu proses: 1,3 dtk → 22–29 dtk sejak 25-08-2026, "masih berlangsung"
  (belum ada perbaikan data sampai dokumen ini ditulis).
- Mutu: 93,5% cocok vs 95–97% pada hari yang masih ber-UUID (sebelum
  perpindahan gateway).
- Volume kombinasi: 8.502 baris panel × bucket nominalnya = 4.969.497
  pasangan, dihitung penuh oleh jalur identitas berat (5,88 µs/pasangan →
  29,2 dtk teoretis, 29.219 ms terukur nyata).
- Sebaran brand: 12 brand Nexus (mxw, bwn, mul, wlg, ssn, ctr, lbs, ltn, stn,
  mtp, ksl, bbs) semuanya AMAN — tetap membawa tiket. Yang kehilangan kunci
  hanya tiga brand Vigor/TM Gaming: **g25** (40.132 baris), **w25** (3.137),
  **cah** (1.254). Nama-nama kode ini sengaja TIDAK dimasukkan ke naskah
  bagian A karena tidak bermakna bagi pihak luar dan termasuk detail internal.
- Pengujian nol-kecocokan: 400 ID vendor ELITE dicoba dicocokkan terhadap
  2.000 baris panel → 0 kecocokan (dicatat di `CLAUDE.md`, metodologi
  pengujian itu sendiri tidak diulang ulang dalam tugas ini — dikutip apa
  adanya).

**Verifikasi tambahan yang saya lakukan sendiri (bukan sekadar kutip
CLAUDE.md), lewat pembacaan kode sumber:**

- `sources/parsers/gateways.py`, fungsi `_qris_elite_tiket_nyata` —
  komentarnya secara eksplisit menyatakan: "Vigor/TM Gaming (W25
  24-08-2026): TICKET vendor selalu `Done` — bukan kunci transaksi... Nexus
  BBS tetap mengirim D… nyata → jalur ticket tak berubah." Ini menguatkan
  klaim "ELITE sudah mengisi TICKET untuk brand Nexus, tidak untuk
  Vigor/TMG" secara independen dari narasi CLAUDE.md.
- `sources/parsers/cor.py` — dua parser panel berbeda menangani QRIS untuk
  keluarga panel ini: `CORPanelQRISParser` (dipakai untuk ekspor yang PUNYA
  kolom `Transaction ID`, termasuk sisi withdraw) membaca
  `r.get("Transaction ID")` dan menjadikannya `reference`; sedangkan
  `CORPanelManualDepositParser` (marker `cor_panel_manual_dp`, dipakai untuk
  ekspor deposit manual/ELITE brand Vigor-TMG) **tidak pernah** membaca kolom
  itu — header yang didukungnya cuma `# | Date | Username | From Bank |
  Destination Bank | Amount | Status | By`, tanpa nomor transaksi sama
  sekali. Ini secara langsung mengonfirmasi klaim "ekspor withdraw QRIS
  mereka sudah punya kolom itu, tinggal disamakan ke sisi deposit" — bukan
  klaim yang hanya dikutip dari prosa, tapi terlihat di dua kelas parser yang
  berbeda.

**Yang TIDAK saya verifikasi ulang** (di luar cakupan tugas — tidak boleh
menjalankan profiler/suite penuh/menyentuh produksi): angka 5,88 µs/pasangan
dan 29.219 ms terukur nyata. Keduanya dikutip apa adanya dari `CLAUDE.md`
sebagai hasil pengukuran yang sudah dilakukan sebelumnya, tidak diulang di
sini.

**Pilihan kata di bagian A.** "Sistem rekonsiliasi", "proses pencocokan
otomatis", "nomor identitas transaksi" dipakai menggantikan istilah internal
(pass 0b, `_identity`, `reference`, `ticket_no`, UUID) — supaya isinya bisa
dipahami pihak luar tanpa perlu tahu arsitektur internal kami. Nama brand
"Vigor/TM Gaming" dan "QRIS ELITE" dipertahankan karena itu nama pihak yang
dituju sendiri, bukan detail internal.
