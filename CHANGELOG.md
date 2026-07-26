# Catatan Perubahan — Truth of Auditor

> Berkas ini **dibuat otomatis** dari `core/version.py`. Jangan diedit langsung:
> ubah daftar `RILIS` di sana lalu jalankan `python manage.py changelog`.

Versi berjalan: **v1.11.0** · 17 rilis (1 besar, 11 fitur, 1 perbaikan, 4 pra-rilis).

Penomoran MAYOR.MINOR.PATCH: **MAYOR** bila cara kerja aplikasi berubah mendasar,
**MINOR** bila ada kemampuan baru, **PATCH** bila isinya murni perbaikan.
Versi 0.x = tahap pra-rilis, sebelum aplikasi dipakai produksi.

## v1.11.0 — Tiga Panel & Rekap Bulanan
*Rilis fitur · 26 Juli 2026*

- Rekonsiliasi Panel↔Bracket kini berjalan untuk brand berpanel Vigor/TM Gaming yang ekspornya tanpa nomor tiket — baris dicocokkan lewat username + nominal. Uji dengan data nyata COR: 10.069 dari 10.072 baris (99,97%) cocok otomatis. Halaman hasil menampilkan mode pencocokan yang dipakai, jadi selalu jelas aturan mana yang bekerja.
- Halaman baru Rekap Bulanan meniru rekap Excel yang selama ini disusun manual: empat seksi (Net Profit, Sisa Dana Member, Total Dana Lebih Web, Selisih beserta penyebabnya), angka otomatis dihitung dari data harian, dan isian manual bisa menimpa angka otomatis dengan jejak siapa-dan-kapan.
- Mode “Semua Toko” untuk admin: dashboard gabungan seluruh toko sekali pandang — kalender status, ringkasan Panel/Bracket/Metode gabungan, dan tabel per toko — plus filter ceklis beberapa toko sekaligus di halaman Hutang/Piutang.
- Gembok alamat IP untuk akun auditor & supervisor: hanya alamat internet yang terdaftar yang bisa masuk; admin tidak pernah terkunci; selama daftar kosong fitur ini tidur. Dikelola dari halaman admin sendiri dan setiap penolakan tercatat di jejak audit.
- Penarikan berlabel bank “OTH” pada brand Vigor/TM kini menampilkan bank aslinya (dibaca dari teks transaksi), dan nama penerima transfer BRI yang tadinya kosong kini terisi — berlaku juga untuk data yang sudah terlanjur diimpor, tanpa unggah ulang.
- Setiap toko kini dikelompokkan menurut panelnya (Nexus / Vigor / TM Gaming) di pemilih toko, dan jenis panel wajib dipilih saat membuat toko baru.

## v1.10.0 — Transparansi Versi
*Rilis fitur · 25 Juli 2026*

- Aplikasi kini punya nomor versi resmi yang tampil di menu samping dan halaman masuk, sehingga jelas versi mana yang sedang dipakai saat melaporkan kendala.
- Halaman Riwayat Versi baru: seluruh rilis sejak awal beserta isinya, bisa dibuka siapa saja yang punya akses aplikasi.
- Catatan perubahan resmi (CHANGELOG) dibuat otomatis dari satu sumber data, dijaga pengujian agar tidak pernah melenceng dari kenyataan.
- Setiap berkas Excel hasil ekspor mencantumkan versi aplikasi yang membuatnya — penting bila hasil lama perlu ditelusuri ulang.

> Riwayat 0.1.0–1.9.0 di bawah ini disusun retroaktif dari catatan perubahan kode.

## v1.9.0 — Kode Unik & Kunci Wilayah
*Rilis fitur · 23 Juli 2026 · `e4a055b`*

