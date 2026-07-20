# Paket E — Rekonsiliasi Bonus Panel↔Bracket + Bulk Marking Area Pengecekan — Desain

**Tanggal:** 2026-07-20 · **Status:** disetujui user (AskUserQuestion: rekonsiliasi penuh, semua kategori, tambah bulk) · **Paket:** E

## Permintaan klien (chat 19–20 Jul)

- "Menambahkan bonus harian, mingguan yang tercatat di bracket, dan panel" — 3 sampel
  MUL 15-07: panel *Credit Balance*, bracket *Credit Bonus*, bracket *Non Credit Bonus*.
- "Untuk lucky draw di bracket terpisah di bagian non credit bonus… di panel terbaca
  sebagai lucky draw, di bracket pke kode **K-BLD ( jadi intinya K-BLD = lucky draw )**".
- "Gw mau manualin dari yg tidak cocok ke cocok cmn meski 1 1, gabisa bulk" — per-baris
  ✓ sudah ada & bekerja; celah nyata: **Area Pengecekan** punya checkbox tapi tak punya
  tombol bulk (form `bulk-form`-nya kosong). Ditambah bulk di sana.

## Bukti data (profil 3 sampel, 2026-07-20)

**Panel Credit Balance** (header baris 2: `No. | Brand | Date & Time | Description |
Remarks | Payment Type | Payment Details | Amt. | Current Credit Balance`; 4.828 baris
data; `Amt.` RIBUAN): Deposit 3.493 · Withdraw 661 · **Promotion Claim 474 ·
Redemption Coupon 122 · Lucky Draw Agent 6 · Adjustment 4** · Offset 6 · Opening 1 ·
Reject 6 · lainnya 2. Setiap Lucky Draw = SEPASANG baris (reward Amt− & `Offset …` Amt+,
net nol di panel) — sisi bonus yang dihitung = baris reward (Amt negatif), **Offset
dilewati**. `Adjustment:` membawa kode bracket di Remarks (`K-BCR3`, `K-BLS`).

**Bracket Credit Bonus** (header baris 1: `Transaction ID | Category | Description |
Nominal | Deleted | Created By | Date`; 128 baris; `Nominal` RUPIAH PENUH): kategori
`BONUS LOYALTY MURAH (BL1)` 81 · `BONUS LOYALTY POINT (BLM)` 41 · CRM 2 · NEW MEMBER 2 ·
ROLLINGAN 1 · EVENT 1. Description memuat `Player: <username>` di baris kedua.

**Bracket Non Credit Bonus**: sama tapi TANPA kolom `Category`; Description =
`K-BLD\nPlayer: <username>`; 6 baris — **cocok persis 1:1 by player+nominal dengan 6
baris Lucky Draw panel** (Pratama121 50rb, ariese7en 25rb, zurazur 25rb, milito77 25rb,
kia112 50rb, ginanjar30 25rb). K-BLD = Lucky Draw TERKONFIRMASI di data.

Kondisi kode saat ini (eksplorasi menyeluruh): ketiga layout **tidak dikenali parser
mana pun** (deteksi kosong; force-parse = nol baris / salah-baca senyap), dan **tidak
ada rekonsiliasi bonus apa pun** di mesin (bonus rows ter-exclude dari semua matcher).

## Keputusan desain

1. **SourceType baru `panel_bonus` & `bracket_bonus`** (seed migration sources 0010 +
   perluasan `KIND_CHOICES`). `check_completeness`, semua matcher, `_consume_scope`,
   dan agregat DP/WD hanya mengenal key `panel/bracket/bank/gateway` → jalur bonus
   **terisolasi penuh dari pipeline harian** tanpa menyentuh engine.
