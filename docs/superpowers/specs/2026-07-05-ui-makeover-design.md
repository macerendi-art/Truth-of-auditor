# Desain: UI/UX Makeover v1 — Truth of Auditor

Tanggal: 2026-07-05
Status: disetujui user (riset 5-agent: design system, dense-data UX, upload-flow UX, visual tokens, library scan — laporan lengkap di scratchpad sesi, keputusan final dirangkum di sini).

## Tujuan

Make-over lengkap tampilan CMS mengikuti referensi dashboard SaaS modern (kartu putih membulat di kanvas lavender lembut, sidebar gelap, aksen coral) **tanpa mengubah logika rekonsiliasi**. Bahasa UI tetap Indonesia. Tabel audit tetap padat ("airy chrome, dense contents").

## Lingkup

- **Masuk**: shell `app_base.html` (sidebar/topbar/modal), `dashboard`, `upload`, `reconcile`, `batch_detail`, `run_detail` (+ `_result_row.html`, partial baru `_run_table.html`).
- **Tidak masuk**: login (`base.html`), `kelola/*`, `transactions` — mewarisi shell + design system baru, restyling konten menyusul.
- Perubahan Python **hanya additive** di `web/views.py` (konteks dashboard, bentuk return `_auto_rematch`, partial htmx). `reconciliation/` dan `sources/` tidak disentuh.

## Keputusan arsitektur

### CSS design system (tanpa build step)

- File baru `web/static/web/css/app.css` — satu file, `@layer tokens, base, components, utilities`. Native nesting, `color-mix()`, `:has()` seperlunya (hindari selector mahal di tabel besar). Tidak ada framework (Tailwind/Pico/Open Props ditolak — token sedikit, palet spesifik).
- Token 3 tingkat: **primitif** (`--gray-*`, `--coral-*`, `--navy-*`, `--sp-1..10` basis 4px, `--radius-*`, `--shadow-1..3`, `--text-0..7`) → **semantik** (`--canvas`, `--surface`, `--surface-alt`, `--border`, `--text-primary/secondary/muted`, `--accent`, `--ok/-warn/-bad-700` + `-tint`) → **komponen** (knob lokal: `--btn-bg`, `--card-pad`, `--table-cell-pad-y`).
- `app_base.html`: hapus blok `<style>` inline (380 baris) + `<link>` Google Fonts; muat `fonts.css` + `app.css` via `{% static %}` (WhiteNoise manifest = cache-bust gratis).
- **Nama selector lama dipertahankan** (`.card .badge .btn .twrap .tabs .msg .stat .side .topbar ...`) supaya template di luar lingkup (kelola, transactions) tetap berfungsi di bawah skin baru.
- Token status **terpisah struktural** dari coral brand — semantik audit tidak boleh bertabrakan dengan aksen.

### Palet (semua pasangan teks sudah dicek AA)

| Token | Hex | Catatan |
|---|---|---|
| `--canvas` | `#E9EAF4` | latar app lavender |
| `--surface` / `--surface-alt` | `#FFFFFF` / `#F6F6FB` | kartu / band header tabel |
| `--border` / `--border-strong` | `#E4E5F0` / `#D3D5E8` | |
| `--text-primary` | `#20223A` | 15.5:1 |
| `--text-secondary` | `#565A73` | 6.76:1 — sekunder AA-aman |
| `--text-muted` | `#8A8DA6` | HANYA teks besar/dekoratif (3.26:1) |
| `--coral-600` | `#F4756B` | dekoratif saja: nav aktif, chip ikon, garis aksen — bukan pembawa teks |
| `--coral-700` | `#D9392D` | CTA solid dengan teks putih (4.59:1) |
| `--coral-text` / `--coral-tint` | `#C23B30` / `#FDEBEA` | coral-sebagai-teks / bg badge |
| `--navy-900/800/700` | `#1B1E3D` / `#232759` / `#2D3282` | sidebar / hover / sekunder |
| `--periwinkle` (+`-text` `#4B52B0`, `-tint`) | `#8B93E8` | aksen data dekoratif |
| `--ok-700` / `--ok-tint` | `#157A4E` / `#E6F6EE` | cocok |
| `--bad-700` / `--bad-tint` | `#B4231C` / `#FCEAE9` | tidak_cocok — merah dalam, sengaja jauh lebih gelap dari coral |
| `--warn-700` / `--warn-tint` | `#9A6400` / `#FDF3E0` | perlu_tinjau (merangkap "orange hangat") |

