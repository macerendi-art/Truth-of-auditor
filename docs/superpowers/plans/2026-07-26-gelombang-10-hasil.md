# Gelombang 10 — Hasil

Tanggal rilis: **26 Juli 2026** · Versi: **v1.11.0 — "Tiga Panel & Rekap Bulanan"** (MINOR) · commit rilis `b2bc0c6` · Sumber: `docs/superpowers/plans/2026-07-26-gelombang-10-plan.md`, `docs/superpowers/specs/2026-07-26-gelombang-10-design.md`, `.superpowers/sdd/progress.md`, `.superpowers/sdd/task-1..11-report.md`.

Semua 12 task gelombang ini selesai. Enam sorotan rilis resmi (dari `core/version.py`, bahasa bisnis untuk manajemen):

1. Rekonsiliasi Panel↔Bracket kini berjalan untuk brand berpanel Vigor/TM Gaming yang ekspornya tanpa nomor tiket — baris dicocokkan lewat username + nominal. Uji dengan data nyata COR: 10.069 dari 10.072 baris (99,97%) cocok otomatis. Halaman hasil menampilkan mode pencocokan yang dipakai, jadi selalu jelas aturan mana yang bekerja.
2. Halaman baru Rekap Bulanan meniru rekap Excel yang selama ini disusun manual: empat seksi (Net Profit, Sisa Dana Member, Total Dana Lebih Web, Selisih beserta penyebabnya), angka otomatis dihitung dari data harian, dan isian manual bisa menimpa angka otomatis dengan jejak siapa-dan-kapan.
3. Mode "Semua Toko" untuk admin: dashboard gabungan seluruh toko sekali pandang — kalender status, ringkasan Panel/Bracket/Metode gabungan, dan tabel per toko — plus filter ceklis beberapa toko sekaligus di halaman Hutang/Piutang.
4. Gembok alamat IP untuk akun auditor & supervisor: hanya alamat internet yang terdaftar yang bisa masuk; admin tidak pernah terkunci; selama daftar kosong fitur ini tidur. Dikelola dari halaman admin sendiri dan setiap penolakan tercatat di jejak audit.
5. Penarikan berlabel bank "OTH" pada brand Vigor/TM kini menampilkan bank aslinya (dibaca dari teks transaksi), dan nama penerima transfer BRI yang tadinya kosong kini terisi — berlaku juga untuk data yang sudah terlanjur diimpor, tanpa unggah ulang.
6. Setiap toko kini dikelompokkan menurut panelnya (Nexus / Vigor / TM Gaming) di pemilih toko, dan jenis panel wajib dipilih saat membuat toko baru.

---

## 1. Ringkasan per fitur (A–I)

