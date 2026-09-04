# Keputusan: `row_hash` QRIS Flyer bocor lewat format desimal — 2026-09-04

Dokumen keputusan untuk pemilik data. **Ini bukan tugas memperbaiki** — tidak
ada kode yang berubah di sini. Tujuannya: menjelaskan cacatnya dengan jujur,
menjelaskan kenapa perbaikan yang tampak jelas justru berbahaya, dan mengajukan
satu arah yang aman beserta rekomendasi.

Sumber: `CLAUDE.md` bagian *"KNOWN DEFECT, not yet fixed"* (di bawah entri
`QRISFlyerParser`), diverifikasi ulang terhadap kode di
`sources/parsers/gateways.py` (`QRFlyerParser`) dan `sources/parsers/base.py`
(fungsi `row_hash`).

## Ringkasan untuk yang buru-buru

Dua unggahan berkas QRIS Flyer yang **isinya sama persis** tapi **format
angkanya berbeda** (satu berkas menulis nominal sebagai angka `150000`, berkas
lain menulisnya sebagai teks `"150000.00"`) menghasilkan dua `row_hash`
berbeda — sehingga sistem gagal mengenalinya sebagai baris yang sama dan
menyimpannya dua kali. Ini sudah terjadi sekali di produksi (BSW, 12-08-2026,
1.366 baris ganda) dan bisa terjadi lagi kapan saja file lama dari toko mana
pun diunggah ulang dalam bentuk vendor yang berbeda. **Jangan diperbaiki
dengan mengganti resep hash** — semua baris yang sudah ada di produksi memakai
resep yang sekarang, jadi resep baru membuat unggah ulang berkas LAMA mana pun
(bukan hanya kasus BSW) mengganda secara massal. Rekomendasi: tambahkan
pemeriksaan duplikat KEDUA yang sifatnya menambah, bukan mengganti — dijelaskan
di bagian Opsi.

## Cacatnya, dalam bahasa yang bisa dipahami pemilik

`row_hash` untuk setiap baris QRIS Flyer dihitung dari tiga nilai: nomor tiket,
nomor referensi, dan nominal — lalu digabung jadi satu teks dan di-hash. Vendor
QRIS Flyer sudah empat kali mengganti bentuk berkas ekspornya, dan salah satu
bentuk (yang keempat) menulis nominal sebagai **teks** ("150000.00"), sedangkan
bentuk pertama menulis nominal sebagai **angka** (150000). Keduanya
menghasilkan Rp150.000 yang sama persis — tapi karena hash dihitung dari teks
yang ditulis apa adanya, dua penulisan itu jadi dua hash berbeda:

- Bentuk 1: nominal masuk sebagai angka Excel → tersimpan sebagai teks
  `"150000"`.
- Bentuk 4: nominal masuk sebagai teks `"150000.00"` → tersimpan apa adanya.

Ini bukan salah baca nominal (nilainya benar di kedua kasus) — murni soal
**bagaimana angka itu ditulis** sebelum dihitung hash-nya.

**Bukti di produksi.** BSW mengunggah data 12 Agustus 2026 dua kali, berselang
satu menit (17:59 lalu 18:00), masing-masing dalam bentuk berkas yang berbeda.
Hasilnya 1.366 baris gateway ganda — bukan diabaikan sebagai unggah ulang
seperti seharusnya. Baris-baris ganda ini sudah ditandai `is_duplicate=True`
(flag yang sudah dihormati semua kueri mesin/laporan), tapi itu terjadi
belakangan sebagai perbaikan titik, bukan karena resep hash-nya diperbaiki.

## Kenapa jangan diganti begitu saja

Godaannya jelas: kalau nominal dinormalisasi ke format yang konsisten sebelum
dihitung hash-nya (persis seperti yang sudah dilakukan untuk namespace
`qris_elite` dan `cor_panel_bonus`, keduanya memakai
`format(d.normalize(), "f")`), masalah lintas-bentuk ini hilang untuk
seterusnya. **Tapi itu memutus jaminan yang sedang menjaga jutaan baris QRIS
Flyer yang SUDAH ada di produksi.**

