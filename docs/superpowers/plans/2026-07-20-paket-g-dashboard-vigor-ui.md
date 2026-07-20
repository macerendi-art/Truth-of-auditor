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

- [ ] **G1**: view `dashboard` + `dashboard.html` + `web/tests_dashboard_summary.py` (subagent). Context key `panel_sum = {"dp": {"n", "v"}, "wd": {"n", "v"}, "total_n", "net"}` atau `None` tanpa batch.
- [ ] **G2**: skrip scratch (flatten + decrypt + migrate + toko slo + validate_brands) — background, lapor match-rate per bucket + kegagalan parser bila ada.
- [ ] **G3–G7**: inline dengan verifikasi browser per perubahan; suite + collectstatic; screenshot bukti.
- [ ] Commit per chunk + push origin/main (ff-only). Deploy HANYA setelah konfirmasi user.
