# Laporan Trial End-to-End — TOKO OKE25, 27–29 Juni 2026

**Tanggal uji:** 5 Juli 2026 · **Lingkungan:** DB scratch lokal (produksi tidak tersentuh) · **Metode:** harness otomatis meniru persis alur browser (upload `analyze` → `commit` → rekonsiliasi harian per tanggal, semua sumber dicentang, toleransi Default ±1 hari)

---

## 1. Ringkasan Eksekutif

Trial 3 hari berturut (27→28→29 Juni) dengan **39 file sumber, 81.950 baris** berjalan **tanpa satu pun error**. Mesin inti — deteksi parser, dedup idempoten, matching, carry-over "menunggu settlement", flip settle terlambat, retro write-back — semuanya bekerja dan **selisih konvergen otomatis** ke angka riil seiring settlement lintas-hari masuk.

Empat celah terukur ditemukan (bukan bug crash, tapi lubang ketelitian audit & beban kerja), dirinci di §5 dengan rekomendasi di §6–7.

> Catatan penting data: file `FR BRACKET OKE25 27-06.xlsx` di folder sampling ternyata berisi **data 28-06** (duplikat konten file 28-06). File asli `FR BRACKET OKE25 TGL 27-06.xlsx` ditemukan di Telegram Desktop dan sudah dipasang ke samples. Tanpa file benar ini, Panel↔Bracket 27-06 hanya cocok 3 dari 8.066 — **dan aplikasi mendeteksinya sendiri** lewat warning "file Panel & Bracket beda periode". Dengan file benar: 7.917 cocok.

---

## 2. Hasil per Hari (saat run)

| Metrik | 27 Juni | 28 Juni | 29 Juni |
|---|---|---|---|
| File diupload / deteksi benar | 13 / **13** | 13 / **13** | 13 / **13** |
| Baris baru (duplikat di-skip) | 30.686 | 17.472 | 15.792 (dup 6.556) |
| Cocok | 14.459 | 14.813 | 14.123 |
| Perlu tinjau | 1.141 | 861 | 894 |
| Tidak cocok | 271 | 458 | 691 |
| DP: panel vs matched | 445,78 jt / 443,59 jt | 417,95 jt / 417,83 jt | 424,46 jt / 420,99 jt |
| WD: panel vs matched | 353,24 jt / 321,00 jt | 350,35 jt / 285,21 jt | 350,88 jt / 260,28 jt |
| Settle terlambat (flip ke batch asal) | — | **25 DP (2,07 jt) + 219 WD (29,21 jt)** | 2 DP + 408 WD (57,21 jt) |
| Baris susulan (retro write-back) | — | 4 | 7 |
| Kadaluarsa (lewat window) | — | 17 | 44 |
| Carry "menunggu settlement" | 261 | 454 | 686 |

## 3. Konvergensi Selisih (angka LIVE setelah flip)

| Batch | Selisih WD saat run | Selisih WD kini | Selisih DP kini |
|---|---|---|---|
| #1 · 27/06 | 32.239.000 | **4.926.000** | 116.000 |
| #2 · 28/06 | 65.139.000 | **7.930.000** | **0** ✓ |
| #3 · 29/06 | 90.596.000 | menunggu run 30/06 | 3.468.000 |

Pola sehat: mayoritas "selisih" WD hari-H hanyalah settlement yang uangnya baru muncul di mutasi H+1 — sistem menutupnya sendiri di run berikutnya dan memperbarui batch asal.

## 4. Validasi Fitur Inti