| # | Fitur | Apa yang berubah bagi pemakai | Task | Commit | Status |
|---|---|---|---|---|---|
| A | Kartu "Ringkasan Bracket" di dashboard | Dashboard kini menampilkan kartu baru di bawah "Ringkasan Panel" berisi total Deposit/Withdraw/Net dari data FR (Bracket) hari batch terakhir, dengan tautan langsung ke halaman Breakdown Bracket tanggal itu. Memberi auditor pembanding cepat panel vs FR tanpa buka halaman terpisah. | Task 6 | `4cb6b94` | Selesai |
| B | Rekap Bulanan (`/rekap-bulanan/`) | Halaman laporan bulanan baru meniru struktur Excel end user: 4 seksi (NET PROFIT, SISA DANA MEMBER, TOTAL DANA LEBIH WEB, SELISIH & PENYEBAB) + kartu Penyebab Selisih. Baris otomatis ditarik dari data yang sudah ada (bonus, FR, panel, hutang/piutang); baris manual (WL, Akuran, Pulsa, Total Cost, dll — lihat §5) diisi lewat popup edit; setiap perubahan tercatat di audit log. Menu "Rekap Bulanan" muncul di sidebar Laporan. | Task 8 (model+modul), Task 9 (halaman) | `14831a3`, `1be3b0e` (fix klasifikasi bonus), `35ff0d6` (halaman), `bedfa12` (fix validasi+banner) | Selesai |
| C | OTH → bank asli | Baris mutasi WD/DP panel COR yang sebelumnya menumpuk di label bank "OTH" (operator kode situs sendiri) kini terurai otomatis ke bank asli (BCA/BNI/BRI/dll) yang tersimpan di ekor nama pemegang rekening — filter chip Bank Title di halaman detail run tidak lagi menggumpal di satu kategori "OTH". Perintah `backfill_oth_bank` sudah tersedia untuk memperbaiki baris lama yang sudah terlanjur ter-ingest sebagai "OTH". | Task 1 | `089db0f`, `134423b` (batch_size backfill) | Selesai |
| D | Pass 0c — join rekening (UNO WD) | Matcher kini bisa memasangkan WD gateway UNO ke baris panel lewat nomor rekening tujuan yang sama persis (anchor tambahan, di luar ticket/reference yang sudah ada) — menambah ketahanan saat ada pergeseran biaya (fee-shifted) atau settlement tertunda. Tidak ada perubahan pada Nexus/brand lain (kunci ini hanya aktif bila datanya membawa nomor rekening gateway UNO). | Task 3 | `c0a6347`, `effa12f` (fix assignment global + jendela tanggal) | Selesai |
| E | Mode username Panel↔Bracket (COR/Vigor/TM Gaming) | Sebelumnya, relasi Panel↔Bracket otomatis DILEWATI ("Dilewati — data tidak ada") untuk toko yang panelnya tidak mencetak nomor tiket (COR & sejenisnya) — padahal datanya lengkap. Sekarang relasi berjalan lewat mode baru: mencocokkan username + nominal + arah + tanggal berdekatan. Hasil pada data riil 23-07: **10069 dari 10072 baris panel (99,97%) cocok** — lihat tabel kalibrasi §2. | Task 4 | `d937950`, `6f351d3` (fix rasio mode + peringatan), `cd63c11` (fix guard ticket kontradiksi) | Selesai |
| F | Nama lawan transaksi BRI (mutasi bank) | Sebagian baris WD BRI sebelumnya tampil kosong di kolom "Nama Sesuai Mutasi" karena varian deskripsi mutasi tanpa kode `ESB` tidak dikenali parser. Sekarang varian itu ikut terbaca, plus ada fallback tampilan (tanpa perlu import ulang) untuk baris lama yang sudah ter-ingest sebelum perbaikan ini. BRIVA tetap kosong — itu memang dari sananya (lihat §4). | Task 2 | `aa4b1da` | Selesai |
| G | `Toko.panel` — kategori Nexus/Vigor/TM Gaming | Setiap Toko sekarang punya label kategori panel (Nexus / Vigor / TM Gaming), wajib dipilih saat membuat toko baru, bisa diubah dari halaman Kelola Toko (tercatat di audit log). Picker toko di topbar & modal pengingat mengelompokkan toko per kategori panel (jika akun melihat lebih dari satu kategori). Murni metadata/UX — tidak menyentuh logika pencocokan. | Task 7 | `f5214d8` | Selesai |
| H | Mode Semua Toko (admin) + ceklis Hutang/Piutang | Admin bisa memilih "Semua Toko" di picker dan melihat dashboard gabungan: kalender status terburuk per hari, kartu strip Panel/Bracket/Metode Pembayaran gabungan (tie-out persis dengan angka per-toko, termasuk overlay koreksi FR), dan tabel ringkasan per toko dengan tombol "Buka" langsung. Halaman single-toko yang belum sadar mode gabungan menampilkan bar penjelas ("Mode Semua Toko aktif — menampilkan toko X"). Halaman Hutang/Piutang dapat ceklis multi-toko (kosong = semua toko, kolom Toko ditampilkan). Non-admin tidak melihat opsi ini sama sekali. | Task 11 | `b1c444e`..`4d3cbbd` (17 commit: pagar sentinel sesi → picker+bar → dashboard gabungan → ceklis hutang → 2 ronde perbaikan review adversarial) | Selesai |
| I | IP Allowlist (gembok akses auditor/supervisor) | Admin bisa mendaftarkan daftar IP/CIDR yang diizinkan (`/kelola/ip/`) khusus untuk role auditor & supervisor — admin/superuser selalu bebas (jalur darurat). Selama daftar kosong, fitur ini dorman (tidak mengunci siapa pun). Percobaan akses dari IP di luar daftar ditolak dengan halaman 403 mandiri dan tercatat di audit log. | Task 10 | `88c117e`, `ec7963f` (fix fail-open+celah media+normalisasi CIDR), `47a71a1` (fix log per-IP+panjang sesi) | Selesai |

