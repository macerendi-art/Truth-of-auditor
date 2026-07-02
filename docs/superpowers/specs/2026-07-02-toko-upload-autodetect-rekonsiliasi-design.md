# Desain: Dimensi Toko, Upload Auto-Detect, & Rekonsiliasi Paralel

- **Tanggal:** 2026-07-02
- **Status:** Disetujui (menunggu review spec)
- **Aplikasi:** Truth of Auditor (Django reconciliation app)
- **Konteks kode saat ini:** 8 parser di `sources/parsers/`, pipeline `sources/services.py:ingest()` (idempoten via `row_hash`), engine `reconciliation/engine.py` (`MATCHERS` pluggable), UI `web/` (tema dark premium + Three.js hero di login).

## 1. Tujuan

Meningkatkan alur **Upload** dan **Rekonsiliasi** agar sesuai keinginan end user:

1. **Upload tanpa pilih format** — user cukup melempar file, sistem menentukan jenis sumbernya sendiri (auto-detect), plus preview dan riwayat upload.
2. **Rekonsiliasi paralel** — satu klik "Jalankan Rekonsiliasi" menjalankan Panel↔Bracket dan Panel↔Bank/Gateway sekaligus, didahului pengecekan kelengkapan file, plus riwayat.
3. **Dimensi Toko** — data dipisah per merek/situs operator (mis. LBS, SLO).

Peningkatan ini merupakan gabungan pola dari dua referensi milik user (lihat §7): melampaui keduanya dengan **satu drop-zone auto-detect** (menghapus pilih-format & toggle DP/WD manual).

## 2. Keputusan yang sudah disepakati

| Topik | Keputusan |
|---|---|
| Arti "Toko" | Merek/situs operator. Upload ditandai per toko; rekonsiliasi dipisah per toko. Perlu model/dimensi baru. |
| Cara upload | Satu drop-zone, **banyak file sekaligus**, tiap file diklasifikasi otomatis. |
| Deteksi ambigu/gagal | **Tebak + minta konfirmasi**: tampilkan tebakan terbaik + skor keyakinan; user konfirmasi/ubah sebelum simpan. |
| Syarat kelengkapan rekonsiliasi | Minimum **Panel (Depo & WD) + minimal 1 Bank/Gateway**. Tidak ada syarat tambahan. |
| Jika kurang lengkap | **Peringatkan tapi boleh lanjut** (soft-gate). |
| Bracket/FR tidak ada | Bagian Panel↔Bracket **dilewati otomatis** + diberi catatan; relasi lain tetap jalan. |
| Parser baru (BNI, Credit Bonus, Panel Provider lain) | Diinginkan tapi **contoh file belum ada** → ditunda; sistem dibuat extensible. |
| Gaya visual | Halaman kerja **terang & padat** (gaya referensi "Finance Report v1"); login tetap dark premium + Three.js. |

## 3. Model data

Model baru & perubahan (app `sources`, kecuali disebut lain):

- **`Toko`** (model baru): `key` (slug unik, mis. `lbs`), `name` (mis. "LBS"), `is_active` (bool). Seed awal: LBS, SLO.
- **`Upload.toko`** → `FK(Toko)`, wajib untuk upload baru.
- **`Upload.provider`** → `CharField(blank=True)` untuk **Panel Provider** (mis. `Nexus`). Disimpan saat upload; extensible saat format provider lain masuk.
- **`Transaction.toko`** → `FK(Toko)`, disalin dari `upload.toko` saat ingest. Dipakai untuk filter UI dan agar pencocokan tidak lintas-toko.
- **`Account.toko`** → `FK(Toko, null=True, blank=True)` — rekening milik toko tertentu.
- **`reconciliation.ReconBatch`** (model baru): `toko` (FK), `date_from`, `date_to`, `tolerance` (FK ToleranceProfile), `created_by` (FK User), `summary` (JSON), `completeness` (JSON snapshot hasil pra-cek).
- **`reconciliation.MatchRun.batch`** → `FK(ReconBatch, null=True, blank=True, related_name="runs")` — menautkan tiap relasi ke satu batch.