Setiap baris yang sudah tersimpan membawa `row_hash` yang dihitung dengan
resep SEKARANG. Kalau resepnya diganti, maka baris QRIS Flyer LAMA mana pun —
bukan cuma kasus BSW — yang filenya diunggah ulang (rolling export, ekspor
ulang periode yang sama, dsb — pola yang sudah terbukti umum di data bank/
gateway lain di sistem ini) akan dihitung ulang dengan resep baru, menghasilkan
hash yang TIDAK cocok dengan hash lama yang tersimpan di baris yang sudah ada.
Pemeriksaan keunikan di database (`source_type + toko + row_hash`) tidak akan
mengenalinya sebagai duplikat — baris itu masuk lagi sebagai baris "baru", dan
setiap baris QRIS Flyer yang pernah ada berpotensi mengganda, bukan hanya
1.366 baris BSW.

Konsekuensi ini SUDAH pernah menjadi pelajaran di modul lain: catatan pada
`manage.py perbaiki_gateway_tanpa_tanggal` (yang menghitung ulang `row_hash`
untuk baris yang tanggalnya dipulihkan) secara eksplisit menghitung ulang hash
dengan resep yang IDENTIK dengan parser, dari nilai `raw` lewat ekspresi yang
sama — persis supaya hasilnya cocok dengan hash yang akan dihasilkan unggahan
berikutnya. Itu bukti bahwa tim yang membangun sistem ini sudah sadar penuh:
mengubah cara hash dihitung, walau demi kebenaran teoretis, berbahaya kalau
baris lama tidak ikut disesuaikan.

## Arah yang aman: pemeriksaan duplikat KEDUA, bersifat aditif

Yang aman bukan mengganti resep `row_hash`, melainkan **menambah** satu
pemeriksaan tambahan saat ingest — dijalankan SETELAH pemeriksaan hash yang
sudah ada, tanpa mengubah nilai hash yang tersimpan pada satu pun baris lama.

