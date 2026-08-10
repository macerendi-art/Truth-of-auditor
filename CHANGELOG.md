# Catatan Perubahan — Truth of Auditor

> Berkas ini **dibuat otomatis** dari `core/version.py`. Jangan diedit langsung:
> ubah daftar `RILIS` di sana lalu jalankan `python manage.py changelog`.

Versi berjalan: **v1.17.3** · 31 rilis (1 besar, 17 fitur, 9 perbaikan, 4 pra-rilis).

Penomoran MAYOR.MINOR.PATCH: **MAYOR** bila cara kerja aplikasi berubah mendasar,
**MINOR** bila ada kemampuan baru, **PATCH** bila isinya murni perbaikan.
Versi 0.x = tahap pra-rilis, sebelum aplikasi dipakai produksi.

## v1.17.3 — Laporan QR Flyer Bentuk Ketiga & Penjaga Kolom
*Perbaikan · 10 Agustus 2026*

- **Laporan QR Flyer bentuk ketiga kini terbaca penuh.** Vendor kembali mengganti penamaan kolom (`Transaction Id`, `Amount`, `Callback`), dan bentuk ini dipakai beberapa brand sejak awal Agustus. Diuji pada berkas asli HKW 1 Agustus 2026: **1.518 dari 1.519 transaksi cocok** lewat nomor tiket — satu sisanya memang tidak ada di panel.
- Kegagalan sebelumnya jauh lebih berbahaya daripada sekadar tidak terbaca: berkasnya **masuk**, tetapi seluruh isinya kosong — tanpa nomor tiket, nominal Rp0, tanpa tanggal. Data yang mengaku data. Akibatnya deposit QRIS Flyer tampak tidak punya uang masuk sama sekali; pada satu batch saja 1.517 transaksi tertahan di daftar “Tidak Cocok”.
- **Kolom kini dikenali dari daftar nama yang mungkin, bukan satu bentuk tetap** — jadi penggantian nama berikutnya tidak otomatis merusak. Dan bila kolom nomor tiket atau nominal benar-benar tidak ditemukan, aplikasi **menolak berkasnya** sambil menyebutkan kolom apa saja yang ada di dalamnya, alih-alih memasukkan baris kosong diam-diam.

## v1.17.2 — QRIS ZPay Terbukti Cocok 69/69
*Perbaikan · 10 Agustus 2026*

- **Laporan QRIS ZPay kini cocok penuh dengan panel.** Diuji pada berkas asli 6 Agustus 2026: **69 dari 69 transaksi cocok** lewat nomor tiket — nomor tiket, nomor pesanan, dan nominalnya sama persis, dan panel menyetujuinya rata-rata 3 detik setelah pembayaran tercatat di ZPay. Rekonsiliasi hari itu naik dari 641 menjadi **710 dari 724 transaksi**.
- Penyebab sebelumnya: kolom status di laporan ZPay punya dua nilai yang sama-sama berarti uang sungguhan — “paid” (sudah dibayar) dan “settled” (dananya sudah cair) — sedangkan aplikasi hanya menerima yang pertama. Seluruh isi berkas ikut terbuang tanpa pesan apa pun. Kini keduanya diterima.
- **Kegagalan diam-diam seperti itu tidak boleh terulang.** Bila sebuah berkas ZPay berisi transaksi tetapi tak satu pun bisa dibaca, aplikasi kini menolak berkasnya dan menyebutkan status apa yang ditemukannya — jauh lebih baik daripada melaporkan “berhasil diunggah” padahal nol baris masuk. Berkas yang memang kosong tetap diterima seperti biasa.

## v1.17.1 — Koreksi Jam Laporan QRIS ZPay
*Perbaikan · 10 Agustus 2026*

- **Jam pada laporan QRIS ZPay ternyata memakai waktu GMT+0, bukan waktu Indonesia Barat.** Aplikasi kini menggesernya 7 jam saat berkas dibaca, sehingga setiap transaksi tercatat pada hari dan jam yang sebenarnya. Salinan mentah dari vendor tetap disimpan apa adanya untuk keperluan audit.
- Tanpa koreksi ini setoran akan tercatat 7 jam lebih awal daripada catatan panelnya sendiri — dan karena aplikasi menolak memasangkan uang yang seolah masuk sebelum transaksinya terjadi, pasangannya tidak akan pernah ketemu meskipun nomor tiketnya sama persis. Perbaikan ini terbit sebelum berkas ZPay pertama diunggah, jadi tidak ada data lama yang perlu diperbaiki.
- Temuan ini sekaligus menjelaskan berkas contoh 6 Agustus 2026: isinya sesungguhnya transaksi dini hari **7 Agustus** (00:01–06:52 WIB), bukan 6 Agustus. Laporan ZPay untuk tanggal 6 Agustus sendiri belum pernah dikirim vendor, sehingga masih perlu diminta ulang dengan rentang waktu Indonesia yang disebutkan tegas.