**Migrasi & backfill:** buat `Toko` default, isi `toko` pada semua `Upload`/`Transaction`/`Account` lama ke toko default itu, lalu (opsional) kunci `null=False`.

## 4. Upload: auto-detect + preview + history

### 4.1 Registry deteksi
Tiap parser mengekspos kemampuan sniff. Rancangan: fungsi/kelas detektor per parser dengan signature seragam:

```
sniff(path, filename) -> {"matches": bool, "confidence": float 0..1, "meta": {...}}
```

Tanda-tangan deteksi (berbasis ekstensi + header/isi, bukan sekadar nama file):

| parser_key | Tanda-tangan |
|---|---|
| `panel` | xlsx; header **baris 2** memuat "Deposit Amount"/"Withdrawal Amount", "Ticket Number", "User Name" (amount dalam ribuan). |
| `bracket` (FR) | xlsx; header baris 1 memuat "Kategori", "Credit Awal", "Credit Akhir", "Transaction ID". |
| `bri` | CSV; header memuat `MUTASI_DEBET`/`MUTASI_KREDIT`/`TGL_TRAN`/`SALDO_AKHIR_MUTASI`. |
| `bca_csv` | CSV; ada preamble + header `Tanggal,Keterangan,Cabang,Jumlah,,Saldo` (DB/CR). |
| `bca_pdf` | PDF; teks pdfplumber memuat penanda mutasi rekening BCA. |
| `mandiri` | xlsx e-Statement; header ~baris 15; format angka ID (`1.000,00`). |
| `nxpay` | xlsx; header baris 2 memuat "Ticket Number", "Admin Fee", "Account Title". |
| `qrflyer` | xlsx; penanda QR FLYER / QRIS. |

Fungsi orkestrasi `detect_source(path, filename)` menjalankan semua sniff, mengembalikan daftar kandidat terurut skor. **Flow (DP/WD)** dideteksi dari nama file (`detect_flow` yang sudah ada) + isi; bila sumber uang (gateway) ambigu → ditandai perlu konfirmasi.

### 4.2 Alur & UI
1. User pilih **Toko** (selektor di atas) dan lempar banyak file ke satu **drop-zone**.
2. Sistem menjalankan `detect_source` untuk tiap file → menyusun tabel **preview sebelum commit**:
   - kolom: *nama file → jenis terdeteksi (+skor keyakinan, dropdown bisa diubah) → toko → provider (panel) → DP/WD → estimasi baris → estimasi duplikat*;
   - cuplikan **~10 baris kanonik** per file (expandable);
   - skor rendah/ambigu → ditandai **"perlu konfirmasi"**.
3. User konfirmasi (ubah bila perlu) → **"Simpan & Parse"** memproses semua file lewat `ingest()` (idempoten via `row_hash`), mengisi `toko`/`provider`.
4. **History upload** di bawah form: tabel *file, jenis, toko, provider, DP/WD, baris, duplikat, status, oleh siapa (`uploaded_by`), kapan (`created_at`)* + filter per toko. Data sudah tersedia di model `Upload`; hanya perlu ditampilkan.

## 5. Rekonsiliasi: paralel + cek kelengkapan + history

### 5.1 Pra-cek kelengkapan
Fungsi `check_completeness(toko, date_from, date_to)` mengembalikan status keberadaan tiap sumber untuk toko+periode: `panel_dp`, `panel_wd`, `bracket`, `bank`, `gateway`, plus flag `minimum_met` (Panel + ≥1 Bank/Gateway). Hasilnya dipakai UI sebagai **checklist**.

### 5.2 Orkestrasi
- Tombol **"Jalankan Rekonsiliasi"** untuk Toko+periode terpilih membuat satu **`ReconBatch`** lalu menjalankan relasi yang **datanya tersedia secara bersamaan**:
  - **Panel↔Bracket** — bila Bracket tidak ada → **dilewati + dicatat** di `completeness`/`summary`.
  - **Panel↔Bank/Gateway** — jalan bila ada sumber uang.
- Semua relasi memakai `MATCHERS` yang sudah ada, **ditambah filter `toko`** pada `sides()` (dan filter tanggal yang sudah ada).
- Bila `minimum_met` false → tampilkan **peringatan** kekurangan, user boleh tetap lanjut (soft-gate).