2. **Dua parser baru di `sources/parsers/bonus.py`**:
   - `panel_bonus`: HANYA baris berawalan `Redemption Coupon`/`Promotion Claim`/
     `Lucky Draw Agent`/`Adjustment:` (skip Deposit/Withdraw/Offset/Opening/Reject —
     DP/WD sudah diimpor parser panel; Offset = penyeimbang net-nol). `Amt.`×1000;
     username = token terakhir Description minus prefix `Brand`; kategori kanonik
     disimpan di `raw["Kategori"]` (Lucky Draw Agent → "Lucky Draw").
   - `bracket_bonus`: satu parser untuk kedua file bracket (`Category` opsional);
     skip `Deleted=Yes`; username dari regex `Player:`; `Nominal` rupiah penuh
     (TANPA ×1000); kategori = kolom `Category`, atau kode awal Description via
     `KODE_BONUS = {"K-BLD": "Lucky Draw"}`.
   - Kedua sisi: `jenis="bonus"`, `money_delta=0` (bonus bukan uang), `ticket_no=""`.
3. **Deteksi** (0.95): panel_bonus = `date & time`+`payment details`+`current credit
   balance`; bracket_bonus = `transaction id`+`nominal`+`deleted`+`created by`.
   Diverifikasi tak bentrok signature lain (FR bracket butuh `kategori`; cor_panel_qris
   butuh `requested date`).
4. **Mesin cocok query-time `web/bonus.py`** (pola retroaktif hutang.py/biaya.py, TANPA
   migrasi hasil, TANPA menyentuh `run_batch`): kunci = **username lowercase + nominal
   bulat + tanggal**; pairing 1:1 greedy per kunci (deque); hasil 3 ember **Cocok /
   Hanya Panel / Hanya Bracket** + ringkasan per kategori. Halaman `/bonus/`
   ("Rekonsiliasi Bonus", menu grup Rekonsiliasi setelah Area Pengecekan): kartu stat,
   filter rentang tanggal (default 30 hari), tab per ember (default Hanya Panel —
   daftar yang actionable), pager 40.
   *Rasional query-time:* app live finansial; bonus tak punya sisi uang → menyuntik
   relasi ke orchestrator (completeness/consume/late-settlement) berisiko tanpa
   manfaat. Bisa dipromosikan ke alur batch nanti bila klien butuh tombol ✓ di bonus.
5. **Bulk marking Area Pengecekan**: view `bulk_review_queue` (POST
   `/tinjau/bulk-review/`, lintas-run; scope `run__batch__toko__in=tokos_for(user)`),
   mutasi per baris identik `bulk_review` (bucket + `manual_override` + `ReviewAction`
   + `catat` + `refresh_batch_summary` per batch tersentuh, sekali per batch); form
   `bulk-form` di `review_queue.html` diisi tombol Setujui/Tinjau terpilih + pilih-semua
   (cermin `run_detail.html`); checkbox baris harus terasosiasi form (atribut
   `form="bulk-form"` bila baris di luar elemen form).

## Uji & kalibrasi

- Unit: parser (fixture xlsx sintetis: filter baris, skip Offset/Deleted, username
  brand-strip & `Player:`, K-BLD→Lucky Draw, skala ×1000 vs penuh, row_hash stabil);
  deteksi 3 layout + regresi signature lama; `web/bonus.py` (cocok/panel_only/
  bracket_only, per-kategori, rentang tanggal); view render + menu + empty state;
  bulk_review_queue (happy, lintas-run, scope toko lain 0 efek, aksi tak dikenal 400,
  refresh summary terpanggil per batch).
- Kalibrasi data nyata (scratch DB): ingest 3 sampel → panel_bonus **606** baris
  (474+122+6+4), bracket_bonus **134** (128+6); rekonsiliasi 15-07: **Lucky Draw 6/6
  cocok**; Redemption/Loyalty mayoritas cocok; Promotion Claim mayoritas Hanya Panel
  (bracket credit-bonus hanya mencakup sebagian kategori — itulah temuan yang memang
  ingin dilihat klien).

## Risiko

- `parse_dt` mungkin belum mengenal format `15-Jul-2026 00:00:09.927` → tambah format
  secara aditif di `base.py` (suite lama menjaga regresi).
- Panel Promotion Claim >> bracket → ember Hanya Panel besar; per-kategori breakdown
  membuatnya legible, bukan bug.
- Bonus lintas-hari dekat tengah malam tak cocok (kunci tanggal eksak) — diterima v1.