## v1.17.0 — QRIS ZPay & Laporan Flyer Versi Vendor
*Rilis fitur · 10 Agustus 2026*

- **Laporan QR Flyer versi vendor kini terbaca kembali.** Sejak laporan itu tidak bisa diunduh sendiri dan harus diminta ke vendor, penamaan kolomnya berubah — isinya tetap sama, hanya nama kolomnya. Aplikasi kini mengenali kedua bentuk sekaligus, jadi berkas lama maupun baru sama-sama masuk. Diuji pada berkas asli 6 Agustus 2026: **120 dari 120 transaksi cocok dengan panel**.
- Kegagalan sebelumnya memang sulit disadari: berkasnya tetap dilaporkan “berhasil diunggah”, tetapi nol baris masuk, karena aplikasi tidak menemukan satu pun kolom yang dikenalnya lalu menganggap seluruh isi berkas sebagai baris penutup. Kini berkas versi vendor dikenali langsung dari kolomnya, bukan sekadar dari nama file.
- **Gateway QRIS baru — ZPay (ZETPAY) — kini didukung.** Nomor tiketnya dibaca sebagai kunci pencocokan utama, lengkap dengan nominal bruto, biaya, dan nama pemain yang diambil dari nomor pesanan. Catatan penting: pada berkas contoh pertama, seluruh tiket ZPay belum ditemukan di ekspor panel yang menyertainya, sehingga transaksinya akan tampil sebagai “uang tanpa panel” sampai ekspor panel yang memuatnya ikut diunggah.

## v1.16.1 — Angka pada Tombol Pilihan Kini Jujur
*Perbaikan · 8 Agustus 2026*

- **Angka kecil di tiap tombol pilihan halaman Detail FR/Bracket kini selalu sama dengan jumlah baris yang muncul saat tombol itu diklik.** Sebelumnya angkanya dihitung tanpa memperhatikan pilihan lain yang sedang aktif, sehingga tombol bertuliskan “Beban Admin Bank 95” bisa berujung hanya 2 baris begitu sebuah rekening ikut dipilih.
- Tombol pilihan yang isinya nol kini disembunyikan — sebelumnya ia tetap tampil padahal hanya menuntun ke halaman kosong. Pilihan yang sedang aktif tetap ditampilkan meski hasilnya kosong, supaya tidak ada yang kehilangan jejak pilihannya sendiri.
- Tombol **Semua** kini juga menyertakan jumlahnya, mengikuti aturan yang sama.

## v1.16.0 — Dari Angka Langsung ke Isinya
*Rilis fitur · 8 Agustus 2026*

- **Rincian sebuah angka kini bisa dibuka langsung dari selnya.** Klik angka di Control Bracket seperti biasa, dan pada panel yang muncul kini ada tautan “Lihat sekian baris penyusunnya” — tidak perlu lagi berpindah menu lalu memilih ulang rekening, kategori, dan tanggalnya.
- Cara mengoreksi angka **tidak berubah sama sekali**: tetap satu klik, form yang sama, di tempat yang sama. Tautan rincian hanyalah tambahan di dalam panel itu, bukan langkah baru yang harus dilewati lebih dulu — mengoreksi adalah pekerjaan harian dan tidak boleh jadi lebih lambat demi keperluan yang sesekali.
- Kolom **Saldo Awal** dan **Saldo Akhir** sengaja tidak diberi tautan. Keduanya adalah posisi saldo pada satu titik waktu, bukan hasil penjumlahan baris mana pun, sehingga menautkannya ke sebuah daftar transaksi justru akan menyesatkan.

## v1.15.0 — Detail FR/Bracket
*Rilis fitur · 8 Agustus 2026*

