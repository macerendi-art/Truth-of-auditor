# Ringkasan Versi Aplikasi Truth of Auditor

## Ringkasan

Truth of Auditor adalah aplikasi rekonsiliasi keuangan yang mencocokkan catatan
kredit perusahaan dengan uang sungguhan di bank dan gateway pembayaran.
Aplikasi mulai dibangun **1 Juli 2026** dan resmi dipakai tim auditor
menggantikan cara kerja manual sejak **7 Juli 2026**.

Sampai 25 Juli 2026, aplikasi telah melewati **16 rilis**:

| Jenis rilis | Jumlah | Artinya |
| --- | ---: | --- |
| Rilis besar | 1 | Cara kerja berubah mendasar |
| Rilis fitur | 10 | Ada kemampuan baru |
| Rilis perbaikan | 1 | Murni membetulkan, tanpa fitur baru |
| Pra-rilis | 4 | Tahap pembangunan sebelum dipakai produksi |

Versi yang berjalan saat ini adalah **v1.10.0**. Nomor versi kini tampil di
dalam aplikasi — di menu samping, di halaman masuk, dan pada setiap berkas
Excel yang diekspor — sehingga setiap laporan kendala dari tim bisa dipetakan
ke rilis yang tepat.

Sebelumnya aplikasi tidak punya penomoran sama sekali. Seluruh riwayat disusun
ulang dari catatan perubahan kode dan sudah diperiksa: **281 dari 281**
perubahan tercakup habis oleh 15 rilis bernomor, tanpa celah dan tanpa
tumpang tindih. Peta versi ini bisa diperiksa ulang kapan saja terhadap
riwayat kode.

# Cara Membaca Nomor Versi

Nomor versi ditulis dalam tiga angka, misalnya **1.10.0**. Setiap angka punya
arti, dan angka mana yang naik ditentukan oleh besarnya perubahan — bukan oleh
tanggal atau banyaknya pekerjaan.

| Angka | Naik bila | Contoh |
| --- | --- | --- |
| Angka pertama — **rilis besar** | Cara kerja aplikasi berubah mendasar, atau statusnya bagi pengguna berubah | 1.0.0: aplikasi resmi menggantikan rekonsiliasi manual |
| Angka kedua — **rilis fitur** | Ada kemampuan baru yang bisa diumumkan: halaman baru, bank baru yang didukung, aturan pencocokan baru | 1.5.0: aplikasi bisa membaca mutasi BNI |
| Angka ketiga — **rilis perbaikan** | Isinya murni membetulkan perilaku yang memang sudah dijanjikan | 1.2.1: penarikan e-wallet BRI yang tadinya gagal cocok |

Nomor yang diawali **0** (0.1.0 sampai 0.4.0) adalah tahap pra-rilis: aplikasi
masih dibangun dan diuji, belum menjadi sandaran kerja harian tim.

Karena pemasangan ke server dilakukan terkendali dan tidak setiap perubahan
langsung tayang, satu nomor rilis mewakili **satu paket perubahan yang
dinyatakan siap dipakai**, bukan satu perubahan kecil.

# Daftar Rilis

| Versi | Tanggal | Nama | Jenis |
| --- | --- | --- | --- |
| 1.10.0 | 25 Juli 2026 | Transparansi Versi | Rilis fitur |
| 1.9.0 | 23 Juli 2026 | Kode Unik & Kunci Wilayah | Rilis fitur |
| 1.8.0 | 21 Juli 2026 | Kedalaman Analisis | Rilis fitur |
| 1.7.0 | 20 Juli 2026 | Rekonsiliasi Bonus | Rilis fitur |
| 1.6.0 | 18 Juli 2026 | Koreksi FR, Hutang/Piutang & Rincian Biaya | Rilis fitur |
| 1.5.0 | 15 Juli 2026 | Mutasi BNI | Rilis fitur |
| 1.4.0 | 13 Juli 2026 | Percepatan | Rilis fitur |
| 1.3.0 | 12 Juli 2026 | Laporan FR/Bracket | Rilis fitur |
| 1.2.1 | 11 Juli 2026 | Perbaikan Penarikan E-wallet BRI | Rilis perbaikan |
| 1.2.0 | 10 Juli 2026 | Keamanan Akun & Jejak Audit | Rilis fitur |
| 1.1.0 | 8 Juli 2026 | Ekspor Massal & Telusur Mutasi | Rilis fitur |
| **1.0.0** | **7 Juli 2026** | **Rilis Produksi Pertama** | **Rilis besar** |
| 0.4.0 | 5 Juli 2026 | Kokpit Auditor | Pra-rilis |
| 0.3.0 | 4 Juli 2026 | Rekonsiliasi Harian | Pra-rilis |
| 0.2.0 | 2 Juli 2026 | Multi-Brand & Hak Akses | Pra-rilis |
| 0.1.0 | 1 Juli 2026 | Fondasi Rekonsiliasi | Pra-rilis |

# Tonggak Utama

## v1.0.0 — Rilis Produksi Pertama (7 Juli 2026)

Ini satu-satunya rilis besar sejauh ini, dan alasannya bukan jumlah fiturnya
melainkan perubahan statusnya: sejak tanggal itu aplikasi menjadi sistem yang
dipakai tim auditor untuk pekerjaan sungguhan.

Bersamaan dengan itu ditetapkan aturan pencocokan yang sampai hari ini menjadi
pegangan: **pasangan hanya boleh terbentuk bila ada bukti identitas** — nomor
tiket, nomor referensi, nomor HP, nomor rekening, nama pengguna, atau nama
orang. Nominal dan tanggal yang sama saja tidak cukup. Sebelum aturan ini
ditegakkan, penarikan milik satu pemain bisa nyasar ke mutasi bank atas nama
orang lain hanya karena nominalnya kebetulan sama.

