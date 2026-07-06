# Onboarding 3 brand (COR / MUL / MXW) + parser & pencocokan kunci-exact

**Tanggal:** 2026-07-07
**Status:** disetujui (brainstorming), lanjut ke rencana implementasi

## Konteks

Tiga brand baru masuk untuk direkonsiliasi:

| Brand | Kode/Brand di file | Status format |
|---|---|---|
| **MXW** — MaxWin77 | panel `Brand=MAW` | **reuse** parser existing |
| **MUL** — Mulia77 | panel `Brand=M77` | **reuse** + 1 gateway baru (QRIS HOKI) |
| **COR** — Gacor25 | bracket `Asset Bank=Gacor25`, panel `By=gacor25subNN` | **operator baru** — 3 format baru |

Temuan kunci: sisi UANG di brand-brand ini membawa **kunci exact** ke Panel
(bukan cuma fuzzy nama+nominal seperti sebelumnya). Ini menaikkan confidence match
secara drastis dan jadi inti nilai pekerjaan ini.

### Bukti match-rate (irisan kunci pada data nyata, tgl 1–3 Jul 2026)

| Brand | Rail (share volume DP) | Kunci exact | Cocok |
|---|---|---|---|
| COR | QRIS DP (**~98%** volume) | panel `Transaction ID` (UUID) = gateway `OrderId` | 96,8% → 100% → 100%; nominal **100%** |
| COR | Bank DP (~2%, ±192/hari) | nama/no.HP + nominal | fuzzy (engine existing) |
| MUL | DP (QH ∪ NXPAY) | QH `Whitelabel`=Ticket / UUID=`TxnID`; NXPAY `Ticket Number` | **96,6%** (9784/10125) |
| MXW | DP (FLYER ∪ NXPAY) | FLYER `TXN ID` / NXPAY `Ticket Number` = Ticket Panel | **97,6%** (6791/6956) |

Konsekuensi desain:
- **COR justru paling "mudah"**: ~98% volume deposit lewat QRIS exact; hanya ~2%
  lewat bank rail fuzzy.
- **Bracket COR tak punya kunci exact** (dibuktikan: 0 UUID & 0 D/W-ticket dari
  11.987 baris `Finance Report`). Jembatan ke panel cuma Username+nominal+waktu.
- Ditemukan **bug loader** saat validasi: exporter COR (`BANK_approved…`,
  `QRIS_…_transactions`) menulis xlsx tanpa tag `<dimension>` dan `styles.xml`
  non-standar → `openpyxl` gagal / baca 0 baris. Wajib reader tahan-styles.

### Topologi rekonsiliasi per brand

- **MUL & MXW** (tak berubah dari model existing): Panel↔Bracket (join Ticket D…
  di `Description` bracket), Panel↔Uang (ticket-join gateway + fuzzy bank),
  Bracket↔Uang (fuzzy).
- **COR**:
  - Panel = **dua rail**: `BANK_approved_*` (bank) + `QRIS_*_transactions` (QRIS),
    keduanya `source_type=panel`.
  - Panel↔Uang = tulang punggung: QRIS exact (UUID) + bank fuzzy.
  - Bracket↔Uang = `BracketBankMatcher` existing (bracket punya No. Rek + nama).
  - Panel↔Bracket = **cross-check agregat** (total DP/WD per hari), BUKAN
    baris-per-baris (tak ada kunci; hindari ribuan "perlu tinjau" palsu).

## Ruang lingkup

### 1. Reader xlsx tahan-styles (fondasi)

Di `sources/parsers/base.py`: buat `read_xlsx_rows` (atau helper baru
`read_xlsx_rows_safe`) yang:
1. Coba `openpyxl` (jalur cepat, existing).
2. Bila raise **atau** menghasilkan ≤1 baris data → fallback ke reader mentah
   (zip + `xml.etree`) yang membaca `xl/sharedStrings.xml` + `xl/worksheets/sheetN.xml`,
   mengabaikan `styles.xml`/`dimension`.

