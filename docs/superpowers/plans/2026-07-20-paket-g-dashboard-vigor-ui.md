# Paket G — Ringkasan Panel Dashboard, Sampling Vigor/TMG (SLO), Polish UI

> **For agentic workers:** dieksekusi subagent-driven + inline (bagian visual butuh browser).

**Goal:** (1) strip ringkasan trx/nilai DP-WD di dashboard (permintaan klien), (2) kalibrasi Fase-0 brand baru Vigor/TM Gaming "SLO" sampel 03-07-2026, (3) rapikan UI: logo baru gaya kotak-gradien, label sidebar, keselarasan tabel/tombol.

## Konteks & keputusan

- **G1 Dashboard**: klien minta "trx dp, value dp, trx wd, value wd, total trx & total value (diambil dari dp-wd)". Sumber data = baris panel yang DIKONSUMSI batch terakhir (`consumed_by_batch=last`, `source_type__key="panel"`, `is_duplicate=False`) — konsisten dengan `summary["dp"]["panel"]` termasuk retro. Total nilai = **net DP − WD**. Nilai rupiah penuh (konvensi app), bukan ribuan panel.
- **G2 Vigor/TMG**: deteksi mengenali SEMUA file sampling (panel = keluarga COR `cor_panel_bank`/`cor_panel_qris`; gateway UNO DP `cor_qris_gateway` + WD `cor_qris_wd_gateway`; bank `bri`/`bca_csv`/`bca_pdf`/`bni_pdf`/`mandiri`; `bracket`). **Tidak butuh parser baru** — jalankan `validate_brands` di DB scratch. Catatan: command tidak rekursif & tanpa password → ratakan folder + pre-decrypt Mandiri (pwd `13062001`) via msoffcrypto. Toko scratch `key="slo"`.
- **G3 Logo**: referensi DataImpulse (konstelasi kotak gradien, sebagian miring 45°). Mark SVG hand-crafted + animasi CSS halus (float/rotasi kotak lepas, hormati `prefers-reduced-motion`). **Bukan GIF** (raster buram di retina, berat, tepi kasar) dan **bukan meshy/threejs** (keputusan gelombang lalu yang disetujui: aset AI-raster = sumber "AI slop"; WebGL = gimmick berat untuk app keuangan). Favicon TIDAK diubah — tetap "Recon Check" tile (baru diverifikasi tajam 16px); mark baru memakai keluarga gradien yang sama supaya satu keluarga visual.
- **G4 Label sidebar**: "Ikhtisar" → **"Laporan"** (empat itemnya memang laporan; terminologi keuangan formal). "Kerja" tetap.
- **G5 Rincian Rekening**: keluhan "angka tak sejajar header". CSS `th.num,td.num{text-align:right}` sudah ada → diagnosa di browser dulu (systematic-debugging), fix akarnya, jangan tebak.
- **G6 Upload & Parse**: toolbar Riwayat (cari nama file + Hapus terpilih) tampak asal — input & tombol beda tinggi (`input` padding 9px vs `.btn.sm` 5px). Rapikan jadi search-group kompak satu tinggi + tombol hapus danger yang proporsional.
- **G7 Mutasi Bank + audit tombol global**: tombol Filter dilaporkan tak rata. `.row` sudah `align-items:flex-end` + `.row>.btn{margin-bottom:14px}` — ukur dulu di browser, lalu samakan TINGGI SEMUA kontrol form (input/select/tombol) via CSS satu sumber; sweep semua template untuk tombol yang menyimpang.

## Tasks

- [x] **G1**: view `dashboard` + `dashboard.html` + `web/tests_dashboard_summary.py` (subagent). Context key `panel_sum = {"dp": {"n", "v"}, "wd": {"n", "v"}, "total_n", "net"}` atau `None` tanpa batch.
- [x] **G2**: skrip scratch (flatten + decrypt + migrate + toko slo + validate_brands) — background, lapor match-rate per bucket + kegagalan parser bila ada.
- [x] **G3–G7**: inline dengan verifikasi browser per perubahan; suite + collectstatic; screenshot bukti.
- [x] Commit per chunk + push origin/main (ff-only). Deploy HANYA setelah konfirmasi user.

