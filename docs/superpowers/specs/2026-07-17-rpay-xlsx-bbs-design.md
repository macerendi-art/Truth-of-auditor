# Parser RafflesPay XLSX (BBS) — Desain

**Tanggal:** 2026-07-17 · **Status:** disetujui user · **Paket:** G (prioritas 1 dari peta feedback 16–17 Jul)

## Masalah

Klien (BBS) mengunggah laporan QRIS RPAY (RafflesPay) DP & WD dan "tidak terbaca".
Bukti empiris (sampel `16.zip`, 16-07-2026):

- `16_07_2026_BBS_DP_QRIS_RPAY_CSV.xlsx` → **salah terdeteksi `nxpay` 0.90** — header
  memuat `Ticket Number` + `Admin Fee` + `Account Title`, persis sinyal nxpay
  (`sources/detect.py:84`). Confidence ≥0.8 membuat web langsung ingest dengan parser
  salah tanpa konfirmasi.
- `16_07_2026_BBS_WD_QRIS_RPAY.xlsx` → **salah terdeteksi `qrflyer` 0.85** hanya karena
  nama file mengandung "QRIS" (`sources/detect.py:90`).

Parser RafflesPay yang sudah ada (`rpay`, `rpay_wd`) berbasis **CSV** dengan kolom
berbeda (`Customer Username`/`UUID`; `External ID`/`Transfer Status`) — format XLSX BBS
ini varian baru, bukan duplikat.

## Format file (dari sampel nyata)

### DP — `*_DP_QRIS_RPAY_CSV.xlsx` (meski bernama CSV, isinya xlsx)

Header 1 baris, 18 kolom, 1.233 baris data:
`Website, Date, Ticket Number, Player, Payment Type, Account Title, Status,
Payment Gateway, RRN, Amount (IDR), Amount (Chip), Player Fee, Agent Fee, Admin Fee,
Player Nett Amount, Agent Nett Amount, Ticket Status, Promotion`

- `Status`: semua `Success`. `Ticket Status`: 1.230 `approved`, 3 `failed`.
- `Amount (IDR)` = rupiah penuh (mis. 30000). `Amount (Chip)` = ribuan (konvensi panel).
- `RRN`: 1.224 unik dari 1.233 (ada duplikat) — campuran numerik & alfanumerik.
- `Payment Gateway`: `RafflesPay`.

### WD — `*_WD_QRIS_RPAY.xlsx`

Header **dua tingkat** (baris 1 grup, baris 2 sub-kolom), data mulai baris 3, 16 kolom:

| Grup (baris 1) | Sub (baris 2) |
|---|---|
| ID, Website, Date, Ticket, Player, Source of Funds | — |
| Beneficiary | Bank, Name, Number |
| Amount | Amount, Disbursed Amount, Fee |
| Status | Status, Approve, Reject, Transfer |

- `Ticket` = tiket panel `W…`. `Beneficiary Bank` bisa bank ATAU e-wallet
  (SEABANK/DANA/BCA/BRI/GOPAY/BSI/BNI/MANDIRI pada sampel).
- `Fee` flat 5000/trx. Sampel: 17 baris, semua `Status=approved`+`Transfer=success`.
- Catatan teknis: `read_xlsx_rows` (reader tahan-styles) menghasilkan grid rusak untuk
  file ini; **openpyxl langsung bekerja normal** → parser WD pakai openpyxl.

## Desain

### 1. Dua parser baru di `sources/parsers/gateways.py`

Konvensi repo: satu class per format. Parser CSV lama (`rpay`, `rpay_wd`) TIDAK disentuh
— sudah dikalibrasi untuk MUL/M77 & BBS/BO7 CSV.

**`RPayDPXlsxParser`** — key `rpay_xlsx`, `source_key="gateway"`:

- Baca via `read_xlsx_rows` (reader tahan-styles; terbukti bekerja pada sampel DP).
- Baris di-ingest bila `Status == Success` (case-insensitive).
- `jenis="depo"`, `amount = abs(Amount (IDR))`, `money_delta = +amount`,
  `credit_delta = 0` (baris gateway = sisi uang saja).