Reader mentah minimal: map kolom `A1` → indeks, dukung `t="s"` (shared string),
`t="inlineStr"`, numeric; stop-early opsional. Pendekatan ini sudah divalidasi
manual pada file COR nyata saat brainstorming (openpyxl gagal, reader mentah baca
penuh) — tinggal diimplementasikan rapi di `base.py`.

`sources/detect.py::_xlsx_tokens` HARUS memakai reader yang sama (kalau tidak,
file COR gagal terdeteksi).

### 2. Parser baru: `cor_panel_bank`

File: `COR/NN/BANK_approved_deposit|withdraw_gacor25subNN_YYYYMMDD.xlsx`
Kolom: `#, Approved Date, Requested Date, Username, From Bank, Destination Bank, Amount, Status, By`

- `source_type="panel"`. `jenis` = depo/wd dari **flow** (nama file `deposit`/`withdraw`).
- **`amount` = rupiah penuh** (JANGAN ×1000). Ini beda dari `PanelParser` (yang ×1000).
- DP: `money_delta=+amt`, `credit_delta=-amt`; sisi pemain = `From Bank`, operator = `Destination Bank`.
- WD: `money_delta=-amt`, `credit_delta=+amt`; sisi operator = `From Bank`, pemain = `Destination Bank`.
- Kolom bank berformat `"KODE - NOREK - NAMA"` (mis. `DANA - 081270670097 - FEBRIA`).
  **Normalisasi ke format raw existing** agar engine reuse maksimal:
  - `raw["Player Bank"] = f"{KODE}|{NAMA}|{NOREK/NoHP}"` (sisi pemain) →
    `_panel_phone()` & phone-match jalan tanpa ubah engine.
  - `raw["Bank Title"] = f"{KODE}|{NAMA}|{NOREK}"` (sisi operator/tujuan) →
    `_expected_owner()` & routing jalan.
  - `player_bank`, `bank_title` via `bank_code()` (segmen pertama).
- `ticket_no=""`, `reference=""`, `username=Username`, `counterparty=NAMA pemain`.
- `occurred_at=Requested Date` (jangkar kredit paling awal, searah date-window),
  `posted_date=Approved Date`.
- Filter `Status=approved`. `row_hash=[username, amount, occurred, NOREK pemain]`.

### 3. Parser baru: `cor_panel_qris`

File: `COR/NN/QRIS_deposit|withdraw_transactions_YYYYMMDD.xlsx`
Kolom DP: `#, Approved Date, Requested Date, Username, Transaction ID, Amount, Bonus, Status`
Kolom WD: `…, Transaction ID, Destination Bank, Amount, Status, By`

- `source_type="panel"`, `jenis` dari flow. `amount` = rupiah penuh.
- **`reference = Transaction ID`** (UUID 20-char) — **kunci exact ke gateway**.
- `ticket_no=""`, `username=Username`.
- DP: `counterparty=""`; WD: `counterparty=NAMA` dari `Destination Bank` (+ isi
  `raw["Player Bank"]` untuk phone-match e-wallet payout).
- Filter `Status ∈ {success}`. `occurred_at=Requested Date`.
- `row_hash=[reference, username, amount]`.

### 4. Parser baru: `cor_qris_gateway`

File: `COR/NN/… DP_QRIS_TRANSACTION.xlsx` (laporan processor QRIS; **hanya DEPOSIT**)
Kolom: `BranchName, GrandTotal, BranchNominal, OrderId, TransactionTime, RRN, IssuerName, CustomerName, Channel, Order Id Merchant`

- `source_type="gateway"`, `jenis="depo"`, `flow=dp`.
- **`reference = OrderId`** (UUID) — kunci exact ke `cor_panel_qris.reference`.
- `amount = GrandTotal` (gross), `fee = GrandTotal − BranchNominal` (net di `BranchNominal`).
- `money_delta = +amount`. `ticket_no=""`. `occurred_at = TransactionTime`.
- Simpan `RRN` di `raw` (konfirmasi sekunder). `counterparty=""` (processor tak bawa nama).
- `row_hash=[reference, amount]`.