Radii: kartu 20px, panel 16px, tabel-wrap 12px, input 10px, tombol/badge pill `999px`. Bayangan 3 elevasi bernada navy (`rgba(27,30,61,…)`).

### Tipografi (hanya weight yang ada di disk)

- **Zodiak Bold** — h1/h2 halaman + angka KPI hero dashboard saja. Jangan di bawah ~19px.
- **Supreme 400/500/700** — seluruh body/UI/label/nav/tabel.
- **IBM Plex Mono 400/500** — nominal, `ticket_no`, `dest_account`, `reference`, timestamp; `font-variant-numeric: tabular-nums`; `font-size:.96em` penyeimbang; fallback `ui-monospace, Menlo, Consolas`. Nama manusia TIDAK pakai mono.
- Skala: 11px caption-tabel (uppercase +.06em) · 13.5px body tabel · 14px body · 15-16px judul kartu · 19-20px h2 · 26-28px h1 · 28-34px KPI hero.
- Google Fonts (Inter/Sora) dihapus dari `app_base.html`.

### Tabel padat

Baris ~40-44px (`td` padding 11px 16px), thead sticky (`position:sticky;top:0` di dalam `.twrap`; bg wajib solid), tanpa zebra, hover `--surface-alt`, numerik rata kanan mono. Kolom status beku (`position:sticky;left:0` + bg solid + `box-shadow` tepi, bukan border) di `run_detail`. Sort tetap server-side.

### Ikon

Sprite Lucide vendored: `web/templates/web/_icon_sprite.html` (~20-25 `<symbol>`, di-inline sekali setelah `<body>`), pakai `<svg><use href="#i-nama"/></svg>`. Stroke 1.75, cap/join round. Mengganti SVG copy-paste per template.

### Aset & kebijakan vendor

- Vendor `htmx.min.js` **2.0.4** (upgrade dari 1.9.12 — hanya 2 call site, semua atribut stabil) dan `gsap.min.js` 3.12.x ke `web/static/web/js/`; hapus unpkg/cdnjs/googleapis dari `app_base.html`. Nol origin eksternal.
- **Buang Lenis** (smooth-scroll melawan pemindaian tabel) dan efek tombol magnetik. GSAP dipertahankan untuk `.reveal` stagger; count-up tetap.
- Tanpa Alpine, tanpa chart lib. Bucket-bar = flex CSS murni; sparkline = filter template Django → `<svg><polyline>`; donat = `conic-gradient`.

### Modal

Shell modal pindah ke `<dialog>` native (`showModal()`): fokus-trap, Esc, backdrop gratis; menghapus gotcha `[hidden]` vs `display:flex`. **Kontrak JS `data-confirm` dipertahankan verbatim** (capture submit di document, substitusi `{n}` via `data-confirm-count`, `dataset.confirmed='1'` → `form.submit()`). Popup pengingat toko ikut gaya baru.

## Desain per layar

### Shell

Sidebar navy-900, pill aktif **coral-700** (label putih AA; coral-600 hanya untuk garis/glow dekoratif pill) + ikon, section label uppercase; blok user + keluar di bawah. Topbar: crumb + pemilih toko (pill putih) di atas kanvas blur. Flash `messages` tetap dirender di atas konten.

### Dashboard

- **Strip kesehatan audit** (butuh konteks view baru, Tier 1): (1) **Selisih terbuka** — jumlah `abs(selisih)` batch belum seimbang; hero Zodiak, merah bila ≠0, "Balanced ✓" hijau bila 0, sparkline 7 hari; (2) **Hari belum direkonsiliasi** — tanggal saran berikutnya (`_saran_tanggal`) + jumlah hari tertunda + tombol "Rekonsiliasi →"; (3) **Batch ekor terbuka** — hitungan batch dengan `tidak_cocok > 0`; (4) **Donat kesehatan** — rasio bucket agregat batch terkini (conic-gradient).
- Tier 2 dipertahankan: bar per-sumber (restyle), "Rekonsiliasi Terkini" + bucket-bar 3 segmen per run, tabel "Upload Terakhir".

### Upload

