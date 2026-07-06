# Rekonsiliasi — Tabel Wide, Pager Bernomor, Make Over CSS, Toast Motivasi

**Tanggal:** 2026-07-06
**Status:** Disetujui (desain), siap ke rencana implementasi
**Konteks halaman utama:** `run_detail` (hasil rekonsiliasi), berimbas ke komponen bersama (tabel, pager, badge) di seluruh app.

## 1. Latar & Masalah

Halaman hasil rekonsiliasi (`web/templates/web/run_detail.html`) menampilkan tabel **13 kolom** di dalam `.table-wrap` ber-`overflow-x:auto`. Di layar desktop lebar, dua hal terjadi bersamaan:

1. Area konten dikunci `max-width:1280px` lalu ditengahkan (`margin:0 auto`), sehingga sisi kiri-kanan jadi **ruang kosong** yang mubazir.
2. Tabel 13 kolom tetap **lebih lebar** dari 1280px, jadi kolom paling kanan ("Mutasi Bank") **ter-clip** dan muncul **scroll horizontal**.

Empat perbaikan yang diminta user:

1. **Tabel muat penuh tanpa scroll samping di desktop** — dengan memanfaatkan ruang kosong kiri-kanan (wide mode), **tanpa mengorbankan/menghapus kolom apa pun**.
2. **Pagination bernomor** dengan jendela geser (mis. tekan hal. 10 → jendela recenter ~5 depan/5 belakang), bukan hanya "Sebelumnya / Berikutnya".
3. **Make over CSS/UI** agar lebih rapi, cantik, profesional — memakai token & font yang sudah ada, restrained (hindari kesan "AI slop").
4. **Toast motivasi kerja** yang muncul & hilang tanpa mengganggu (pojok kanan-bawah, sekali saat buka halaman).

## 2. Tujuan & Non-Tujuan

**Tujuan**
- Semua 13 kolom hasil rekonsiliasi terlihat tanpa scroll horizontal pada desktop lebar (diverifikasi empiris lewat preview, bukan asumsi).
- Komponen pager bernomor reusable dipakai di semua tabel berpaginasi, mempertahankan **semua** filter query saat pindah halaman.
- Peningkatan visual yang konsisten & tasteful pada komponen bersama.
- Toast motivasi non-blocking, ~200 kalimat berkualitas (nuansa audit mayoritas + sebagian umum), mudah ditambah menuju 1000+ tanpa ubah kode.

**Non-Tujuan**
- Tidak menggabung/menghapus kolom tabel hasil (13 kolom dipertahankan).
- Tidak mengubah logika ingest/match/engine.
- Tidak redesign total; hanya elevasi bertahap pada styling yang sudah ada.
- Tidak menaruh konten/dekorasi di margin kosong — margin dipakai murni untuk melebarkan tabel.

## 3. Fitur 1 — Tabel "wide mode" (isi ruang kosong) + rapatkan

### Mekanisme lebar per-halaman
- `app_base.html`: ubah `<div class="content">` → `<div class="content {% block content_class %}{% endblock %}">`.
- Tambah CSS: `.content.wide{max-width:min(1680px,100%)}` (fluid; di ultrawide tetap ada sedikit margin agar baris tak terlampau panjang).
- `run_detail.html` opt-in: `{% block content_class %}wide{% endblock %}`.
- Nilai `1680px` adalah titik awal; **akan dikalibrasi di preview** agar 13 kolom benar-benar muat pada lebar desktop realistis.

### Rapatkan kolom (tanpa hapus kolom)
Target lebar tabel turun agar muat dalam area wide. Lever yang dipakai (styling saja, jumlah kolom tetap 13):
- Rapatkan padding sel (mis. mode default lebih ramping; mode "Padat" yang sudah ada tetap tersedia untuk lebih rapat lagi).
- Kecilkan teks sekunder/faint & pakai `white-space:nowrap` + `text-overflow:ellipsis` + `title=` (tooltip) pada kolom teks panjang (Player Bank, Bank Title, Nama, Mutasi Bank) — **tidak ada data hilang**, hanya dipotong visual dengan tooltip penuh.
- Set lebar kolom terarah (numerik & kolom pendek diberi lebar tetap; kolom teks fleksibel) supaya tidak ada kolom yang meledak.

### Fallback
- `.table-wrap` tetap `overflow-x:auto`. Di laptop sangat sempit (≤~1366px) 13 kolom penuh bisa saja masih menggeser sedikit — itu **fallback scroll mulus, tanpa kehilangan kolom/data**, bukan pengorbanan.
- Perilaku mobile (`.col-hide` menyembunyikan Player Bank/Bank Title/Handler <760px) **tidak berubah**.