- Deposit berkode unik — uang masuk sedikit lebih besar dari nominal panel karena pemain menambahkan kode (selisih maksimal Rp999) — langsung dinyatakan cocok, tidak lagi mengantre pemeriksaan manual. Kelebihan bayar besar tetap ditinjau.
- Pembatasan akses aplikasi per wilayah negara, lengkap dengan halaman penolakan. Celah yang memungkinkan orang luar menyamar sebagai pengunjung dari wilayah yang diizinkan ditemukan saat pengujian dan ditutup pada hari yang sama.
- Keputusan manual auditor mengunci barisnya ke laporan asal — keputusan tidak bisa lagi tertimpa hasil otomatis di hari berikutnya sehingga tampak batal sendiri.
- Tabel Riwayat Batch menampilkan kolom Tidak Cocok, sehingga ketiga status terlihat sekaligus.
- Tab “Tidak Ada di Panel” bisa disaring per bank/sumber uang, dan Rincian Rekening memakai filter rentang Dari/Sampai seragam dengan Rincian Biaya.

## v1.8.0 — Kedalaman Analisis
*Rilis fitur · 21 Juli 2026 · `f7fb5a1`*

- Kartu Metode Pembayaran di halaman utama memecah nilai deposit dan penarikan menurut QRIS, e-wallet, dan bank.
- Setiap keputusan Setujui/Tinjau kini menyertakan alasan dari daftar baku plus catatan bebas, tersimpan di jejak audit — pertanggungjawaban keputusan jadi jelas.
- Breakdown FR/Bracket bisa dilihat untuk rentang tanggal, dengan saldo awal otomatis dibawa dari penutupan hari sebelumnya.
- Rekonsiliasi Bonus menampilkan nama program promo dan bisa disaring per kategori.
- Berkas Excel hasil rekonsiliasi otomatis menyertakan lembar Breakdown Bracket dan Rincian Rekening.
- Semua tabel besar bisa diseleksi persegi dengan mouse lalu disalin dan ditempel langsung ke Excel dengan kolom tetap rapi.

## v1.7.0 — Rekonsiliasi Bonus
*Rilis fitur · 20 Juli 2026 · `676d03f`*

- Halaman Rekonsiliasi Bonus: catatan bonus dan promo dari panel dicocokkan dengan catatan bonus di bracket. Jalurnya terpisah penuh dari rekonsiliasi harian, jadi tidak bisa mengganggu proses deposit/penarikan.
- Aksi massal Setujui/Tinjau lintas hari langsung dari Area Pengecekan.
- Halaman utama menampilkan strip Ringkasan Panel — jumlah transaksi dan nilai deposit/penarikan laporan terakhir (permintaan klien).
- Penarikan yang terpotong biaya antarbank kembali terdeteksi: kasus nyata penarikan Rp400.000 yang di mutasi tercatat Rp406.500 sebelumnya dilaporkan tanpa pasangan.
- Identitas visual baru dan penataan ulang menu samping.

## v1.6.0 — Koreksi FR, Hutang/Piutang & Rincian Biaya
*Rilis fitur · 18 Juli 2026 · `80e6c41`*

- Auditor bisa memperbaiki satu angka yang salah di tabel Control Bracket lewat popup — data asli hasil impor tidak diubah, total dan Selisih Kontrol langsung dihitung ulang, sel yang dikoreksi ditandai, dan setiap perubahan tercatat di log audit.
- Halaman Hutang/Piutang mengumpulkan seluruh catatan hutang dan piutang lintas tanggal beserta totalnya.
- Halaman Rincian Biaya merekap biaya administrasi bank per rekening dan per kanal (e-wallet Rp1.000, BI Fast Rp2.500, transfer online Rp6.500).
- Biaya administrasi di mutasi BRI dan Mandiri dikenali sejak impor sehingga tidak lagi mencemari total penarikan — aturannya dikalibrasi pada 8.937 baris data produksi dan diuji bebas salah-tandai pada 662 baris biaya Mandiri.
- Dukungan berkas gateway RafflesPay versi Excel untuk brand BBS, setoran maupun penarikan.
- Pencarian nama berkas di Riwayat Upload, pencatatan nama berkas saat hapus massal, dan penggantian nama toko dari panel admin.

## v1.5.0 — Mutasi BNI
*Rilis fitur · 15 Juli 2026 · `c2a2612`*

