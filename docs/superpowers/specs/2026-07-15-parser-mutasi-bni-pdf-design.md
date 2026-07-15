# Parser Mutasi BNI (PDF) — sisi UANG WD

**Tanggal:** 2026-07-15
**Status:** disetujui (brainstorming), lanjut ke rencana implementasi

## Konteks

Mutasi bank **BNI** selama ini masuk daftar "di luar lingkup — menunggu contoh
file" di seluruh spec/plan sebelumnya (lihat `2026-07-02-...autodetek...`,
`2026-07-07-multi-brand-...`, `2026-07-10-parser-uno-wd-rpay`). Akibatnya baris
panel WD yang dibayar via BNI jatuh jadi `no_money` — struktural, bukan cacat
matcher. File contoh kini tersedia, jadi BNI bisa dibangun sebagai sisi UANG WD
yang sebenarnya.

Format file: **BNI Mobile Banking "HISTORI TRANSAKSI"** (PDF text-based).
Contoh yang dipakai untuk desain & kalibrasi:

- `12_07_2026_WD_BNI_MARULLOH.pdf`, `13_07_2026_WD_BNI_MARULLOH.pdf` — mutasi
  rekening BNI TAPLUS DIGITAL no. **1916713823** (pemilik: MARULLOH).
- `HISTORY WD BNI PANEL GP 13 JULI.xlsx` — sisi **panel** (kredit) WD hari yang
  sama, **Brand=SUH**, format **panel standar** (bukan format COR).

### Temuan kunci (validasi data nyata 13 Juli)

**1. Anchor identitas BNI = nomor rekening tujuan, bukan nama.** Baris WD besar
tampil sebagai `TRF/PAY/TOP-UP ECHANNEL KARTU ... BIZID ...` tanpa nama, tetapi
**nomor rekening tujuan tertanam di ekor deskripsi** dan cocok ke kolom
`Player Bank` panel. Uji silang 7 WD panel SUH ↔ baris Db. BNI:

| Panel WD | Nominal | Player Bank (acct) | Nomor rekening ada di baris BNI? |
|---|---|---|---|
| W1460189 | 100k | BRI 488801058180531 | ✅ `...0218001129`**`488801058180531`** |
| W1460187 | 100k | SEABANK 901494940601 | ✅ `...0218001006`**`901494940601`** |
| W1460158 | 60k | DANA 085849792965 | ✅ tertanam di VA `8810`**`085849792965`** |
| W1460045 | 372k | SEABANK 901329828251 | ❌ baris 372k = kartu `5264...` LANDMARK |
| W1459697 | 114k | SEABANK 901113275828 | ✅ |
| W1459695 | 900k | SEABANK 901113275828 | ✅ |
| W1459533 | 328k | SEABANK 901113275828 | ✅ |

**6/7 cocok via nomor rekening tujuan.** Yang 372k hanya cocok-nominal tapi
rekening BEDA (rail LANDMARK/kartu) → **benar** tidak boleh auto-cocok. Temuan ini
**membenarkan** aturan anchor (nominal+tanggal = pendukung, tak pernah cukup),
bukan melanggarnya.

**2. Mesin matching yang ada sudah menangani ini — tanpa kode engine baru.**
`_money_phones` (`engine.py:61`) memindai deret digit ≥9 dari `raw` baris uang;
`_phone_match` (`engine.py:77`) cocok bila **ujung nomor sama** (`endswith`/
`startswith`) — toleran terhadap watermark/pemotongan digit. Sisi panel,
`_expected_phone` mengambil nomor dari `Player Bank`. Syaratnya: parser BNI
**menyimpan teks echannel utuh (berisi nomor rekening) di `raw`**.

**3. Skala terkonfirmasi.** Panel standar ×1000 (100 → Rp100.000, dst.; total
1.974 = Rp1.974.000). BNI sudah rupiah penuh — **tanpa ×1000**. Nominal cocok
persis.

**4. Watermark "Mobile Banking" (diagonal) = risiko akurasi nyata.** Menyusup
sebagai baris 1-karakter (`'g','n','i'...`), huruf nyasar menempel (`BY TRX
BIFAST` **`l`**`Db.`), dan kadang memecah deret digit (`O0217753931` →
`O021775393 1`). Toleransi ujung-sama `_phone_match` meredamnya, tetapi **wajib
diuji kalibrasi**, bukan diasumsikan.

### Lingkup

Satu-satunya kode baru = **parser PDF BNI + deteksi PDF**. Sisi panel sudah
didukung penuh oleh parser `panel` standar (`SCALE=1000`, menyimpan seluruh kolom
ke `raw` termasuk `Player Bank`/`Bank Title`). Aturan anchor & mesin matching
**tidak berubah**.

## Desain

### 1. Parser `bni_pdf`

Kelas `BNIPDFParser(BaseParser)` di `sources/parsers/bni_pdf.py`, `source_key =
"bank"`. Meniru pola `BCAPDFParser` (parsing baris-teks pdfplumber).

