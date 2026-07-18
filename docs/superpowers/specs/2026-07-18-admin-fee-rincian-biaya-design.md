# Paket C — Deteksi Admin Fee + Laporan Rincian Biaya — Desain

**Tanggal:** 2026-07-18 · **Status:** eksekusi otonom atas mandat user; lingkup dari pemetaan feedback klien 16–17 Jul · **Paket:** C

## Permintaan klien

- "Fitur admin fee ada perubahan… angkanya selalu sama dan jaraknya tidak
  berjauhan" — daftar tarif: Gopay/LinkAja/Shopeepay **1.000**, BI Fast **2.500**,
  transfer realtime/online **6.500**.
- "Menambahkan rincian biaya transfer E-Money" (laporan).

## Bukti produksi (probe 2026-07-18, read-only)

**8.937 baris bank keluar bernominal fee TANPA tanda `jenis="admin"`**
(1.000×859 · 2.500×6.383 · 6.500×1.695). Pola per bank:

| Bank | Pola deskripsi | Nominal | Baris | Makna |
|------|----------------|---------|-------|-------|
| BRI | `ATMSTRPRM…` | 6.500 | ±726 | biaya transfer jaringan ATM Prima |
| BRI | `BFST…` | 2.500 | ±1.000 | biaya BI-Fast (transfer BI-Fast min 10rb → 2.500 pasti fee) |
| BRI | `BRIVA…` | 1.000 | ±658 | fee kembar BRIVA — twin-nya ADA di file yang sama; baris legacy ter-ingest SEBELUM `is_briva_fee` lahir, dedup membuat re-upload tak menandai ulang |
| MANDIRI | `Biaya …` (mis. "Biaya transfer BI Fast", "Biaya transaksi") | 1.000/2.500/6.500 | ±760 | teks fee eksplisit |
| BRI | prefix numerik (`52218…`, `40735…`) | 6.500 | ±350 | AMBIGU — TIDAK ditangani paket ini (kalibrasi lanjutan) |

Akar akumulasi: `jenis` dibekukan saat ingest; baris lama dari sebelum tiap
aturan fee ada tidak pernah ditandai ulang (re-upload kena dedup). Dampak: noise
"Tidak Ada di Panel" + total WD kotor.

## Desain

### C1 — Aturan fee dibagikan: `sources/parsers/fee_rules.py` (modul murni baru)

```python
def is_admin_fee(bank, description, amount) -> bool
```

`bank` ∈ {"bri", "mandiri", ...} (kunci parser). Aturan (case-insensitive,
description di-strip):

- `mandiri`: description startswith `"biaya"` → True (nominal berapa pun).
- `bri`: (startswith `"atmstrprm"` dan amount == 6500) atau
  (startswith `"bfst"` dan amount == 2500) atau
  (startswith `"briva"` dan amount == 1000) → True.
- Selain itu False. (BCA sudah punya `is_bca_fee` + merge SWITCHING — tidak diubah.)

Parser memakai saat ingest (baris money_delta<0):
- `MandiriParser`: jenis admin bila `is_admin_fee("mandiri", ket, amount)`.
- `BRIParser`: jenis admin bila `is_admin_fee("bri", ...)` — pelengkap
  `is_briva_fee` twin yang sudah ada (aturan BRIVA@1000 menangkap fee walau
  twin terpotong jendela rolling).
- Baris fee tetap DIKECUALIKAN dari total WD/matching/kelengkapan (perilaku
  `jenis="admin"` yang sudah ada — tidak ada perubahan engine).

### C2 — Laporan "Rincian Biaya Admin" (`/biaya-admin/`)

Modul agregasi murni **`web/biaya.py`** (query-time, retroaktif, tanpa migrasi):

`rincian_biaya(toko, dari, sampai)` — baris bank+gateway keluar yang merupakan
fee menurut (a) `jenis="admin"` TERSIMPAN, ATAU (b) `is_admin_fee(...)` yang
sama diterapkan saat baca (menutup baris legacy yang belum bertanda; kunci
`bank` diturunkan dari nama file upload — `BRI`/`MANDIRI` token, pola
`provider_from_filename`). Gateway: kolom `fee` per baris TIDAK dipakai di sini
(bukan mutasi debit) — lingkup laporan = fee yang benar-benar keluar dari
rekening (baris debit), plus catatan jumlah `fee` gateway sebagai kolom
informatif per sumber.