### 5. Parser baru: `qhoki` (QRIS HOKI — gateway MUL)

File: `MUL/DP QH MUL … .xlsx`
Kolom: `Transaction Date, Paid Date, Finished Date, Settlement Date, Settled At, Member ID, Rrn, NMID, Transaction ID, Whitelabel Transaction ID, Status, Amount, Downline Fee Amount, Total Amount, Memo, Payment Method`

- `source_type="gateway"`, `jenis="depo"`, `flow=dp`.
- **`ticket_no = Whitelabel Transaction ID`** (D…) → cocok via **pass 0 existing** (ticket-join).
- **`reference = Transaction ID`** (UUID) → cocok via reference-join (redundansi/konfirmasi).
- `username = Member ID`. `amount = Amount` (gross), `fee = Downline Fee Amount`
  (net di `Total Amount`). `money_delta=+amount`.
- Filter `Status ∈ {Success}`. `occurred_at = Transaction Date`.
  Catatan: `Settlement Date` = pagi H+1 → normal untuk logika late-settlement existing.
- `row_hash=[reference, ticket_no, amount]`.

### 6. Registrasi & deteksi

`sources/services.py::PARSERS` tambah: `cor_panel_bank`, `cor_panel_qris`,
`cor_qris_gateway`, `qhoki`.

`sources/detect.py` tambah signature (token header + hint nama file):
- `cor_panel_bank`: header berisi `{From Bank, Destination Bank, Approved Date}`.
- `cor_panel_qris`: `{Transaction ID, Amount}` + nama file `QRIS_*_transactions`.
- `cor_qris_gateway`: `{OrderId, GrandTotal, BranchNominal}`.
- `qhoki`: `{Whitelabel Transaction ID, NMID}`.

Flow DP/WD diambil dari nama file (`deposit|DP` → dp, `withdraw|WD` → wd) —
pakai/expand helper flow yang sudah dipakai upload web.

### 7. Engine: reference-join pass (kecil, general)

Di `reconciliation/engine.py::_MoneyMatcher.match`, tambah **pass 0b** tepat
setelah ticket-join, **simetris & gateway-only** (jangan sentuh `reference` bank
seperti SEQ BRI):

```
gw_ref = defaultdict(list)          # hanya b.source_type.key=="gateway" & b.reference
for b in right:
    if b.source_type.key == "gateway" and b.reference:
        gw_ref[b.reference].append(b)
panel_refs = {p.reference for p in left if p.reference}

# pass 0b: untuk tiap panel p ber-reference, cari gateway b dgn reference sama,
#   arah uang sama, belum used → nominal sama = COCOK("reference"),
#   beda = TINJAU("reference_amount").
# blocked_ref = gateway ber-reference yg reference-nya TIDAK dikenal panel →
#   dikeluarkan dari kandidat fuzzy (muncul sbg no_panel), seperti pass 0.
```

- Menyalakan match pasti QRIS COR (UUID). MXW sudah lewat ticket-join; MUL lewat
  keduanya. Aman untuk brand lama (mereka tak punya panel.reference == gateway.reference
  selain kasus yang memang benar).

Opsional (redundansi MUL): helper `extract_uuid` + set panel `reference =
extract_ref(remarks) or extract_uuid(remarks)`. Tidak wajib (MUL sudah cocok via
Whitelabel=ticket); tambahkan hanya bila murah & tak mengganggu brand lama.

### 8. Engine: PanelBracket lewati baris panel tanpa ticket

`PanelBracketMatcher.match`: baris `left` (panel) dengan `ticket_no==""`
**di-skip** (jangan emit `no_bracket`). Alasan: baris tanpa ticket tak bisa
di-ticket-join; verdict-nya ditangani money-matcher. Untuk COR (panel tanpa ticket)
ini bikin PanelBracket menghasilkan 0 hasil palsu; MUL/MXW (semua ticket ada) tak
terpengaruh.