**Ekstraksi baris:**
- Kumpulkan `page.extract_text()` semua halaman → daftar baris.
- **Buang baris ≤1 karakter** (watermark).
- Baris utama transaksi cocok regex:
  `^(\d{4}-\d{2}-\d{2})\s+(.*?)\s*[A-Za-z]?(Db|Cr)\.\s+([\d.]+,\d{2})\s+([\d.]+,\d{2})\s*$`
  → grup: tanggal, deskripsi-awal, tipe (huruf nyasar sebelum `Db/Cr`
  ditoleransi), nominal, saldo.
- Baris berikut yang **bukan** baris-tanggal & panjang >1 = **lanjutan
  deskripsi** → digabung. Baris lanjutan inilah yang memuat nomor rekening tujuan
  (echannel) — **wajib dipertahankan**.

**Pemetaan field → `Transaction`:**

| Kolom BNI | Field | Catatan |
|---|---|---|
| Tanggal Transaksi (`2026-07-12`) | `occurred_at` / `posted_date` | ISO, **tanpa jam** (midnight). Window matcher pakai `date` → aman. |
| Tipe `Db.`/`Cr.` | arah `money_delta` | Db → **−** (uang keluar/WD); Cr → **+** (masuk). |
| Nominal (`200.000,00`) | `amount`=abs, `money_delta` | format `id`. **Tanpa ×1000.** |
| Saldo Akhir | `balance_after` | saldo berjalan → dedup & laporan saldo. |
| Uraian (utuh) | `description` + `raw` | teks lanjutan (nomor rekening) dipertahankan. |
| — | `credit_delta` | `0` (sisi uang). |

### 2. Fee → `jenis="admin"`

Dikecualikan dari total WD, matching, & kelengkapan (bukan WD nyata). Dari data
nyata:

| Deskripsi | Nominal | Pola |
|---|---|---|
| `BY TRX BIFAST` | Rp2.500 | `BY TRX` |
| `BY TRX ATM BERSAMA` | Rp6.500 | `BY TRX` |
| `TRANSFER KE BIAYA ADMIN (GOPAY) NO :...` | Rp1.000 | `BIAYA ADMIN` |
| `TRANSFER KE aba... BIAYA ADMIN (LINKAJA) NO :...` | Rp1.000 | `BIAYA ADMIN` |

Aturan: deskripsi memuat `BY TRX` **atau** `BIAYA ADMIN` → `admin`. Selain itu
`depo`/`wd` dari tanda `money_delta`.

### 3. Identitas / anchor (inti nilai)

**Anchor utama = nomor rekening tujuan tertanam di `raw`.** Parser tidak
mengekstrak nomor rekening ke field khusus; cukup **menyimpan teks deskripsi utuh
(baris utama + lanjutan) di `raw`** agar `_money_phones` menemukannya dan
`_phone_match` mencocokkannya ke `Player Bank` panel. Pola nomor per kanal:

- **Echannel/BIZID** (`TRF/PAY/TOP-UP ECHANNEL ... O<10digit> <acct>`) → nomor
  rekening tujuan (BRI/SEABANK, 12–15 digit). ✅ anchor kuat.
- **DANA** (`ESPAY DEBIT INDONESIA KOE <VA> Dana-DNID <nama tersamar>`) → nomor
  HP tertanam di VA 16-digit (`8810` + HP). ✅ cocok via `endswith`.
- **LINKAJA** (`... LINKAJA <HP>`) → HP 12-digit. ✅
- **GOPAY** (`TRANSFER KE GOPAY) NO :<nomor pendek/tersamar>`) → tak bawa
  identitas. ⚠️ konsisten catatan `BNI→GOPAY carries NO number`.
- **Transfer bank ke orang** (`TRANSFER KE FAJAR`, `TRANSFER KE Bpk KELPIN
  BORNEO`) → **`counterparty`** = nama (fuzzy).

**`counterparty`** diisi helper `extract_bni_name` untuk baris `TRANSFER KE
<nama>`: buang `TRANSFER KE`, gelar (`Bpk`/`Ibu`/`Sdr`), token struktural
(`ESPAY DEBIT INDONESIA`, `AIRPAY INTERNATIONAL INDONESIA`, `LINKAJA`, `GOPAY`,
`BIFAST`, `Dana-DNID`, `BIAYA ADMIN`), dan nomor rekening/HP. Baris tanpa nama
(echannel/GOPAY) → `""` (jangan dikarang). Nama e-wallet tersamar (`Dana-DNID
FICXX`, `IRSXX`) boleh dibiarkan apa adanya — skor fuzzy rendah, tak merusak.

### 4. Deteksi (`detect.py`)

Saat ini `.pdf` **selalu** → `bca_pdf` (0.75) tanpa membaca isi → PDF BNI
salah-deteksi. Tambah penyaring isi PDF halaman-1 (helper `_pdf_text`):

- Token `HISTORI TRANSAKSI` **dan** (`Uraian Transaksi` **atau** `Saldo Akhir`)
  → `add("bni_pdf", 0.9)`.