### Kompatibilitas partial bersama
- `_result_row.html` dipakai `run_detail` **dan** `review_queue` (yang menambah kolom "run" via `show_run_col`). Karena kita mempertahankan 13 kolom & hanya mengubah styling/truncation, kedua konsumen tetap selaras. Perubahan header/lebar diterapkan lewat CSS class, bukan restrukturisasi sel.

## 4. Fitur 2 — Pagination bernomor (reusable, jendela geser)

### Komponen
- **Inclusion tag** baru di `web/templatetags/web_extras.py`:
  ```python
  @register.inclusion_tag("web/_pager.html", takes_context=True)
  def pager(context, page, on_each_side=4, on_ends=1):
      request = context["request"]
      try:
          nums = list(page.paginator.get_elided_page_range(
              page.number, on_each_side=on_each_side, on_ends=on_ends))
      except Exception:
          nums = []
      params = request.GET.copy()
      params.pop("page", None)
      return {
          "page": page,
          "nums": nums,
          "base_qs": params.urlencode(),
          "ellipsis": page.paginator.ELLIPSIS,
      }
  ```
- **Partial** `web/templates/web/_pager.html` merender: tombol `‹` (prev), daftar nomor (halaman aktif = state, elipsis = `…`, lainnya = link), tombol `›` (next). Href: `?{{ base_qs }}{% if base_qs %}&{% endif %}page={{ num }}` → **mempertahankan semua filter** (bucket/flow/reason/bank/btitle/sort/dir).
- Pakai `Paginator.get_elided_page_range` (Django 5.2) untuk jendela geser + elipsis. `on_each_side=4` (±4 sekitar aktif) sebagai default; **dikalibrasi di preview** agar mendekati "5 depan/5 belakang" tanpa terlalu lebar di layar sempit.

### Penggunaan
- Ganti blok `.pager` manual di `run_detail.html`, `transactions.html`, `review_queue.html` (dan `batch_uang.html` bila ada) menjadi `{% pager page %}`.
- Menghapus duplikasi & **memperbaiki bug**: pager `run_detail` sekarang tidak menyertakan `bank`/`btitle` → filter hilang saat pindah halaman. Versi baru menyertakan semuanya via `base_qs`.

### Perilaku recenter
- Tekan hal. 10 (dari total besar) → `get_elided_page_range(10, 4, 1)` → `1 … 6 7 8 9 10 11 12 13 14 … N` (aktif di tengah, ~4-5 tiap sisi). Sesuai maksud user.

## 5. Fitur 3 — Make over CSS (rapi, cantik, profesional)

Semua di `app_base.html` `<style>`, memakai token/`--var` & font (Inter/Sora, biru→cyan) yang sudah ada. Prinsip: **restrained, konsisten, tanpa emoji acak / gradient berlebihan / over-animation.**

Sasaran polish:
- **Pager bernomor**: pil/rounded, halaman aktif beraksen brand (solid/gradient), hover & disabled state jelas, elipsis muted, angka tabular. (Bintang dari fitur ini.)
- **Tabel**: header micro-caps yang sudah ada dipertajam; hover baris lebih halus; garis/border lebih bersih; angka `tabular-nums` rapi; sticky header mulus; kepadatan default sedikit lebih ramping (mendukung Fitur 1).
- **Badge / toolbar aksi / kartu statistik**: penyelarasan spasi (ritme 8px), hierarki (primary tebal, sekunder faint), micro-interaction halus. Kartu statistik boleh diberi aksen tipis (mis. garis atas gradient) — secukupnya.
- **Responsif aman**: shell mobile yang sudah tuned tidak rusak; verifikasi di preview (mobile 375px, desktop, dark tetap tak berlaku karena app terang).

Karena CSS bersama, halaman lain ikut terangkat — ini **disengaja** (konsistensi) dan akan **diverifikasi di preview** agar tak ada regresi visual.

## 6. Fitur 4 — Toast motivasi (muncul & hilang, non-blocking)

### Data
- Berkas baru `web/quotes.py`:
  - `AUDIT = [...]` ~140 kalimat nuansa audit (ketelitian, integritas, rekonsiliasi, akurasi angka, konsistensi, kesabaran, tanggung jawab, kejujuran).
  - `UMUM = [...]` ~60 kalimat motivasi kerja umum (Indonesia).
  - `MOTIVATION = AUDIT + UMUM` (≈200), `def random_quote() -> str: return random.choice(MOTIVATION)`.
  - Kualitas: semua kalimat Indonesia, bervariasi, tanpa duplikat, tidak terasa generik/AI. Terstruktur agar mudah ditambah menuju 1000+ tanpa ubah kode lain.

### Injeksi
- Context processor baru `web/context_processors.py::motivation(request)` → `{"motivation_quote": random_quote()}` (hanya untuk user terautentikasi; ringan, `random.choice` O(1)).
- Daftarkan di `truth_auditor/settings.py` TEMPLATES `context_processors` setelah `web.context_processors.toko`.
- Toast dirender di `app_base.html` → tampil di semua halaman kerja. Halaman login pakai base lain → tidak terpengaruh.