- Rekening BNI bisa diunggah langsung dalam bentuk e-statement PDF; aplikasi membedakannya sendiri dari PDF BCA tanpa perlu dipilih manual.
- Nomor HP pelanggan yang di mutasi BNI menempel pada nomor virtual account e-wallet dipisahkan, sehingga penarikan lewat e-wallet punya identitas untuk dicocokkan.
- Penarikan antar-bank lewat BCA yang biaya transfernya menempel jadi satu baris debit kini ketemu pasangannya.

## v1.4.0 — Percepatan
*Rilis fitur · 13 Juli 2026 · `f2016bf`*

- Tiga halaman terberat dipercepat, terukur pada data produksi: Kelola Toko dari 29,8 detik (praktis tidak bisa dibuka) menjadi 0,1 detik, dan halaman Impor Data dari 10,8 detik menjadi 0,01 detik. Angka yang ditampilkan tetap sama persis.
- Kapasitas server dinaikkan menjadi delapan jalur paralel — rekonsiliasi atau unggahan besar satu orang tidak lagi membuat pengguna lain menunggu.
- Seluruh skrip dan huruf tampilan dipindah ke dalam aplikasi sendiri; halaman tidak lagi bisa gagal tampil karena gangguan layanan pihak luar.
- Memilih satu berkas di Mutasi Bank kini menampilkan seluruh isinya, menjawab laporan “mutasi tidak terbaca penuh”.
- Riwayat Upload berhalaman sehingga berkas lama bisa dijangkau dan dihapus.
- Dukungan penarikan RafflesPay/QRIS RPAY untuk brand BBS — 6 dari 6 transaksi cocok pada verifikasi data nyata.
- Impor laporan COR/UNOPAY yang sempat gagal total kini normal, dan nama pemain pulih untuk 353 baris sehingga pencocokan berbasis nama ikut pulih.

## v1.3.0 — Laporan FR/Bracket
*Rilis fitur · 12 Juli 2026 · `fec2adb`*

- Halaman Breakdown FR/Bracket per rekening, mengikuti format laporan Control Bracket harian klien, lengkap dengan kolom Selisih Kontrol yang idealnya nol sehingga ketidakcocokan buku langsung terlihat.
- Perhitungan saldo awal dan akhir tidak lagi bergantung pada urutan baris yang sering diacak sumbernya: 21 dari 21 rekening selisih kontrolnya menjadi nol, dan selisih Rp5,95 juta yang selama ini tidak terjelaskan akhirnya cocok persis.
- Tiga halaman laporan baru: Ringkasan Bulanan, Rincian Rekening, dan Settlement Tertunda.
- Menu samping dikelompokkan agar tetap mudah ditelusuri saat daftar halaman bertambah.

## v1.2.1 — Perbaikan Penarikan E-wallet BRI
*Perbaikan · 11 Juli 2026 · `d864fed`*

- Penarikan ke DANA, GOPAY, OVO, ShopeePay, dan LinkAja lewat BRI sebelumnya selalu gagal dicocokkan karena nomor HP pemain menempel pada kode kanal di mutasi bank, sehingga semua transaksi menumpuk sebagai menunggu settlement. Pada kasus nyata, 15 dari 15 penarikan langsung cocok setelah perbaikan.
- Biaya Rp1.000 yang selalu mengikuti setiap penarikan e-wallet BRI tidak lagi dihitung sebagai transaksi — 182 baris palsu pada satu brand dalam 10 hari hilang dari daftar.
- Ketelitian pembacaan laporan gateway diperketat: baris tanpa nomor identitas tidak lagi dibuang karena dikira kembar, dan tanggal gaya Indonesia (09/07) dibaca sebagai 9 Juli, bukan 7 September.

> Rilis perbaikan murni — tidak ada halaman atau kemampuan baru. Perbaikannya berlaku surut: data lama cukup dijalankan ulang rekonsiliasinya.

## v1.2.0 — Keamanan Akun & Jejak Audit
*Rilis fitur · 10 Juli 2026 · `5ad5640`*