**Kenapa itu tidak boleh sekadar mencocokkan nomor tiket.** Godaan paling
sederhana adalah: "kalau nomor tiketnya sama, itu baris yang sama." `CLAUDE.md`
memperingatkan justru terhadap ini: pemeriksaan kedua "tidak boleh berupa
pencocokan tiket polos: BBS RafflesPay punya tiket yang memang berulang secara
sah". Saya menelusuri kode sumber parser yang dirujuk (`rpay_xlsx`, gateway
RafflesPay varian XLSX brand BBS) untuk memverifikasi klaim ini secara
langsung, bukan sekadar mengutip — dan menemukan sesuatu yang perlu
dilaporkan jujur, bukan diselesaikan sepihak: catatan di kode itu sendiri
menyebut **kolom RRN** (nomor referensi vendor, disimpan hanya di `raw`) yang
"ada duplikat nyata (9 dari 1.233, sampel BBS 16-07-2026)" — sementara
`Ticket Number` pada parser yang SAMA dipakai sebagai kunci join utama ke
panel, sesuatu yang biasanya berarti ia dianggap unik. Resep `row_hash` untuk
`rpay_xlsx` sendiri menggabungkan `[ticket, rrn]`, bukan `ticket` saja — dan
parser `rpay_wd` yang berdekatan punya catatan sejenis ("UUID … unik per
percobaan disbursement; + ticket sebagai cadangan"), yang mengisyaratkan
`ticket` sendirian tidak sepenuhnya dipercaya sebagai kunci tunggal. Saya
**tidak bisa memastikan** dari kode saja apakah "tiket yang berulang" pada
`CLAUDE.md` merujuk pada `Ticket Number` itu sendiri atau pada RRN yang
menyertainya — keduanya dokumentasi sumbernya bisa dibaca kedua arah, dan
memastikannya butuh sampel berkas RafflesPay asli (di luar cakupan tugas ini).
**Yang tidak berubah pada rekomendasi apa pun dari dua pembacaan ini:** kolom
identitas vendor mana pun pada sistem ini — nomor tiket, RRN, atau keduanya —
sudah terbukti bisa berulang secara sah pada baris yang berbeda. Pemeriksaan
kedua yang aman untuk QRIS Flyer harus menggabungkan beberapa bidang, bukan
mengandalkan satu kolom identitas tunggal.

**Rancangan yang saya usulkan untuk dikalibrasi (bukan kode final):**
setelah baris baru lolos pemeriksaan `row_hash`, jalankan satu pemeriksaan
tambahan yang membandingkan bidang-bidang yang SUDAH tersimpan sebagai kolom
database bertipe (bukan teks mentah `raw`): `ticket_no`, `reference`, `amount`,
pada baris QRIS Flyer lain milik toko yang sama. Ini penting: `amount` di
database adalah `DecimalField(decimal_places=2)` — begitu tersimpan, `150000`
dan `150000.00` menjadi nilai yang SAMA PERSIS secara database, terlepas dari
teks mentah yang dulu menghasilkannya. Artinya cacat format-desimal yang
membocorkan `row_hash` **tidak** ikut membocorkan pemeriksaan kedua ini, karena
pemeriksaan kedua dilakukan atas nilai yang sudah dinormalisasi presisi oleh
database, bukan atas teks mentah. Kalau ditemukan baris lain dengan
`ticket_no`+`reference`+`amount` sama tapi `row_hash` berbeda, baris baru
ditandai `is_duplicate=True` — bukan didrop diam-diam, supaya jejak forensiknya
tetap ada (pola yang sama seperti perbaikan `is_duplicate` yang sudah
digunakan untuk kasus BSW).

Cakupan pemeriksaan sebaiknya dipersempit ke baris QRIS Flyer saja (misalnya
lewat `description` yang diawali `"QRFLYER "` — verifikasi saya di kode
menunjukkan awalan ini unik untuk parser ini, tidak dipakai parser gateway lain
mana pun), bukan seluruh `source_type=gateway` — supaya nomor tiket vendor lain
yang kebetulan mirip tidak ikut salah tertangkap. Pola "prefilter longgar +
keputusan akhir presisi" ini sudah dipakai di tempat lain pada sistem ini
(`web/biaya.py`, `PRAFILTER_FEE`), jadi bukan pendekatan asing.

## Opsi, biaya, dan risiko

| Opsi | Biaya | Risiko |
|---|---|---|
| **A. Ganti resep `row_hash`** (normalisasi desimal sebelum hash, seperti `qris_elite`) | Kecil untuk baris baru | **Besar dan tersembunyi**: unggah ulang berkas QRIS Flyer LAMA mana pun mengganda massal (bukan cuma kasus BSW) — angka uang di seluruh namespace ini bisa berubah tanpa satu pun error muncul |
| **B. Pemeriksaan duplikat kedua yang aditif** (diuraikan di atas) | Sedang: satu kueri tambahan per baris QRIS Flyer saat ingest (dipersempit lewat prefilter, murah); perlu kalibrasi terhadap data BSW nyata sebelum dilepas | Kecil, terkendali: pemeriksaan hanya MENANDAI (`is_duplicate=True`), tidak pernah mengubah/menghapus baris yang sudah ada; kalau kunci gabungannya salah rancang, akibat terburuknya adalah baris yang seharusnya dianggap unik ikut tertandai — bisa ditinjau lewat flag itu sendiri, bukan hilang |
| **C. Biarkan (status quo)** | Nol pekerjaan | Berkelanjutan: kejadian BSW terbukti bisa terulang kapan pun kombinasi bentuk-berkas yang sama terjadi lagi di toko mana pun; setiap kali terjadi, uang gateway tercatat dobel sampai ada yang menyadari dan menandai manual |

## Rekomendasi

**Opsi B** — tambahkan pemeriksaan duplikat kedua yang aditif, dengan syarat:

1. **Jangan sentuh `row_hash` yang tersimpan** pada satu pun baris lama —
   pemeriksaan baru murni menambah, dijalankan setelah pemeriksaan hash yang
   sudah ada.
2. Kunci pembanding memakai kolom database yang sudah ternormalisasi
   (`ticket_no`, `reference`, `amount`), bukan teks `raw` — supaya cacat format
   yang sama tidak ikut membocorkan pemeriksaan kedua ini.
3. **Bukan** pencocokan tiket tunggal — gabungkan minimal tiga bidang, karena
   sistem ini sendiri sudah punya bukti (RafflesPay/`rpay_xlsx`) bahwa satu
   bidang identitas vendor bisa berulang secara sah.
4. Kalibrasi ulang terhadap data nyata BSW 12-08-2026 (atau fixture yang
   merekonstruksinya) sebelum dilepas — buktikan pemeriksaan baru menangkap
   1.366 baris itu TANPA menandai baris QRIS Flyer lain yang sah sebagai
   duplikat palsu.
5. Hasil akhirnya baris ditandai (`is_duplicate=True`), tidak dihapus —
   konsisten dengan bagaimana kasus BSW sudah ditangani, dan menjaga jejak
   forensik kalau kelak perlu ditelusuri ulang.

Opsi A (ganti resep) sebaiknya tidak dilakukan sama sekali kecuali ada rencana
migrasi ulang seluruh baris QRIS Flyer yang sudah ada — pekerjaan yang jauh
lebih besar dan berisiko daripada nilai yang didapat.