- Selain itu tetap `add("bca_pdf", 0.75)` (perilaku lama).

Registrasi `"bni_pdf": BNIPDFParser` di `PARSERS` (`sources/services.py`).

### 5. WD-only untuk rekening payout

Ingest **semua** baris (Db & Cr) dengan `jenis` jujur (Db=`wd`, Cr=`depo`).
Baris Cr. (top-up saldo operator, mis. `TRF/PAY/TOP-UP ... Cr. 2.000.000`)
**inert di run WD** — engine hanya memasangkan arah uang yang sama
(`engine.py:381`, `(p.money_delta>0) != (b.money_delta>0)` ditolak) — jadi tak
perlu tag baru. Rantai Saldo Akhir tetap utuh untuk laporan saldo per-rekening.

### 6. Idempotensi

`row_hash("bni", [tgl, amount, tipe, saldo, idx])`. Saldo Akhir (saldo berjalan,
unik per baris) jadi pembeda kuat — perlu karena tanpa jam, baris bisa sama
tanggal+nominal.

### 7. Rekening bersama antar-brand (catatan operasional)

Rekening BNI ini **dipakai beberapa brand**; tiap brand = toko tersendiri (contoh
data untuk toko **SUH**). Baris BNI di luar WD toko yang direkonsiliasi (mis.
`TRANSFER KE Bpk KELPIN BORNEO` 800k, `LANDMARK` 372k, 50k) wajar jadi
`no_panel`. Recon penuh butuh panel tiap brand; karena idempotensi
per-`(source_type, toko)`, mutasi yang sama dapat diunggah di tiap toko dan cocok
ke WD toko masing-masing. **Otomasi dedup lintas-toko = di luar lingkup tugas
parser ini** (parser toko-agnostik).

## Pengujian & kalibrasi

- **TDD unit** (`sources/tests_*` mengikuti pola test parser existing): arah
  Db/Cr, fee tagging (`BY TRX`/`BIAYA ADMIN`), filter watermark (baris 1-karakter
  & `lDb.`), **nomor rekening terpelihara di `raw`**, ekstraksi nama
  `TRANSFER KE`, dedup via saldo.
- **Uji end-to-end data nyata 13 Juli** (panel SUH + mutasi BNI): harapan
  6/7 WD SUH cocok via nomor rekening; 372k → `no_money`; baris non-SUH →
  `no_panel`.
- **`validate_brands`** untuk laporan match-rate (jujur termasuk porsi `no_money`
  struktural).

**Investigasi kalibrasi (bukan penghambat):** kasus 372k (Somad/SEABANK) — baris
BNI 372k adalah `LANDMARK`/kartu tanpa nomor rekening cocok. Selidiki apakah
payout Somad lewat rail lain atau kebetulan nominal sama.

## Di luar lingkup

- OCR (PDF sudah text-based).
- Layout export BNI lain (selain "HISTORI TRANSAKSI" TAPLUS DIGITAL) — tunggu
  contoh bila muncul.
- Pencocokan **referensi echannel** (`O0217...`) — korup watermark, tak
  diandalkan.
- Otomasi dedup/reconciliation lintas-toko untuk rekening bersama.

## Hasil kalibrasi (2026-07-15, data nyata 13 Juli, DB scratch)

Ingest `panel` (7 WD SUH) + `bni_pdf` (17 baris: 10 wd, 1 depo/Cr topup,
6 admin/fee) → `match panel_bank 2026-07-13`:

| Hasil | Jumlah | Detail |
|---|---|---|
| `cocok` | **6/7** | Semua skor 100 via anchor identitas: W1459533/695/697 + W1460187 (rekening SEABANK), W1460189 (rekening BRI), W1460158 (HP DANA via `raw["hp"]`). |
| `tidak_cocok` | 1 | W1460045 (372k, Somad/SEABANK) → `no_money` — **benar**: baris BNI 372k = rail LANDMARK/kartu tanpa rekening cocok (nominal sama saja tidak cukup, sesuai aturan anchor). |
| Idempotensi | ✓ | Re-ingest file sama: 0 baris baru, 17 duplikat. |
| Deteksi | ✓ | Kedua PDF nyata → `bni_pdf` 0.9 (tunggal). |

**Temuan kalibrasi → perbaikan parser (commit `a0ae4eb`):** VA e-wallet BNI
menempelkan prefiks 4-digit ke HP tujuan (ESPAY/DANA `8810`+HP, AIRPAY/ShopeePay
`8807`+HP = 16 digit) — deret 16-digit lolos dari scan HP engine
(`_DIGIT_RUN_RE` 9–15 digit), kelas masalah yang sama dengan BRIVA di BRI.
Sesuai konvensi (identitas diisolasi di parser, engine tak berubah), parser
memisahkan HP dari prefiks VA ke `raw["hp"]` → `_money_phones` menemukannya
generik. Tanpa fix ini DANA jatuh ke `perlu_tinjau` (nama tersamar, skor 61).