- Dropzone 5 status: idle / dragover (border solid coral, copy "Lepas untuk menambahkan") / staged / analyzing (tombol spinner "Menganalisa…", zona dim) / preview.
- **Daftar file staged** menggantikan teks `a · b · c`: baris per file — chip ikon jenis (xlsx hijau, csv periwinkle, pdf merah, zip amber "diekstrak", tak dikenal abu "dilewati"), nama + subpath folder, ukuran mono, **hapus per-baris** (rebuild `DataTransfer`). JS akumulator + traversal folder tidak berubah; hanya `render()` diganti.
- Tabel preview: meter keyakinan mikro 4px (≥80 hijau / 60-79 amber / <60 merah), baris `needs_confirm` beraksen amber kiri, select flow di-style segmen, password terkunci pakai afiks 🔒 + border merah sampai diisi, baris ringkasan "N siap · N perlu dicek · N perlu password". **Kontrak commit dipertahankan persis**: array paralel `staged`/`parser_key`/`flow`/`password` satu nilai per baris urut DOM + `provider` tunggal.
- **Panel laporan penyembuhan** pasca-commit (bukan toast): baris per batch sembuh — "Batch #12 (04/07) · +18 cocok · selisih 4,2jt → 0 ✓" + tautan batch + kalimat "Uang baru dicocokkan ke batch lama, selisih tercatat di tanggal aslinya (bukan hari ini)". Nol batch sembuh → satu baris konfirmasi. Server-rendered, animasi `.reveal`.

### Reconcile

Satu layar, tanpa stepper. Panel tanggal pra-isi = hero dengan badge "disarankan ✨" bila `tanggal_disarankan`; tombol ▶ Jalankan Rekonsiliasi full-width; baris rekap live "{N} sumber · {tanggal}" (JS baca input yang sama). **Guard tanggal kosong dipertahankan** (toggle `data-confirm` di `sync()`) + diperkuat: tombol berubah merah + label "⚠ Jalankan SEMUA data" sebelum modal muncul. Checkbox sumber kosong dapat `title` penjelasan. Riwayat Batch + bucket-bar.

### batch_detail

Bucket-bar 3 segmen di atas ringkasan; kartu DP/WD selisih angka mono + badge Balanced; tombol ⟳ Re-match jadi `hx-post` → kartu laporan penyembuhan in-place (tanpa meninggalkan halaman); tabel Relasi kompak + bar per-run.

### run_detail

Tab bucket + channel dan pager jadi swap parsial htmx (`hx-get` + `hx-target="#result-table"` + `hx-push-url="true"` + `hx-indicator` dim); tabel + pager dipecah ke `_run_table.html`; view mengembalikan partial saat header `HX-Request`. Sticky thead + kolom status beku; badge status ikon-pill; aksi baris ✓/⚑ opacity .35 → 1 saat `tr:hover`/`focus-within` (tetap di DOM, aman keyboard). Struktur sel kiri/kanan bertumpuk di `_result_row.html` dipertahankan.

## Perubahan view (additive)

1. **`dashboard`**: tambah `selisih_terbuka` (total), `hari_tertunda` (count + tanggal berikut), `ekor_terbuka` (count batch), `selisih_trend` (list 7 hari), agregat bucket untuk donat.
2. **`_auto_rematch`**: return per batch dilebarkan ke dict `{batch_pk, batch_no, terpasang, cocok, perlu_tinjau, selisih_before, selisih_after}`; view upload melempar list terstruktur ke template (flash `messages` tetap sebagai fallback ringkas).
3. **`run_detail` + `rematch_batch`**: cabang `HX-Request` → render partial.

## Kontrak yang TIDAK boleh pecah (checklist verifikasi)

- Upload analyze/commit: `action`, `files`, array paralel `staged/parser_key/flow/password` per urutan DOM, `provider`.
- `data-confirm` + `data-confirm-count` (bulk delete `{n}`), `form="bulkform"` checkbox linking.
- Guard tanggal kosong reconcile (toggle atribut dinamis).
- Checkbox include `inc_*` attach via `form="jalankan-form"`.
- RBAC `toko__in=tokos_for(...)`, pemilih toko session, nomor batch per-toko.
- `.reveal`/count-up (`data-count`) tetap berfungsi; `prefers-reduced-motion` dihormati.
- Modal apa pun yang tampil harus punya jalur sembunyi yang benar (dialog native menggantikan pola `[hidden]`).

## Verifikasi

- `python manage.py test` hijau (±368) + test baru: bentuk konteks dashboard, bentuk return `_auto_rematch`, partial `HX-Request`.
- Smoke manual runserver: screenshot 5 layar + kelola/transactions (regresi shell).
- Staging Railway: `railway up` dari worktree, cek volume `/app/media`.

## Risiko & mitigasi

- Template cache loader basi → restart runserver tiap edit template.
- Sticky + radius: sticky butuh bg solid; tepi kolom beku pakai box-shadow.
- htmx 2: `hx-headers` CSRF tetap sama; verifikasi 2 call site `_result_row.html`.
- Font mono lebih besar visual → `.96em` normalisasi.