### 5.3 Halaman hasil batch (gaya referensi)
- Kartu **Deposit (DP)** & **Withdraw (WD)**: *Panel (koin) vs Uang real (Bank/Gateway) + Selisih* dengan indikator **Balanced ✓ / ⚠**.
- **Bucket** per relasi: Cocok / Perlu Tinjau / Tidak Cocok (dari `MatchResult`), plus **metrik nilai (Rp)** — bukan sekadar hitungan.
- Daftar **unmatched**: "Panel tanpa pasangan" / "Bank/Gateway tanpa pasangan".
- **Search/filter**, **Export Excel** (sudah ada di `web/views.py:export_run`), dan **review/override** (sudah ada, HTMX → `ReviewAction`).
- **History run/batch** per toko di bawah.

## 6. Navigasi, tema, & scope

- **Selektor Toko global** di header + sidebar bergaya referensi. Tema **terang & padat** untuk halaman kerja; **login tetap dark premium + Three.js**.
- **Masuk sekarang:** Toko + Upload auto-detect/preview/history + Rekonsiliasi paralel, untuk **8 parser yang sudah ada**.
- **Ditunda (extensible, tunggu contoh file):** parser **BNI**, **Credit Bonus**, **Panel Provider** lain; halaman turunan referensi (Credit Bonus, Credit Mutation, Rincian Bank, Summary Bulanan). Titik-sambung disiapkan, tidak dibangun dulu.

## 7. Temuan referensi (acuan UX)

**draw-to-data-magic ("Finance · Report v1") — yang diharapkan:** selektor Toko (LBS/SLO) di kanan-atas; sidebar Dashboard/Import Excel/Credit Bonus/Credit Mutation/Rekonsiliasi/Summary Bulanan/Rincian Bank/Admin; Import Excel pakai slot terpisah (FR, DP Panel, WD Panel, Credit Bonus) + dropdown Perusahaan & **Panel Provider (Nexus)**; Rekonsiliasi = kartu DP/WD (Panel koin vs FR uang real + Selisih) + Winloss/Akuran manual → Profit Real + daftar unmatched; Rincian Bank = rekap per rekening; Credit Bonus = summary per kategori + rincian (kolom **Created By**).

**checkerboard — yang dipakai sekarang:** konsep "sesi audit" per Brand (Recent Sessions: Tanggal, Brand, Tipe, Total, Lunas, Tidak Match, Status); Upload = toggle WD/Deposit + drop-zone Panel (maks 2) & Bank (multi-file) → Apply & Jalankan Audit (butuh langkah Parser Data dulu); Audit Result = bucket Lunas/Perlu Review/Belum Dibayar/Belum Dicek/HV + metrik nilai Rp + metodologi (nama ≥80% + amount → Lunas; 50–79% → Review; norek match → Lunas; BIFAST fee ±2.500; e-wallet ±1.000) + search + Download + Simpan ke History.

## 8. Di luar lingkup (non-goals) sekarang

- Parser BNI, Credit Bonus, dan format Panel Provider selain yang sudah didukung (menunggu contoh file).
- Halaman Credit Bonus, Credit Mutation, Rincian Bank, Summary Bulanan (referensi) — menyusul.
- Winloss/Akuran/Profit Real manual (fitur referensi) — belum diminta; dapat ditambah kemudian.
- Toleransi fee per-kanal (BIFAST/e-wallet) gaya checkerboard — enhancement `ToleranceProfile` di masa depan.

## 9. Risiko & catatan

- **Akurasi auto-detect**: format mirip (Panel & NXPAY sama-sama header baris 2) → sniff harus cek nama kolom khas, bukan hanya posisi header. Fallback "tebak + konfirmasi" menutup kasus ragu.
- **Backfill Toko**: data lama harus dipetakan ke toko default sebelum `toko` dijadikan wajib.
- **Scope pencocokan per toko**: pastikan `sides()` semua matcher memfilter `toko` agar tidak ada match lintas-toko.
- **File bank kumulatif** (BRI month-to-date): tetap ditangani lewat slice per tanggal recon seperti sekarang; `row_hash` mencegah re-import.
