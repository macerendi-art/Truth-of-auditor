# Anchor Utama Matcher Uang (Panel/Bracket ↔ Bank/Gateway) — Desain

**Tanggal:** 2026-07-07 · **Status:** disetujui user (chat) · **Konteks:** temuan user di prod (Run #41 MUL): WD `W6170895` "Samsul maarif" 300rb (01/07 23:22) dipasangkan `weak_name` score 36 ke mutasi "ARI PRIHARTANTO" 300rb — padahal uangnya baru keluar di mutasi BCA 02/07 (`…300000.00SAMSUL MAARIF`). Pass 3 lama memasangkan nominal+tanggal **tanpa batas skor identitas**, baris jadi `perlu_tinjau` → terkonsumsi → tidak pernah ikut "menunggu settlement" (yang sebenarnya sudah berlaku untuk DP & WD), dan baris mutasi milik player lain ikut terpakai.

## Aturan (dari user)

Anchor **UTAMA** = identitas unik: nama lengkap, ticket no, no. HP, no. rekening, user ID. Nominal & tanggal hanya anchor **PENDUKUNG**.

- **Cocok** = anchor utama sama (+ pendukung penuh).
- **Perlu Ditinjau** = anchor utama sama/mirip tapi pendukung sedikit beda, ATAU nama mirip belum pasti.
- **Tidak Cocok** = anchor utama beda / kemiripan rendah → **tidak dipasangkan**, menunggu settlement.

## Perubahan `_MoneyMatcher` (Panel↔Bank & Bracket↔Bank)

Nominal persis + window terarah tetap syarat wajib (blocking kandidat) tapi **tidak pernah cukup** untuk memasangkan:

| Kondisi | Bucket | Reason | Status |
|---|---|---|---|
| HP/VA/rekening match (100) / username persis / nama ≥85 | `cocok` | `amount+date+name` | pass 1 — tetap |
| Identitas ≥85 + selisih nominal ≤ max(2.500, 1%) | `cocok` bila 100, else `perlu_tinjau` | `amount_fee` | pass 2 — tetap |
| Identitas ≥85 + uang H-1 | `perlu_tinjau` | `date_before` | pass 2 — tetap |
| Nama mirip **60–84** (`NAME_REVIEW_FLOOR=60`) | `perlu_tinjau` | **`name_partial`** (baru) | pass 3 — DIUBAH |
| Skor identitas **<60** | `tidak_cocok`, right=None | `no_money` | pass 3 — DIUBAH |

- Pass 3 baru: pasangan band 60–84 di-assign **global urut skor** (sort `(skor, rute, -Δhari)` desc, seperti pass 1) — pasangan 62 tidak mencuri kandidat milik baris 80. Detail `nama mirip (score N)` + label kanal wallet dipertahankan.
- Sisa → `no_money`; detail dibedakan: ada kandidat nominal+tanggal tapi identitas beda → `"N kandidat nominal+tanggal ada, identitas beda — menunggu settlement"`; tanpa kandidat → `NO_MONEY_DETAIL` lama. `reason_code` tetap `"no_money"` (carry-forward & revert bergantung padanya).
- `weak_name` tidak diproduksi lagi (label UI tetap ada untuk data historis). Reason baru `name_partial` → label "Nama mirip".
- Late settlement otomatis ikut (resolver memakai `match()` yang sama): settle H+1 nama persis → flip `cocok`; band → flip `perlu_tinjau`; <60 → tetap menunggu s.d. kadaluarsa. Window tetap 1 hari (profil toleransi).

## Alasan historis weak_name & mengapa aman dihapus

Weak_name lahir dari audit 27–29 Juni (mismatch nama e-wallet nyata: agregator korporat / nama akun DANA terdaftar). Sejak itu: gateway ber-ticket/reference sudah exact (pass 0/0b), baris VA membawa nomor HP/VA → anchor nomor (skor 100) menangkap kasus e-wallet yang sah. Sisanya yang benar-benar tanpa anchor memang tidak boleh dipasangkan buta — biarkan menunggu settlement / manual; alias learning tetap agenda Paket C.

## Kompatibilitas & risiko

- Tanpa model/migrasi baru. `NAME_REVIEW_FLOOR = 60` konstanta engine (kalibrasi via `validate_brands`; naik ke `ToleranceProfile` nanti bila perlu).
- Angka bergeser by design: "Perlu Ditinjau" menyusut drastis; "Tidak Cocok" hari-H naik lalu flip `cocok` saat settle H+1.
- Batch lama ber-`weak_name` tidak berubah otomatis — hapus batch (terbaru→mundur) lalu run ulang (terlama→maju) via UI oleh user.

## Uji & penerimaan

1. Regresi kasus riil: Samsul↔ARI (36) → `no_money` tanpa pasangan; H+1 SAMSUL MAARIF → flip `cocok` `late_settlement`. DANA nomor beda (Hermanto↛PIAN) → `no_money`.
2. Band 60–84 → `name_partial`; assignment global anti-curi; detail no_money dua varian.
3. Anchor nomor format riil BCA (`FTFVA/DANA`, `GO-PAY TOPUP`, counterparty kosong; normalisasi 0/62; digit terpotong).
4. Suite penuh hijau; `validate_brands` COR/MUL/MXW — QRIS COR tetap ~96,8%, pasangan hilang hanya skor <60 dan settle di run berikutnya.

## Hasil kalibrasi (data nyata 1–3 Juli 2026, DB scratch, sebelum→sesudah)

Suite: **466 test hijau** (dari 455). Baseline "sebelum" = **engine prod berjalan** (`origin/main`
d17f524, sudah termasuk fix review adversarial `0e70833`). `validate_brands` per hari (auto-batch, window 1):

| Brand/hari | cocok prod | cocok baru | tinjau prod→baru | tidak prod→baru |
|---|---|---|---|---|
| MUL 07-01 | 8454 (97,4%) | **8472 (97,6%)** | 90 → **5** | 140 → 207 |
| MUL 07-02 | 7426 (96,9%) | **7431 (97,0%)** | 58 → **5** | 176 → 224 |
| MUL 07-03 | 7348 (97,0%) | 7348 (97,0%) | 15 → **3** | 209 → 221 |
| COR 07-01 | 10386 (92,7%) | **10386 (92,7%)** | 189 → **9** | 624 → 804 |

- **Cocok identik/NAIK** → anchor kuat (nomor/username/nama≥85) & kunci exact QRIS tak tersentuh
  (COR persis sama); naik di MUL karena baris uang yang dulu dicuri pasangan buta kini bebas untuk match benar.
- **Tinjau runtuh** → pasangan buta `weak_name` hilang; sisanya `name_partial` asli + `amount_mismatch`/`amount_fee`.
- **Tidak naik** → baris tanpa anchor kini menunggu settlement (benar), bukan disanding paksa.
- Kasus prod `W6170895` "Samsul maarif" 300rb: batch 07-01 tahan (uang belum keluar) → settle **cocok/late_settlement ke SAMSUL MAARIF** di batch 07-02, BUKAN ke ARI PRIHARTANTO.