### Markup & perilaku
- Kartu toast kecil fixed **pojok kanan-bawah**, `role="status"` `aria-live="polite"` (diumumkan lembut, tidak blocking; **tanpa overlay gelap**).
- Ikon kutipan/spark kecil beraksen brand + teks kutipan + tombol tutup `×`.
- Animasi slide-in + fade; **auto-hilang ~7 dtk** (slide-out+fade); hormati `prefers-reduced-motion`.
- **Throttle lembut** via `localStorage` timestamp (~60 dtk): tidak memunculkan toast lagi bila baru saja tampil — mencegah spam saat navigasi cepat, tetap "muncul saat buka halaman".
- **Tidak tampil barengan** modal pengingat toko: bila `show_toko_reminder` aktif, toast ditunda (skip render/putuskan di template atau JS).
- Hover mem-pause auto-dismiss (opsional, nice-to-have).

## 7. Berkas yang disentuh

| Berkas | Perubahan |
|---|---|
| `web/templates/web/app_base.html` | `content_class` block; CSS `.content.wide`; make over CSS (pager/tabel/badge/kartu); markup+CSS+JS toast |
| `web/templates/web/run_detail.html` | opt-in `content_class=wide`; ganti pager → `{% pager page %}`; tuning class kolom/lebar |
| `web/templates/web/_result_row.html` | penyesuaian styling/truncation (jumlah kolom tetap) |
| `web/templates/web/_pager.html` | **baru** — partial pager bernomor |
| `web/templatetags/web_extras.py` | **inclusion tag** `pager` |
| `web/templates/web/transactions.html`, `review_queue.html`, `batch_uang.html` | ganti pager lama → `{% pager page %}` |
| `web/quotes.py` | **baru** — pool ~200 kutipan + `random_quote()` |
| `web/context_processors.py` | processor `motivation` |
| `truth_auditor/settings.py` | daftarkan processor `motivation` |
| `web/tests_*.py` | test baru (lihat §8) |

## 8. Rencana pengujian (TDD untuk logika server)

- **`pager` tag**
  - `get_elided_page_range` diteruskan benar: untuk (num_pages besar, page tengah) menghasilkan nomor + `ELLIPSIS` sesuai; page 1 & page terakhir tak error.
  - `base_qs` mempertahankan semua param **kecuali** `page` (uji dgn `RequestFactory` + query string berisi bucket/bank/btitle/sort).
  - Render `_pager.html`: halaman aktif bukan link; nomor lain link ber-href memuat `base_qs`; elipsis muncul; prev/next sesuai `has_previous/has_next`.
- **Context processor `motivation`**
  - Mengembalikan `motivation_quote` berupa `str` non-kosong ∈ pool.
  - Pool: jumlah ≥ ~150; semua entri `str` non-kosong (setelah `strip`); **tanpa duplikat** (jaga kualitas).
- **Smoke `run_detail`**
  - GET 200; mengandung container toast; untuk run dgn >40 hasil, mengandung markup pager bernomor (nav).
- **Regresi**
  - Jalankan seluruh suite (410 test) tetap hijau. Periksa/ubah test yang mungkin meng-assert teks pager lama ("Sebelumnya"/"Halaman X / Y") atau struktur kolom.

## 9. Risiko & mitigasi

- **13 kolom tetap tak muat di layar tertentu** → wide mode + rapatkan dikalibrasi empiris di preview; sisakan fallback scroll (tanpa data hilang). Bila user mau, opsi lanjutan (konsolidasi kolom) tersedia terpisah — **di luar scope ini**.
- **Perubahan CSS bersama memicu regresi visual di halaman lain** → verifikasi tiap halaman utama di preview (desktop + mobile 375px).
- **Test lama meng-assert markup pager lama** → sesuaikan saat implementasi.
- **Toast dianggap terlalu sering** → throttle 60 dtk + auto-dismiss + dismissible; mudah diubah ke "sekali per sesi" bila perlu.
- **Kualitas 200 kutipan** → kurasi manual, tanpa duplikat, nada Indonesia yang wajar; hindari klise generik.

## 10. Kriteria selesai

- [ ] Di preview desktop lebar, tabel hasil menampilkan **semua 13 kolom tanpa scroll horizontal** (termasuk "Mutasi Bank").
- [ ] Pager bernomor tampil, recenter saat pindah, mempertahankan semua filter.
- [ ] Polish CSS terpasang, tak ada regresi visual di halaman utama (dicek preview).
- [ ] Toast motivasi muncul sekali saat buka halaman, auto-hilang, non-blocking, tak bentrok modal toko.
- [ ] Seluruh test hijau (410 lama + test baru).