**Task 12 (rilis v1.11.0)** — selesai, commit `b2bc0c6` ("rilis: v1.11.0 — Tiga Panel & Rekap Bulanan"), 2026-07-26. Entri `Rilis(...)` ditambahkan di `core/version.py` (enam sorotan dikutip di pembuka dokumen ini), `CHANGELOG.md` disinkronkan lewat `python manage.py changelog`, suite penuh hijau (lihat §3), `CLAUDE.md` diperbarui.

Task 9 tercatat lengkap di ledger `.superpowers/sdd/progress.md` (commits `35ff0d6`+`bedfa12`, re-review Approved) — dimasukkan ke tabel di atas selaras dengan ledger dan laporan `task-9-report.md`.

---

## 2. Kalibrasi data riil COR (23-07-2026)

Sumber: `.superpowers/sdd/progress.md` baris Task 5, silang-periksa dengan angka independen di `.superpowers/sdd/task-4-report.md` §7 (yang menghitung ulang rasio panel_bracket dari run nyata dan mendapat angka identik: 10069/10072 = 99,97%).

| Metrik | Baseline (sebelum gelombang 10) | Sesudah | Keterangan |
|---|---|---|---|
| Panel↔Bracket — cocok | — (relasi dilewati sepenuhnya) | **10069 / 10072 = 99,97%** | Relasi sebelumnya tidak berjalan sama sekali untuk toko COR (gerbang `panel_has_ticket`); sekarang berjalan via mode username (fitur E) |
| Panel↔Bank — cocok | 9550 | **9553** (≥ baseline) | |
| Panel↔Bank — tidak cocok | 510 | **507** (≤ baseline) | |
| Bank Title "OTH" tersisa | 1212–1277 baris (per desain §4 temuan riset) | **0** (rincian: BCA 955, BNI 132, BRI 128, MANDIRI 62) | Semua baris OTH lama berhasil diurai ke bank asli (fitur C) |
| Violations (pelanggaran aturan anchor) | — | **0** | Tidak ada pasangan yang terbentuk di luar aturan anchor utama |
| Residu tak terjelaskan | — | **11 baris** | Baris DP *backdated* lintas-tengah-malam (posting FR menyeberang hari) — terdokumentasi + memicu warning, bukan kegagalan matcher (lihat `task-4-report.md` §7 dan §8 catatan 2) |

File Mandiri terenkripsi password tidak ikut dikalibrasi pada langkah ini (dilewati sesuai catatan brief Task 5 — butuh alur password saat upload, lihat follow-up §5).

**[cek]** Tidak ditemukan file `task-5-report.md`/`task-5-fix-report.md` bertema kalibrasi COR di `.superpowers/sdd/` — kedua nama file itu ternyata berisi laporan dari gelombang/task lain (verifikasi FR-Koreksi 18 Juli, dan perbaikan parser BNI PDF), bukan hasil kalibrasi Gelombang 10 Task 5. Angka pada tabel di atas diambil dari `progress.md` (ditulis langsung oleh orkestrator sesuai catatan plan "Orkestrator, bukan subagent") dan dicocokkan dengan angka independen di `task-4-report.md`; keduanya konsisten satu sama lain dan dengan angka yang diberikan dalam pengarahan tugas ini.

---

## 3. QA 4 Level (2026-07-26, HEAD `4d3cbbd`)