Klasifikasi kanal per baris fee: `1.000` → "E-wallet" · `2.500` → "BI Fast" ·
`6.500` → "Transfer online" · lainnya → "Lainnya".

Keluaran: per (tanggal, sumber `source_label_full`) → n & total per kanal +
grand total; ringkasan periode {total, per kanal}.

View `rincian_biaya` + template `biaya_admin.html`: filter rentang (default 30
hari), 4 kartu stat kanal + tabel per tanggal×sumber, pager. Menu sidebar dekat
"Rincian Rekening", label "Rincian Biaya". Admin/supervisor/auditor semua boleh
(read-only, scoped toko aktif).

## Uji

1. `fee_rules`: tabel kasus per aturan + negatif (BFST 2.500 ≠ 250.000; BRIVA
   100.000 bukan fee; BCA tak tersentuh).
2. Parser: baris Mandiri "Biaya transfer BI Fast" & BRI ATMSTRPRM/BFST/BRIVA
   ter-jenis admin; baris transfer normal tidak.
3. `web/biaya.py`: klasifikasi kanal; baris legacy tanpa tanda ikut terhitung
   (rule-based); rentang tanggal; ringkasan.
4. View render + menu + empty state.

## Risiko

- Salah-tanda baris nyata bernominal fee: dianalisis — transfer BI-Fast min
  10rb, WD riil ≫ 1.000, ATMSTRPRM 6.500 = tarif jaringan; pola numerik BRI
  6.500 yang ambigu SENGAJA dilewati.
- Baris legacy tetap `jenis` lama di DB (laporan menutupnya query-time; noise
  no_panel lama berhenti tumbuh untuk data baru).

## Hasil implementasi

**C1 (fee_rules + parser, commit `407a2eb` + `a7f60d3`):** kalibrasi prod
18-07 pada 662 baris Mandiri berawalan `"Biaya…"` — **semuanya fee**
(nominal ≤9rb, nol baris fee di atas 10rb) — aturan `is_admin_fee` untuk
Mandiri bebas false-positive pada data nyata. BRI ATMSTRPRM/BFST/BRIVA
diverifikasi lewat probe read-only sebelumnya (lihat tabel "Bukti produksi"
di atas).

**C2 (laporan Rincian Biaya, modul ini):**

- `web/biaya.py` (`rincian_biaya`) + view `rincian_biaya` (`/biaya-admin/`)
  + template `biaya_admin.html` + menu sidebar "Rincian Biaya" (setelah
  "Rincian Rekening") — TDD per brief, 5 test baru di `web/tests_biaya.py`
  (agregasi kanal+legacy-rule, rentang tanggal, grouping tanggal×sumber,
  render halaman, empty state).
- Filter `raw_get` (di `web/templatetags/web_extras.py`) diverifikasi AMAN
  untuk rantai `dict|raw_get:"X"|raw_get:"Y"` pada kunci absen — implementasi
  `(d or {}).get(key, "")` membuat hasil `""` dari lookup pertama jatuh balik
  ke `{}` pada lookup kedua (bukan error), jadi template literal brief
  dipakai apa adanya tanpa perlu flatten manual di modul agregasi.
- Baris kanal diklasifikasi dari nominal tetap: 1.000 → E-wallet, 2.500 →
  BI Fast, 6.500 → Transfer online, lainnya → Lainnya.
- Efek retroaktif: probe prod 18-07 mencatat **8.937 baris bank keluar
  bernominal fee tanpa tanda `jenis="admin"`** (1.000×859 · 2.500×6.383 ·
  6.500×1.695) — baris-baris ini sekarang TERCAKUP laporan Rincian Biaya
  lewat jalur `is_admin_fee` query-time (tanpa migrasi, tanpa re-ingest;
  `jenis` di DB tetap seperti semula, hanya laporan yang menutup celahnya).

**Verifikasi:**
`web.tests_biaya` (5) + `sources.tests_fee_rules` (8) → PASS. Suite penuh:
814 test, OK (2 skipped, tidak terkait) — naik dari 809 sebelum modul ini
(+5 test baru `tests_biaya.py`).