- `ticket_no = Ticket Number` (`D…`) → anchor pass-0 exact join ke panel DP.
- `username = Player`, `fee = Admin Fee`, `occurred_at/posted_date = Date`.
- `reference = ""` — RRN hanya di `raw`: ada duplikat, dan aturan blocked engine
  mengasingkan reference asing (pelajaran RPay CSV, verifikasi M77 09-07).
- **Keputusan:** baris `Ticket Status=failed` (uang QR masuk, tiket panel gagal)
  TETAP di-ingest → muncul sebagai "Tidak Ada di Panel". Itu selisih nyata yang
  auditor harus lihat, bukan disembunyikan parser.
- `row_hash = row_hash("rpay_xlsx", [ticket, rrn])` — occurrence-index di base
  menangani duplikat kembar.
- `flow` diabaikan (selalu DP) — salah pilih di UI tak bisa membalik tanda.

**`RPayWDXlsxParser`** — key `rpay_wd_xlsx`, `source_key="gateway"`:

- Baca via openpyxl; flatten header dua tingkat (sub-kolom menang bila terisi);
  data mulai baris 3.
- Baris di-ingest bila `Transfer == success` (uang benar-benar keluar — meniru
  keputusan `rpay_wd` CSV).
- `jenis="wd"`, `amount = abs(Disbursed Amount)`, `money_delta = -amount`.
- `ticket_no = Ticket` (`W…`) → pass-0. `counterparty = Beneficiary Name`,
  `fee = Fee`. `Beneficiary Number` tersimpan di `raw` (kelak berguna paket B).
- `row_hash = row_hash("rpay_wd_xlsx", [ID, ticket])` — tanpa nominal supaya
  idempoten terhadap variasi format angka.
- `flow` diabaikan (selalu WD).

### 2. Deteksi (`sources/detect.py`, cabang xlsx)

- DP: `payment gateway` + `rrn` + `amount (chip)` → `rpay_xlsx` **0.95**.
- WD: `source of funds` + `disbursed amount` + `beneficiary` → `rpay_wd_xlsx` **0.95**.
- **Pengetatan nxpay:** tambah `and not _has(t, "payment gateway")` pada sinyal nxpay
  supaya file RPAY tak pernah nyasar lagi (0.95 juga sudah mengalahkan 0.90, ini
  lapisan kedua).
- Sinyal qrflyer-by-filename dibiarkan — 0.95 menang atas 0.85; memangkas sinyal itu
  berisiko regresi MXW.

### 3. Registrasi

`PARSERS["rpay_xlsx"]` dan `PARSERS["rpay_wd_xlsx"]` di `sources/services.py`.

## Rencana uji

1. **TDD unit:** fixture xlsx kecil dibangkitkan dari struktur sampel (data anonim).
   - Deteksi: kedua file baru → key baru 0.95 di peringkat 1; non-regresi: fixture
     nxpay/qrflyer/rpay-CSV/rpay_wd-CSV lama tetap terdeteksi benar.
   - Parser DP: filter Status, rupiah penuh (bukan ×1000), arah +, ticket/username/fee,
     baris ticket-failed ikut, row_hash stabil.
   - Parser WD: flatten dua tingkat, filter Transfer, arah −, Disbursed (bukan Amount),
     counterparty, fee, row_hash stabil.
   - Ingest E2E kedua parser (idempoten: re-ingest 0 baris baru).
2. **Kalibrasi nyata:** `validate_brands --dir <zip BBS 16.zip>` pada DB scratch
   (`DATABASE_URL=sqlite:////tmp/...`) — target: kedua file terdeteksi & ter-ingest,
   WD RPAY match via ticket ke panel WD, DP RPAY match ke panel DP; laporkan match-rate.

## Risiko & mitigasi

- **Regresi deteksi nxpay** (file NXPay asli ada yang memuat "payment gateway"?):
  cek fixture/sampel NXPay yang ada sebelum mengetatkan; test non-regresi wajib.
- **Varian format antar toko** (BO7 dsb. bisa beda kolom): parser mencari kolom by
  nama pada header ter-flatten, bukan posisi tetap; kolom hilang → baris dilewati
  (bukan crash), konsisten parser lain.
- **File WD kecil (17 baris)** — kalibrasi tetap bermakna karena anchor exact ticket.
