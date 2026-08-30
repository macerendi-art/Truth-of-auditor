"""Sumber-kebenaran tunggal versi aplikasi + riwayat rilis.

Satu daftar `RILIS` di berkas ini memberi makan SEMUA tempat versi muncul:
badge sidebar & footer login (lewat `core.context_processors.versi`), halaman
Riwayat Versi `/versi/`, stempel versi di workbook ekspor, dan `CHANGELOG.md`
(digenerate oleh `python manage.py changelog`, dijaga tes agar tak pernah
melenceng dari berkas ini).

Aturan penomoran — MAYOR.MINOR.PATCH
------------------------------------
MAYOR  Cara kerja aplikasi berubah mendasar, atau aplikasi melewati tonggak
       yang mengubah statusnya bagi pengguna. Contoh: 1.0.0 = hari aplikasi
       resmi dipakai tim auditor menggantikan cara kerja manual. Rilis mayor
       menuntut pengumuman & pendampingan pengguna, bukan sekadar catatan.
MINOR  Ada kemampuan baru yang bisa dijelaskan sebagai "sekarang aplikasi
       bisa X" — halaman baru, sumber berkas baru yang didukung, aturan
       pencocokan baru, atau lompatan performa yang terasa. Cara kerja lama
       tetap berlaku; pengguna tak perlu belajar ulang.
PATCH  Isinya murni perbaikan atas perilaku yang memang sudah dijanjikan —
       tidak ada kemampuan baru untuk diumumkan.

Versi 0.x adalah tahap pra-rilis: aplikasi masih dibangun dan divalidasi,
belum jadi sandaran kerja harian tim auditor.

Syarat sebuah rilis pantas disebut 2.0.0 — minimal satu dari:
  1. Aturan pencocokan inti diganti sedemikian rupa sehingga laporan lama akan
     berbeda hasilnya bila dijalankan ulang.
  2. Model data atau alur kerja berubah mendasar (mis. persetujuan berjenjang
     maker-checker, atau perombakan konsep batch/tanggal kerja).
  3. Susunan berkas keluaran yang sudah dipakai klien berubah, sehingga
     template kerja mereka harus ikut disesuaikan.
  4. Migrasi data yang tidak bisa dimundurkan.
Menambah bank/gateway/brand, menambah halaman laporan, atau memperketat
keamanan akses TETAP MINOR — sebanyak apa pun jumlahnya.

Batas antar-rilis selalu ditarik pada rentang commit yang BERSAMBUNG: satu
rilis = satu rentang tanggal utuh, tidak pernah berselang-seling dengan rilis
lain. Ini yang membuat peta versi bisa diverifikasi ulang dari `git log`.

Menambah rilis baru
-------------------
1. Tambahkan entri `Rilis(...)` PALING ATAS di `RILIS` (urutan terbaru→terlama).
2. Jalankan `python manage.py changelog` untuk memperbarui `CHANGELOG.md`.
3. Jalankan `python manage.py test core.tests_version` — tes menjaga urutan
   versi, urutan tanggal, kecocokan jenis dengan lompatan nomor, dan
   kesinkronan `CHANGELOG.md`.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

MAYOR = "mayor"
MINOR = "minor"
PATCH = "patch"
PRA_RILIS = "pra-rilis"

JENIS_LABEL = {
    MAYOR: "Rilis besar",
    MINOR: "Rilis fitur",
    PATCH: "Perbaikan",
    PRA_RILIS: "Pra-rilis",
}


@dataclass(frozen=True)
class Rilis:
    """Satu rilis aplikasi, dalam bahasa yang bisa dibaca non-teknis."""

    versi: str
    tanggal: _dt.date
    nama: str
    jenis: str
    sorotan: tuple[str, ...]
    commit: str = ""
    catatan: str = ""

    @property
    def nomor(self) -> tuple[int, int, int]:
        mayor, minor, patch = self.versi.split(".")
        return int(mayor), int(minor), int(patch)

    @property
    def label(self) -> str:
        return f"v{self.versi}"

    @property
    def jenis_label(self) -> str:
        return JENIS_LABEL[self.jenis]

    @property
    def tanggal_id(self) -> str:
        """Tanggal gaya Indonesia, mis. '23 Juli 2026'."""
        return f"{self.tanggal.day} {BULAN_ID[self.tanggal.month]} {self.tanggal.year}"


BULAN_ID = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}


# Urutan: TERBARU di atas (sama seperti konvensi CHANGELOG).
#
# Riwayat 0.1.0–1.9.0 disusun retroaktif pada 25 Juli 2026 dari 281 commit
# (1–23 Juli 2026); tanggal tiap rilis = tanggal commit terakhir yang tercakup.
# Angka hasil pengukuran di bawah dikutip dari laporan kalibrasi data nyata
# yang tersimpan di docs/superpowers/specs/.
RILIS: tuple[Rilis, ...] = (
    Rilis(
        versi="1.20.1",
        tanggal=_dt.date(2026, 8, 29),
        nama="Dashboard Lebih Ringan & Tanggal Salah Ketik Tak Lagi Mematikan Halaman",
        jenis=PATCH,
        commit="",
        sorotan=(
            "**Dashboard toko besar jauh lebih cepat dibuka.** Kartu "
            "\"Transaksi per Sumber\" sebelumnya memaksa database membaca "
            "1,6 GB dari disk hanya untuk menampilkan enam angka. Sekarang "
            "jawabannya diambil langsung dari index. Pada toko G25 (1,49 juta "
            "baris) query itu turun dari 3,8 detik menjadi 0,9 detik, dan "
            "angka yang tampil sama persis seperti sebelumnya.",
            "**Salah ketik tanggal tidak lagi mematikan halaman Rekonsiliasi.** "
            "Satu operator mengetik tahun \"20026\" (kelebihan satu angka nol) "
            "dan seluruh halaman berhenti dengan layar error. Sekarang "
            "aplikasi menolak dengan pesan yang jelas dan menyebut tanggal "
            "mana yang salah — rekonsiliasi tidak dijalankan, sehingga salah "
            "ketik tidak bisa diam-diam memperluas cakupan yang diproses.",
            "**Halaman yang sesekali gagal terbuka kini tidak lagi.** Saat "
            "beberapa orang membuka halaman berat bersamaan, database "
            "kehabisan ruang memori bersama dan sebagian halaman membalas "
            "layar error. Setelan database sudah disesuaikan sehingga hal itu "
            "berhenti terjadi, tanpa perlu menghentikan aplikasi.",
        ),
    ),
    Rilis(
        versi="1.20.0",
        tanggal=_dt.date(2026, 8, 16),
        nama="QRIS ELITE & Arah UNOPAY yang Tepat",
        jenis=MINOR,
        commit="",
        sorotan=(
            "**Laporan QRIS ELITE sekarang bisa diunggah dan dicocokkan lewat "
            "nomor tiket.** Diuji pada laporan BBS 13 Agustus: seluruh 85 dari "
            "85 transaksi menemukan pasangan panelnya. Nominal berkode unik "
            "tetap dicatat apa adanya, sehingga selisih Rp1–Rp2 tidak "
            "disembunyikan oleh pembacaan file.",
            "**Arah deposit UNOPAY tidak lagi terbalik karena nama file.** "
            "Nama ekspor dapat memuat dua penanda sekaligus, misalnya `WD DP`; "
            "sebelumnya penanda WD selalu menang dan 596 deposit 13 Agustus "
            "tercatat sebagai uang keluar, membuat 586 baris panel berhenti di "
            "\"Belum ada uang masuk\". Sekarang penanda terakhir yang berdiri "
            "sendiri dipakai, dan bentuk kolom deposit dari vendor selalu "
            "diperlakukan sebagai deposit.",
            "**Baris UNOPAY lama yang sudah salah arah dapat dipulihkan di "
            "tempat tanpa unggah ulang.** Perintah pemulihan secara bawaan "
            "hanya menampilkan pratinjau per toko dan tanggal; penulisan harus "
            "diminta tegas, dan otomatis dihentikan bila ada baris yang masih "
            "terkunci oleh batch rekonsiliasi.",
            "**File Excel dari eksportir COR/UNO yang bentuk internalnya tidak "
            "standar kini dibaca penuh.** Aplikasi tidak lagi mengira file "
            "berisi ratusan baris sebagai satu baris header saja.",
        ),
    ),
    Rilis(
        versi="1.19.0",
        tanggal=_dt.date(2026, 8, 14),
        nama="Bonus Panel Vigor/TM Gaming — Dua Cara Bracket Membukukan Bonus",
        jenis=MINOR,
        commit="",
        sorotan=(
            "**File bonus panel merek Vigor/TM Gaming sekarang bisa diunggah.** "
            "Sebelumnya tidak bisa sama sekali: bentuk file-nya berbeda dari "
            "merek lain, sehingga sisi panel tak pernah masuk dan halaman "
            "Rekonsiliasi Bonus untuk merek itu buta sebelah sejak awal — hanya "
            "sisi bracket yang pernah terlihat. File 4 Agustus terbaca 677 baris "
            "senilai Rp1.358.797 — persis sama dengan angka Grand Total yang "
            "dicetak file itu sendiri.",
            "**Bonus yang dibukukan gelondongan kini dicocokkan sebagai total, "
            "bukan per pemain.** Bracket mencatat sebagian bonus sebagai satu "
            "baris per kategori per hari tanpa nama pemain, sementara panel "
            "mencatatnya per pemain. Dicocokkan dengan cara lama, satu hari "
            "menghasilkan ±671 baris \"hanya di panel\" yang semuanya bunyi "
            "palsu padahal angkanya sebenarnya cocok. Sekarang keduanya "
            "dibandingkan pada tingkat yang sama, dan baris per pemain tetap "
            "dicocokkan satu-satu seperti biasa — terbukti 6 dari 6 pada 4 "
            "Agustus dan 17 dari 17 pada 6 Agustus.",
            "**Baris gelondongan yang bertuliskan \"TGL 03.08.2026\" dicocokkan "
            "ke hari yang tertulis**, bukan ke hari pembukuannya, karena bonus "
            "jenis ini memang dibukukan sehari setelah kejadiannya.",
            "**Bonus ikut masuk ke berkas ekspor.** Ada lembar Bonus baru di "
            "workbook hasil rekonsiliasi, dan tombol Export di halaman "
            "Rekonsiliasi Bonus yang mengikuti rentang tanggal serta filter "
            "kategori yang sedang dipakai. Berlaku untuk semua merek, dan "
            "berlaku surut untuk batch lama.",
            "**File yang jenisnya tak dikenali sekarang berkata tidak tahu.** "
            "Sebelumnya file asing tampil sebagai tebakan yang terlihat "
            "meyakinkan — pilihan pertama pada daftar jenis — sehingga sekali "
            "Simpan ditekan file itu benar-benar terbaca sebagai jenis yang "
            "salah. Kini jenisnya kosong sampai dipilih, dan penyimpanan "
            "ditolak dengan pesan yang menyebut nama file-nya.",
        ),
    ),
    Rilis(
        versi="1.18.1",
        tanggal=_dt.date(2026, 8, 13),
        nama="QRIS Flyer Format Baru — Uang yang Hilang Tanpa Pesan",
        jenis=PATCH,
        commit="",
        sorotan=(
            "**Laporan QRIS Flyer bentuk baru terbaca utuh.** Vendor kembali "
            "mengganti nama kolom di file ekspornya — kali ini kolom tanggal. "
            "Tiket dan nominalnya masih terbaca benar, jadi unggahannya "
            "dilaporkan BERHASIL, tetapi baris tanpa tanggal tak pernah terlihat "
            "oleh pencocokan maupun laporan. Akibatnya 339 baris LTN 12 Agustus "
            "berhenti di \"Belum ada uang masuk\" padahal uangnya sudah masuk. "
            "Setelah diperbaiki: 339 dari 339 cocok, dan Panel ↔ Mutasi Bank hari "
            "itu naik dari 674 menjadi 1.002 dari 1.148.",
            "**Ganti nama kolom sekarang jauh lebih sulit menjatuhkan aplikasi.** "
            "Nama kolom dicocokkan tanpa mempedulikan huruf besar/kecil, spasi, "
            "maupun garis bawah — sehingga variasi penulisan yang sama tak lagi "
            "perlu perbaikan program. Dua brand lain yang diam-diam terkena "
            "masalah serupa ikut pulih tanpa penyesuaian tersendiri.",
            "**Dan kalau format barunya tetap tak dikenali, aplikasi berhenti dan "
            "bilang — tidak lagi diam.** Setiap file yang barisnya masuk tanpa "
            "satu pun tanggal kini ditolak sejak awal, dengan pesan yang menyebut "
            "nama kolom di file itu dan meminta file dikirim ke pengembang. "
            "Berlaku untuk semua jenis sumber, bukan cuma QRIS Flyer. Penolakan "
            "yang terlihat jauh lebih murah daripada uang yang hilang diam-diam.",
            "**Baris lama yang terlanjur masuk tanpa tanggal bisa dipulihkan di "
            "tempat**, tanpa mengunggah ulang apa pun, karena aplikasi menyimpan "
            "seluruh kolom asli setiap file. Pemulihan ini juga menjaga agar file "
            "yang sama tidak terhitung dua kali bila kelak diunggah lagi.",
        ),
    ),
    Rilis(
        versi="1.18.0",
        tanggal=_dt.date(2026, 8, 13),
        nama="Percepatan Menyeluruh — Halaman Berat Jadi Ringan",
        jenis=MINOR,
        commit="",
        sorotan=(
            "**Dashboard toko besar terbuka di bawah 1 detik, sebelumnya hampir 15 "
            "detik.** Data sudah tumbuh ke 6 juta baris, sementara cara aplikasi "
            "mencari baris masih dirancang saat datanya masih kecil: untuk "
            "menampilkan ringkasan satu hari, aplikasi membaca seluruh riwayat "
            "toko. Sekarang ia langsung menuju baris yang dibutuhkan.",
            "**Semua halaman laporan ikut ringan.** Rincian Rekening 1,9 → 0,4 "
            "detik, Breakdown Bracket 1,5 → 0,8 detik, Detail FR 1,4 → 0,7 detik, "
            "Rekap Bulanan 3,3 → 1,4 detik, Rekonsiliasi Bonus 1,0 → 0,6 detik. "
            "Halaman Settlement Tertunda tak lagi tersendat saat antreannya panjang, "
            "dan Rincian Biaya berhenti menghitung ulang label sumber untuk setiap "
            "baris — kini sekali saja per file dan rekening.",
            "**Tidak ada satu angka pun yang berubah.** Yang dipercepat adalah cara "
            "aplikasi mencari datanya, bukan cara ia menghitungnya. Setiap angka di "
            "layar dikunci lebih dulu oleh pengujian sebelum jalurnya disentuh, dan "
            "dibandingkan lagi sesudahnya pada data produksi yang sama.",
            "Aplikasi juga sanggup melayani empat kali lebih banyak permintaan "
            "bersamaan, sehingga beberapa orang yang membuka halaman berat pada "
            "saat yang sama tak lagi saling menunggu.",
            "**Hasil rekonsiliasi kini dijamin sama setiap kali dijalankan.** "
            "Pemeriksaan menemukan bahwa ketika dua kemungkinan pasangan sama "
            "kuatnya, pemenangnya selama ini ditentukan oleh urutan baris yang "
            "kebetulan dikembalikan basis data — sehingga jumlah \"Cocok\" bisa "
            "berbeda antar-penjalanan untuk data yang sama persis. Urutannya kini "
            "ditetapkan, dan aturan pencocokannya sendiri tidak berubah sedikit pun.",
            "Beberapa halaman juga tak lagi bisa dimatikan oleh tanggal yang "
            "ekstrem: memutar tahun di kolom tanggal sampai ujung kalender dulu "
            "membuat halaman gagal terbuka; sekarang ia menampilkan hasil kosong "
            "sebagaimana mestinya.",
        ),
    ),
    Rilis(
        versi="1.17.4",
        tanggal=_dt.date(2026, 8, 12),
        nama="QRIS ZPay Penamaan Status Baru & Peringatan Gateway Lebih Tenang",
        jenis=PATCH,
        commit="",
        sorotan=(
            "**Laporan QRIS ZPay terbaca lagi.** Vendor mengganti penamaan status "
            "transaksinya (dari `paid`/`settled` menjadi `done`/`unpaid`), sehingga "
            "berkas 11 Agustus ditolak seluruhnya. Diuji pada berkas asli STN "
            "11 Agustus 2026: **564 dari 564 deposit QRIS ZPay cocok** lewat nomor "
            "tiket — nomor tiket di laporan ZPay memang sudah menjadi acuan utama "
            "sejak awal, tanpa perlu mencocokkan nama pemain atau kode RRN. Batch "
            "hari itu naik dari 360 menjadi 924 transaksi cocok.",
            "Penolakannya sendiri bekerja sebagaimana mestinya: aplikasi berhenti "
            "sambil menyebutkan status apa saja yang ditemukannya, alih-alih "
            "melaporkan “berhasil” dengan nol baris. Status `unpaid` (QRIS yang "
            "dibuat lalu ditinggalkan pemain) tetap **sengaja tidak dihitung sebagai "
            "uang**, dan pesannya kini membedakan berkas yang memang tak berisi "
            "pembayaran sukses dari berkas berpenamaan asing.",
            "**Peringatan oranye “kode transaksi tidak dikenal panel” tidak lagi "
            "muncul palsu.** Sebelumnya peringatan itu bisa menuduh berkas gateway "
            "yang sepenuhnya benar hanya karena kebetulan diunggah sebelum berkas "
            "panel hari yang sama — pada satu kiriman nyata, 224 transaksi dituduh "
            "asing padahal ke-224-nya ada di panel yang masuk beberapa detik "
            "kemudian. Peringatan kini menunggu panel arah yang sama untuk tanggal "
            "itu, sehingga urutan unggah tidak lagi mengubah putusannya.",
        ),
    ),
    Rilis(
        versi="1.17.3",
        tanggal=_dt.date(2026, 8, 10),
        nama="Laporan QR Flyer Bentuk Ketiga & Penjaga Kolom",
        jenis=PATCH,
        commit="",
        sorotan=(
            "**Laporan QR Flyer bentuk ketiga kini terbaca penuh.** Vendor kembali "
            "mengganti penamaan kolom (`Transaction Id`, `Amount`, `Callback`), dan "
            "bentuk ini dipakai beberapa brand sejak awal Agustus. Diuji pada berkas "
            "asli HKW 1 Agustus 2026: **1.518 dari 1.519 transaksi cocok** lewat nomor "
            "tiket — satu sisanya memang tidak ada di panel.",
            "Kegagalan sebelumnya jauh lebih berbahaya daripada sekadar tidak terbaca: "
            "berkasnya **masuk**, tetapi seluruh isinya kosong — tanpa nomor tiket, "
            "nominal Rp0, tanpa tanggal. Data yang mengaku data. Akibatnya deposit "
            "QRIS Flyer tampak tidak punya uang masuk sama sekali; pada satu batch "
            "saja 1.517 transaksi tertahan di daftar “Tidak Cocok”.",
            "**Kolom kini dikenali dari daftar nama yang mungkin, bukan satu bentuk "
            "tetap** — jadi penggantian nama berikutnya tidak otomatis merusak. Dan "
            "bila kolom nomor tiket atau nominal benar-benar tidak ditemukan, "
            "aplikasi **menolak berkasnya** sambil menyebutkan kolom apa saja yang "
            "ada di dalamnya, alih-alih memasukkan baris kosong diam-diam.",
        ),
    ),
    Rilis(
        versi="1.17.2",
        tanggal=_dt.date(2026, 8, 10),
        nama="QRIS ZPay Terbukti Cocok 69/69",
        jenis=PATCH,
        commit="",
        sorotan=(
            "**Laporan QRIS ZPay kini cocok penuh dengan panel.** Diuji pada berkas "
            "asli 6 Agustus 2026: **69 dari 69 transaksi cocok** lewat nomor tiket — "
            "nomor tiket, nomor pesanan, dan nominalnya sama persis, dan panel "
            "menyetujuinya rata-rata 3 detik setelah pembayaran tercatat di ZPay. "
            "Rekonsiliasi hari itu naik dari 641 menjadi **710 dari 724 transaksi**.",
            "Penyebab sebelumnya: kolom status di laporan ZPay punya dua nilai yang "
            "sama-sama berarti uang sungguhan — “paid” (sudah dibayar) dan “settled” "
            "(dananya sudah cair) — sedangkan aplikasi hanya menerima yang pertama. "
            "Seluruh isi berkas ikut terbuang tanpa pesan apa pun. Kini keduanya "
            "diterima.",
            "**Kegagalan diam-diam seperti itu tidak boleh terulang.** Bila sebuah "
            "berkas ZPay berisi transaksi tetapi tak satu pun bisa dibaca, aplikasi "
            "kini menolak berkasnya dan menyebutkan status apa yang ditemukannya — "
            "jauh lebih baik daripada melaporkan “berhasil diunggah” padahal nol "
            "baris masuk. Berkas yang memang kosong tetap diterima seperti biasa.",
        ),
    ),
    Rilis(
        versi="1.17.1",
        tanggal=_dt.date(2026, 8, 10),
        nama="Koreksi Jam Laporan QRIS ZPay",
        jenis=PATCH,
        commit="",
        sorotan=(
            "**Jam pada laporan QRIS ZPay ternyata memakai waktu GMT+0, bukan waktu "
            "Indonesia Barat.** Aplikasi kini menggesernya 7 jam saat berkas dibaca, "
            "sehingga setiap transaksi tercatat pada hari dan jam yang sebenarnya. "
            "Salinan mentah dari vendor tetap disimpan apa adanya untuk keperluan audit.",
            "Tanpa koreksi ini setoran akan tercatat 7 jam lebih awal daripada catatan "
            "panelnya sendiri — dan karena aplikasi menolak memasangkan uang yang "
            "seolah masuk sebelum transaksinya terjadi, pasangannya tidak akan pernah "
            "ketemu meskipun nomor tiketnya sama persis. Perbaikan ini terbit sebelum "
            "berkas ZPay pertama diunggah, jadi tidak ada data lama yang perlu diperbaiki.",
            "Temuan ini sekaligus menjelaskan berkas contoh 6 Agustus 2026: isinya "
            "sesungguhnya transaksi dini hari **7 Agustus** (00:01–06:52 WIB), bukan "
            "6 Agustus. Laporan ZPay untuk tanggal 6 Agustus sendiri belum pernah "
            "dikirim vendor, sehingga masih perlu diminta ulang dengan rentang waktu "
            "Indonesia yang disebutkan tegas.",
        ),
    ),
    Rilis(
        versi="1.17.0",
        tanggal=_dt.date(2026, 8, 10),
        nama="QRIS ZPay & Laporan Flyer Versi Vendor",
        jenis=MINOR,
        commit="",
        sorotan=(
            "**Laporan QR Flyer versi vendor kini terbaca kembali.** Sejak laporan itu tidak "
            "bisa diunduh sendiri dan harus diminta ke vendor, penamaan kolomnya berubah — "
            "isinya tetap sama, hanya nama kolomnya. Aplikasi kini mengenali kedua bentuk "
            "sekaligus, jadi berkas lama maupun baru sama-sama masuk. Diuji pada berkas asli "
            "6 Agustus 2026: **120 dari 120 transaksi cocok dengan panel**.",
            "Kegagalan sebelumnya memang sulit disadari: berkasnya tetap dilaporkan “berhasil "
            "diunggah”, tetapi nol baris masuk, karena aplikasi tidak menemukan satu pun kolom "
            "yang dikenalnya lalu menganggap seluruh isi berkas sebagai baris penutup. Kini "
            "berkas versi vendor dikenali langsung dari kolomnya, bukan sekadar dari nama file.",
            "**Gateway QRIS baru — ZPay (ZETPAY) — kini didukung.** Nomor tiketnya dibaca "
            "sebagai kunci pencocokan utama, lengkap dengan nominal bruto, biaya, dan nama "
            "pemain yang diambil dari nomor pesanan. Catatan penting: pada berkas contoh "
            "pertama, seluruh tiket ZPay belum ditemukan di ekspor panel yang menyertainya, "
            "sehingga transaksinya akan tampil sebagai “uang tanpa panel” sampai ekspor panel "
            "yang memuatnya ikut diunggah.",
        ),
    ),
    Rilis(
        versi="1.16.1",
        tanggal=_dt.date(2026, 8, 8),
        nama="Angka pada Tombol Pilihan Kini Jujur",
        jenis=PATCH,
        commit="",
        sorotan=(
            "**Angka kecil di tiap tombol pilihan halaman Detail FR/Bracket kini selalu "
            "sama dengan jumlah baris yang muncul saat tombol itu diklik.** Sebelumnya "
            "angkanya dihitung tanpa memperhatikan pilihan lain yang sedang aktif, sehingga "
            "tombol bertuliskan “Beban Admin Bank 95” bisa berujung hanya 2 baris begitu "
            "sebuah rekening ikut dipilih.",
            "Tombol pilihan yang isinya nol kini disembunyikan — sebelumnya ia tetap tampil "
            "padahal hanya menuntun ke halaman kosong. Pilihan yang sedang aktif tetap "
            "ditampilkan meski hasilnya kosong, supaya tidak ada yang kehilangan jejak "
            "pilihannya sendiri.",
            "Tombol **Semua** kini juga menyertakan jumlahnya, mengikuti aturan yang sama.",
        ),
    ),
    Rilis(
        versi="1.16.0",
        tanggal=_dt.date(2026, 8, 8),
        nama="Dari Angka Langsung ke Isinya",
        jenis=MINOR,
        commit="",
        sorotan=(
            "**Rincian sebuah angka kini bisa dibuka langsung dari selnya.** Klik angka di "
            "Control Bracket seperti biasa, dan pada panel yang muncul kini ada tautan "
            "“Lihat sekian baris penyusunnya” — tidak perlu lagi berpindah menu lalu "
            "memilih ulang rekening, kategori, dan tanggalnya.",
            "Cara mengoreksi angka **tidak berubah sama sekali**: tetap satu klik, form yang "
            "sama, di tempat yang sama. Tautan rincian hanyalah tambahan di dalam panel itu, "
            "bukan langkah baru yang harus dilewati lebih dulu — mengoreksi adalah pekerjaan "
            "harian dan tidak boleh jadi lebih lambat demi keperluan yang sesekali.",
            "Kolom **Saldo Awal** dan **Saldo Akhir** sengaja tidak diberi tautan. Keduanya "
            "adalah posisi saldo pada satu titik waktu, bukan hasil penjumlahan baris mana "
            "pun, sehingga menautkannya ke sebuah daftar transaksi justru akan menyesatkan.",
        ),
    ),
    Rilis(
        versi="1.15.0",
        tanggal=_dt.date(2026, 8, 8),
        nama="Detail FR/Bracket",
        jenis=MINOR,
        commit="",
        sorotan=(
            "**Halaman baru: Detail FR/Bracket.** Selama ini Control Bracket menjawab "
            "“berapa”, tapi tidak “isinya apa saja”. Kalau sel Adjustment sebuah rekening "
            "tertulis 450.000, satu-satunya cara mengetahui isinya adalah membuka kembali "
            "berkas FR-nya. Sekarang cukup memilih rekening dan kategorinya, lalu seluruh "
            "baris penyusunnya tampil lengkap dengan jam, member, keterangan, nominal, dan "
            "saldo berjalannya.",
            "Berlaku untuk **semua kategori dan semua rekening** — Deposit, Withdrawal, "
            "Sesama CM, Beban Admin, Biaya Transaksi, dan seterusnya — serta bisa disaring "
            "per rentang tanggal atau dicari bebas berdasarkan keterangan, member, maupun "
            "username.",
            "Angkanya dijamin **selalu sama dengan halaman Breakdown**: aturan hitungnya "
            "satu sumber, dan kesamaannya dikunci uji otomatis untuk setiap sel, bukan "
            "sekadar diperiksa sekali. Bila sebuah sel pernah dikoreksi manual, halaman ini "
            "menyebutkannya terang-terangan — nilai tampil sekian, isi aslinya sekian — "
            "supaya selisihnya tidak pernah jadi teka-teki.",
        ),
    ),
    Rilis(
        versi="1.14.2",
        tanggal=_dt.date(2026, 8, 7),
        nama="Peringatan Menyebut Berkas yang Benar",
        jenis=PATCH,
        commit="",
        sorotan=(
            "**Peringatan unggahan kini menyebut nama berkas yang benar.** Sesaat setelah "
            "perbaikan sebelumnya, dua dari tiga peringatan keliru mencantumkan nama berkas "
            "lain — isinya tepat, labelnya bukan berkas yang sedang diperiksa. Justru itu "
            "yang paling membingungkan: orang mencari berkas yang sebenarnya tidak "
            "bermasalah.",
            "Angka dan penilaian peringatan tidak berubah sama sekali; hanya nama berkas "
            "yang ditampilkan yang dibetulkan.",
            "Ditemukan lewat pemeriksaan pada data produksi sungguhan, bukan dari pengujian "
            "otomatis — karena itu pemeriksaan namanya kini ikut dikunci uji agar tidak "
            "terulang.",
        ),
    ),
    Rilis(
        versi="1.14.1",
        tanggal=_dt.date(2026, 8, 7),
        nama="Penjaga yang Tahu Bedanya",
        jenis=PATCH,
        commit="",
        sorotan=(
            "**Peringatan “jumlah baris tidak wajar” tidak lagi salah tuduh.** Pada panel "
            "Vigor/TM Gaming, satu jenis sumber sebenarnya memuat dua jenis berkas yang "
            "volumenya sangat berbeda — panel QRIS (ribuan baris) dan panel biasa untuk "
            "bank (ratusan baris) — dan berkas bank pun terpisah per rekening. Sebelumnya "
            "semuanya dibandingkan dalam satu kelompok, sehingga berkas yang sepenuhnya "
            "normal ikut ditegur. Kini tiap jenis berkas punya kebiasaannya sendiri, "
            "dikenali dari pola penamaan yang dipakai pengunggah.",
            "Ikutannya, hasil peringatan tidak lagi bergantung pada urutan berkas diunggah. "
            "Sebelumnya berkas yang diproses belakangan dinilai terhadap kebiasaan yang "
            "baru saja bergeser oleh berkas sebelumnya dalam kiriman yang sama.",
            "Bila pola penamaan sebuah berkas berubah, peringatan volumenya **berhenti "
            "sementara** untuk berkas itu sampai terkumpul lima kali unggahan dengan pola "
            "baru — sengaja diam daripada menuduh berdasarkan pembanding yang keliru. "
            "Dua pemeriksaan lain, yaitu tanggal isi berkas dan kecocokan kode transaksi "
            "gateway dengan panel, tidak terpengaruh dan tetap berjalan penuh.",
        ),
    ),
    Rilis(
        versi="1.14.0",
        tanggal=_dt.date(2026, 8, 7),
        nama="Penjaga Salah Unggah",
        jenis=MINOR,
        commit="",
        sorotan=(
            "**Aplikasi kini memperingatkan saat sebuah file sepertinya salah tarik.** "
            "Begitu file selesai diunggah, tiga hal diperiksa: apakah tanggal isinya jauh "
            "dari tanggal di nama filenya, apakah jumlah barisnya melenceng jauh dari "
            "kebiasaan sumber itu di toko tersebut, dan — khusus file gateway — apakah kode "
            "transaksinya benar-benar dikenal panel hari itu. Sebelumnya kesalahan seperti ini "
            "baru ketahuan berhari-hari kemudian lewat ribuan baris tidak cocok yang harus "
            "ditelusuri satu per satu.",
            "Peringatannya **tidak menghalangi**. File tetap masuk dan pekerjaan tetap jalan; "
            "yang diberikan hanyalah angkanya, supaya orang yang paling tahu — pengunggahnya — "
            "bisa menilai sendiri. Ketiga pemeriksaan juga sengaja diam saat buktinya tipis, "
            "misalnya pada brand baru yang belum punya kebiasaan pembanding, karena penjaga "
            "yang sering salah tuduh akan berhenti dibaca orang.",
            "Kartu **Kelengkapan Data** kini membedakan “belum diunggah” dari “sudah terpakai”. "
            "Dulu keduanya tampil sama-sama abu-abu bertulis “opsional”, sehingga file yang "
            "sebenarnya sudah masuk dan sudah dipakai rekonsiliasi terbaca seolah tidak "
            "terdeteksi. Sekarang baris seperti itu menyebutkan jumlah barisnya dan batch "
            "mana yang memakainya.",
            "Saat rekonsiliasi ditolak karena ada tanggal tanpa panel penutup, saran "
            "“jalankan sebagian dulu” kini berupa **tautan yang langsung mengisikan filternya**. "
            "Sebelumnya pesan itu menyuruh mengisi sebuah kolom yang tersembunyi di dalam "
            "panel “Filter lanjutan” yang tertutup.",
        ),
    ),
    Rilis(
        versi="1.13.0",
        tanggal=_dt.date(2026, 8, 1),
        nama="Filter Bank Menyeluruh, Upload Ketiban & Cari Toko",
        jenis=MINOR,
        commit="",
        sorotan=(
            "Tab **“Perlu Ditinjau”** dan **“Tidak Cocok”** kini punya filter bank juga. "
            "Sebelumnya, pada toko berpanel Vigor/TM Gaming, seluruh baris filter menghilang "
            "begitu saja karena sebagian transaksi memang tidak membawa nama bank sama sekali. "
            "Baris seperti itu sekarang dikumpulkan sebagai **“(Tanpa Bank)”** — jadi bisa "
            "disaring seperti bank lain, bukan lagi menyembunyikan filternya dari semua orang. "
            "Mengurutkan kolom maupun berpindah ke tab **Deposit/Withdraw** juga tidak lagi "
            "membuang filter bank yang sedang dipakai.",
            "Transaksi **QRIS** pada panel Gacor25 kini berlabel QRIS, bukan kosong. "
            "Efeknya terasa di tiga tempat: kolom Bank Title terisi, kartu **“Metode Pembayaran”** "
            "di dashboard tidak lagi menghitungnya sebagai “Lainnya”, dan filter banknya punya "
            "pilihan yang berarti. Tersedia perintah pengisian ulang untuk data lama.",
            "**Upload ulang file mutasi yang lebih lengkap kini menandai file lama “Ketiban”.** "
            "Tarikan bank kadang terpotong di bagian bawah; begitu versi utuhnya diunggah dengan "
            "nama yang sama, sistem memeriksa bahwa seluruh isi file lama benar-benar tercakup, "
            "lalu memberi tanda di Riwayat Upload dan di daftar file halaman Mutasi Bank. "
            "**Tidak ada data yang dihapus** — file lama tetap utuh sebagai jejak audit, dan "
            "tandanya hilang sendiri bila file penggantinya dihapus.",
            "Pemilih **Toko** di bilah atas kini punya kotak pencarian: ketik “25” dan daftar "
            "16 toko langsung menyusut ke yang cocok, lengkap dengan navigasi papan ketik. "
            "Tidak perlu lagi menggulir daftar panjang berisi kode-kode yang mirip.",
        ),
    ),
    Rilis(
        versi="1.12.2",
        tanggal=_dt.date(2026, 7, 27),
        nama="Penolakan Rekonsiliasi yang Menuntun",
        jenis=PATCH,
        commit="",
        sorotan=(
            "Saat rekonsiliasi ditolak karena ada tanggal ber-uang tanpa panel penutup, "
            "pesannya kini menyebut **panel tanggal berapa** yang dibutuhkan tiap baris "
            "(mis. “butuh panel 23/07 atau 24/07”) — sebelumnya pemakai harus menebak sendiri.",
            "Pesan yang sama menawarkan jalan keluar kedua: menjalankan sebagian dulu dengan "
            "mengisi “Dari tanggal” pada tanggal aman terdekat. Baris lama tetap menunggu "
            "sampai panelnya diupload, jadi tak ada yang hilang atau salah dihitung.",
            "Tanggal yang sudah pernah direkonsiliasi tidak lagi ikut memblokir. Mutasi bank "
            "biasa diekspor berputar sehingga unggahan hari ini kerap membawa baris baru "
            "bertanggal lampau; baris seperti itu memang sudah punya jalurnya sendiri "
            "(ditulis balik ke batch tanggalnya), sehingga menahan seluruh rekonsiliasi "
            "karenanya cuma menyuruh pemakai mengupload panel yang sebenarnya sudah ada.",
        ),
    ),
    Rilis(
        versi="1.12.1",
        tanggal=_dt.date(2026, 7, 27),
        nama="Filter Sumber Panel↔Bracket",
        jenis=PATCH,
        commit="",
        sorotan=(
            "Pada hasil Panel↔Bracket, tab “Tidak Ada di Panel” punya filter "
            "“bank/sumber” yang sebelumnya hanya berisi satu pilihan bertuliskan "
            "“Bracket” — tidak ada gunanya untuk menyaring. Sekarang isinya rekening "
            "FR yang sebenarnya (mis. “BANK BCA — HENDI · WITHDRAW”, “QRIS FLYER · "
            "DEPOSIT / WITHDRAW”), ditulis sama seperti di halaman Breakdown "
            "FR/Bracket dan lengkap dengan jumlah barisnya.",
            "Perbaikan yang sama berlaku di Area Pengecekan, supaya daftar kerja "
            "lintas hari bisa disaring per rekening FR juga.",
            "Yang tidak berubah: pencocokan dengan bank atau gateway tetap "
            "menampilkan nama banknya (BRI, BCA, Mandiri, NXPay, …) seperti "
            "sebelumnya. Baris FR yang kolom rekeningnya kosong dikelompokkan "
            "sebagai “(Tanpa Akun)” — bukan disembunyikan.",
        ),
    ),
    Rilis(
        versi="1.12.0",
        tanggal=_dt.date(2026, 7, 26),
        nama="Dashboard Bisa Menoleh ke Belakang",
        jenis=MINOR,
        commit="",
        sorotan=(
            "Dashboard kini punya filter tanggal: isi Dari–Sampai lalu Terapkan untuk melihat "
            "potret hari yang sudah lewat, atau menjumlahkan seluruh rekonsiliasi dalam satu "
            "rentang (mis. sepekan). Tombol “Terbaru” mengembalikan tampilan ke rekonsiliasi "
            "terakhir. Tanpa mengisi filter, dashboard tetap seperti sebelumnya.",
            "Dalam mode rentang, Ringkasan Panel, Metode Pembayaran, Ringkasan Bracket, tren "
            "selisih, dan daftar rekonsiliasi semuanya mengikuti rentang yang dipilih; jumlah "
            "batch yang tercakup ditulis apa adanya agar angkanya tak salah dibaca sebagai satu hari.",
            "Filter yang sama tersedia di dashboard mode “Semua Toko” untuk admin — satu rentang, "
            "seluruh toko, termasuk kolom rekon terakhir per toko di dalam rentang itu.",
            "Panel “Kerjakan hari ini” sengaja TIDAK ikut filter: daftar kerja tetap menunjuk "
            "rekonsiliasi terakhir yang sebenarnya, supaya menengok data lama tak pernah "
            "mengubah apa yang harus dikerjakan hari ini.",
        ),
    ),
    Rilis(
        versi="1.11.0",
        tanggal=_dt.date(2026, 7, 26),
        nama="Tiga Panel & Rekap Bulanan",
        jenis=MINOR,
        commit="1cff0a9",
        sorotan=(
            "Rekonsiliasi Panel↔Bracket kini berjalan untuk brand berpanel Vigor/TM Gaming yang "
            "ekspornya tanpa nomor tiket — baris dicocokkan lewat username + nominal. Uji dengan data "
            "nyata COR: 10.069 dari 10.072 baris (99,97%) cocok otomatis. Saat aturan baru ini yang "
            "bekerja, halaman hasil mencantumkan mode pencocokannya.",
            "Pencocokan sisi uang mengenal jangkar baru: nomor rekening tujuan dari laporan gateway "
            "(UNO) yang sama persis dengan rekening pemain di panel — pelengkap kunci UUID yang sudah "
            "ada, hanya dipakai bila nominalnya juga sama persis.",
            "Dashboard menampilkan kartu Ringkasan Bracket — total deposit, penarikan, dan bersih "
            "menurut catatan FR/Bracket hari itu — berdampingan dengan Ringkasan Panel, dan angkanya "
            "selalu klop dengan halaman Breakdown (termasuk koreksi sel yang pernah disimpan).",
            "Halaman baru Rekap Bulanan meniru rekap Excel yang selama ini disusun manual: empat seksi "
            "(Net Profit, Sisa Dana Member, Total Dana Lebih Web, Selisih beserta penyebabnya), angka "
            "otomatis dihitung dari data harian, dan isian manual bisa menimpa angka otomatis dengan "
            "jejak siapa-dan-kapan.",
            "Mode “Semua Toko” untuk admin: dashboard gabungan seluruh toko sekali pandang — kalender "
            "status, ringkasan Panel/Bracket/Metode gabungan, dan tabel per toko — plus filter ceklis "
            "beberapa toko sekaligus di halaman Hutang/Piutang.",
            "Gembok alamat IP untuk akun auditor & supervisor: hanya alamat internet yang terdaftar "
            "yang bisa masuk; admin tidak pernah terkunci; selama daftar kosong fitur ini tidur. "
            "Dikelola dari halaman admin sendiri; penolakan tercatat di jejak audit (satu catatan "
            "per sesi per alamat).",
            "Penarikan berlabel bank “OTH” pada brand Vigor/TM kini menampilkan bank aslinya (dibaca "
            "dari teks transaksi), dan nama penerima transfer BRI yang tadinya kosong kini terisi — "
            "untuk nama BRI berlaku otomatis termasuk data lama; untuk label OTH data lama tersedia "
            "perintah perapihan sekali jalan, tanpa perlu unggah ulang berkas.",
            "Setiap toko kini dikelompokkan menurut panelnya (Nexus / Vigor / TM Gaming) di pemilih "
            "toko, dan jenis panel wajib dipilih saat membuat toko baru.",
        ),
    ),
    Rilis(
        versi="1.10.0",
        tanggal=_dt.date(2026, 7, 25),
        nama="Transparansi Versi",
        jenis=MINOR,
        commit="",
        sorotan=(
            "Aplikasi kini punya nomor versi resmi yang tampil di menu samping dan halaman masuk, "
            "sehingga jelas versi mana yang sedang dipakai saat melaporkan kendala.",
            "Halaman Riwayat Versi baru: seluruh rilis sejak awal beserta isinya, bisa dibuka siapa saja "
            "yang punya akses aplikasi.",
            "Catatan perubahan resmi (CHANGELOG) dibuat otomatis dari satu sumber data, "
            "dijaga pengujian agar tidak pernah melenceng dari kenyataan.",
            "Setiap berkas Excel hasil ekspor mencantumkan versi aplikasi yang membuatnya — "
            "penting bila hasil lama perlu ditelusuri ulang.",
        ),
        catatan="Riwayat 0.1.0–1.9.0 di bawah ini disusun retroaktif dari catatan perubahan kode.",
    ),
    Rilis(
        versi="1.9.0",
        tanggal=_dt.date(2026, 7, 23),
        nama="Kode Unik & Kunci Wilayah",
        jenis=MINOR,
        commit="e4a055b",
        sorotan=(
            "Deposit berkode unik — uang masuk sedikit lebih besar dari nominal panel karena pemain "
            "menambahkan kode (selisih maksimal Rp999) — langsung dinyatakan cocok, tidak lagi mengantre "
            "pemeriksaan manual. Kelebihan bayar besar tetap ditinjau.",
            "Pembatasan akses aplikasi per wilayah negara, lengkap dengan halaman penolakan. Celah yang "
            "memungkinkan orang luar menyamar sebagai pengunjung dari wilayah yang diizinkan ditemukan "
            "saat pengujian dan ditutup pada hari yang sama.",
            "Keputusan manual auditor mengunci barisnya ke laporan asal — keputusan tidak bisa lagi "
            "tertimpa hasil otomatis di hari berikutnya sehingga tampak batal sendiri.",
            "Tabel Riwayat Batch menampilkan kolom Tidak Cocok, sehingga ketiga status terlihat sekaligus.",
            "Tab “Tidak Ada di Panel” bisa disaring per bank/sumber uang, dan Rincian Rekening "
            "memakai filter rentang Dari/Sampai seragam dengan Rincian Biaya.",
        ),
    ),
    Rilis(
        versi="1.8.0",
        tanggal=_dt.date(2026, 7, 21),
        nama="Kedalaman Analisis",
        jenis=MINOR,
        commit="f7fb5a1",
        sorotan=(
            "Kartu Metode Pembayaran di halaman utama memecah nilai deposit dan penarikan menurut "
            "QRIS, e-wallet, dan bank.",
            "Setiap keputusan Setujui/Tinjau kini menyertakan alasan dari daftar baku plus catatan bebas, "
            "tersimpan di jejak audit — pertanggungjawaban keputusan jadi jelas.",
            "Breakdown FR/Bracket bisa dilihat untuk rentang tanggal, dengan saldo awal otomatis dibawa "
            "dari penutupan hari sebelumnya.",
            "Rekonsiliasi Bonus menampilkan nama program promo dan bisa disaring per kategori.",
            "Berkas Excel hasil rekonsiliasi otomatis menyertakan lembar Breakdown Bracket dan "
            "Rincian Rekening.",
            "Semua tabel besar bisa diseleksi persegi dengan mouse lalu disalin dan ditempel langsung "
            "ke Excel dengan kolom tetap rapi.",
        ),
    ),
    Rilis(
        versi="1.7.0",
        tanggal=_dt.date(2026, 7, 20),
        nama="Rekonsiliasi Bonus",
        jenis=MINOR,
        commit="676d03f",
        sorotan=(
            "Halaman Rekonsiliasi Bonus: catatan bonus dan promo dari panel dicocokkan dengan catatan "
            "bonus di bracket. Jalurnya terpisah penuh dari rekonsiliasi harian, jadi tidak bisa "
            "mengganggu proses deposit/penarikan.",
            "Aksi massal Setujui/Tinjau lintas hari langsung dari Area Pengecekan.",
            "Halaman utama menampilkan strip Ringkasan Panel — jumlah transaksi dan nilai deposit/penarikan "
            "laporan terakhir (permintaan klien).",
            "Penarikan yang terpotong biaya antarbank kembali terdeteksi: kasus nyata penarikan Rp400.000 "
            "yang di mutasi tercatat Rp406.500 sebelumnya dilaporkan tanpa pasangan.",
            "Identitas visual baru dan penataan ulang menu samping.",
        ),
    ),
    Rilis(
        versi="1.6.0",
        tanggal=_dt.date(2026, 7, 18),
        nama="Koreksi FR, Hutang/Piutang & Rincian Biaya",
        jenis=MINOR,
        commit="80e6c41",
        sorotan=(
            "Auditor bisa memperbaiki satu angka yang salah di tabel Control Bracket lewat popup — "
            "data asli hasil impor tidak diubah, total dan Selisih Kontrol langsung dihitung ulang, "
            "sel yang dikoreksi ditandai, dan setiap perubahan tercatat di log audit.",
            "Halaman Hutang/Piutang mengumpulkan seluruh catatan hutang dan piutang lintas tanggal "
            "beserta totalnya.",
            "Halaman Rincian Biaya merekap biaya administrasi bank per rekening dan per kanal "
            "(e-wallet Rp1.000, BI Fast Rp2.500, transfer online Rp6.500).",
            "Biaya administrasi di mutasi BRI dan Mandiri dikenali sejak impor sehingga tidak lagi "
            "mencemari total penarikan — aturannya dikalibrasi pada 8.937 baris data produksi dan "
            "diuji bebas salah-tandai pada 662 baris biaya Mandiri.",
            "Dukungan berkas gateway RafflesPay versi Excel untuk brand BBS, setoran maupun penarikan.",
            "Pencarian nama berkas di Riwayat Upload, pencatatan nama berkas saat hapus massal, "
            "dan penggantian nama toko dari panel admin.",
        ),
    ),
    Rilis(
        versi="1.5.0",
        tanggal=_dt.date(2026, 7, 15),
        nama="Mutasi BNI",
        jenis=MINOR,
        commit="c2a2612",
        sorotan=(
            "Rekening BNI bisa diunggah langsung dalam bentuk e-statement PDF; aplikasi membedakannya "
            "sendiri dari PDF BCA tanpa perlu dipilih manual.",
            "Nomor HP pelanggan yang di mutasi BNI menempel pada nomor virtual account e-wallet "
            "dipisahkan, sehingga penarikan lewat e-wallet punya identitas untuk dicocokkan.",
            "Penarikan antar-bank lewat BCA yang biaya transfernya menempel jadi satu baris debit "
            "kini ketemu pasangannya.",
        ),
    ),
    Rilis(
        versi="1.4.0",
        tanggal=_dt.date(2026, 7, 13),
        nama="Percepatan",
        jenis=MINOR,
        commit="f2016bf",
        sorotan=(
            "Tiga halaman terberat dipercepat, terukur pada data produksi: Kelola Toko dari 29,8 detik "
            "(praktis tidak bisa dibuka) menjadi 0,1 detik, dan halaman Impor Data dari 10,8 detik "
            "menjadi 0,01 detik. Angka yang ditampilkan tetap sama persis.",
            "Kapasitas server dinaikkan menjadi delapan jalur paralel — rekonsiliasi atau unggahan besar "
            "satu orang tidak lagi membuat pengguna lain menunggu.",
            "Seluruh skrip dan huruf tampilan dipindah ke dalam aplikasi sendiri; halaman tidak lagi bisa "
            "gagal tampil karena gangguan layanan pihak luar.",
            "Memilih satu berkas di Mutasi Bank kini menampilkan seluruh isinya, menjawab laporan "
            "“mutasi tidak terbaca penuh”.",
            "Riwayat Upload berhalaman sehingga berkas lama bisa dijangkau dan dihapus.",
            "Dukungan penarikan RafflesPay/QRIS RPAY untuk brand BBS — 6 dari 6 transaksi cocok pada "
            "verifikasi data nyata.",
            "Impor laporan COR/UNOPAY yang sempat gagal total kini normal, dan nama pemain pulih untuk "
            "353 baris sehingga pencocokan berbasis nama ikut pulih.",
        ),
    ),
    Rilis(
        versi="1.3.0",
        tanggal=_dt.date(2026, 7, 12),
        nama="Laporan FR/Bracket",
        jenis=MINOR,
        commit="fec2adb",
        sorotan=(
            "Halaman Breakdown FR/Bracket per rekening, mengikuti format laporan Control Bracket harian "
            "klien, lengkap dengan kolom Selisih Kontrol yang idealnya nol sehingga ketidakcocokan buku "
            "langsung terlihat.",
            "Perhitungan saldo awal dan akhir tidak lagi bergantung pada urutan baris yang sering diacak "
            "sumbernya: 21 dari 21 rekening selisih kontrolnya menjadi nol, dan selisih Rp5,95 juta yang "
            "selama ini tidak terjelaskan akhirnya cocok persis.",
            "Tiga halaman laporan baru: Ringkasan Bulanan, Rincian Rekening, dan Settlement Tertunda.",
            "Menu samping dikelompokkan agar tetap mudah ditelusuri saat daftar halaman bertambah.",
        ),
    ),
    Rilis(
        versi="1.2.1",
        tanggal=_dt.date(2026, 7, 11),
        nama="Perbaikan Penarikan E-wallet BRI",
        jenis=PATCH,
        commit="d864fed",
        sorotan=(
            "Penarikan ke DANA, GOPAY, OVO, ShopeePay, dan LinkAja lewat BRI sebelumnya selalu gagal "
            "dicocokkan karena nomor HP pemain menempel pada kode kanal di mutasi bank, sehingga semua "
            "transaksi menumpuk sebagai menunggu settlement. Pada kasus nyata, 15 dari 15 penarikan "
            "langsung cocok setelah perbaikan.",
            "Biaya Rp1.000 yang selalu mengikuti setiap penarikan e-wallet BRI tidak lagi dihitung "
            "sebagai transaksi — 182 baris palsu pada satu brand dalam 10 hari hilang dari daftar.",
            "Ketelitian pembacaan laporan gateway diperketat: baris tanpa nomor identitas tidak lagi "
            "dibuang karena dikira kembar, dan tanggal gaya Indonesia (09/07) dibaca sebagai 9 Juli, "
            "bukan 7 September.",
        ),
        catatan=(
            "Rilis perbaikan murni — tidak ada halaman atau kemampuan baru. Perbaikannya berlaku surut: "
            "data lama cukup dijalankan ulang rekonsiliasinya."
        ),
    ),
    Rilis(
        versi="1.2.0",
        tanggal=_dt.date(2026, 7, 10),
        nama="Keamanan Akun & Jejak Audit",
        jenis=MINOR,
        commit="5ad5640",
        sorotan=(
            "Pengguna baru — atau yang kata sandinya baru direset admin — wajib membuat kata sandi sendiri "
            "sebelum bisa membuka halaman apa pun. Kata sandi sementara dari admin tidak bisa dipakai "
            "terus-menerus.",
            "Halaman Log Audit mencatat siapa membuat, mengubah, mereset, atau menghapus pengguna dan toko, "
            "lengkap dengan waktunya. Nama pelaku ikut disimpan sebagai salinan sehingga jejaknya tetap "
            "terbaca walau akun orang itu kemudian dihapus.",
            "Setiap pengguna bisa mengganti kata sandinya sendiri kapan saja tanpa meminta admin.",
            "Dukungan penarikan QRIS UNO (Vigor/TMG) — 278 dari 278 baris cocok pada data uji.",
            "Dukungan gateway QRIS RPay — 2.048 dari 2.058 transaksi (99,5%) cocok otomatis.",
            "Uang dari satu kanal pembayaran tidak lagi bisa dipasangkan dengan setoran lewat kanal lain; "
            "18 baris yang dulu tertukar pada data uji menjadi nol.",
            "Jam server dikembalikan ke waktu Indonesia Barat setelah sempat tampil mundur tujuh jam.",
        ),
    ),
    Rilis(
        versi="1.1.0",
        tanggal=_dt.date(2026, 7, 8),
        nama="Ekspor Massal & Telusur Mutasi",
        jenis=MINOR,
        commit="44b453d",
        sorotan=(
            "Menu Ekspor Data: unduh hasil rekonsiliasi untuk rentang tanggal dan satu atau semua brand "
            "sekaligus, dikemas menjadi satu berkas ZIP berisi satu Excel per brand per tanggal.",
            "Sub-menu Mutasi Bank menampilkan seluruh baris mutasi bank dan gateway persis seperti urutan "
            "di berkas aslinya, dengan penyaringan per bank, per berkas, arah transaksi, dan tanggal.",
            "Antrean Tinjau berganti nama menjadi Area Pengecekan dan kini punya tiga tab lintas-tanggal: "
            "Perlu Ditinjau, Tidak Cocok, dan Tidak Ada di Panel, plus ringkasan jumlah dan nilai.",
            "Nama pemilik rekening dibaca dari kepala berkas mutasi dan ditampilkan di setiap baris hasil, "
            "sehingga terlihat rekening mana yang dipakai.",
            "Filter tanggal di Ringkasan Toko dan penyaringan lebih rinci di Area Pengecekan.",
        ),
    ),
    Rilis(
        versi="1.0.0",
        tanggal=_dt.date(2026, 7, 7),
        nama="Rilis Produksi Pertama",
        jenis=MAYOR,
        commit="6e550a0",
        sorotan=(
            "Aplikasi resmi dipakai tim auditor di server produksi, menggantikan rekonsiliasi manual.",
            "Aturan pencocokan final ditegakkan: pasangan hanya boleh terbentuk bila ada bukti identitas "
            "(nomor tiket, nomor referensi, nomor HP/rekening, username, atau nama). Nominal dan tanggal "
            "hanya pendukung — keduanya tidak lagi cukup untuk menyatakan dua baris berpasangan.",
            "Nama yang hanya mirip sebagian masuk antrean Perlu Tinjau dengan label jelas, bukan "
            "dipasangkan diam-diam; nama yang tidak mirip dibiarkan menunggu pencairan hari berikutnya.",
            "Tiga brand baru di-onboard (COR/Gacor25, MUL, MXW) berikut pembaca berkas Excel dari "
            "exporter non-standar yang sebelumnya gagal dibuka.",
            "Pencocokan kunci pasti lewat nomor referensi QRIS gateway, tanpa perlu menebak nama.",
            "Halaman hasil dirombak: baris uang tanpa jejak di Panel dipisah, sehingga Cocok + Perlu "
            "Tinjau + Tidak Cocok benar-benar menjumlah ke total baris Panel.",
            "Pengerasan produksi: kunci rahasia wajib disetel, mode aman menjadi bawaan, kebijakan "
            "kekuatan kata sandi penuh, serta halaman 404 dan 500 bermerek.",
        ),
        catatan=(
            "Hasil rekonsiliasi versi ini diaudit ulang secara independen pada 8 Juli 2026 memakai data "
            "nyata dua brand selama tiga hari: 53.949 pasangan diperiksa satu per satu di luar aplikasi, "
            "nol pelanggaran aturan, nol pasangan kuat yang terlewat, dan total nominal harian klop "
            "sampai rupiah pada enam dari enam pemeriksaan."
        ),
    ),
    Rilis(
        versi="0.4.0",
        tanggal=_dt.date(2026, 7, 5),
        nama="Kokpit Auditor",
        jenis=PRA_RILIS,
        commit="f2e2039",
        sorotan=(
            "Mesin pencocokan generasi kedua berjalan bertahap, mulai dari bukti terkuat (nomor tiket dan "
            "nomor referensi gateway) menuju identitas pemain.",
            "Pemain dikenali dari nomor HP atau virtual account e-wallet di mutasi bank, yang sering tidak "
            "mencantumkan nama sama sekali — pada uji data nyata tiga hari, transaksi yang perlu diperiksa "
            "manual turun sekitar 88 persen.",
            "Halaman Uang Tanpa Pasangan: uang yang tidak menemukan pasangan tidak lagi menghilang, "
            "melainkan dikelompokkan menurut sebabnya.",
            "Halaman utama menjadi ruang kendali harian: status rekonsiliasi terakhir, antrean pemeriksaan, "
            "kalender status 14 hari, tren selisih 30 hari, dan daftar kerja hari ini — rapi juga di ponsel.",
            "Antrean Tinjau lintas laporan dengan persetujuan massal; setiap keputusan tetap tercatat "
            "satu per satu.",
            "Jejak aksi tersimpan dan berkas yang sudah menjadi bukti rekonsiliasi tidak bisa dihapus.",
            "Unggah satu folder atau arsip ZIP sekaligus.",
        ),
    ),
    Rilis(
        versi="0.3.0",
        tanggal=_dt.date(2026, 7, 4),
        nama="Rekonsiliasi Harian",
        jenis=PRA_RILIS,
        commit="7b83175",
        sorotan=(
            "Rekonsiliasi terikat pada satu tanggal kerja dan tidak bisa lagi tercampur antar hari.",
            "Transaksi yang uangnya belum masuk hari itu tidak dianggap gagal — statusnya menunggu "
            "settlement dan otomatis diselesaikan saat uangnya muncul, dengan hasil diperbaiki di laporan "
            "tanggal aslinya.",
            "Data yang sudah dipakai rekonsiliasi dikunci agar tidak terhitung dua kali; menghapus laporan "
            "mengembalikannya.",
            "Nama pengirim dan penerima dibersihkan lebih dulu dari kode dan nominal yang menempel di "
            "keterangan mutasi — 225 baris tambahan cocok otomatis pada data uji tiga hari.",
            "Angka Uang Real dan Selisih diperbaiki, dan biaya transaksi bank tidak lagi dihitung "
            "sebagai penarikan.",
            "Mutasi Mandiri yang terkunci kata sandi bisa dibaca langsung dari halaman unggah.",
        ),
    ),
    Rilis(
        versi="0.2.0",
        tanggal=_dt.date(2026, 7, 2),
        nama="Multi-Brand & Hak Akses",
        jenis=PRA_RILIS,
        commit="90df919",
        sorotan=(
            "Seluruh data melekat pada satu brand, sehingga satu aplikasi bisa melayani banyak brand "
            "tanpa datanya tercampur.",
            "Unggah banyak berkas sekaligus dengan pengenalan jenis otomatis — pada pengujian 39 berkas "
            "asli, semuanya dikenali dengan benar.",
            "Rekonsiliasi sekali klik: satu tombol menjalankan seluruh pencocokan, didahului pemeriksaan "
            "berkas mana yang belum diunggah.",
            "Hak akses berjenjang Admin, Supervisor, dan Auditor, dibatasi per brand — termasuk bila "
            "seseorang mencoba membuka laporan brand lain lewat alamat langsung.",
            "Panel Kelola Toko dan Kelola Pengguna agar admin tidak perlu bantuan pengembang.",
        ),
    ),
    Rilis(
        versi="0.1.0",
        tanggal=_dt.date(2026, 7, 1),
        nama="Fondasi Rekonsiliasi",
        jenis=PRA_RILIS,
        commit="58a5c04",
        sorotan=(
            "Berkas ekspor dari Panel, Bracket, bank, dan gateway pembayaran dibaca dan diseragamkan "
            "menjadi satu daftar transaksi baku dalam rupiah.",
            "Mesin pencocokan otomatis menggolongkan setiap baris menjadi Cocok, Perlu Tinjau, atau "
            "Tidak Cocok berikut alasannya — menggantikan pencocokan manual baris per baris.",
            "Halaman kerja auditor: ringkasan, unggah, daftar transaksi, hasil rekonsiliasi dengan "
            "peninjauan manual, dan ekspor Excel.",
            "Berkas yang sama diimpor ulang tidak menggandakan data.",
        ),
    ),
)


def rilis_terbaru() -> Rilis:
    return RILIS[0]


def versi() -> str:
    return RILIS[0].versi


def ringkasan_jumlah() -> dict[str, int]:
    """Berapa kali tiap jenis rilis terjadi — dipakai halaman & dokumen."""
    hitung = {MAYOR: 0, MINOR: 0, PATCH: 0, PRA_RILIS: 0}
    for r in RILIS:
        hitung[r.jenis] += 1
    return hitung


def changelog_markdown() -> str:
    """Isi CHANGELOG.md, dirender dari RILIS.

    Dipakai `python manage.py changelog` untuk MENULIS berkas, dan oleh
    `core.tests_version` untuk MEMBANDINGKAN berkas — jadi berkas di repo tak
    pernah bisa diam-diam melenceng dari daftar rilis di modul ini.
    """
    n = ringkasan_jumlah()
    baris = [
        "# Catatan Perubahan — Truth of Auditor",
        "",
        "> Berkas ini **dibuat otomatis** dari `core/version.py`. Jangan diedit langsung:",
        "> ubah daftar `RILIS` di sana lalu jalankan `python manage.py changelog`.",
        "",
        f"Versi berjalan: **v{versi()}** · {len(RILIS)} rilis "
        f"({n[MAYOR]} besar, {n[MINOR]} fitur, {n[PATCH]} perbaikan, {n[PRA_RILIS]} pra-rilis).",
        "",
        "Penomoran MAYOR.MINOR.PATCH: **MAYOR** bila cara kerja aplikasi berubah mendasar,",
        "**MINOR** bila ada kemampuan baru, **PATCH** bila isinya murni perbaikan.",
        "Versi 0.x = tahap pra-rilis, sebelum aplikasi dipakai produksi.",
        "",
    ]
    for r in RILIS:
        baris.append(f"## v{r.versi} — {r.nama}")
        jejak = f" · `{r.commit}`" if r.commit else ""
        baris.append(f"*{r.jenis_label} · {r.tanggal_id}{jejak}*")
        baris.append("")
        baris.extend(f"- {s}" for s in r.sorotan)
        if r.catatan:
            baris.extend(("", f"> {r.catatan}"))
        baris.append("")
    return "\n".join(baris)
