# Desain: Fitur Auditor Gelombang 2 — Export, Sorting, Drill-down, Tren, Per-Bank, Antar-Toko

Tanggal: 2026-07-05 · Branch: `feat/ui-auditor-v2` · Status: disetujui user (paket A+B+C+D lengkap)

## 1. Tujuan

Melengkapi UI auditor dengan tujuh kemampuan kerja berbasis data yang sudah ada, tanpa
menyentuh engine matching dan tanpa migrasi skema:

1. Export Excel mengikuti filter aktif di halaman Transaksi.
2. Sorting kolom server-side di tabel besar (Transaksi, Run detail, Uang Tanpa Pasangan).
3. Drill-down dari semua kartu status dashboard, termasuk halaman antrean tinjau baru.
4. Tren selisih dashboard diperluas: 30 hari + garis total selisih.
5. Filter rentang tanggal di Transaksi.
6. Ringkasan per sumber uang (per-bank) di halaman Batch.
7. Halaman ringkasan antar-toko (`/tokos/`).

## 2. Keputusan yang sudah disepakati

- **Server-side, bukan client-side**: sorting/export bekerja atas seluruh data terfilter
  (bukan 40 baris per halaman); semua state di querystring.
- **Read-only**: nol migrasi; perilaku `engine.py` tidak berubah — view *memakai* helper
  yang sudah ada (`_carried_results`, `check_completeness`, `pending_settlement_count`);
  angka kartu "Menunggu settlement" dan hasil filter `carry=1` dijamin sama karena
  bersumber dari helper yang sama.
- **Antrean tinjau** = halaman baru `/tinjau/` lintas batch/run (opsi yang dipilih user),
  bukan sekadar link ke batch terakhir.
- **Akses `/tokos/`**: semua role, di-scope `tokos_for(user)`; link menu hanya muncul bila
  user mengakses >1 toko.
- Semua parameter querystring di-whitelist; nilai asing jatuh diam-diam ke default.

## 3. Fitur per halaman

### 3.1 Transaksi (`/transactions/`) — filter tanggal, sorting, export

- **Filter tanggal**: dua `<input type=date>` (`date_from`, `date_to`) di filter bar →
  `occurred_at__date__gte/__lte`. Nilai tak valid diabaikan (fallback kosong).
- **Sorting**: `?sort=<key>&dir=asc|desc`. Whitelist:
  `waktu→occurred_at` (default, desc), `amount→amount`, `delta→money_delta`,
  `sumber→source_type__key`, `jenis→jenis`. Header kolom = link dengan indikator ▲/▼;
  klik kolom yang sama membalik arah. Secondary key `id` agar urutan stabil.
- **Export**: `?export=1` pada URL yang sama (semua filter + sort ikut).
  Openpyxl `write_only` + `qs.iterator()` (pola `export_run`). Kolom: Waktu, Sumber,
  Jenis, Amount, Δ Uang, Ticket, Username, Nama Lengkap, Counterparty — nilai pasangan
  rekonsiliasi (≈) diberi prefiks `≈ ` seperti di tabel. Guard: > 100.000 baris →
  `messages.error` minta persempit filter, redirect balik (tanpa export).
  Nama file: `transaksi_<toko>_<YYYYMMDD-HHMM>.xlsx`.
- **Konsistensi link**: semua link (sort, pager, chip bank, export) membawa seluruh
  parameter lain. Refactor kecil di template: bangun querystring lewat satu include/
  variabel konteks `qs_base` supaya tidak copy-paste parameter di 6 tempat.

### 3.2 Run detail (`/run/<pk>/`) — sorting

- `?sort=` whitelist: `amount→left__amount`, `skor→score`, `waktu→left__occurred_at`;
  default tetap `bucket, -score`. Kolom lain tidak bisa di-sort (kolom raw JSON).
- Link sort mempertahankan `bucket`, `reason`, `page`.

### 3.3 Uang Tanpa Pasangan (`/batch/<pk>/uang/`) — sorting

- Baris berupa list Python (kategori dihitung pasca-query) → sort via `sorted(key=…)`:
  `tanggal→occurred_at` (default asc), `nominal→abs(money_delta)`.