- **Halaman baru: Detail FR/Bracket.** Selama ini Control Bracket menjawab “berapa”, tapi tidak “isinya apa saja”. Kalau sel Adjustment sebuah rekening tertulis 450.000, satu-satunya cara mengetahui isinya adalah membuka kembali berkas FR-nya. Sekarang cukup memilih rekening dan kategorinya, lalu seluruh baris penyusunnya tampil lengkap dengan jam, member, keterangan, nominal, dan saldo berjalannya.
- Berlaku untuk **semua kategori dan semua rekening** — Deposit, Withdrawal, Sesama CM, Beban Admin, Biaya Transaksi, dan seterusnya — serta bisa disaring per rentang tanggal atau dicari bebas berdasarkan keterangan, member, maupun username.
- Angkanya dijamin **selalu sama dengan halaman Breakdown**: aturan hitungnya satu sumber, dan kesamaannya dikunci uji otomatis untuk setiap sel, bukan sekadar diperiksa sekali. Bila sebuah sel pernah dikoreksi manual, halaman ini menyebutkannya terang-terangan — nilai tampil sekian, isi aslinya sekian — supaya selisihnya tidak pernah jadi teka-teki.

## v1.14.2 — Peringatan Menyebut Berkas yang Benar
*Perbaikan · 7 Agustus 2026*

- **Peringatan unggahan kini menyebut nama berkas yang benar.** Sesaat setelah perbaikan sebelumnya, dua dari tiga peringatan keliru mencantumkan nama berkas lain — isinya tepat, labelnya bukan berkas yang sedang diperiksa. Justru itu yang paling membingungkan: orang mencari berkas yang sebenarnya tidak bermasalah.
- Angka dan penilaian peringatan tidak berubah sama sekali; hanya nama berkas yang ditampilkan yang dibetulkan.
- Ditemukan lewat pemeriksaan pada data produksi sungguhan, bukan dari pengujian otomatis — karena itu pemeriksaan namanya kini ikut dikunci uji agar tidak terulang.

## v1.14.1 — Penjaga yang Tahu Bedanya
*Perbaikan · 7 Agustus 2026*

- **Peringatan “jumlah baris tidak wajar” tidak lagi salah tuduh.** Pada panel Vigor/TM Gaming, satu jenis sumber sebenarnya memuat dua jenis berkas yang volumenya sangat berbeda — panel QRIS (ribuan baris) dan panel biasa untuk bank (ratusan baris) — dan berkas bank pun terpisah per rekening. Sebelumnya semuanya dibandingkan dalam satu kelompok, sehingga berkas yang sepenuhnya normal ikut ditegur. Kini tiap jenis berkas punya kebiasaannya sendiri, dikenali dari pola penamaan yang dipakai pengunggah.
- Ikutannya, hasil peringatan tidak lagi bergantung pada urutan berkas diunggah. Sebelumnya berkas yang diproses belakangan dinilai terhadap kebiasaan yang baru saja bergeser oleh berkas sebelumnya dalam kiriman yang sama.
- Bila pola penamaan sebuah berkas berubah, peringatan volumenya **berhenti sementara** untuk berkas itu sampai terkumpul lima kali unggahan dengan pola baru — sengaja diam daripada menuduh berdasarkan pembanding yang keliru. Dua pemeriksaan lain, yaitu tanggal isi berkas dan kecocokan kode transaksi gateway dengan panel, tidak terpengaruh dan tetap berjalan penuh.

## v1.14.0 — Penjaga Salah Unggah
*Rilis fitur · 7 Agustus 2026*

- **Aplikasi kini memperingatkan saat sebuah file sepertinya salah tarik.** Begitu file selesai diunggah, tiga hal diperiksa: apakah tanggal isinya jauh dari tanggal di nama filenya, apakah jumlah barisnya melenceng jauh dari kebiasaan sumber itu di toko tersebut, dan — khusus file gateway — apakah kode transaksinya benar-benar dikenal panel hari itu. Sebelumnya kesalahan seperti ini baru ketahuan berhari-hari kemudian lewat ribuan baris tidak cocok yang harus ditelusuri satu per satu.
- Peringatannya **tidak menghalangi**. File tetap masuk dan pekerjaan tetap jalan; yang diberikan hanyalah angkanya, supaya orang yang paling tahu — pengunggahnya — bisa menilai sendiri. Ketiga pemeriksaan juga sengaja diam saat buktinya tipis, misalnya pada brand baru yang belum punya kebiasaan pembanding, karena penjaga yang sering salah tuduh akan berhenti dibaca orang.
- Kartu **Kelengkapan Data** kini membedakan “belum diunggah” dari “sudah terpakai”. Dulu keduanya tampil sama-sama abu-abu bertulis “opsional”, sehingga file yang sebenarnya sudah masuk dan sudah dipakai rekonsiliasi terbaca seolah tidak terdeteksi. Sekarang baris seperti itu menyebutkan jumlah barisnya dan batch mana yang memakainya.
- Saat rekonsiliasi ditolak karena ada tanggal tanpa panel penutup, saran “jalankan sebagian dulu” kini berupa **tautan yang langsung mengisikan filternya**. Sebelumnya pesan itu menyuruh mengisi sebuah kolom yang tersembunyi di dalam panel “Filter lanjutan” yang tertutup.

