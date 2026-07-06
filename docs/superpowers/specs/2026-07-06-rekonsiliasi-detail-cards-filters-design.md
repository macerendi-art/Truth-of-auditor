# Rekonsiliasi detail — kartu, filter bank, ringkasan total, rename

**Tanggal:** 2026-07-06
**Status:** disetujui (brainstorming), lanjut implementasi → deploy

## Konteks

Halaman detail run (`web/templates/web/run_detail.html` + `web.views.run_detail`)
menampilkan hasil satu `MatchRun` untuk salah satu dari 3 relasi
(`panel_bank`, `bracket_bank`, `panel_bracket`). Semua perubahan di bawah
memakai template + view yang sama, jadi otomatis berlaku untuk ketiga relasi.

Temuan data (dari DB nyata):
- Panel `raw`: punya `Player Bank` (`DANA|Nama|08xxx`) dan `Bank Title`
  (`QRIS|QRISFLYER|156…`, `BCA|…`).
- Bracket `raw`: punya `No. Rek Bank Member` (`BCA 7126201591`, `QRIS 156…`)
  dan `Bank` (`BANK BCA | …`, `QRIS FLYER | …`).
- `Tidak Cocok` (mis. 279) = `no_money`/"Belum ada uang masuk" (mis. 174, ada
  baris kredit `left`) + `no_panel`/"Tak ada di panel" (mis. 105, orphan uang,
  `left` null). Split bersih lewat `left__isnull`.

## Ruang lingkup (7 bagian)

### 1. Lima kartu ringkasan + tab baru (pisah bucket)
Kartu (urut): **Total** · Cocok · Perlu Ditinjau · **Tidak Cocok** ·
**Tidak Ada di Panel** (`grid cols-5`, menumpuk di mobile).
- **Tidak Cocok** = `bucket=tidak_cocok` **AND** `left` NOT NULL (`no_money`).
- **Tidak Ada di Panel** = `bucket=tidak_cocok` **AND** `left` IS NULL
  (`no_panel`); label mengikuti relasi ("Tak ada di Panel" / "…Bracket").
- Dua angka baru dihitung **live** (pola sama dgn chip alasan yang sudah ada);
  Total/Cocok/Perlu tetap dari `run.summary`.
- Tab baru **Tidak Ada di Panel**; view memakai pseudo-bucket:
  - `bucket=tidak_cocok` → filter `bucket=TIDAK, left__isnull=False`.
  - `bucket=tidak_ada_panel` → filter `bucket=TIDAK, left__isnull=True`.

### 2. Filter alasan → collapsible
Bungkus baris chip alasan dalam `<details><summary>Filter alasan (n)</summary>`
native, **default tertutup**; `open` otomatis bila ada alasan aktif.

### 3. Filter Player Bank (baru, collapsible)
- Kolom denormalisasi `Transaction.player_bank` (CharField, tanpa index —
  query selalu dibatasi `run_id` seperti chip alasan).
- Isi saat ingest: panel → `Player Bank` seg-0; bracket →
  `No. Rek Bank Member` token-0 (uppercase + strip). Helper di `parsers/base.py`.
- Chip live via `qs.values('left__player_bank').annotate(Count)` dalam
  bucket/flow aktif; klik → `qs.filter(left__player_bank=…)`. Default tertutup.

### 4. Rename (semua tempat)
- Header nominal kiri → **Kredit/Koin**; nominal kanan → **Saldo Bank** (relasi
  uang), panel↔bracket tetap "Kredit/Koin". Lewat `REL_AMOUNT_LABELS` baru.
- `Bank/Gateway` → **Mutasi Bank** di: `reconciliation/models.py`
  (Relation choices → migrasi `AlterField`, no-op DB), `web.views.REL_LABELS`,
  `reconcile.html`, `review_queue.html`, dan `engine.NO_MONEY_DETAIL`.
- Tes terdampak diperbarui: `tests_run_columns`, `tests_fullname_labels`,
  `tests_batch_filter`.

### 5. Ringkasan total terfilter (bawah tabel)
Bar di bawah tabel: **Baris: N · Total Kredit/Koin: Rp… · Total Saldo Bank:
Rp…**, dari `qs.aggregate(Sum(left__amount), Sum(right__amount), Count(id))`
pada set terfilter penuh (bucket+flow+alasan+player_bank+bank_title). Tampil di
semua tab (mencakup Perlu Ditinjau). Label ikut `REL_AMOUNT_LABELS`.

### 6. Filter Bank Title (baru, collapsible)
- Kolom denormalisasi `Transaction.bank_title`: panel → `Bank Title` seg-0;
  bracket → `Bank` seg-0 (channel; **bukan** `Asset Bank` = "HOKI25").
- Di-backfill bersama `player_bank` dalam satu migrasi data.
- Chip collapsible, pola sama dgn Player Bank; klik → re-total bar bagian 5.

### 7. Migrasi (jalan di prod saat deploy)
1. Schema: tambah `player_bank` + `bank_title`; `AlterField` label choices.
2. Data: backfill `player_bank` + `bank_title` untuk baris panel+bracket lama
   (batched `iterator()` + `bulk_update` ~2000/batch; efisien di prod).

## Tes & verifikasi
Tes baru: hitung split bucket, filter tab `tidak_ada_panel`, ekstraksi
`player_bank`/`bank_title` + backfill, query filter bank, agregat total, label
hasil rename. Jalankan seluruh suite + cek browser-preview sebelum deploy.

## Deploy
Commit di worktree → push branch ke `origin/main` (fast-forward; branch == main)
→ di repo standalone `/Users/macads/Truth-of-auditor`: `git pull origin main` →
`railway up --ci`. **Deploy dari repo standalone, BUKAN worktree** (worktree
mengirim konten basi). Verifikasi live via hash aset login / smoke test.

## Asumsi (dikonfirmasi user)
- Ringkasan total tampil di semua tab (bukan hanya Perlu Ditinjau).
- Bracket "Bank Title" = `Bank` seg-0.
