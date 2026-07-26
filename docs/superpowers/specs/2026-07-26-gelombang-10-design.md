# Gelombang 10 — Desain: Paket Vigor/TM Gaming, Rekap Bulanan, Semua Toko, IP Allowlist

Tanggal: 2026-07-26 · Target rilis: **v1.11.0 (MINOR)** · Status: disetujui user (plan mode), eksekusi otonom penuh; deploy = gerbang konfirmasi terpisah.

## Latar

Satu batch permintaan end user (8 fitur + 1 investigasi) untuk brand panel Vigor/TM Gaming (COR dkk) + laporan bulanan ala Excel mereka + kontrol akses. Acuan: data riil `COR 23-07-2026.zip`, proyek Lovable "Visual Data Maker" (spec report), screenshot Telegram.

## Temuan riset yang mengikat desain

1. **FR BREKET COR per-transaksi, bukan agregat.** Kolom persis yang sudah didukung `sources/parsers/bracket.py` (docstring-nya memuat daftar kolom yang sama). `ticket_no=""` semata karena Description COR tak memuat ticket `D…/W…`. Kunci `username+|nominal|` terverifikasi dua arah pada data 23-07: **DP 8538/8549 = 99,9%, WD 1542/1560 = 98,8%** (sisi panel 100%).
2. **Relasi panel_bracket dilewati bukan karena data**, tapi gerbang `panel_has_ticket` (engine.py±1039): parser panel COR hard-code `ticket_no=""`. Label UI "Dilewati (data tidak ada)" menyesatkan. Tes `reconciliation/tests_bracket_cor.py` mem-pin perilaku lama — diubah sadar.
3. **Kunci UNO yang diminta end user sudah terpasang & 100%**: WD panel `Transaction ID` (UUID) == gateway `Order ID (Merchant)` 265/265; DP UUID == `OrderId` 8338/8338 ("Order ID (Uno)" hanyalah label web portal). Nomor rekening dua sisi (`Destination Bank` ↔ `AccountNumber`) 229/229 → dijadikan anchor pasti TAMBAHAN (pass 0c), nilai utamanya ketahanan (fee-shifted / settlement tertunda).
4. **OTH**: `From Bank` WD = `OTH - <rek> - <NAMA> / WITHDRAW <BANK>` → bank asli di ekor segmen nama; kolom `bank_title` terisi "OTH" (1212/1277 baris WD bank pada data 23-07) sehingga chip filter run-detail menggumpal.
5. **BRI nama kosong**: regex parser `NBMB (.+?) TO (.+?) ESB` — varian tanpa ` ESB` (nama sampai akhir baris) gagal; BRIVA memang masked oleh bank (mustahil ada nama).
6. **Spec report bulanan** (chat + 2 gambar Lovable): 4 seksi — NET PROFIT; SISA DANA MEMBER; TOTAL DANA LEBIH WEB; SELISIH & PENYEBAB (+ DIFFERENT vs DANA LEBIH FNC). Tag kolom sumber di Excel end user: `RPT COM`=otomatis dari data, `FORM EXPENSE`=input manual, `BS`=panel/bank, `RUMUS`=hitungan. Konfirmasi end user di chat: OTHER INCOME manual; expired dana pending = PDP >30 hari; penyebab selisih semi-otomatis.

## Keputusan desain per fitur