## v1.13.0 — Filter Bank Menyeluruh, Upload Ketiban & Cari Toko
*Rilis fitur · 1 Agustus 2026*

- Tab **“Perlu Ditinjau”** dan **“Tidak Cocok”** kini punya filter bank juga. Sebelumnya, pada toko berpanel Vigor/TM Gaming, seluruh baris filter menghilang begitu saja karena sebagian transaksi memang tidak membawa nama bank sama sekali. Baris seperti itu sekarang dikumpulkan sebagai **“(Tanpa Bank)”** — jadi bisa disaring seperti bank lain, bukan lagi menyembunyikan filternya dari semua orang. Mengurutkan kolom maupun berpindah ke tab **Deposit/Withdraw** juga tidak lagi membuang filter bank yang sedang dipakai.
- Transaksi **QRIS** pada panel Gacor25 kini berlabel QRIS, bukan kosong. Efeknya terasa di tiga tempat: kolom Bank Title terisi, kartu **“Metode Pembayaran”** di dashboard tidak lagi menghitungnya sebagai “Lainnya”, dan filter banknya punya pilihan yang berarti. Tersedia perintah pengisian ulang untuk data lama.
- **Upload ulang file mutasi yang lebih lengkap kini menandai file lama “Ketiban”.** Tarikan bank kadang terpotong di bagian bawah; begitu versi utuhnya diunggah dengan nama yang sama, sistem memeriksa bahwa seluruh isi file lama benar-benar tercakup, lalu memberi tanda di Riwayat Upload dan di daftar file halaman Mutasi Bank. **Tidak ada data yang dihapus** — file lama tetap utuh sebagai jejak audit, dan tandanya hilang sendiri bila file penggantinya dihapus.
- Pemilih **Toko** di bilah atas kini punya kotak pencarian: ketik “25” dan daftar 16 toko langsung menyusut ke yang cocok, lengkap dengan navigasi papan ketik. Tidak perlu lagi menggulir daftar panjang berisi kode-kode yang mirip.

## v1.12.2 — Penolakan Rekonsiliasi yang Menuntun
*Perbaikan · 27 Juli 2026*

- Saat rekonsiliasi ditolak karena ada tanggal ber-uang tanpa panel penutup, pesannya kini menyebut **panel tanggal berapa** yang dibutuhkan tiap baris (mis. “butuh panel 23/07 atau 24/07”) — sebelumnya pemakai harus menebak sendiri.
- Pesan yang sama menawarkan jalan keluar kedua: menjalankan sebagian dulu dengan mengisi “Dari tanggal” pada tanggal aman terdekat. Baris lama tetap menunggu sampai panelnya diupload, jadi tak ada yang hilang atau salah dihitung.
- Tanggal yang sudah pernah direkonsiliasi tidak lagi ikut memblokir. Mutasi bank biasa diekspor berputar sehingga unggahan hari ini kerap membawa baris baru bertanggal lampau; baris seperti itu memang sudah punya jalurnya sendiri (ditulis balik ke batch tanggalnya), sehingga menahan seluruh rekonsiliasi karenanya cuma menyuruh pemakai mengupload panel yang sebenarnya sudah ada.

## v1.12.1 — Filter Sumber Panel↔Bracket
*Perbaikan · 27 Juli 2026*