Verifikasi akhir gelombang, dijalankan setelah Task 11 mendarat (sebelum commit rilis `b2bc0c6`). Sumber: baris penutup `.superpowers/sdd/progress.md`.

- **UNIT** — suite penuh `python manage.py test`: **1.347 tes, OK** (2 skip disengaja — sample file BCA yang memang tidak disertakan di repo).
- **INTEGRASI** — kalibrasi ulang data riil COR 23-07-2026, gerbang identik dengan Task 5 (§2): panel_bracket **10.069/10.072 = 99,97%**; panel_bank **9.553 cocok / 507 tidak / 12 tinjau**, sehingga baris gabungan kedua relasi **19.622/20.144 = 97,4%**; **0 violation** aturan anchor; residu **11 baris** backdated lintas-tengah-malam, sudah dikenali & terdokumentasi (bukan kegagalan matcher baru).
- **SISTEM** — sweep browser end-to-end: dashboard gabungan (mode Semua Toko) dan dashboard single-toko K25 dengan tie-out visual antara keduanya, halaman Rekap Bulanan, Hutang/Piutang dengan ceklis, halaman Upload (bar peringatan mode Semua Toko baru), Kelola IP, dan Breakdown Bracket; termasuk pengecekan tampilan mobile (lebar 375px) untuk dashboard gabungan dan Rekap Bulanan. **0 error konsol browser, 0 error server** di seluruh sweep.
- **ACCEPTANCE** — matriks fitur A–I (§1) seluruhnya terpenuhi dengan bukti (detail per fitur ada di laporan task masing-masing, dirangkum di §1 dokumen ini).

### 3b. Review final whole-branch + ronde fix (pasca-QA, HEAD akhir `caa8fa3`)

Gerbang terakhir sebelum push: review whole-branch atas seluruh 35 commit gelombang (model terkuat, probe adversarial). Temuan & penanganannya:

- **C1 (blocker, selesai `a2adb2e`)** — nama rilis "Tiga Panel **&** Rekap Bulanan" meledakkan bug laten dua tes lama halaman `/versi/` yang membandingkan nama rilis tanpa `escape()`. Halaman tampil benar bagi pengguna; hanya tesnya yang keliru. Diperbaiki di tes (membunuh kelas bug ini permanen — 6 dari 16 nama rilis lama juga mengandung `&`).
- **I1 (selesai `aba5a13`)** — probe reviewer membuktikan klausa *blocked* rekening di pass 0c bisa merampas pasangan sah (nama identik + nominal persis + hari sama → `no_money`) saat sebagian baris panel tak membawa segmen rekening. Keputusan: klausa blocked untuk kunci rekening DIHAPUS (rekening = kunci *pemain*, bukan *transaksi*; pairing exact-account pass 0c tetap). Tes pin ditulis ulang sadar + tes regresi skenario probe. **Gerbang kalibrasi ulang: angka identik baseline** (10.069 + 9.553/507/12, violations 0) — nol pergeseran pada data COR; nilai perbaikan ada di populasi campuran yang belum terwakili dataset ini.
- **I2 (selesai `caa8fa3`)** — CLAUDE.md diperbarui: mode username, pass 0c (semantik pasca-I1), IPAllowlistMiddleware + urutan rantai, sentinel "Semua Toko" + guard `_active_toko`, Rekap Bulanan & kartu Ringkasan Bracket, koreksi baris geo-block Envoy yang basi.
- **Minor baru (selesai)** — `unseed` migrasi panel terfilter key seed (`09e18b6`); bar peringatan mode Semua Toko diperluas ke halaman tulis `/rekap-bulanan/` & `/bracket/` + bar disenyapkan di 5 halaman admin global bebas-toko (`4764c64`); cap panjang id di aksi kelola toko (`1cff0a9`); sorotan rilis dipresisikan + anchor commit (`caa8fa3`).
- Suite penuh pasca-fix: **1.352 tes OK** (di worktree verifikasi bersih; diulang di HEAD akhir).

---