- Pengguna baru — atau yang kata sandinya baru direset admin — wajib membuat kata sandi sendiri sebelum bisa membuka halaman apa pun. Kata sandi sementara dari admin tidak bisa dipakai terus-menerus.
- Halaman Log Audit mencatat siapa membuat, mengubah, mereset, atau menghapus pengguna dan toko, lengkap dengan waktunya. Nama pelaku ikut disimpan sebagai salinan sehingga jejaknya tetap terbaca walau akun orang itu kemudian dihapus.
- Setiap pengguna bisa mengganti kata sandinya sendiri kapan saja tanpa meminta admin.
- Dukungan penarikan QRIS UNO (Vigor/TMG) — 278 dari 278 baris cocok pada data uji.
- Dukungan gateway QRIS RPay — 2.048 dari 2.058 transaksi (99,5%) cocok otomatis.
- Uang dari satu kanal pembayaran tidak lagi bisa dipasangkan dengan setoran lewat kanal lain; 18 baris yang dulu tertukar pada data uji menjadi nol.
- Jam server dikembalikan ke waktu Indonesia Barat setelah sempat tampil mundur tujuh jam.

## v1.1.0 — Ekspor Massal & Telusur Mutasi
*Rilis fitur · 8 Juli 2026 · `44b453d`*

- Menu Ekspor Data: unduh hasil rekonsiliasi untuk rentang tanggal dan satu atau semua brand sekaligus, dikemas menjadi satu berkas ZIP berisi satu Excel per brand per tanggal.
- Sub-menu Mutasi Bank menampilkan seluruh baris mutasi bank dan gateway persis seperti urutan di berkas aslinya, dengan penyaringan per bank, per berkas, arah transaksi, dan tanggal.
- Antrean Tinjau berganti nama menjadi Area Pengecekan dan kini punya tiga tab lintas-tanggal: Perlu Ditinjau, Tidak Cocok, dan Tidak Ada di Panel, plus ringkasan jumlah dan nilai.
- Nama pemilik rekening dibaca dari kepala berkas mutasi dan ditampilkan di setiap baris hasil, sehingga terlihat rekening mana yang dipakai.
- Filter tanggal di Ringkasan Toko dan penyaringan lebih rinci di Area Pengecekan.

## v1.0.0 — Rilis Produksi Pertama
*Rilis besar · 7 Juli 2026 · `6e550a0`*

- Aplikasi resmi dipakai tim auditor di server produksi, menggantikan rekonsiliasi manual.
- Aturan pencocokan final ditegakkan: pasangan hanya boleh terbentuk bila ada bukti identitas (nomor tiket, nomor referensi, nomor HP/rekening, username, atau nama). Nominal dan tanggal hanya pendukung — keduanya tidak lagi cukup untuk menyatakan dua baris berpasangan.
- Nama yang hanya mirip sebagian masuk antrean Perlu Tinjau dengan label jelas, bukan dipasangkan diam-diam; nama yang tidak mirip dibiarkan menunggu pencairan hari berikutnya.
- Tiga brand baru di-onboard (COR/Gacor25, MUL, MXW) berikut pembaca berkas Excel dari exporter non-standar yang sebelumnya gagal dibuka.
- Pencocokan kunci pasti lewat nomor referensi QRIS gateway, tanpa perlu menebak nama.
- Halaman hasil dirombak: baris uang tanpa jejak di Panel dipisah, sehingga Cocok + Perlu Tinjau + Tidak Cocok benar-benar menjumlah ke total baris Panel.
- Pengerasan produksi: kunci rahasia wajib disetel, mode aman menjadi bawaan, kebijakan kekuatan kata sandi penuh, serta halaman 404 dan 500 bermerek.

> Hasil rekonsiliasi versi ini diaudit ulang secara independen pada 8 Juli 2026 memakai data nyata dua brand selama tiga hari: 53.949 pasangan diperiksa satu per satu di luar aplikasi, nol pelanggaran aturan, nol pasangan kuat yang terlewat, dan total nominal harian klop sampai rupiah pada enam dari enam pemeriksaan.