- **A. Kartu "Ringkasan Bracket"** di dashboard bawah Ringkasan Panel: helper ringan `ringkas_bracket_hari(toko, tanggal)` (1 query grouped `raw["Kategori"]`+`raw["Bank"]`, slug `_slug_kategori`, DP=Σdeposit, WD=|Σwithdrawal|, pending dp keluar, overlay FRKoreksi sel deposit/withdrawal, TANPA `_saldo_carry`). Wajib tie-out dengan total `/bracket/` di tanggal sama. Populasi beda dengan kartu panel (batch-locked) — subjudul menjelaskan basisnya.
- **B. Rekap Bulanan** `/rekap-bulanan/`: modul murni `web/rekap.py` + dua model overlay (`RekapManual` unik (toko,periode,field); `RekapPenyebab` daftar label+nilai). Baris auto ditarik dari modul yang SUDAH ada (bonus per kategori, kategori FR, sum panel langsung, hutang/piutang); manual menimpa auto dengan provenance (pola FRKoreksi); carry antar-bulan depth-1; seluruh rumus di modul, template tanpa aritmetika.
- **C. OTH → bank asli**: `resolve_oth_bank(code, name)` di cor.py (pola `…/ (WITHDRAW|DEPOSIT) <BANK>$`) memperbaiki `bank_title` + `raw["Bank Title"]` sintetis; kolom export asli di raw tidak disentuh; row_hash tak berubah. Backfill idempoten `backfill_oth_bank` untuk baris lama (preseden backfill kode_unik).
- **D. Pass 0c rekening (UNO WD)**: indeks dari `raw["AccountNumber"]` (kunci persis, hanya UNO yang memilikinya → inert untuk Nexus), normalisasi ala `_panel_phone`, **exact amount saja** — rekening adalah kunci PEMAIN, bukan kunci transaksi (satu pemain bisa beberapa WD ke rekening sama); non-exact jatuh ke pass 1/2 yang sudah punya toleransi fee. Perluas set `blocked` (rekening gateway yang tak dikenal panel tampil sebagai uang-tanpa-pasangan, bukan dicomot fuzzy).
- **E. Mode username Panel↔Bracket**: data-driven (panel tanpa ticket & dua sisi berisi), BUKAN dari field panel toko — salah-set metadata tidak boleh bisa merusak pencocokan. Username persis = anchor UTAMA (aturan anchor dipertahankan); nominal-persis + jendela tanggal = pendukung; greedy 1:1 nearest-date. Baris FR non depo/wd tidak menghasilkan `no_panel`. Gerbang skip diganti + `skipped_detail` + copy UI dibedakan "tanpa join ticket" vs "data tidak ada".
- **F. BRI**: terminator ` ESB` jadi opsional (ingest baru) + fallback tampilan query-time dari `raw["DESK_TRAN"]` di Mutasi Bank (retroaktif tanpa backfill — pelajaran "engine deploy tak retroaktif"). BRIVA tetap "—".
- **G. `Toko.panel`** (nexus/vigor/tm_gaming): metadata + pengelompokan picker (optgroup) + badge kelola + audit. Migrasi data: slo→vigor; w25,g25→tm_gaming; sisanya nexus. TIDAK menyentuh engine.
- **H. Semua Toko (admin)**: sentinel sesi `"all"` ala export_center; guard `_active_toko` (crash Postgres bila tidak); `active_toko` context TETAP objek Toko nyata + flag `semua_toko` + bar notifikasi di halaman single-toko; dashboard gabungan = template terpisah, semua agregat `toko__in` (larangan loop per-toko, ~24 toko); tabel per-toko transparan (tanggal batch beda-beda); hutang: ceklis toko + kolom Toko.
- **I. IP Allowlist**: `AllowedIP` di web; gerbang role auditor+supervisor (`is_ip_gated`), admin/superuser bebas (break-glass alami); dorman saat kosong; rantai resolusi IP GeoBlock dipakai persis (XFF paling-kiri; allowlist diuji pada IP asli, bukan edge CF); 403 halaman mandiri + audit sekali per sesi; CRUD `/kelola/ip/`.

## Asumsi (diambil tanpa bertanya, sesuai mandat)
- "Khusus panel Admin" = gerbang `is_admin` (supervisor tak dapat mode Semua Toko, tapi KENA allowlist IP — permintaan eksplisit).
- Allowlist kosong = dorman; Rekap v1 baris FORM tetap manual; EXPIRED DANA PENDING manual dulu; CAH25/COR menyusul saat tokonya dibuat.
- v1.11.0 MINOR — tak ada kriteria 2.0.0 yang terpenuhi (aturan inti tak diganti, alur tak dirombak, layout ekspor tetap, migrasi reversibel).