- Pada hasil Panel↔Bracket, tab “Tidak Ada di Panel” punya filter “bank/sumber” yang sebelumnya hanya berisi satu pilihan bertuliskan “Bracket” — tidak ada gunanya untuk menyaring. Sekarang isinya rekening FR yang sebenarnya (mis. “BANK BCA — HENDI · WITHDRAW”, “QRIS FLYER · DEPOSIT / WITHDRAW”), ditulis sama seperti di halaman Breakdown FR/Bracket dan lengkap dengan jumlah barisnya.
- Perbaikan yang sama berlaku di Area Pengecekan, supaya daftar kerja lintas hari bisa disaring per rekening FR juga.
- Yang tidak berubah: pencocokan dengan bank atau gateway tetap menampilkan nama banknya (BRI, BCA, Mandiri, NXPay, …) seperti sebelumnya. Baris FR yang kolom rekeningnya kosong dikelompokkan sebagai “(Tanpa Akun)” — bukan disembunyikan.

## v1.12.0 — Dashboard Bisa Menoleh ke Belakang
*Rilis fitur · 26 Juli 2026*

- Dashboard kini punya filter tanggal: isi Dari–Sampai lalu Terapkan untuk melihat potret hari yang sudah lewat, atau menjumlahkan seluruh rekonsiliasi dalam satu rentang (mis. sepekan). Tombol “Terbaru” mengembalikan tampilan ke rekonsiliasi terakhir. Tanpa mengisi filter, dashboard tetap seperti sebelumnya.
- Dalam mode rentang, Ringkasan Panel, Metode Pembayaran, Ringkasan Bracket, tren selisih, dan daftar rekonsiliasi semuanya mengikuti rentang yang dipilih; jumlah batch yang tercakup ditulis apa adanya agar angkanya tak salah dibaca sebagai satu hari.
- Filter yang sama tersedia di dashboard mode “Semua Toko” untuk admin — satu rentang, seluruh toko, termasuk kolom rekon terakhir per toko di dalam rentang itu.
- Panel “Kerjakan hari ini” sengaja TIDAK ikut filter: daftar kerja tetap menunjuk rekonsiliasi terakhir yang sebenarnya, supaya menengok data lama tak pernah mengubah apa yang harus dikerjakan hari ini.

## v1.11.0 — Tiga Panel & Rekap Bulanan
*Rilis fitur · 26 Juli 2026 · `1cff0a9`*

- Rekonsiliasi Panel↔Bracket kini berjalan untuk brand berpanel Vigor/TM Gaming yang ekspornya tanpa nomor tiket — baris dicocokkan lewat username + nominal. Uji dengan data nyata COR: 10.069 dari 10.072 baris (99,97%) cocok otomatis. Saat aturan baru ini yang bekerja, halaman hasil mencantumkan mode pencocokannya.
- Pencocokan sisi uang mengenal jangkar baru: nomor rekening tujuan dari laporan gateway (UNO) yang sama persis dengan rekening pemain di panel — pelengkap kunci UUID yang sudah ada, hanya dipakai bila nominalnya juga sama persis.
- Dashboard menampilkan kartu Ringkasan Bracket — total deposit, penarikan, dan bersih menurut catatan FR/Bracket hari itu — berdampingan dengan Ringkasan Panel, dan angkanya selalu klop dengan halaman Breakdown (termasuk koreksi sel yang pernah disimpan).
- Halaman baru Rekap Bulanan meniru rekap Excel yang selama ini disusun manual: empat seksi (Net Profit, Sisa Dana Member, Total Dana Lebih Web, Selisih beserta penyebabnya), angka otomatis dihitung dari data harian, dan isian manual bisa menimpa angka otomatis dengan jejak siapa-dan-kapan.
- Mode “Semua Toko” untuk admin: dashboard gabungan seluruh toko sekali pandang — kalender status, ringkasan Panel/Bracket/Metode gabungan, dan tabel per toko — plus filter ceklis beberapa toko sekaligus di halaman Hutang/Piutang.
- Gembok alamat IP untuk akun auditor & supervisor: hanya alamat internet yang terdaftar yang bisa masuk; admin tidak pernah terkunci; selama daftar kosong fitur ini tidur. Dikelola dari halaman admin sendiri; penolakan tercatat di jejak audit (satu catatan per sesi per alamat).
- Penarikan berlabel bank “OTH” pada brand Vigor/TM kini menampilkan bank aslinya (dibaca dari teks transaksi), dan nama penerima transfer BRI yang tadinya kosong kini terisi — untuk nama BRI berlaku otomatis termasuk data lama; untuk label OTH data lama tersedia perintah perapihan sekali jalan, tanpa perlu unggah ulang berkas.
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