## Hasil

- **G1** (subagent, TDD merah→hijau): 4 test baru `tests_dashboard_summary`, suite penuh 849 pass. Strip tampil di dev data K25 27/06: Deposit 6.767 trx / 443.754.000 · Withdraw 927 / 325.212.000 · Total 7.694 / net 118.542.000; mobile 375px collapse 1 kolom.
- **G2 kalibrasi Vigor/TMG (SLO) 03-07-2026**: 14/14 file terdeteksi & ter-ingest TANPA parser baru — 19.510 baris (panel `cor_panel_bank`+`cor_panel_qris` — varian kolom `Bonus` QR UNO aman, gateway `cor_qris_gateway`+`cor_qris_wd_gateway`, bank bri/bca_csv/bca_pdf/bni_pdf/mandiri terdekripsi, bracket 6.509 agregat → seperti COR, relasi bracket dilewati otomatis). `run_batches_auto`: **cocok 6.017/6.229 = 96,6%**, tinjau 3 (`name_partial`), tidak 209 (semua `no_money` — pola settlement H+1, wajar utk sampel 1 hari), no_panel 189. By value: DP selisih 4,05jt dari 713,98jt (99,4%), WD 28,49jt dari 511,36jt (94,4%). **Onboarding SLO tinggal buat Toko di prod — nol perubahan kode.**
- **G3 logo**: mark konstelasi kotak (grid 2×2 teal→biru + aksen violet, 2 kotak terbang rotate 45° dgn animasi float CSS, `prefers-reduced-motion` dihormati, drop-shadow brand). GIF/meshy/threejs ditolak dengan alasan terdokumentasi di atas; favicon tetap.
- **G4**: sec sidebar "Ikhtisar" → **"Laporan"**.
- **G5**: diagnosa Range-API membuktikan header↔angka sudah rata (d=0) — akar keluhan = kolom melar di layar lebar; fix: lebar kolom numerik dikunci (Rekening menyerap sisa), `th.num` nowrap. Bug ikutan `{# #}` multi-baris ter-render → `{% comment %}`.
- **G6**: toolbar Riwayat Upload → chip jumlah + search-group menyatu (`.searchbox`, input `.ctl-sm` 32px + tombol ikon) + tombol Hapus terpilih danger ber-badge `.cnt`; separator `.vr`.
## Lampiran — Paket H (fee-glued WD, insiden LBS 19/07)

Klien: "WD BCA kenapa tidak cocok padahal ada di mutasi?" Diagnosa prod run #520 (LBS):
(a) **fee antarbank menempel di debit** — panel WD 400.000, mutasi 406.500 satu baris
("UMAR MANAP NASUTIO… SWITCHING DB"; ≥4 baris 406.500 hari itu); pass 2 lama
`tol_amt=max(2500, amt//100)`=4.000 utk 400rb → kandidat tak terlihat → `no_money` palsu.
(b) **WD 23:4x → uang H+1** — mutasi 20/07 belum diupload; biarkan late settlement
(JANGAN tandai manual — nanti uangnya jadi no_panel).
Fix H: konstanta `FEE_TOL_MIN=6500` sebagai lantai tol pass 2 (BI-Fast 2.500 & online
antarbank 6.500). Identitas tetap gerbang (persis/prefix-terpotong=100 → cocok `amount_fee`;
fuzzy (mis. typo "MANAF" 94) → perlu_tinjau; nama beda → tetap no_money). TDD 5 test
`web/tests_fee_glued.py` (merah→hijau); `_name_score` prefix-truncation=100 adalah by-design
(docstring) — kasus nama terpotong memang COCOK.

- **G7 akar tombol tak simetris (terukur)**: input/select 39px vs `.btn.primary` 34px (border:none) vs `.btn` 36px → fix global `min-height:39px` + `.primary` border transparan + `.btn.sm` 32px + `:disabled`. Sesudah: select/input/Filter/Reset SEMUA top 269 bottom 308 h 39 (identik) di Mutasi Bank; Area Pengecekan & Bonus & Rekening ikut beres dari satu sumber CSS.
