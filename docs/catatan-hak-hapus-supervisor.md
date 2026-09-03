# Supervisor Kini Bisa Menghapus Seperti Admin

**Versi 1.24.0 · 2 September 2026 · Untuk supervisor & admin**

Supervisor tidak perlu lagi menunggu admin untuk membereskan berkas salah unggah
atau batch yang perlu diulang. Ada satu hal yang wajib diperhatikan — di bagian
"Yang wajib dibaca" di bawah.

---

## Siapa boleh menghapus apa

| Tindakan | Auditor | Supervisor | Admin |
|---|:---:|:---:|:---:|
| Hapus berkas unggahan **(baru)** | — | Ya | Ya |
| Hapus banyak berkas sekaligus **(baru)** | — | Ya | Ya |
| Hapus batch mana pun, bukan cuma yang terakhir **(baru)** | — | Ya | Ya |
| Hapus batch terakhir | — | Ya | Ya |
| Hapus koreksi, rekap, hutang/piutang | Ya | Ya | Ya |
| Kelola toko, pengguna, daftar IP | — | — | Ya |
| Cari nama berkas di halaman Upload | — | — | Ya |

---

## Menghapus berkas unggahan

1. Buka **Upload** → tabel **Riwayat Upload**.
2. Satu berkas: klik tombol hapus di barisnya.
   Beberapa berkas: centang kolom kiri, lalu **Hapus terpilih**.
3. Konfirmasi. Semua transaksi dari berkas itu ikut terhapus.

**Kalau berkasnya menolak dihapus.** Berkas bertanda `🔒 Dipakai hasil
rekonsiliasi` tidak bisa dihapus — kotak centangnya pun tidak muncul. Layar
menyebut batch nomor berapa yang memakainya; hapus batch itu dulu. Aturan ini
berlaku untuk admin juga, jadi bukan soal peran Anda.

---

## Menghapus batch rekonsiliasi

1. Buka **Rekonsiliasi** → tabel **Riwayat Batch**.
2. Satu batch: tombol hapus di barisnya (atau dari halaman detail batch).
   Beberapa batch: centang, lalu **Hapus terpilih**.
3. Konfirmasi. Transaksinya **tidak** ikut terhapus — hanya hasil pencocokannya,
   dan datanya kembali siap dicocokkan ulang.

---

## ⚠️ Yang wajib dibaca

Hasil satu hari dibangun di atas hari sebelumnya. Baris yang belum ketemu
pasangannya diteruskan, lalu dicocokkan dengan uang yang masuk esok harinya.

Kalau Anda menghapus batch **di tengah** — misalnya tanggal 20, sementara 21–23
sudah ada — baris tanggal 20 kembali menganggur, padahal pasangan uangnya sudah
terpakai di batch sesudahnya. Kalau tanggal 20 dijalankan ulang, **angkanya bisa
berbeda dari semula, dan tidak ada satu pun pesan kesalahan yang muncul.**

Sistem tidak lagi menghalangi Anda melakukan ini. Menjaganya sekarang jadi
tanggung jawab Anda.

> **Cara amannya:** hapus dari tanggal terbaru, mundur ke belakang. Perlu
> menghapus tanggal 20 sementara 21–23 sudah ada? Hapus 23, lalu 22, lalu 21,
> baru 20 — kemudian jalankan ulang semuanya berurutan.

**Keputusan review manual ikut hilang.** Kalau batch yang dihapus berisi baris
yang pernah Anda tandai sendiri (Cocok / Perlu Tinjau / Tidak Cocok), keputusan
itu **hilang permanen** dan tidak bisa dikembalikan. Dulu sistem menolak
menghapus batch semacam ini; sekarang tidak lagi. Yang tersisa hanya catatan
*berapa banyak* keputusan yang hilang — bukan isinya.

---

## Semuanya tercatat

Setiap penghapusan masuk ke **Log Aktivitas** dan tidak bisa dihapus dari sana:

- Siapa yang menghapus, dan kapan.
- Batch nomor berapa, tanggal rekonsiliasinya, ringkasan hasilnya
  (Cocok / Tinjau / Tidak Cocok).
- Berapa keputusan review manual yang ikut hilang.
- Untuk berkas: nama berkas dan jumlah transaksi yang ikut terhapus.

Catatan ini tetap ada walau akun penggunanya kelak dihapus. Log Aktivitas hanya
bisa dibuka admin.

---

## Kalau ragu

Penghapusan tidak bisa dibatalkan, dan tidak ada tombol "kembalikan". Kalau Anda
tidak yakin sebuah batch masih dipakai atau tidak, tanyakan dulu — mengulang
rekonsiliasi satu hari jauh lebih murah daripada menemukan angka yang bergeser
tanpa jejak beberapa minggu kemudian.

---

*Perubahan ini dibuat atas permintaan tim. Ada yang membingungkan atau tidak
sesuai dengan yang Anda lihat di layar? Sampaikan supaya bisa diperbaiki.*
