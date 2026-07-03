# Plan: Pop-up Pengingat Toko + Polish Rekonsiliasi

Tanggal: 2026-07-03 · Basis: `c1309d5` (main) · Spec disetujui user di percakapan (dogfood round 1).

Empat permintaan user, dikemas 3 task berurutan:
(A) pop-up pengingat toko + atribusi setelah login; (B) nomor batch per-toko
(bug: tampil pk global, lanjut terus setelah hapus); (C+D) tampilkan Nama
Lengkap panel di hasil rekonsiliasi + engine pakai nama saat username beda +
ganti label "Kiri (Panel)/Kanan" jadi nama sumber asli.

## Global Constraints

- Bahasa UI & pesan: Indonesia. Komentar kode: gaya repo (ringkas, bahasa Indonesia, hanya bila perlu).
- Test: `.venv/bin/python manage.py test` (full suite harus hijau sebelum commit; saat iterasi cukup test terfokus). TDD wajib per task (RED dulu).
- Test baru per task masuk FILE BARU (nama di tiap task) — jangan menambah ke file test lain.
- Commit di branch `main` (workflow repo ini). Pesan commit gaya repo: `feat(web): …` / `fix(web): …`, bahasa Indonesia, + trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- JANGAN PERNAH `git add -A` / `git add .` — add file spesifik yang kamu ubah saja.
- Ada perubahan pre-existing BUKAN milik task di `web/static/web/css/login.css` dan `web/static/web/js/login-hero.js` — jangan di-add, di-commit, atau di-revert.
- Desain UI mengikuti token app di `web/templates/web/app_base.html` (`--brand`, `--grad`, `--line`, `--radius`, font Sora untuk judul, Inter untuk body).
- `web/templates/registration/login.html` TIDAK disentuh (extends `web/base.html`, bukan `app_base.html`).

## Task 1: Pop-up pengingat toko + atribusi setelah login

Muncul SEKALI per login (bukan tiap buka halaman), di halaman pertama setelah login.

**Mekanisme:**
1. `web/signals.py` (BARU): receiver `django.contrib.auth.signals.user_logged_in` → set `request.session["show_toko_reminder"] = True`.
2. `web/apps.py`: method `ready()` → `from web import signals  # noqa: F401` (pola koneksi signal standar Django).
3. `web/context_processors.py` fungsi `toko()`: untuk user anonim tambahkan key `"show_toko_reminder": False` di dict return awal; untuk user login tambahkan `"show_toko_reminder": request.session.pop("show_toko_reminder", False)` di dict return akhir. (Pop = flag terhapus setelah render pertama.)
4. `web/templates/web/app_base.html`: sebelum `{% block scripts %}` render modal bila `{% if show_toko_reminder %}`. CSS modal masuk blok `<style>` yang sudah ada; JS penutup inline kecil.

**Markup modal (ikuti struktur ini, class boleh disesuaikan):**
- Overlay: fixed inset 0, `background:rgba(12,19,34,.6)`, `backdrop-filter:blur(4px)`, `z-index:100`, center via flex.
- Card: `background:var(--panel)`, `border-radius:16px`, `box-shadow:var(--shadow-lg)`, `max-width:460px`, padding ±26px, animasi fade+scale-in halus (hormati `prefers-reduced-motion: reduce` → tanpa animasi).
- Isi berurutan:
  1. Ikon toko 38×38 (SVG toko yang sama dengan topbar) dalam kotak `background:var(--grad)`, warna putih, radius 10px + kicker `PENGINGAT` (uppercase, 11px, `color:var(--faint)`, letter-spacing .08em).
  2. Judul (Sora, ±19px): `Pastikan toko aktif sudah tepat`
  3. Paragraf (14.5px, `color:var(--muted)`, line-height 1.7): `Setiap berkas yang diunggah dan setiap rekonsiliasi tercatat atas nama toko yang sedang aktif. Sebelum mengunggah atau mencocokkan laporan, pastikan dulu toko di bawah ini sudah benar — ketelitian di langkah kecil ini menjaga hasil audit tetap bersih dan dapat dipertanggungjawabkan.`
  4. Bila `all_tokos` tidak kosong: label `Toko aktif` + `<form method="post" action="{% url 'set_toko' %}">` berisi `{% csrf_token %}`, `<input type="hidden" name="next" value="{{ request.path }}">`, `<select name="toko_id" onchange="this.form.submit()">` dengan opsi `all_tokos` (selected = `active_toko.id`, pola sama dengan topbar) + teks kecil `Ganti di sini bila belum sesuai.` (12.5px, faint).
  5. Divider 1px `var(--line)`.
  6. Intro (12.5px, faint): `Terima kasih — panel ini berkembang berkat wawasan dari:`
  7. Dua baris atribusi (13.5px, line-height 1.6, nama bold warna ink, sisa `var(--muted)`):
     - `Sendy Auditor` — `untuk arahan UI/UX yang merapikan tampilan dan alur kerja panel ini.` + link `draw-to-data-magic` → `https://draw-to-data-magic.lovable.app/app`
     - `Pak Bertus DM` — `untuk gagasan verifikasi Panel ↔ Bank yang menjadi fondasi rekonsiliasi.` + link `checkerboard.online` → `https://checkerboard.online/`
     - Semua link: `target="_blank" rel="noopener"`, warna `var(--brand)`.
  8. Tombol full-width `.btn.primary`: `Lanjut →` → JS remove overlay dari DOM.
