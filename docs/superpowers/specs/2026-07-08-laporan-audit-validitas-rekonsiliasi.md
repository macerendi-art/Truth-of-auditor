# Laporan Audit Validitas Hasil Rekonsiliasi

**Tanggal:** 2026-07-08 · **Versi diaudit:** commit `6e550a0` (= produksi live) · **Data:** file nyata MUL & COR, 1–3 Juli 2026 (37.186 + 34.304 transaksi) · **Metode:** dua jalur independen — *pengecekan manual* (skrip auditor yang **tidak memakai kode matcher**: join kunci dihitung langsung dari file mentah dengan pandas/XML mentah, identitas dihitung ulang dari spek) vs *rekonsiliasi aplikasi* (`validate_brands` di DB scratch terpisah) — lalu di-compare baris-per-baris.

## Verdict

**LAYAK DIPERTANGGUNGJAWABKAN.** Hasil rekonsiliasi valid: setiap pasangan "Cocok" terbukti ulang punya anchor identitas (kunci exact / nomor / nama ≥85), tidak ada pasangan yang gagal dibuktikan, tidak ada match kuat yang terlewat, dan total nominal batch klop ke rupiah dengan file mentah. Baris "Tidak Cocok" bukan kesalahan mesin — itu temuan yang memang tugas auditor meninjau.

## Bukti utama

### 1. Kunci exact — manual vs mesin: klop 100%

| Pengecekan | Manual (independen) | Mesin | Selisih |
|---|---|---|---|
| MUL ticket QH+NXPAY (3 hari) | **9.868** panel ber-uang exact | 9.862 `ticket` + 3 `late_settlement` + 3 `no_money` batas-malam = **9.868** | **0** |
| COR UUID QRIS (3 hari) | **27.305** join UUID + nominal sama | 27.295 `reference` + 10 `late_settlement` (semua terbukti UUID sama) = **27.305** | **0** |

### 2. Validasi ulang SETIAP pasangan: 53.949 pasangan, 0 pelanggaran

Setiap MatchResult ber-pasangan (MUL 23.265 + COR 30.684) dibuktikan ulang sesuai alasannya: `ticket`/`reference` → kunci memang identik + nominal sama; `amount+date+name` → identitas ≥85 + nominal persis + tanggal dalam window; `amount_fee` → identitas ≥85 + selisih ≤ maks(2.500, 1%); `name_partial` → skor 60–84; `late_settlement` → identitas ≥60 **atau** kunci exact. **Nol** pasangan gagal dibuktikan; **nol** `weak_name`; **nol** uang dipakai dua kali; arah uang konsisten di semua relasi uang.

### 3. Scan false-negative: 0 match kuat yang terlewat

Untuk semua 2.695 baris `no_money` (MUL 642 + COR 2.053), auditor memindai ulang **seluruh** baris uang senominal-searah dalam window: **tidak ada satu pun** kandidat identitas ≥85 yang menganggur. Mesin tidak melewatkan pasangan yang seharusnya cocok.

### 4. Tie-out total nominal: 6/6 SAMA sampai rupiah

| Hari | DP batch vs file | WD batch vs file |
|---|---|---|
| 01/07 | 528.753.000 = 528.753.000 ✓ | 482.698.000 = 482.698.000 ✓ |
| 02/07 | 505.118.000 = 505.118.000 ✓ | 501.793.000 = 501.793.000 ✓ |
| 03/07 | 442.332.000 = 442.332.000 ✓ | 366.339.000 = 366.339.000 ✓ |

### 5. Sampling manual pasangan fuzzy

12 sampel acak `cocok` bank (nama/nomor): semua identitas 100 (nama persis atau nomor HP/VA persis — termasuk baris DANA/GO-PAY tanpa nama). 10 sampel `late_settlement`: semua nama persis / via nomor — pola persis kasus `W6170895` Samsul maarif → settle H+1 ke `SAMSUL MAARIF`, bukan orang lain.

## Anomali yang ditelusuri sampai akar (semuanya BUKAN salah mesin)

1. **85 baris "nominal beda" versi manual** → file NXPAY WD menulis nominal **negatif** (`-1.500.000,00`); parser mesin benar (nilai mutlak), skrip manual awal yang naif. Mesin benar.
2. **3 + 10 transaksi batas tengah malam** → settle 23:59 tapi panel approved 00:00 hari berikutnya. 10 (COR) ter-settle otomatis via UUID H+1; 3 (MUL) uangnya sudah terkonsumsi batch kemarin → jujur ditandai `no_money` (0,025% — tak salah pasang, tinggal disetujui manual).
3. **2 anomali ledger bracket** (`W6167339` panel −100rb vs bracket +300rb; `D6172556` DP vs bracket −200rb) → justru **temuan audit asli** di Finance Report agent; mesin menandai yang pertama `perlu_tinjau`. Rekomendasi kecil: beda arah pada ticket-join bracket sebaiknya ikut `perlu_tinjau` (saat ini nominal-sama-arah-beda = cocok).

## Yang bukan kesalahan — tapi memang pekerjaan auditor

- **`perlu_tinjau` "Nama mirip" hanya 17 baris / 3 hari / 2 brand** (MUL 5, COR 12) — pita 60–84 memang zona keputusan manusia: sebagian nama kepotong bank (`MUHAMAD DINA M-BCA`, `Steven E E Tor`), sebagian mirip-tapi-beda (`YUNI ARDIANTO` vs `ENI HARYANI`) → itulah gunanya tombol Setujui/Tinjau.
- **`no_money` hari terakhir (220 MUL)** = uang H+1 (04/07) belum diupload — akan settle otomatis begitu file besoknya masuk.
- **`no_money` hari 1–2 (422 MUL, sebagian COR)** = uang benar-benar tidak ditemukan di sumber yang diupload → temuan asli untuk ditinjau (jalur pembayaran yang file-nya tidak ikut, atau selisih sungguhan).
- **3 file Mandiri COR terenkripsi** (butuh password) → mutasi Mandiri tidak ikut; sebagian `no_money` COR dijelaskan oleh ini. Minta password/file terbuka bila mau full-coverage.

## Reproduksi

DB scratch (bukan DB kerja): `DATABASE_URL=sqlite:///<scratch>/audit/{mul,cor}.sqlite3 python manage.py validate_brands --dir <folder> --toko <mul|g25> --flow-from-name`. Skrip auditor independen: `gt_mul.py`, `gt_cor` (inline), `audit_pairs.py` (scratchpad sesi 2026-07-08).