- Link sort mempertahankan `k` (kategori) dan reset `page`.

### 3.4 Dashboard — drill-down + tren 30 hari

- **Kartu "Rekon terakhir"** → `a.card.click` ke `batch_detail` batch terakhir
  (kosongkan bila belum ada batch).
- **Kartu "Menunggu settlement"** → `/transactions/?carry=1`.
  Di view transaksi: `carry=1` → `qs.filter(id__in=_carried_results(active).keys())`;
  chip status "menunggu settlement" tampil di filter bar dengan tombol hapus filter.
  Bila dikombinasi filter lain, AND biasa.
- **Kartu "Antrean tinjau"** → halaman baru `/tinjau/` (lihat 3.5).
- **Kartu "Uang periksa (D)"** → seluruh kartu klikabel ke `batch_uang?k=d` (link teks
  yang ada sekarang dipromosikan jadi kartu-link).
- **Tren**: jendela data diubah dari 14 batch terakhir → batch dalam **30 hari kalender**
  terakhir (dari `recon_date` maksimum). Bar DP/WD tetap; tambah `<polyline>` total
  selisih (skala sama, warna `var(--ink)` tipis) + judul "Tren selisih — 30 hari".
  Perhitungan tetap di view `dashboard` (pola sekarang), JS SVG builder diperluas.

### 3.5 Halaman baru: Antrean Tinjau (`/tinjau/`)

- View `review_queue`: semua `MatchResult` bucket `perlu_tinjau` milik toko aktif
  (`run__batch__toko=active`), `select_related` left/right/run/batch,
  urut `-run__batch__recon_date, -score`, paginate 40.
- Tabel memakai kolom inti `_result_row` (Status, Ticket kiri, User ID, Nama, Amount,
  kanan, Amount, Alasan, Aksi ✓/⚑) **plus** kolom "Batch/Run" (link ke run asal,
  nomor batch per-toko). Aksi ✓/⚑ memakai endpoint `review` per-hasil yang sudah ada
  (htmx swap baris) — bekerja lintas run; satu-satunya perubahan backend adalah view
  `review` meneruskan flag kolom (§5) — logika bucket/ReviewAction tidak disentuh.
  Implementasi template: `_result_row.html` diberi flag konteks opsional
  `show_run_col` agar dipakai dua halaman tanpa duplikasi.
- Tanpa bulk action di gelombang ini (bulk_review terikat run) — tercatat di §7.
- Sidebar: badge angka di menu Rekonsiliasi tetap; kartu dashboard "Antrean tinjau"
  dan badge menu menaut ke `/tinjau/`.
- Empty state: "Antrean kosong — semua hasil sudah ditinjau. ✓"

### 3.6 Batch detail — ringkasan per sumber uang

- Kartu tabel baru "Per Sumber Uang" di bawah kartu DP/WD, satu baris per label sumber
  (`specific_source_label(key, account, upload)` per upload — label sama dengan chip
  bank di Transaksi; fallback "Bank"/"Gateway").
- Basis data: `Transaction.objects.filter(consumed_by_batch=batch,
  source_type__key__in=["bank","gateway"]).exclude(jenis="admin")` + annotate
  `berpasangan=Exists(MatchResult left≠null right=OuterRef)` (pola `batch_uang`).
- Kolom: Sumber · Transaksi (n) · DP masuk (Σ money_delta>0) · WD keluar (Σ |money_delta<0|)
  · Berpasangan (n) · Tanpa pasangan (n, link ke `batch_uang`).
- Dihitung on-the-fly di view `batch_detail` → batch lama otomatis kebagian; summary
  JSON batch TIDAK diubah.

### 3.7 Halaman baru: Ringkasan Toko (`/tokos/`)

- View `toko_overview`: loop `tokos_for(user)` (≈16 toko, query per toko dapat diterima;
  optimasi agregat ditunda sampai terasa lambat).
- Per toko: batch terakhir (`recon_date`, status warna: hijau selisih 0 / kuning
  < 10 jt / merah ≥ 10 jt — ambang sama dengan kalender dashboard), selisih DP+WD,
  antrean tinjau (count bucket TINJAU), menunggu settlement
  (`pending_settlement_count`), uang periksa D (dari `summary.unmatched_money.d.n`
  batch terakhir), tombol "Buka" (form POST `set_toko` dengan `next=/`).