- ✅ **Auto-deteksi**: 39/39 parser & flow benar. BCA PDF selalu 75% → UI minta konfirmasi (sesuai ambang 0.8) — benar tapi repetitif (lihat UI/UX #5).
- ✅ **Idempoten**: file bank yang periodenya tumpang-tindih antar hari otomatis di-skip (BRI 4.905 & 5.031 baris, Mandiri 1.313, QR 3).
- ✅ **Rekonsiliasi harian**: 1 batch per tanggal, guard tanggal ganda bekerja.
- ✅ **Carry-over & late settlement**: kredit no_money dalam window tetap aktif, flip ke batch asal dengan jejak (`late_settlement`, batch penyelesai, summary asal dihitung ulang).
- ✅ **Retro write-back**: baris susulan bertanggal lampau ditulis ke batch tanggal asalnya.
- ✅ **Warning kualitas data**: file bracket salah-periode terdeteksi otomatis.

## 5. Temuan Terukur

| # | Temuan | Angka | Dampak |
|---|---|---|---|
| T1 | **Uang bertanggal > tanggal rekon ikut terkonsumsi** batch hari itu | 49 / 35 / 42 baris per hari (≈5–6 jt/hari) | Baris uang milik "besok" terkunci sebagai tidak-cocok di batch hari ini; pasangan panel-nya di hari berikutnya tak akan pernah match (re-upload = duplikat = skip) |
| T2 | **Uang tak berpasangan tidak muncul di hasil mana pun** — matcher hanya membuat hasil per baris panel | 9.269 baris dari 32.379 (DP 5,10 M + WD 3,98 M gross) | Untuk alat audit, uang masuk tanpa catatan panel adalah sinyal utama fraud — saat ini hanya terlihat sebagai selisih gross-vs-matched, tak bisa ditelusuri per baris. Catatan: sebagian besar wajar (rekening/gateway dipakai bersama beberapa toko — kolom Asset Bank bracket menunjukkan brand lain), justru karena itu perlu dipetakan |
| T3 | **Beban tinjau manual struktural** | 1.346 / 1.258 / 894 baris per batch (live); ±85% score<50 | Pemain pakai DANA/GOPAY/SEABANK → nama di mutasi bank ≠ nama pemain (contoh: `Farhanudin` ↔ `HASANUDIN HASDI`). Fuzzy name tidak akan pernah menolong; harus alias learning. UI review 40 baris/halaman × 32 halaman, aksi per baris |
| T4 | **Validasi isi file vs konteks baru terjadi SETELAH run** | file bracket salah-periode lolos ingest | Warning muncul di batch, bukan saat upload — kesempatan koreksi terlewat satu siklus |

## 6. Rekomendasi Backend Logic (prioritas)

1. **[P0] Carry-over sisi uang** — di `run_batch`: baris uang `occurred_at > recon_date` yang tak berpasangan **jangan dikonsumsi** (tetap aktif untuk run berikutnya), cermin dari carry kredit yang sudah ada. Perubahan kecil di blok konsumsi + test. Menutup T1.
2. **[P0] Hasil eksplisit "uang tanpa pasangan"** — `_MoneyMatcher.match` membuat `MatchResult(left=None, right=uang, reason="no_panel")` untuk uang dalam scope tanggal rekon yang tak terpakai, ATAU view khusus + export "Uang Tanpa Pasangan" per batch. Menutup T2. (Perhatikan volume: batasi ke uang bertanggal = recon_date agar tidak membanjiri hasil.)
3. **[P1] Alias learning** — tabel `NameAlias (toko, no_rek/nama_bank ↔ username panel)` yang terisi otomatis setiap reviewer meng-approve (✓) pasangan weak_name; matcher memeriksa alias sebelum fuzzy → skor 100. Memangkas T3 secara permanen (antrean tinjau turun drastis setelah 1–2 minggu pemakaian).
4. **[P1] Validasi saat upload (analyze)** — baca sebaran tanggal isi file, bandingkan dengan tanggal rekonsiliasi/nama file: "⚠ File ini berisi data 28/06 — kamu upload untuk 27/06". Menutup T4 di sumbernya.
5. **[P2] Pemetaan akun bersama** — model `Account` sudah ada; tautkan rekening/gateway yang dipakai multi-toko supaya "uang tanpa pasangan" bisa difilter "kemungkinan milik toko lain" dan angka gross per toko lebih bermakna.
6. **[P2] Operasional** — (a) guard `max_wal_size=96MB` hidup di volume Postgres, **hilang jika DB di-rebuild** — dokumentasikan/otomasikan; (b) config LOGGING traceback sudah dikomit — ikut deploy berikutnya; (c) angkat harness trial ini jadi `manage.py trial_e2e` untuk regresi rilis.

## 7. Rekomendasi UI/UX Web Dashboard

1. **Dashboard → kokpit operasional harian.** Sekarang: 4 kartu statistik + daftar. Usulan: (a) **kalender/heatmap status per toko** — tiap sel tanggal berwarna: belum upload / belum rekon / selisih besar / beres; (b) tren selisih DP & WD 7–30 hari; (c) panel "Kerjakan hari ini": file yang belum lengkap, antrean tinjau, settlement mendekati kadaluarsa; (d) breakdown per bank/gateway.
2. **Halaman "Antrean Tinjau" lintas-batch** (menggantikan review per-run 32 halaman): filter gabungan (score, alasan, bank, arah), **bulk-approve** hasil terfilter (mis. semua `late_settlement` score≥60), grouping per counterparty/rekening, keyboard shortcut (j/k navigasi, y/n aksi), progress bar & jejak reviewer (siapa, kapan, berapa). Target: dari jam → menit; ditambah backend #3, antrean mengecil sendiri.
3. **Settlement tertunda**: di halaman batch sekarang tabel flat (244 baris di batch #2, akan tumbuh). Usulan: collapse per arah dengan subtotal, paginasi, dan halaman global "Menunggu Settlement" dengan **aging** (H-1/H-2/hampir expired) + notifikasi saat mendekati window.
4. **Halaman batch**: tampilkan **dua angka berdampingan** — "selisih saat run" vs "selisih efektif kini" (datanya sudah ada, tinggal diekspos) + timeline flip; link langsung dari kartu ringkasan ke daftar terfilter ("lihat 44 tidak cocok").
5. **Upload**: checklist kelengkapan per tanggal (Panel DP/WD ✓, Bracket ✓, BCA/BRI/Mandiri ✓, NXPay/QR ✓) sehingga file kurang langsung kelihatan; ingat konfirmasi parser per pola nama file (BCA PDF 75% tak perlu dikonfirmasi ulang tiap hari); auto-isi tanggal rekon dari nama file; peringatan isi-vs-tanggal (backend #4).
6. **Tab "Uang Tanpa Pasangan"** per batch/tanggal (menyertai backend #2): daftar + filter "tanggal > rekon (terkunci)" + export Excel — halaman kerja fraud-check.
7. **Polesan teknis**: animasi fade-in menahan konten (screenshot otomatis sempat menangkap halaman kosong/samar) → pakai skeleton, hormati `prefers-reduced-motion`; tabel 11 kolom → sticky header, mode kompak, kolom bisa disembunyikan; angka rupiah rata kanan konsisten.

## 8. Roadmap Usulan

| Tahap | Isi | Ukuran |
|---|---|---|
| P0 (engine, minggu ini) | Backend #1 + #2 (+ test) | kecil — menutup lubang audit |
| P1 (dampak harian terbesar) | UI #2 Antrean Tinjau + Backend #3 alias learning | sedang |
| P1.5 | Backend #4 + UI #5 (validasi upload) | kecil |
| P2 | UI #1 kokpit + #3 aging + #4 batch detail; Backend #5 akun bersama | sedang–besar |

---

## Pembaruan 2026-07-05 malam — Matcher v2 + Paket B TERPASANG

Semua rekomendasi P0 + matcher v2 diimplementasikan (commit `3bf3267`, `a079ad3`, `a2210e8`) dan divalidasi trial ulang + audit independen:

| Metrik (3 hari) | Sebelum | Sesudah |
|---|---|---|
| Perlu tinjau per hari | 1.141 / 861 / 894 | **182 / 107 / 108 (−88%)** |
| Bukti identitas pada cocok | 97% (sisanya fuzzy/salah sanding) | **100% berbukti keras** (ticket 19.855 · nomor HP/VA 1.687 · nama≥85 1.222) |
| Match terlewat (audit independen) | 8 terbukti + salah sanding ratusan | **0** |
| Uang tanpa pasangan | 9.269 baris tak terlihat | terklasifikasi A/B/C/D + halaman `/batch/<id>/uang/` + export |
| Uang lintas-hari terkunci | 49/35/42 per hari | 0 (carry-over sisi uang) |

Kunci kemenangan: (1) **ticket-join gateway** (100% baris QR/NXPay ber-ticket panel), (2) **assignment global identitas-dulu** (anti-curi kandidat), (3) **identitas nomor HP/VA** — mutasi `FTFVA/DANA`, `GOPAY TOPUP` tak membawa nama tapi membawa nomor HP pemain yang juga ada di `raw["Player Bank"]` panel (riset format mutasi: transfer e-wallet tampil atas nama korporat agregator — PT Espay Debit/DANA, PT Dompet Anak Bangsa/GoPay), (4) prioritas rekening tujuan `Bank Title`, (5) deteksi fee (`amount_fee`, 146 baris) & uang H-1.

Catatan pembacaan angka: selisih live WD 27/06 kini 16,9 jt (sebelumnya "4,9 jt") — angka lama itu SEMU karena pasangan-asing ikut dihitung matched; angka baru dapat dipertanggungjawabkan per baris. Selisih yang tersisa = kredit yang uangnya sungguh belum tiba + daftar D untuk investigasi.

## Lampiran — Catatan Operasional (insiden 4 Juli 2026)

- Produksi 500 total: **volume Postgres 500MB penuh** (WAL run besar; default `max_wal_size=1GB` mustahil untuk volume 500MB). Dipulihkan tanpa kehilangan data (pg_wal dipindah sementara ke disk ephemeral, recovery selesai, `max_wal_size=96MB` dipasang permanen). Backup pra-pemulihan: `~/Truth-of-auditor-backups/pgdata-backup-20260704.tgz`.
- **Beta reset** produksi atas persetujuan user (semua transaksi/hasil/upload dihapus; user, toko, konfigurasi utuh; DB 129MB → 9,8MB). Kesepakatan: **setelah Ready Production, tidak ada penghapusan data**.
- Laju data riil ±35–50MB/hari pada plan Hobby (volume max 500MB) → sebelum go-live perlu keputusan: upgrade Pro + grow volume, atau kebijakan arsip yang disetujui eksplisit.
