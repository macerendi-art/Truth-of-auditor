# Pesan untuk End User — v1.13.0

Naskah siap-kirim untuk tiga fitur yang diminta end user, plus catatan cadangan
untuk pertanyaan susulan. Bagian A boleh disalin apa adanya; bagian B untuk
pegangan internal.

---

## A. Naskah siap kirim

### 1. Filter bank di tab "Perlu Ditinjau" dan "Tidak Cocok"

Pada hasil **Panel ↔ Bracket** untuk toko berpanel Vigor/TM Gaming, tab **"Perlu
Ditinjau"** dan **"Tidak Cocok"** sekarang punya filter bank — sebelumnya baris
filternya hilang sama sekali.

Penyebabnya dulu: sebagian transaksi (terutama QRIS) memang tidak membawa nama
bank sama sekali, sehingga daftar pilihannya kosong dan filternya ikut
tersembunyi. Sekarang transaksi seperti itu dikumpulkan menjadi satu pilihan
bernama **"(Tanpa Bank)"**, jadi bisa disaring seperti bank lain.

Ikutannya: mengurutkan kolom atau berpindah ke tab **Deposit / Withdraw** tidak
lagi membuang filter bank yang sedang dipakai.

### 2. Transaksi QRIS panel Gacor25 kini berlabel QRIS

Transaksi QRIS pada panel Gacor25 dulu tampil kosong pada kolom Bank Title.
Sekarang berlabel **QRIS**, sehingga:

- kolom Bank Title terisi,
- kartu **"Metode Pembayaran"** di dashboard tidak lagi menghitungnya sebagai
  "Lainnya",
- pilihan filter banknya jadi berarti.

Untuk transaksi lama yang sudah terlanjur masuk, ada perintah pengisian ulang
yang dijalankan terpisah.

### 3. File lama otomatis ditandai "Ketiban"

Kalau tarikan bank yang diupload ternyata kepotong, tinggal upload ulang file
yang lebih lengkap **dengan nama file yang sama**. Sistem akan otomatis menandai
file lama dengan label **"Ketiban"** di halaman Riwayat Upload, supaya kelihatan
mana yang sudah tidak terpakai.

**Cara sistem memastikannya bukan asal tebak.** Bukan cuma dilihat dari nama
filenya. Sistem mencocokkan **seluruh isi** file lama baris per baris — kalau
semua barisnya memang sudah ada di dalam file baru, barulah ditandai. Kalau ada
satu saja baris di file lama yang tidak ada di file baru, sistem **tidak** akan
menandai, karena berarti file baru bukan versi yang lebih lengkap.

**Tidak ada data yang dihapus.** File lama tetap tersimpan utuh beserta seluruh
transaksinya sebagai jejak audit, dan tetap bisa dibuka di halaman Mutasi Bank
(ditandai " · ketiban" di daftar filenya). Label ini murni penanda tampilan —
tidak mengubah angka rekonsiliasi, tidak mengubah hasil pencocokan, tidak
mengubah total apa pun.

**Upload ulang tidak membuat data menumpuk.** Ini sering ditanyakan, jadi perlu
ditegaskan:

- **Baris yang sudah pernah masuk tidak dibuat ulang.** File utuh 700 baris yang
  menimpa file terpotong 660 baris hanya menambahkan **40 baris baru** — bukan
  700. Perlindungan ini sudah berjalan sejak dulu; justru itulah yang membuat
  upload ulang aman sejak awal.
- **File aslinya tidak ikut disimpan.** Berkas yang diupload dipakai sekali untuk
  dibaca isinya, lalu dihapus. Yang tersimpan hanya barisnya.
- **Label "Ketiban" sendiri hanya satu penanda kecil** pada catatan file yang
  memang sudah ada — bukan salinan file, bukan salinan data.

**Yang tidak akan ditandai:**

- Nama file berbeda
- File barunya tidak lebih lengkap (ada baris lama yang hilang)
- File yang benar-benar sama persis (tidak ada baris baru sama sekali)
- File lama yang sudah terlalu jauh ke belakang

**Kalau ternyata salah tandai:** hapus file penggantinya, maka label "Ketiban" di
file lama akan hilang sendiri.

### 4. Kotak pencarian di pemilih Toko

Pemilih **Toko** di bilah atas sekarang punya kotak pencarian. Ketik "25" dan
daftar 16 toko langsung menyusut ke yang cocok, lengkap dengan navigasi papan
ketik (panah atas/bawah, Enter untuk memilih, Esc untuk menutup). Tidak perlu
lagi menggulir daftar panjang berisi kode-kode yang mirip.

---

## B. Catatan cadangan (pegangan internal, jangan dikirim)

**"Kalau aku upload file mutasi harian yang isinya kumulatif, file kemarin ikut
ketandai dong?"**
Ya, kalau namanya persis sama — dan itu perilaku yang jujur, karena isi file
kemarin memang seluruhnya ada di file hari ini. Solusinya: beri nama berbeda per
hari. Tanggal di nama file sudah cukup; sistem sengaja tidak menganggap
`MUTASI_27JUN26` dan `MUTASI_28JUN26` sebagai nama yang sama.

**"Berapa lama batas waktunya?"**
14 hari. Ini batas teknis supaya sistem tidak menyisir file terlalu jauh ke
belakang, bukan aturan bisnis — bisa disetel kalau dirasa kurang atau kelebihan.

**"Apa berlaku untuk file panel dan FR juga?"**
Ya, semua jenis file, bukan cuma mutasi bank. Bisa dibatasi ke bank/gateway saja
kalau ternyata membingungkan di lapangan.

**Sebutkan lebih dulu sebelum ditemukan sendiri:** labelnya lengket — satu-satunya
cara mencabut adalah menghapus file penggantinya. Kalau di lapangan sering salah
tandai, tombol "batalkan tanda" bisa ditambahkan; sengaja belum dibuat supaya
tidak menambah tombol yang mungkin tak pernah dipakai.

**Angka pendukung** (diukur dari basis data 108,8 MB berisi 71.584 transaksi):
seluruh metadata upload hanya **0,05 MB** atau **0,06%** dari total; tidak satu
pun upload menyimpan berkas fisik; yang memang tumbuh adalah tabel transaksi
(63% dari basis data), dan itu tidak berubah karena fitur ini.