### 9. Cross-check agregat Panel↔Bracket (untuk COR)

Tambah warning di `_aggregate_batch` (atau helper baru seperti
`_bracket_overlap_warning`): bandingkan `Σ panel depo.amount` vs
`Σ bracket(jenis=depo).amount` (dan WD) dalam scope batch; bila selisih >
toleransi → `warnings.append(...)`. Memberi sinyal Panel↔Bracket untuk COR tanpa
match baris. Berlaku umum (berguna juga sbg sanity total brand lain).

### 10. Bracket: lengkapi KATEGORI_MAP COR

Kategori COR teramati: `Deposit, Withdrawal, BEBAN ADMIN BANK, BEBAN ADMIN QRIS,
Biaya Transaksi, Sesama CM, Pending DP, Adjustment, Hutang`. Yang belum dipetakan
(`Sesama CM, Pending DP, Adjustment, Hutang`) → tetap `lainnya` (dikecualikan dari
total DP/WD) — konfirmasi ini benar (mis. `Pending DP` **bukan** deposit selesai).

### 11. Onboarding

- Buat 3 Toko: COR, MUL, MXW (via admin UI existing) + assign RBAC auditor.
- MUL & MXW: verifikasi auto-deteksi lalu upload pakai parser existing
  (`panel, bracket, bri, bca_csv, bca_pdf, mandiri, nxpay, qrflyer`) + `qhoki` (MUL).

## Tes & verifikasi

- **Unit parser** (fixture kecil per format): assert field kanonik — amount rupiah
  (COR tanpa ×1000), `reference`/`ticket_no` terisi benar, DP/WD sign, filter status.
- **Reader tahan-styles**: fixture xlsx tanpa `<dimension>` → baris terbaca.
- **Engine**: (a) reference-join → COCOK saat panel.reference==gateway.reference &
  nominal sama; (b) PanelBracket skip baris panel tanpa ticket.
- **Fase 0 — harness validasi** (gate "buktikan dulu", pakai engine ASLI):
  management command / test yang ingest file sampel nyata (atau fixture ringkas) ke
  DB uji lalu `run_batch`, dan assert ambang match-rate:
  - COR QRIS DP: bucket `cocok` ≥ 95% baris panel-QRIS.
  - MUL/MXW DP: `cocok` ≥ 95%.
  Laporkan rincian exact vs fuzzy vs tidak-cocok sebelum integrasi UI penuh.
- `python manage.py test` hijau (target ≥ jumlah test existing).

## Deploy

Ikuti alur existing (Railway). Tak ada migrasi skema baru (Toko lewat data/admin).
Setelah hijau + Fase 0 lolos → commit per chunk, push origin `main` (sumber deploy).

## Asumsi & di-luar-lingkup (dikonfirmasi user)

- Semua 3 brand dikerjakan sekaligus (satu spec).
- Bracket COR = **cross-check agregat**, bukan baris-per-baris.
- **Buktikan match-rate dulu** (Fase 0) sebelum integrasi web penuh.
- **File datang bertahap:** set file saat ini belum tentu lengkap (bisa ada
  statement bank / gateway WD tambahan kemudian). Desain sudah tahan ini —
  `check_completeness` + carry-over harian membuat baris uang/kredit tanpa pasangan
  tetap `no_money`/"menunggu settlement", dan idempotensi `row_hash` membuat upload
  susulan aman (baris lama tak dobel). Plan **tidak boleh** mengasumsikan semua
  sumber selalu hadir dalam satu run.
- **Di luar lingkup (deferred):**
  - Match nomor rekening bank-vs-bank (hanya ~2% volume COR; e-wallet sudah via
    phone-match). Bisa jadi peningkatan lanjutan.
  - Sisi uang **WD QRIS COR** (tak ada file gateway WD; direkon ke mutasi
    bank/e-wallet bila tersedia).
  - Ketersediaan statement BNI/SeaBank COR (baris panel `From Bank=BNI/SEABANK`
    tanpa file uang → akan jadi `no_money`; wajar, menunggu file).
