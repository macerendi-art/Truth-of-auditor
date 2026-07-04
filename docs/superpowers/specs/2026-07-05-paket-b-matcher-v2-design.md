# Paket B + Matcher v2 — Desain

**Tanggal:** 2026-07-05 · **Status:** disetujui user (chat) · **Konteks:** audit manual trial OKE25 27–29 Juni membuktikan (a) 8 baris uang lintas-hari terkunci, (b) 9.269 baris uang tanpa jejak hasil, (c) 834 tinjau gateway 100% salah-sanding padahal 100% baris gateway ber-ticket `D…/W…` (96% dikenal panel), (d) 475 tinjau bank terbukti salah-sanding lintas-rekening padahal panel menyimpan rekening tujuan di `raw["Bank Title"]`, (e) 9 kasus fee ±1–2rb dan 15 kasus uang H-1 tak termatch karena blocking nominal persis + window terarah.

## Matcher v2 — `PanelBankMatcher.match()` (multi-pass)

Interface `sides()`/`match()` tidak berubah; hanya isi `match()`.

- **Pass 0 — ticket-join gateway.** Panel ↔ gateway via `ticket_no` (kunci pasti, seperti Panel↔Bracket). Nominal sama → `cocok` (skor 100, reason `ticket`); nominal beda → `perlu_tinjau` reason `ticket_amount` (detail selisih; arah uang tetap harus sama). Gateway yang ticketnya tak dikenal TIDAK dipasangkan fuzzy ke panel lain (biar jatuh ke "uang tanpa pasangan" B2).
- **Pass 1 — identitas kuat, global.** Kandidat = nominal persis + arah sama + window terarah [0..+N]. Skor identitas seperti lama (username persis=100 / `_name_score`). Kumpulkan semua pasangan berskor ≥ `fuzzy_threshold`, urutkan skor menurun (tie-break: rute rekening benar dulu, lalu selisih hari terkecil), assign global tanpa saling curi → `cocok`.
- **Pass 2 — sisa berbasis nominal.** Panel sisa: kandidat sama; pilih terbaik dgn urutan (rute benar, skor, kedekatan tanggal) → `perlu_tinjau` `weak_name`. Detail diberi label kanal bila lawannya agregator e-wallet dikenal (ESPAY/DANA, DOMPET/APLIKASI KARYA ANAK BANGSA (GoPay), AIRPAY (ShopeePay), VISIONET (OVO), FINARYA (LinkAja), BIFAST) — membantu reviewer.
- **Pass 3 — near-miss identitas-kuat.** Panel sisa: (a) nominal beda ≤ max(2.500, 1%) dgn skor ≥ threshold/username persis → `perlu_tinjau` reason `amount_fee` (detail selisih); (b) uang H-1 (sehari SEBELUM panel) dgn identitas kuat → `perlu_tinjau` reason `date_before`. Keduanya tidak pernah `cocok` otomatis.
- **Sisa** → `tidak_cocok` `no_money` (tak berubah; tetap kandidat carry-over harian).
- **Rute rekening:** pemilik diharapkan = segmen tengah `raw["Bank Title"]`; pemilik uang = nama file uploadnya (cache per upload). Cocok = `rapidfuzz.partial_ratio ≥ 85` (gateway: token FLYER/NXPAY). Rute dipakai untuk PRIORITAS, bukan filter keras (file bisa saja tidak diupload).
- `BracketBankMatcher` tetap perilaku lama (tidak dipakai alur web).

## B1 — Carry-over sisi uang

Di `run_batch` (cabang `recon_date`): baris uang (bank/gateway) dalam scope konsumsi bertanggal **> recon_date** yang tidak menjadi `right` hasil mana pun di run ini → dikecualikan dari konsumsi (tetap aktif). Lintas-hari yang berpasangan tetap dikonsumsi. Jalur tanpa `recon_date` tak berubah.

## B2 — Uang tanpa pasangan (hybrid, disetujui)

Setelah konsumsi, klasifikasi uang tak-berpasangan bertanggal ≤ recon_date yang dikonsumsi batch ini:

| Kat | Definisi | Perlakuan |
|---|---|---|
| A histori | tanggal < recon_date − window | hitung saja (summary), tanpa hasil |
| B ticket asing | gateway, ticket tak dikenal panel toko | `MatchResult` `no_panel` (left=None) |
| C internal | counterparty ≈ nama rekening operator (dari nama file upload bank toko, fuzzy ≥85) | hitung saja |
| D periksa | sisanya | `MatchResult` `no_panel` |

`summary["unmatched_money"] = {a|b|c|d: {n, dp, wd}}`. Hasil B/D menempel ke run PANEL_BANK batch (dibuat bila relasi dilewati? → tidak: B2 hanya berjalan bila run PANEL_BANK ada). Bucket `tidak_cocok` naik ratusan (bermakna), bukan ribuan.

**Web:** kartu "Uang tanpa pasangan" di batch → `/batch/<pk>/uang/` (chip filter kategori, paginasi 40, export Excel util yang ada). Flag/tinjau hanya baris B/D (punya hasil). RBAC `tokos_for` seperti halaman lain. Baris kategori A/C dihitung live dari transaksi terkonsumsi tanpa hasil + klasifikasi ulang saat render (fungsi klasifikasi dipakai dua tempat, satu sumber kebenaran di engine).

## Kompatibilitas & risiko

- Tanpa model/migrasi baru. `MatchResult.left` sudah nullable.
- Perilaku matching berubah (by design): angka batch lama ≠ baru.
- reason_code baru: `ticket`, `ticket_amount`, `amount_fee`, `date_before` — halaman run menampilkan apa adanya.
- Riset (2026-07-05): transfer e-wallet→bank tampil atas nama korporat agregator (PT Espay Debit Indonesia=DANA, PT Dompet/Aplikasi Karya Anak Bangsa=GoPay, AIRPAY=ShopeePay); WD bank→DANA tampil atas nama TERDAFTAR akun DANA (sering bukan si pemain) → mismatch nama adalah nyata, bukan format; solusi jangka panjang alias learning (Paket C).

## Uji & penerimaan

1. Unit: pass 0/1/2/3 (termasuk anti-curi kandidat), B1 (skenario 8-korban), klasifikasi A–D, summary, halaman+export+RBAC.
2. Suite penuh hijau.
3. Trial 3 hari ulang: (a) gateway-tinjau ≈ 0 kecuali `ticket_amount`; (b) ≥400 eks-salah-sanding jadi cocok; (c) kategori D ratusan & berisi WD besar NIJUN/HENDI; (d) selisih & bucket dibandingkan dgn audit manual — sepakat.