- Urutan default: total selisih terbesar dulu; toko tanpa batch di bawah (status "belum
  rekon", badge muted).
- Link menu sidebar "Ringkasan Toko" (seksi Menu) hanya bila `all_tokos|length > 1`.
- RBAC: scoping otomatis via `tokos_for`; auditor 1 toko tetap boleh akses URL-nya
  (isinya cuma tokonya) — menu saja yang disembunyikan.

## 4. Struktur kode

- `web/views.py`: perluas `transactions` (tanggal/sort/carry/export), `run_detail`
  (sort), `batch_uang` (sort), `batch_detail` (per-bank), `dashboard` (tren 30 hari,
  konteks link kartu); view baru `review_queue`, `toko_overview`.
  Helper sort bersama: `_apply_sort(qs, request, whitelist, default)` di `web/views.py`.
- `web/urls.py`: `path("tinjau/", …, name="review_queue")`,
  `path("tokos/", …, name="toko_overview")`.
- Template: `transactions.html`, `run_detail.html`, `batch_uang.html`,
  `batch_detail.html`, `dashboard.html`, `_result_row.html` (flag `show_run_col`),
  `app_base.html` (menu Ringkasan Toko + link badge tinjau); baru:
  `review_queue.html`, `toko_overview.html`. Komponen visual memakai design system
  yang ada (card-head, badge, num, tall, cell-empty, empty).
- Ikon header sort: karakter ▲/▼ (tanpa SVG baru).

## 5. Edge cases

- `sort`/`dir`/`k`/`bucket` tak dikenal → default, tanpa error.
- `date_from > date_to` → hasil kosong wajar (tidak dianggap error).
- `carry=1` saat tidak ada carry → tabel kosong + chip filter tetap tampil.
- Export 0 baris → file tetap dibuat (header saja).
- Toko tanpa batch / batch tanpa `recon_date` (era lama) di `/tokos/` → "belum rekon" /
  tanggal `created_at` sebagai fallback tampilan.
- `/tinjau/` hasil yang barisnya sudah di-flip late settlement tetap tampil apa adanya
  (bucket live dari DB — selalu jujur).
- Hasil `review` di `/tinjau/` memakai htmx swap `_result_row` dengan `show_run_col`
  → view `review` perlu meneruskan flag dari `hx-vals` agar baris pengganti berkolom sama.

## 6. Testing (TDD, `web/tests_*.py`)

- `tests_tx_filters`: filter tanggal membatasi; sort amount asc/desc mengubah urutan;
  sort asing → default; kombinasi filter+sort+page konsisten.
- `tests_tx_export`: export menghormati filter (jumlah baris data = queryset), header
  kolom benar, guard >100k (monkeypatch batas kecil), 0 baris → header saja.
- `tests_tx_carry`: `carry=1` hanya menampilkan baris `_carried_results`; kombinasi
  dengan filter lain.
- `tests_review_queue`: hanya bucket TINJAU toko aktif; lintas batch; RBAC (auditor
  toko lain tidak melihat); aksi review dari halaman ini mengubah bucket + baris
  pengganti memuat kolom run.
- `tests_batch_perbank`: angka per sumber cocok dengan fixture kecil (2 upload beda
  bank, sebagian berpasangan).
- `tests_toko_overview`: urutan selisih; auditor hanya melihat tokonya; toko tanpa
  batch tampil "belum rekon"; tombol Buka mengganti toko aktif.
- `tests_dashboard_links`: URL drill-down kartu benar (carry, tinjau, uang?k=d).
- Sorting run/batch_uang: satu test per halaman (urutan berubah, param dipertahankan).

## 7. Di luar cakupan (gelombang berikutnya)

- Bulk action (✓ massal) di `/tinjau/` lintas run.
- Export untuk `/tinjau/` dan `/tokos/`.
- Agregasi `/tokos/` dalam satu query (optimasi bila jumlah toko membengkak).
- Kolom sort untuk field JSON raw (Player Bank dst.).
- Filter tanggal di halaman selain Transaksi.