## 4. Template jawaban BRI (siap kirim ke end user)

> Konteks pertanyaan: "Kenapa sebagian baris mutasi WD BRI kolom NAMA SESUAI MUTASI-nya kosong?"

Berikut penjelasan yang bisa disalin-tempel (bahasa non-teknis):

---

**Kenapa sebagian baris WD BRI tidak ada nama di kolom "Nama Sesuai Mutasi"?**

Ada dua penyebab berbeda, dan sekarang kami sudah menutup satu di antaranya:

1. **Sudah diperbaiki — varian format mutasi BRI tanpa kode "ESB".** Sebagian ekspor mutasi BRI mencatat nama tujuan transfer dengan format yang sedikit berbeda dari biasanya (tidak diakhiri kode "ESB"). Sistem sebelumnya hanya mengenali format yang berakhiran ESB, jadi baris dengan format satunya tampil kosong. Ini sudah kami perbaiki: sistem sekarang mengenali kedua format. **Perbaikan ini juga otomatis berlaku untuk data yang sudah pernah diunggah sebelumnya** — tidak perlu upload ulang, nama akan langsung tampil begitu halaman dibuka lagi.

2. **Tetap kosong (dan memang akan selalu kosong) — transaksi lewat BRIVA.** Untuk penarikan (WD) yang lewat jalur BRIVA (misalnya e-wallet DANA/GoPay/OVO/LinkAja yang diproses via kode virtual account BRI), bank BRI sendiri **menyamarkan (masking) nama penerima** di data mutasinya — informasi itu memang tidak tersedia dari sumbernya sama sekali. Ini bukan celah pada sistem kami; tidak ada cara mengisinya karena datanya tidak pernah dikirim oleh bank. Baris BRIVA akan selalu tampil "—" di kolom nama, dan itu memang seharusnya begitu.

Ringkasnya: kalau sebuah baris WD BRI *sekarang* masih kosong namanya setelah perbaikan ini, itu hampir pasti baris BRIVA — bukan bug.

---

*(Sumber: `.superpowers/sdd/task-2-report.md`, commit `aa4b1da`. Poles bahasa dilakukan untuk audiens non-teknis; detail regex/kode sengaja dihilangkan dari versi end user.)*

---

## 5. Follow-up teknis (bukan blocker rilis)

Item-item ini tidak menghalangi rilis v1.11.0, tapi perlu masuk backlog:

1. **Mode username Panel↔Bracket tidak punya bucket `perlu_tinjau` untuk near-miss nominal.** Selisih nominal tipis antar panel-FR pada mode username saat ini langsung jatuh ke `no_bracket`/`no_panel` terpisah (bukan `amount_mismatch` seperti mode ticket). Skala kecil di data riil (±3 baris/hari), tapi layak dipertimbangkan sebagai pass tambahan. (`task-4-report.md` §8 catatan 1)
2. **`_mode_ticket_warning` perlu floor/ambang** bila jumlah "baris Panel tanpa ticket tidak dinilai" berisik di produksi (mis. toko campuran) — saat ini menyala tanpa ambang minimum. (`task-4-report.md` FIX 1)
3. **File `MDR SUPANDI LAYER 3.xlsx` tidak terdeteksi parser mana pun** saat kalibrasi — perlu investigasi format/penambahan signature deteksi. **[cek]** detail lengkap file ini tidak ditemukan lebih jauh di report yang tersedia; dicatat sesuai pengarahan tugas.
4. **File Mandiri terenkripsi butuh alur password saat upload** — saat ini dilewati/gagal di jalur otomatis kalibrasi; UI upload perlu jalur eksplisit untuk memasukkan password (parser pendukungnya sudah ada, ini soal alur UI).
5. **Tanda (arah) baris Hutang/Piutang di Rekap Bulanan masih inferensi**, belum diverifikasi terhadap ekspor piutang riil pertama dari end user — `arah=+1` diambil apa adanya dari data FR yang ada (lihat FIX 2 di `task-8-report.md`); perlu konfirmasi begitu ada data piutang riil pertama.
6. **Asumsi arah `akuran_lalu = +1`** di Rekap Bulanan belum dikonfirmasi end user (brief tidak menyebutkan tandanya) — dampak bila salah adalah 2× lipat pada baris itu karena arah dikodekan tunggal di registry `FIELDS`, mudah dibalik satu baris bila perlu. (`task-8-report.md` §"Catatan/risiko terbuka" no. 3)
7. **Divergensi FRKoreksi vs Rekap Bulanan terdokumentasi tapi belum disatukan**: koreksi sel per-tanggal di Breakdown Bracket (`FRKoreksi`) **tidak** diterapkan ke Rekap Bulanan (yang beroperasi per-bulan) — perbedaan kunci granularitas, dicatat eksplisit di footer halaman `/rekap-bulanan/` dan di catatan modul `web/rekap.py`.
8. **Keterbatasan scope single-day pada FR backdated**: `_date_filter` di engine hanya menyaring lewat `occurred_at`, sedangkan pencocokan mengutamakan `posted_date` — baris FR backdated (posting hari D, tanggal transaksi D−1) tidak ikut tersaring pada run yang scope-nya persis satu hari; baru ikut bila scope melebar ke D−1. Memperbaikinya berarti mengubah `_date_filter` untuk seluruh matcher — di luar cakupan gelombang ini. (`task-4-report.md` "Catatan tambahan")
9. **Penyeragaman nama parameter `?bulan=` (Rekap Bulanan) vs `?month=` (Ringkasan Bulanan/`monthly_overview`)** — instruksi orkestrator eksplisit memilih `?bulan=` untuk halaman baru, override brief awal yang menulis `?month=`; kedua halaman sekarang tidak konsisten satu sama lain, sengaja dicatat untuk halaman berikutnya. (`task-9-report.md` catatan 2)
10. **`is_ip_gated`/query allowlist fail-open by design** dicatat eksplisit: bila query `AllowedIP` gagal (mis. DB hiccup), middleware sengaja lolos (pass-through) alih-alih mengunci semua auditor/supervisor — dikomentari di kode, perlu diketahui operator sebagai keputusan sadar, bukan celah. (`task-10-report.md` addendum temuan #1)
11. **Throttle/rate-limit audit log per user** belum ada — flag sesi `ip_block_logged` sudah dibatasi 1 baris audit per sesi per IP (bukan per request), tapi belum ada pembatasan lintas-sesi/lintas-user bila banyak akun dicoba dari IP asing berurutan. Dicatat sebagai potensi peningkatan, bukan kerentanan aktif (mengikuti pola gerbang lain di file yang sama-sama mengutamakan "jangan pernah brick app live" di atas throttle ketat).
12. **Bar mode Semua Toko menyebut "menampilkan `<toko>`" di halaman admin global yang sebenarnya bebas-toko** (mis. `/kelola/ip/`) — kosmetik, bar itu tetap benar secara fungsional (halaman tak butuh scope toko) tapi kalimatnya sedikit menyesatkan di konteks itu. (`task-11-report.md`, catatan review Task 11)
13. **`_batch_terakhir_per_toko` (dashboard gabungan) menarik seluruh riwayat summary batch** — beban query linear terhadap jumlah baris batch historis, bukan terhadap jumlah toko (jumlah toko tetap konstan ~24). Pola yang sama persis sudah hidup di produksi lewat `toko_overview`, jadi bukan regresi baru — dicatat sebagai kandidat optimasi bersama jika riwayat batch tumbuh sangat besar.
14. **Kartu "Area Pengecekan" di dashboard gabungan menaut ke antrean `/tinjau/` single-toko** (v1 yang disengaja) — angka di kartu memang lintas-toko, tapi klik akan membuka antrean toko fallback saja, dengan subteks penjelas yang sudah ditambahkan. Antrean tinjau lintas-toko sungguhan adalah pekerjaan tersendiri di luar cakupan gelombang ini.
15. **Guard "id kepanjangan" efektif untuk 11–18 digit saja** — nilai ≥19 digit sudah otomatis ditolak lebih awal oleh ORM Django (`BigAutoField` overflow → `EmptyResultSet`, terverifikasi langsung terhadap Django 5.2, berlaku di sqlite maupun Postgres), jadi guard eksplisit di `set_toko`/`rekap_penyebab_simpan` sebenarnya hanya "aktif" pada rentang 11–18 digit; tetap dipasang sebagai defense-in-depth sesuai resep review, bukan menggantungkan kebenaran pada detail internal ORM.

---

## 6. Bundel konfirmasi klien (pertanyaan untuk end user)

Sebelum Rekap Bulanan dianggap final, empat hal berikut perlu dikonfirmasi langsung ke end user (dari `.superpowers/sdd/task-8-report.md`):

1. **TOTAL COST** — apakah baris ini dimaksudkan untuk memasukkan biaya transaksi (fee bank/QRIS), atau murni biaya lain di luar biaya transaksi yang sudah punya baris tersendiri (ADMIN, ADMIN QRIS)?
2. **PDP (Pending DP) bulan ini** — apakah dihitung *net-of-returns* (pengembalian/refund ikut mengurangi angka PDP), atau harus gross tanpa dikurangi pengembalian?
3. **Penempatan "Beban Other Expense"** — apakah baris FR "beban other expense" sudah tepat digabungkan sebagai baris terpisah setelah ADMIN QRIS di seksi NET PROFIT, atau end user mengharapkan penempatan/pengelompokan lain?
4. **Isi baris "BONUS LAINNYA"** — kategori bonus di luar Harian/Mingguan/Lucky Draw (mis. Rollingan, Redemption Coupon, Adjustment, CRM, New Member, Event) sekarang ditampung satu baris "BONUS LAINNYA" — apakah semua kategori ini memang dimaksudkan ikut sebagai beban bonus, termasuk item seperti "Adjustment" dan "Redemption Coupon" yang sifatnya bisa jadi bukan bonus promosi murni?

---

## 7. Catatan deploy (untuk operator — bukan eksekusi otomatis)

**Deploy ke production adalah keputusan terpisah, di luar cakupan gelombang ini.** `origin/main` sudah/akan berisi commit rilis `b2bc0c6` (setelah dipush), tapi push **tidak** memicu deploy otomatis (lihat `CLAUDE.md` — deploy prod selalu manual, `railway up --ci` dari checkout standalone, bukan worktree). Jangan deploy tanpa konfirmasi eksplisit dari user.

Begitu user memutuskan untuk deploy, operator perlu menjalankan langkah **manual** berikut setelah deploy prod:

- **Backfill data OTH lama**: jalankan `python manage.py backfill_oth_bank` di prod pasca-deploy (opsional `--toko <key>` untuk membatasi scope, `--dry-run` untuk pratinjau tanpa menulis) — memperbaiki baris `bank_title="OTH"` yang sudah ter-ingest sebelum fitur C aktif. Idempoten, aman dijalankan berkali-kali.
- **Aktivasi IP Allowlist**: saat mengaktifkan gembok IP (menambah entri pertama di `/kelola/ip/`), set env var `GEO_BLOCK_REQUIRE_CF=true` di Railway (`GEO_BLOCK_REQUIRE_CF` sudah ada di `truth_auditor/settings.py`, default `False`) — memastikan resolusi IP asli hanya dipercaya bila request benar-benar lewat edge Cloudflare, konsisten dengan rantai resolusi IP yang dipakai ulang dari GeoBlock.
- **Migrasi baru yang perlu diterapkan** (otomatis lewat `migrate` di start command, tapi dicatat untuk verifikasi pasca-deploy): `web` `0002_rekap_bulanan`, `web` `0003_allowed_ip`; `sources` `0011_toko_panel`, `sources` `0012_seed_toko_panel` (migrasi data — mapping `slo→vigor`, `w25,g25→tm_gaming`, sisanya `nexus`). Semua additive & reversibel, tidak menyentuh data transaksi produksi.