Rilis ini juga membawa tiga brand baru dan pencocokan dengan nomor referensi
QRIS yang bersifat pasti.

## Sesudahnya: pelebaran cakupan, bukan perombakan

Sepuluh rilis fitur berikutnya semuanya memperluas kemampuan tanpa mengubah
aturan dasar. Pola pekerjaannya terbagi tiga:

**Menjangkau lebih banyak sumber uang.** Setiap bank dan gateway punya format
laporan sendiri, dan setiap format yang belum didukung berarti transaksinya
menumpuk sebagai "belum ada uang". Rilis 1.2.0 sampai 1.6.0 menambahkan QRIS
UNO, gateway RPay, RafflesPay (dua varian), dan mutasi BNI dari e-statement
PDF. Hasil ujinya terukur: QRIS UNO cocok 278 dari 278 baris, RPay 2.048 dari
2.058 transaksi.

**Menambah laporan yang diminta tim.** Halaman Breakdown FR/Bracket, Ringkasan
Bulanan, Rincian Rekening, Settlement Tertunda, Hutang/Piutang, Rincian Biaya,
dan Rekonsiliasi Bonus. Semuanya menghitung dari data yang sudah ada, sehingga
langsung berlaku untuk data lama tanpa perlu impor ulang.

**Membetulkan yang keliru.** Beberapa perbaikan berdampak besar meski tidak
terdengar seperti fitur. Perhitungan saldo yang tidak lagi bergantung urutan
baris membuat 21 dari 21 rekening selisih kontrolnya menjadi nol dan
menjelaskan selisih Rp5,95 juta yang sebelumnya menggantung. Pengenalan biaya
administrasi bank menghapus 182 baris palsu dari daftar pemeriksaan pada satu
brand dalam sepuluh hari.

## v1.4.0 — Percepatan (13 Juli 2026)

Layak disebut terpisah karena dampaknya langsung terasa pengguna. Halaman
Kelola Toko turun dari **29,8 detik menjadi 0,1 detik**, halaman Impor Data
dari **10,8 detik menjadi 0,01 detik**. Angka yang ditampilkan tetap sama
persis — hanya cara menghitungnya yang diperbaiki. Kapasitas server juga
dinaikkan menjadi delapan jalur paralel, sehingga rekonsiliasi besar satu
orang tidak lagi membuat pengguna lain menunggu.

# Bukti Mutu

Angka-angka berikut berasal dari pengukuran, bukan perkiraan.

| Ukuran | Nilai |
| --- | ---: |
| Pengujian otomatis yang dijalankan tiap perubahan | 1.038 |
| Format berkas sumber yang didukung | 20 |
| Perubahan kode sejak awal | 281 |
| Rilis dalam 25 hari | 16 |

**Validasi independen (8 Juli 2026).** Hasil rekonsiliasi versi 1.0.0 diperiksa
ulang di luar aplikasi memakai data nyata dua brand selama tiga hari. Setiap
pasangan yang dinyatakan cocok dibuktikan ulang satu per satu dengan
perhitungan terpisah yang tidak memakai kode aplikasi sama sekali.

Hasilnya: **53.949 pasangan diperiksa, nol pelanggaran aturan.** Tidak ada satu
pun pasangan yang gagal dibuktikan, tidak ada pasangan kuat yang terlewat oleh
mesin, dan total nominal harian klop sampai satuan rupiah pada enam dari enam
pemeriksaan.

Baris yang ditandai "Tidak Cocok" pun terbukti bukan kesalahan mesin —
sebagiannya justru temuan audit yang memang perlu ditindaklanjuti manusia.

# Posisi Sekarang

Aplikasi berada di **v1.10.0**, berjalan di produksi, dan dipakai untuk
rekonsiliasi harian lintas brand. Seluruh riwayat rekonsiliasi tersimpan utuh
dan bisa ditelusuri.

Mulai rilis ini, setiap berkas Excel yang diekspor mencantumkan versi aplikasi
yang membuatnya. Ini penting untuk penelusuran: aturan pencocokan berkembang
antar versi, sehingga bila suatu hari hasil lama dipertanyakan, akan langsung
terlihat versi mana yang menghasilkannya.

## Kapan rilis berikutnya pantas disebut 2.0.0

Agar penomoran ini tetap punya arti dan tidak digelembungkan, syaratnya
ditetapkan di muka. Sebuah rilis baru pantas disebut rilis besar berikutnya
bila memenuhi minimal satu dari:

1. **Aturan pencocokan inti diganti** sedemikian rupa sehingga laporan lama
   akan berbeda hasilnya bila dijalankan ulang.
2. **Alur kerja berubah mendasar** — misalnya keputusan auditor harus melewati
   persetujuan supervisor, atau konsep laporan harian dirombak.
3. **Susunan berkas keluaran berubah**, sehingga template kerja yang sudah
   dipakai penerima laporan harus ikut disesuaikan.
4. **Perpindahan data yang tidak bisa dimundurkan.**

Sebaliknya, menambah bank atau gateway baru, menambah halaman laporan, atau
memperketat keamanan akses tetap dihitung sebagai rilis fitur — sebanyak apa
pun jumlahnya.

*Dokumen ini disusun 25 Juli 2026. Daftar rilis yang sama bisa dibuka kapan
saja langsung di dalam aplikasi melalui menu Versi di bagian bawah menu
samping.*