- Penutup: klik tombol Lanjut, klik area overlay di luar card, atau tekan Escape.

**Test (`web/tests_login_popup.py`, TDD):**
- Login POST `/login/` lalu follow ke `/` → response mengandung `Pastikan toko aktif sudah tepat`, `Sendy Auditor`, `Pak Bertus DM`, `https://checkerboard.online/`, `https://draw-to-data-magic.lovable.app/app`.
- GET `/` kedua (session sama) → TIDAK mengandung `Pastikan toko aktif sudah tepat`.
- User login tanpa toko (no_toko.html juga extends app_base) → halaman 200, tidak error meski `all_tokos` kosong.
- Pola setup user/toko: contoh di `web/tests_auth.py` dan `web/tests_scope.py`.

## Task 2: Nomor batch per-toko (bukan pk global)

Nomor tampilan = posisi urut batch di antara batch toko itu yang MASIH ADA
(terlama = #1). Hapus semua → batch berikutnya #1 lagi. Nomor bergeser bila
batch lama dihapus — diterima user secara eksplisit. URL tetap pakai pk.

**Perubahan:**
1. `web/views.py` `reconcile()` (GET): untuk daftar `batches` (order `-id`, max 20), hitung `total = qs.count()` lalu set atribut nomor per item: item pertama = `total`, berikutnya menurun. Kirim sebagai atribut objek (mis. `b.no`) via list comprehension/loop sebelum render.
2. `web/views.py` `reconcile()` (POST): setelah `run_batch(...)`, `no = ReconBatch.objects.filter(toko=active).count()`; pesan sukses → `f"Rekonsiliasi selesai (Batch #{no})."` Redirect tetap ke `batch_detail` pk.
3. `web/views.py` `batch_detail()`: tambah context `batch_no = ReconBatch.objects.filter(toko=batch.toko, id__lte=batch.id).count()`.
4. `web/templates/web/reconcile.html`: `#{{ b.pk }}` → `#{{ b.no }}`; confirm hapus `Hapus Batch #{{ b.no }}? …`.
5. `web/templates/web/batch_detail.html`: SEMUA `{{ batch.pk }}` yang tampil ke user (title, crumb, h1, confirm hapus) → `{{ batch_no }}`. `{% url %}`/action tetap pk.
6. `web/admin_views.py` `delete_batch` (line ±157): pesan `Batch #{pk} dihapus…` → hitung nomor urut SEBELUM delete (`ReconBatch.objects.filter(toko=batch.toko, id__lte=batch.id).count()`) dan pakai itu.

**Test (`web/tests_batch_number.py`, TDD):** login user admin ber-toko; buat batch via `ReconBatch.objects.create(toko=…, tolerance=…)` langsung (lihat pola `web/tests_reconcile.py`):
- 2 batch → halaman reconcile memuat `#1` dan `#2` pada kolom Batch.
- Hapus keduanya, buat 1 baru → halaman memuat `#1`, tidak memuat `#3`.
- `batch_detail` batch tsb → h1 memuat `Batch #1`.
- Toko lain sudah punya 5 batch → nomor toko ini tetap mulai `#1` (scoping per-toko).

## Task 3: Nama Lengkap panel + label sumber asli (bukan Kiri/Kanan)

Fakta kode: parser panel simpan kolom `Full Name` → `Transaction.counterparty`
(`sources/parsers/panel.py:68`). Untuk baris bank `username` selalu `""` sehingga
engine sudah fuzzy-match `counterparty`; tapi bila KEDUA sisi punya username
(kasus gateway NXPay), nama lengkap diabaikan. Di UI, Nama Lengkap tak pernah tampil.

**Perubahan:**
1. `reconciliation/engine.py` `_MoneyMatcher.match()` blok skor: pertahankan cabang yang ada, tambah boost nama:
   ```python
   if p.username and b.username:
       s = 100.0 if p.username.lower() == b.username.lower() else 40.0
       if p.counterparty and b.counterparty:
           s = max(s, fuzz.token_set_ratio(p.counterparty.upper(), b.counterparty.upper()))
   else:
       s = fuzz.token_set_ratio((p.counterparty or "").upper(), (b.counterparty or "").upper())
   ```
   (Cabang `else` TIDAK berubah — jaga perilaku lama utk bank.)
2. `web/views.py`: konstanta module-level
   ```python
   REL_LABELS = {
       "panel_bracket": ("Panel", "Bracket"),
       "panel_bank": ("Panel", "Bank/Gateway"),
       "bracket_bank": ("Bracket", "Bank/Gateway"),
       "saldo": ("Kiri", "Kanan"),
   }
   ```
   `run_detail()`: `left_label, right_label = REL_LABELS.get(run.relation, ("Kiri", "Kanan"))` → masuk context.
3. `web/templates/web/run_detail.html`: kartu stat `Kiri (Panel)` → `{{ left_label }}`; header tabel `Kiri (Panel)` → `{{ left_label }}`, `Kanan` → `{{ right_label }}`.
4. `web/templates/web/_result_row.html` sel kiri baris kedua, format PERSIS:
   ```django
   <div class="faint" style="font-size:12px">{{ r.left.username|default:"" }}{% if r.left.counterparty %} · {{ r.left.counterparty|truncatechars:26 }}{% endif %}{% if r.left.occurred_at %} · {{ r.left.occurred_at|date:"d/m H:i" }}{% endif %}</div>
   ```
5. `web/views.py` `export_run()`: `L, R = REL_LABELS.get(run.relation, ("Kiri", "Kanan"))`; headers → `[f"{L} Ticket", f"{L} Amount", f"{L} User", f"{L} Nama Lengkap", f"{L} Waktu", R, f"{R} Sumber", f"{R} Amount", f"{R} Waktu", "Skor", "Alasan", "Detail"]`; di baris data sisipkan `left.counterparty if left else ""` setelah kolom username.
6. Sheet "Ringkasan" export: baris `("Rekonsiliasi", …)` tetap.

**Test (`web/tests_fullname_labels.py`, TDD):** pola setup transaksi lihat `web/tests_reconcile.py`. Wajib:
- Engine: panel & gateway sama-sama ber-`username` TAPI BEDA, `counterparty` identik, nominal+tanggal cocok → bucket `cocok` (skor 100 ≥ threshold default 85). (Ini RED di kode lama: skor 40 → `perlu_tinjau`.)
- Engine regresi: bank tanpa username, `counterparty` mirip → tetap `cocok` seperti sebelumnya.
- `run_detail` relasi `panel_bank` → mengandung `Bank/Gateway` dan `{{ left_label }}`-nya `Panel`; TIDAK mengandung `Kiri (Panel)`.
- Baris hasil menampilkan `counterparty` panel (Nama Lengkap).
- Export: parse response `export_run` dengan `openpyxl.load_workbook(io.BytesIO(resp.content))` → sheet `Hasil` header memuat `Panel Nama Lengkap`; baris data memuat nama lengkap transaksi kiri.