## v0.4.0 — Kokpit Auditor
*Pra-rilis · 5 Juli 2026 · `f2e2039`*

- Mesin pencocokan generasi kedua berjalan bertahap, mulai dari bukti terkuat (nomor tiket dan nomor referensi gateway) menuju identitas pemain.
- Pemain dikenali dari nomor HP atau virtual account e-wallet di mutasi bank, yang sering tidak mencantumkan nama sama sekali — pada uji data nyata tiga hari, transaksi yang perlu diperiksa manual turun sekitar 88 persen.
- Halaman Uang Tanpa Pasangan: uang yang tidak menemukan pasangan tidak lagi menghilang, melainkan dikelompokkan menurut sebabnya.
- Halaman utama menjadi ruang kendali harian: status rekonsiliasi terakhir, antrean pemeriksaan, kalender status 14 hari, tren selisih 30 hari, dan daftar kerja hari ini — rapi juga di ponsel.
- Antrean Tinjau lintas laporan dengan persetujuan massal; setiap keputusan tetap tercatat satu per satu.
- Jejak aksi tersimpan dan berkas yang sudah menjadi bukti rekonsiliasi tidak bisa dihapus.
- Unggah satu folder atau arsip ZIP sekaligus.

## v0.3.0 — Rekonsiliasi Harian
*Pra-rilis · 4 Juli 2026 · `7b83175`*

- Rekonsiliasi terikat pada satu tanggal kerja dan tidak bisa lagi tercampur antar hari.
- Transaksi yang uangnya belum masuk hari itu tidak dianggap gagal — statusnya menunggu settlement dan otomatis diselesaikan saat uangnya muncul, dengan hasil diperbaiki di laporan tanggal aslinya.
- Data yang sudah dipakai rekonsiliasi dikunci agar tidak terhitung dua kali; menghapus laporan mengembalikannya.
- Nama pengirim dan penerima dibersihkan lebih dulu dari kode dan nominal yang menempel di keterangan mutasi — 225 baris tambahan cocok otomatis pada data uji tiga hari.
- Angka Uang Real dan Selisih diperbaiki, dan biaya transaksi bank tidak lagi dihitung sebagai penarikan.
- Mutasi Mandiri yang terkunci kata sandi bisa dibaca langsung dari halaman unggah.

## v0.2.0 — Multi-Brand & Hak Akses
*Pra-rilis · 2 Juli 2026 · `90df919`*

- Seluruh data melekat pada satu brand, sehingga satu aplikasi bisa melayani banyak brand tanpa datanya tercampur.
- Unggah banyak berkas sekaligus dengan pengenalan jenis otomatis — pada pengujian 39 berkas asli, semuanya dikenali dengan benar.
- Rekonsiliasi sekali klik: satu tombol menjalankan seluruh pencocokan, didahului pemeriksaan berkas mana yang belum diunggah.
- Hak akses berjenjang Admin, Supervisor, dan Auditor, dibatasi per brand — termasuk bila seseorang mencoba membuka laporan brand lain lewat alamat langsung.
- Panel Kelola Toko dan Kelola Pengguna agar admin tidak perlu bantuan pengembang.

## v0.1.0 — Fondasi Rekonsiliasi
*Pra-rilis · 1 Juli 2026 · `58a5c04`*

- Berkas ekspor dari Panel, Bracket, bank, dan gateway pembayaran dibaca dan diseragamkan menjadi satu daftar transaksi baku dalam rupiah.
- Mesin pencocokan otomatis menggolongkan setiap baris menjadi Cocok, Perlu Tinjau, atau Tidak Cocok berikut alasannya — menggantikan pencocokan manual baris per baris.
- Halaman kerja auditor: ringkasan, unggah, daftar transaksi, hasil rekonsiliasi dengan peninjauan manual, dan ekspor Excel.
- Berkas yang sama diimpor ulang tidak menggandakan data.
