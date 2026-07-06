# Rekonsiliasi — Tabel Wide, Pager Bernomor, Make Over CSS, Toast Motivasi — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Buat tabel hasil rekonsiliasi memakai ruang kosong kiri-kanan agar 13 kolom muat tanpa scroll samping, tambah pager bernomor jendela-geser yang reusable, poles CSS agar profesional, dan tampilkan toast motivasi non-blocking.

**Architecture:** Perubahan terpusat di lapisan template/CSS Django + satu inclusion tag + satu context processor. Tidak menyentuh engine ingest/match. Komponen pager & CSS bersifat bersama (dipakai lintas halaman); wide-mode & toast di-opt-in lewat blok template + context processor.

**Tech Stack:** Django 5.2 (templates, `Paginator.get_elided_page_range`, inclusion tag, context processor), CSS di `app_base.html` (token `--var` + font Inter/Sora yang sudah ada), JS vanilla kecil, htmx (sudah ada, tak diubah).

## Global Constraints

- Django floor: `>=5.2,<5.3`. `Paginator.get_elided_page_range` & tag `{% querystring %}` tersedia — tapi rencana ini pakai inclusion tag sendiri (bukan `{% querystring %}`).
- `USE_TZ = False` — jangan memperkenalkan datetime tz-aware.
- Semua UI, komentar, dan teks dalam **Bahasa Indonesia**.
- CSS wajib memakai token/`--var` & font yang **sudah ada** (biru→cyan, Inter/Sora). Restrained: tanpa emoji acak, gradient berlebihan, atau over-animation ("AI slop" dihindari).
- Test framework: **Django `TestCase`/`SimpleTestCase`** (bukan pytest). Jalankan `python manage.py test ...` dari dalam `.venv` (`source .venv/bin/activate`).
- **13 kolom tabel hasil dipertahankan** — tidak ada kolom digabung/dihapus.
- Commit **lokal** tiap task. Akhiri setiap pesan commit dengan baris:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- Verifikasi visual pakai preview tools (bukan Bash runserver). Login lokal: `rnd` / `RnD-Audit#2026`.

---

## File Structure

| File | Tanggung jawab |
|---|---|
| `web/templatetags/web_extras.py` | + inclusion tag `pager` (jendela geser + preserve query) |
| `web/templates/web/_pager.html` | **baru** — markup pager bernomor |
| `web/templates/web/run_detail.html` | opt-in wide; ganti pager; class kolom/lebar |
| `web/templates/web/transactions.html` | load web_extras; ganti pager |
| `web/templates/web/review_queue.html` | load web_extras; ganti pager |
| `web/templates/web/batch_uang.html` | load web_extras; ganti pager |
| `web/templates/web/_result_row.html` | truncation + tooltip pada sel teks panjang (kolom tetap 13) |
| `web/templates/web/app_base.html` | `content_class` block; CSS `.content.wide`; make over CSS (pager/tabel/badge/kartu); markup+CSS+JS toast |
| `web/quotes.py` | **baru** — pool ~200 kutipan + `random_quote()` |
| `web/context_processors.py` | + processor `motivation` |
| `truth_auditor/settings.py` | daftarkan processor `motivation` |
| `web/tests_pager.py` | **baru** — test tag pager |
| `web/tests_motivation.py` | **baru** — test pool + processor + toast |
| `web/tests_pager_wiring.py` | **baru** — test filter dipertahankan saat paging |

---

## Task 1: Komponen pager bernomor (tag + partial)

**Files:**
- Modify: `web/templatetags/web_extras.py` (append tag)
- Create: `web/templates/web/_pager.html`
- Test: `web/tests_pager.py`

**Interfaces:**
- Produces: template tag `{% pager page %}` (opsional kwargs `on_each_side`, `on_ends`). Fungsi `pager(context, page, on_each_side=4, on_ends=1) -> dict` mengembalikan `{"page", "nums", "base_qs", "ellipsis"}`. Partial `web/_pager.html` merender `<nav class="pager reveal">…</nav>`.

- [ ] **Step 1: Tulis test yang gagal** — `web/tests_pager.py`:

```python
from django.core.paginator import Paginator
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase

from web.templatetags.web_extras import pager


class PagerTagTests(SimpleTestCase):
    def _page(self, total, per, number):
        return Paginator(list(range(total)), per).get_page(number)

    def test_base_qs_preserves_filters_but_drops_page(self):
        req = RequestFactory().get("/x?bucket=tidak_cocok&bank=BCA&page=3&sort=amount")
        ctx = pager({"request": req}, self._page(4000, 40, 3))
        self.assertIn("bucket=tidak_cocok", ctx["base_qs"])
        self.assertIn("bank=BCA", ctx["base_qs"])
        self.assertIn("sort=amount", ctx["base_qs"])
        self.assertNotIn("page=", ctx["base_qs"])

    def test_elided_window_has_ellipsis_and_neighbors(self):
        req = RequestFactory().get("/x")
        ctx = pager({"request": req}, self._page(4000, 40, 50))  # 100 halaman, aktif 50
        nums = ctx["nums"]
        self.assertIn(ctx["ellipsis"], nums)
        for n in range(46, 55):
            self.assertIn(n, nums)
        self.assertIn(1, nums)
        self.assertIn(100, nums)

    def test_render_marks_current_and_keeps_filter_on_links(self):
        req = RequestFactory().get("/x?bucket=cocok")
        page = self._page(4000, 40, 50)
        html = Template("{% load web_extras %}{% pager page %}").render(
            Context({"page": page, "request": req})
        )
        self.assertIn('aria-current="page"', html)
        self.assertIn("Navigasi halaman", html)
        self.assertIn("page=49", html)      # link tetangga ada
        self.assertIn("bucket=cocok", html)  # filter dipertahankan di href

    def test_single_page_renders_nothing(self):
        req = RequestFactory().get("/x")
        html = Template("{% load web_extras %}{% pager page %}").render(
            Context({"page": self._page(10, 40, 1), "request": req})
        )
        self.assertNotIn("Navigasi halaman", html)
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

```bash
source .venv/bin/activate && python manage.py test web.tests_pager -v2
```
Expected: FAIL — `ImportError: cannot import name 'pager'` / template tag `pager` tidak dikenal.

- [ ] **Step 3: Implementasi tag** — append ke `web/templatetags/web_extras.py`:

```python
@register.inclusion_tag("web/_pager.html", takes_context=True)
def pager(context, page, on_each_side=4, on_ends=1):
    """Pager bernomor jendela-geser (elided) yang mempertahankan semua query kecuali `page`."""
    request = context.get("request")
    try:
        nums = list(
            page.paginator.get_elided_page_range(
                page.number, on_each_side=on_each_side, on_ends=on_ends
            )
        )
    except Exception:
        nums = []
    if request is not None:
        params = request.GET.copy()
        params.pop("page", None)
        base_qs = params.urlencode()
    else:
        base_qs = ""
    return {
        "page": page,
        "nums": nums,
        "base_qs": base_qs,
        "ellipsis": page.paginator.ELLIPSIS,
    }
```

- [ ] **Step 4: Buat partial** — `web/templates/web/_pager.html`:

```html
{% if page.has_other_pages %}
<nav class="pager reveal" aria-label="Navigasi halaman">
  {% if page.has_previous %}<a class="pg nav" rel="prev" aria-label="Halaman sebelumnya" href="?{% if base_qs %}{{ base_qs }}&{% endif %}page={{ page.previous_page_number }}"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="15 18 9 12 15 6"/></svg></a>{% else %}<span class="pg nav disabled" aria-hidden="true"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg></span>{% endif %}
  {% for num in nums %}{% if num == ellipsis %}<span class="pg gap" aria-hidden="true">…</span>{% elif num == page.number %}<span class="pg cur" aria-current="page">{{ num }}</span>{% else %}<a class="pg" href="?{% if base_qs %}{{ base_qs }}&{% endif %}page={{ num }}">{{ num }}</a>{% endif %}{% endfor %}
  {% if page.has_next %}<a class="pg nav" rel="next" aria-label="Halaman berikutnya" href="?{% if base_qs %}{{ base_qs }}&{% endif %}page={{ page.next_page_number }}"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg></a>{% else %}<span class="pg nav disabled" aria-hidden="true"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg></span>{% endif %}
</nav>
{% endif %}
```

> Catatan: styling `.pg` dibuat di Task 4. Tanpa CSS itu pager tetap fungsional (mewarisi `.pager`).

- [ ] **Step 5: Jalankan test, pastikan LULUS**

```bash
python manage.py test web.tests_pager -v2
```
Expected: PASS (4 test).

- [ ] **Step 6: Commit**

```bash
git add web/templatetags/web_extras.py web/templates/web/_pager.html web/tests_pager.py
git commit -m "$(printf 'feat(web): inclusion tag pager bernomor jendela-geser + partial\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 2: Pasang pager di semua tabel berpaginasi

**Files:**
- Modify: `web/templates/web/run_detail.html:125-131`, `web/templates/web/transactions.html:93-100`, `web/templates/web/review_queue.html:26-33`, `web/templates/web/batch_uang.html:63-68`
- Test: `web/tests_pager_wiring.py`

**Interfaces:**
- Consumes: `{% pager page %}` dari Task 1.

- [ ] **Step 1: Tulis test yang gagal** — `web/tests_pager_wiring.py` (mem-verifikasi filter dipertahankan saat paging — sekaligus mengunci perbaikan bug bank/btitle):

```python
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


class PagerWiringTests(TestCase):
    def setUp(self):
        User.objects.create_user("admpg", password="pw123456", role="admin")
        self.client.login(username="admpg", password="pw123456")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.batch = ReconBatch.objects.create(toko=self.toko, tolerance=self.tol)
        self.run = MatchRun.objects.create(
            batch=self.batch, tolerance=self.tol,
            relation=MatchRun.Relation.PANEL_BANK, summary={"left": 60},
        )
        up = Upload.objects.create(source_type=self.panel, toko=self.toko)
        # 60 hasil TIDAK (left ada) -> >40 => multi-halaman
        for i in range(60):
            tx = Transaction.objects.create(
                source_type=self.panel, toko=self.toko, upload=up,
                jenis="depo", occurred_at=datetime(2026, 7, 1, 10, 0),
                amount=Decimal("50000"), credit_delta=Decimal("-50000"),
                money_delta=Decimal("50000"), username=f"user{i}",
                player_bank="BCA", ticket_no=f"D{i:07d}", row_hash=f"h{i}",
            )
            MatchResult.objects.create(
                run=self.run, left=tx, bucket=MatchResult.Bucket.TIDAK,
                reason_code="no_money", score=0,
            )

    def test_run_detail_pager_preserves_bank_filter(self):
        url = reverse("run_detail", args=[self.run.pk])
        r = self.client.get(url, {"bucket": "tidak_cocok", "bank": "BCA"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Navigasi halaman")
        # href halaman berikut wajib membawa bank=BCA (bukan hanya page=)
        self.assertContains(r, "bank=BCA")
        self.assertContains(r, "page=2")
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

```bash
python manage.py test web.tests_pager_wiring -v2
```
Expected: FAIL — pager lama tak punya "Navigasi halaman"; `bank=BCA` tak ada di href pager lama.

- [ ] **Step 3: Ganti pager di `run_detail.html`** — hapus baris 125-131 (blok `{% if page.has_other_pages %}<div class="pager">…</div>{% endif %}`) ganti dengan:

```html
{% pager page %}
```

- [ ] **Step 4: Ganti pager di `transactions.html`** — tambahkan `{% load web_extras %}` tepat di bawah `{% load humanize %}` (baris atas file), lalu hapus baris 93-100 (blok `.pager`) ganti dengan:

```html
{% pager page %}
```

- [ ] **Step 5: Ganti pager di `review_queue.html`** — tambahkan `{% load web_extras %}` di bawah `{% load %}` teratas, lalu hapus baris 26-33 (blok `.pager`) ganti dengan:

```html
{% pager page %}
```

- [ ] **Step 6: Ganti pager di `batch_uang.html`** — tambahkan `{% load web_extras %}` di bawah `{% load %}` teratas, lalu hapus baris 63-68 (blok `.pager reveal`) ganti dengan:

```html
{% pager page %}
```

- [ ] **Step 7: Jalankan test target + seluruh suite (pastikan tak ada regresi)**

```bash
python manage.py test web.tests_pager_wiring -v2
python manage.py test
```
Expected: `tests_pager_wiring` PASS; seluruh suite tetap hijau (410+ test). Bila ada test lama meng-assert teks pager lama, perbaiki assertion-nya ke marker baru (`Navigasi halaman` / `class="pg cur"`). (Sudah dicek: tidak ada.)

- [ ] **Step 8: Commit**

```bash
git add web/templates/web/run_detail.html web/templates/web/transactions.html web/templates/web/review_queue.html web/templates/web/batch_uang.html web/tests_pager_wiring.py
git commit -m "$(printf 'feat(web): pakai pager bernomor di semua tabel + preserve filter saat paging\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 3: Wide mode + rapatkan tabel (13 kolom muat)

**Files:**
- Modify: `web/templates/web/app_base.html` (`.content` block + CSS)
- Modify: `web/templates/web/run_detail.html` (opt-in wide + class kolom)
- Modify: `web/templates/web/_result_row.html` (truncation + tooltip)
- Test: `web/tests_motivation.py` tak dipakai di sini; tambah smoke ke `web/tests_pager_wiring.py`

**Interfaces:**
- Produces: class CSS `.content.wide`, util `.cell-tr` (truncate). Blok `{% block content_class %}` di app_base.

- [ ] **Step 1: Tulis smoke test yang gagal** — tambahkan method ke `PagerWiringTests` di `web/tests_pager_wiring.py`:

```python
    def test_run_detail_pakai_wide_mode(self):
        r = self.client.get(reverse("run_detail", args=[self.run.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'class="content wide"')
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

```bash
python manage.py test web.tests_pager_wiring.PagerWiringTests.test_run_detail_pakai_wide_mode -v2
```
Expected: FAIL — `.content` belum punya class `wide`.

- [ ] **Step 3: Tambah hook lebar di `app_base.html`** — ubah baris 388:

```html
  <div class="content">
```
menjadi:

```html
  <div class="content {% block content_class %}{% endblock %}">
```

- [ ] **Step 4: Tambah CSS wide + util truncate** — di `app_base.html`, di dalam `<style>` setelah blok `.content{...}` (sekitar baris 81), tambahkan:

```css
/* Wide mode: halaman padat-data (rekonsiliasi) memakai ruang kosong kiri-kanan */
.content.wide{max-width:min(1680px,100%)}
/* Sel teks panjang: potong visual + tetap utuh via tooltip (title=) */
td.cell-tr{max-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
```

- [ ] **Step 5: Opt-in wide di `run_detail.html`** — tepat setelah `{% block content %}` (baris 6), tambahkan baris:

```html
{% block content_class %}wide{% endblock %}
```

- [ ] **Step 6: Rapatkan padding default tabel** — di `app_base.html` ubah aturan `tbody td` (baris 173) dan `thead th` (baris 171) menjadi lebih ramping:

`thead th` padding `10px 14px` → `9px 12px`; `tbody td` padding `10px 14px` → `9px 12px`. (Mode `.dense` yang sudah ada tetap tersedia untuk lebih rapat.)

- [ ] **Step 7: Terapkan truncation pada sel teks panjang** — di `web/templates/web/_result_row.html` tambahkan class `cell-tr` (dan pastikan `title=` berisi teks penuh) pada sel:
  - Nama Lengkap (baris 10): bungkus isi dengan `<td class="cell-tr" ...><span title="{{ r.left.counterparty }}">…</span></td>` (hapus `truncatechars` — biar CSS yang memotong, tooltip menampilkan penuh).
  - Player Bank (baris 12): `<td class="faint col-hide cell-tr" title="{{ pb }}" style="font-size:12px">`
  - Bank Title (baris 13): `<td class="faint col-hide cell-tr" title="{{ bt }}" style="font-size:12px">`
  - Sel kanan/Mutasi Bank (baris 17-18): tambahkan `cell-tr` pada `<td>` pembungkus dan `title=` pada counterparty.

  Contoh sel Nama Lengkap menjadi:

```html
  <td class="cell-tr" style="font-size:12.5px">{% if r.left.counterparty %}<span title="{{ r.left.counterparty }}">{{ r.left.counterparty }}</span>{% else %}<span class="faint">—</span>{% endif %}</td>
```

- [ ] **Step 8: Beri lebar terarah pada kolom sempit** — di `run_detail.html` thead (baris 105-109), tambahkan `style="width:..."` pada kolom pendek agar kolom teks dapat sisa ruang: Status `width:104px`, Username `width:104px`, Handler `width:96px`, kolom num (Kredit/Saldo) `width:104px`, Aksi tetap center `width:84px`. (Kolom teks Player Bank/Bank Title/Nama/Mutasi dibiarkan fleksibel + `cell-tr`.)

- [ ] **Step 9: Verifikasi di preview (KALIBRASI lebar)** — pastikan dev server jalan:

  1. Buat `.claude/launch.json` bila belum ada:
```json
{
  "version": "0.0.1",
  "configurations": [
    { "name": "web", "runtimeExecutable": ".venv/bin/python", "runtimeArgs": ["manage.py", "runserver", "8000"], "port": 8000 }
  ]
}
```
  2. `preview_start` name `web`. Login lewat preview: `preview_fill` username=`rnd`, password=`RnD-Audit#2026`, submit. Navigasi ke sebuah run_detail dengan banyak baris (dari menu Rekonsiliasi → Batch → salah satu Run).
  3. `preview_resize` desktop 1440×900 lalu 1680×1000. `preview_inspect` selector `#hasil-table` untuk `width`, dan `.content.wide` untuk `width`. **Pastikan `#hasil-table` width ≤ container width** (tak ada overflow → tak ada scroll samping). `preview_eval`: `document.querySelector('.table-wrap.tall').scrollWidth <= document.querySelector('.table-wrap.tall').clientWidth` harus `true`.
  4. Bila masih overflow di 1440: turunkan lagi padding sel (mis. `8px 10px`) dan/atau font teks sekunder, atau naikkan `.content.wide` max-width. Iterasi sampai kondisi (3) `true` di 1440px. Bila di 1366 tetap overflow tipis, itu fallback yang diterima (scroll mulus).
  5. `preview_screenshot` sebagai bukti "muat penuh, termasuk kolom Mutasi Bank".
  6. `preview_resize` mobile 375px → pastikan `.col-hide` tetap menyembunyikan Player Bank/Bank Title/Handler dan layout tak rusak.

- [ ] **Step 10: Jalankan test + commit**

```bash
python manage.py test web.tests_pager_wiring
git add web/templates/web/app_base.html web/templates/web/run_detail.html web/templates/web/_result_row.html web/tests_pager_wiring.py .claude/launch.json
git commit -m "$(printf 'feat(web): tabel hasil wide-mode + rapatkan kolom agar muat tanpa scroll samping\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 4: Make over CSS (pager bernomor + poles tabel/badge/kartu)

**Files:**
- Modify: `web/templates/web/app_base.html` (`<style>`)

**Interfaces:**
- Consumes: markup `.pg` dari `_pager.html` (Task 1). Tak ada perubahan Python/logika.

- [ ] **Step 1: Styling pager bernomor** — di `app_base.html`, ganti aturan `.pager` (baris 169) dan tambahkan style `.pg` sesudahnya:

```css
.pager{display:flex;gap:6px;align-items:center;justify-content:center;margin-top:22px;flex-wrap:wrap}
.pg{display:inline-grid;place-items:center;min-width:36px;height:36px;padding:0 10px;border-radius:10px;
  border:1px solid var(--line);background:var(--panel);color:var(--muted);font-size:13px;font-weight:600;
  font-variant-numeric:tabular-nums;box-shadow:var(--shadow);transition:background .14s,color .14s,border-color .14s,box-shadow .14s}
.pg:hover{color:var(--ink);border-color:var(--line-2);background:var(--panel-2)}
.pg.cur{background:var(--brand);border-color:var(--brand);color:#fff;box-shadow:0 6px 16px -8px rgba(37,99,235,.7)}
.pg.nav{color:var(--faint)}
.pg.nav svg{width:15px;height:15px}
.pg.gap{border:none;background:none;box-shadow:none;color:var(--faint);min-width:22px;cursor:default}
.pg.disabled{opacity:.4;pointer-events:none;box-shadow:none}
.pg:focus-visible{outline:2px solid var(--brand);outline-offset:2px}
```

- [ ] **Step 2: Poles tabel (hover + border + header)** — di `app_base.html` sempurnakan aturan tabel yang ada (jangan hapus fungsionalitas sticky/dense):
  - `tbody tr:hover` (baris 175): tambahkan transisi & aksen kiri halus saat hover:

```css
tbody tr{transition:background .12s}
tbody tr:hover{background:var(--panel-2)}
tbody tr:hover td:first-child{box-shadow:inset 3px 0 0 var(--brand)}
```
  - `thead th` (baris 171): pertegas garis bawah header — tambahkan `border-bottom:1px solid var(--line-2)` (ganti `border-bottom:1px solid var(--line)`).

> Catatan gaya: kartu statistik SUDAH baik (warna semantik ok/warn/bad/info). **Jangan** menambah aksen gradient di kartu — akan berbenturan dengan warna semantik & terasa berlebihan. Fokus polish di pager (bintang fitur) + tabel.

- [ ] **Step 3: Verifikasi lintas halaman di preview** — `preview_start`/reuse. Login bila perlu. Cek berurutan dan ambil `preview_screenshot`:
  - run_detail: pager bernomor tampil (pil, halaman aktif brand, elipsis), tabel rapi.
  - transactions, review_queue, batch_uang: pager bernomor tampil normal, tak ada layout pecah.
  - dashboard: kartu/tabel tak regresi.
  - `preview_resize` mobile 375px pada run_detail & dashboard: pager membungkus rapi (`flex-wrap`), sidebar off-canvas normal.
  - `preview_console_logs` level error: pastikan tak ada error baru.

- [ ] **Step 4: Commit**

```bash
git add web/templates/web/app_base.html
git commit -m "$(printf 'style(web): make over pager bernomor + poles tabel hover/header\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 5: Pool kutipan + context processor motivasi

**Files:**
- Create: `web/quotes.py`
- Modify: `web/context_processors.py` (+ fungsi `motivation`)
- Modify: `truth_auditor/settings.py` (daftarkan processor)
- Test: `web/tests_motivation.py`

**Interfaces:**
- Produces: `web/quotes.py::MOTIVATION` (list[str], ≈200), `web/quotes.py::random_quote() -> str`; context var `motivation_quote` (str) di semua template beraut.

- [ ] **Step 1: Tulis test yang gagal** — `web/tests_motivation.py`:

```python
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import Toko
from web import quotes

User = get_user_model()


class QuotePoolTests(TestCase):
    def test_pool_cukup_besar_dan_valid(self):
        self.assertGreaterEqual(len(quotes.MOTIVATION), 150)
        for q in quotes.MOTIVATION:
            self.assertIsInstance(q, str)
            self.assertTrue(q.strip(), "kutipan kosong tidak boleh ada")

    def test_pool_tanpa_duplikat(self):
        norm = [q.strip().lower() for q in quotes.MOTIVATION]
        self.assertEqual(len(norm), len(set(norm)), "ada kutipan duplikat")

    def test_random_quote_dari_pool(self):
        q = quotes.random_quote()
        self.assertIn(q, quotes.MOTIVATION)


class MotivationProcessorTests(TestCase):
    def setUp(self):
        User.objects.create_user("admmot", password="pw123456", role="admin")
        self.client.login(username="admmot", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": Toko.objects.get(key="lbs").id})

    def test_context_menyediakan_kutipan(self):
        from web.context_processors import motivation

        req = type("R", (), {})()
        ctx = motivation(req)
        self.assertIn("motivation_quote", ctx)
        self.assertIn(ctx["motivation_quote"], quotes.MOTIVATION)
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

```bash
python manage.py test web.tests_motivation -v2
```
Expected: FAIL — modul `web.quotes` belum ada.

- [ ] **Step 3: Buat `web/quotes.py`** — struktur berikut, lalu **lengkapi hingga ≈200** kalimat mengikuti gaya contoh (mayoritas `AUDIT`, sebagian `UMUM`). Aturan mutu: Bahasa Indonesia wajar, bervariasi (jangan menyalin pola sama), **tanpa duplikat**, tak klise/generik, relevan kerja auditor. Contoh awal (perluas dari sini):

```python
"""Kumpulan kalimat motivasi untuk toast — nuansa audit (mayoritas) + kerja umum.

Ditata sebagai dua list agar mudah ditambah menuju 1000+ tanpa mengubah kode lain.
Satu kalimat dipilih acak per pemuatan halaman (lihat context_processors.motivation).
"""
import random

# Nuansa audit: ketelitian, integritas, rekonsiliasi, akurasi, konsistensi, tanggung jawab.
AUDIT = [
    "Setiap angka punya cerita — tugas kita memastikan ceritanya jujur.",
    "Ketelitian hari ini menyelamatkan penyesalan esok hari.",
    "Selisih sekecil apa pun layak ditanya, bukan diabaikan.",
    "Rekonsiliasi bukan mencari siapa yang salah, tapi memastikan semua benar.",
    "Data yang rapi lahir dari auditor yang sabar.",
    "Percaya boleh, verifikasi wajib.",
    "Satu baris yang cocok hari ini, satu masalah yang tak meledak nanti.",
    "Integritas adalah laporan yang tetap sama walau tak ada yang mengawasi.",
    "Angka tidak berbohong; yang berbohong adalah yang enggan mencocokkannya.",
    "Teliti di awal lebih murah daripada memperbaiki di akhir.",
    "Kejujuran sebuah panel diukur dari seberapa berani ia dicocokkan.",
    "Auditor hebat bukan yang cepat, tapi yang tak melewatkan.",
    "Setiap transaksi yang kau tinjau menjaga kepercayaan seseorang.",
    "Ragu sedikit, periksa lagi — itu tanda profesional, bukan lemah.",
    "Konsistensi kecil setiap hari mengalahkan usaha besar sesekali.",
    "Yang tidak cocok bukan musuh, melainkan petunjuk.",
    "Bersihkan selisih hari ini agar besok bekerja dengan tenang.",
    "Ketelitian adalah bentuk hormat pada uang orang lain.",
    "Rekening boleh banyak, ketelitian tetap satu standar.",
    "Sabar menelusuri, lega menemukan.",
    "Tutup buku dengan hati tenang: semuanya sudah dicocokkan.",
    "Kualitas audit terlihat saat tak ada yang memeriksa ulang.",
    "Selisih yang dibiarkan akan tumbuh; selisih yang dikejar akan hilang.",
    "Fokus pada yang janggal, tenang pada yang wajar.",
    "Setiap centang adalah janji bahwa angka ini benar.",
]

# Motivasi kerja umum.
UMUM = [
    "Mulai dari yang bisa dikerjakan sekarang, sisanya menyusul.",
    "Pekerjaan besar selesai satu baris pada satu waktu.",
    "Istirahat sejenak bukan kalah — itu menjaga ketelitian tetap tajam.",
    "Kemajuan kecil tetap kemajuan.",
    "Selesaikan yang sulit dahulu, sisanya terasa ringan.",
    "Tenang itu produktif; buru-buru itu boros.",
    "Hari ini cukup satu langkah lebih baik dari kemarin.",
    "Rapi di meja, jernih di kepala.",
    "Disiplin hari biasa membentuk hasil luar biasa.",
    "Fokus pada proses, hasil mengikuti.",
]

MOTIVATION = AUDIT + UMUM


def random_quote() -> str:
    """Satu kutipan acak dari pool gabungan."""
    return random.choice(MOTIVATION)
```

> Wajib: perbanyak `AUDIT` hingga ≈140 dan `UMUM` hingga ≈60 (total ≈200) sebelum lanjut. Test `test_pool_cukup_besar_dan_valid` menuntut ≥150; target ≈200.

- [ ] **Step 4: Tambah context processor** — di `web/context_processors.py` tambahkan fungsi baru (tak mengubah `toko`):

```python
def motivation(request):
    """Satu kutipan motivasi acak untuk toast (dipakai app_base). Ringan: O(1)."""
    from web.quotes import random_quote

    return {"motivation_quote": random_quote()}
```

- [ ] **Step 5: Daftarkan processor** — di `truth_auditor/settings.py`, dalam list `context_processors` (baris 78-83), tambahkan setelah `'web.context_processors.toko',`:

```python
                'web.context_processors.motivation',
```

- [ ] **Step 6: Jalankan test, pastikan LULUS**

```bash
python manage.py test web.tests_motivation -v2
```
Expected: PASS (4 test).

- [ ] **Step 7: Commit**

```bash
git add web/quotes.py web/context_processors.py truth_auditor/settings.py web/tests_motivation.py
git commit -m "$(printf 'feat(web): pool ~200 kutipan motivasi audit + context processor\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 6: Toast motivasi (markup + CSS + JS) non-blocking

**Files:**
- Modify: `web/templates/web/app_base.html` (markup toast sebelum `{% block scripts %}`, CSS di `<style>`, JS)
- Test: `web/tests_motivation.py` (+ metode toast)

**Interfaces:**
- Consumes: `motivation_quote` (Task 5), `show_toko_reminder` (sudah ada).

- [ ] **Step 1: Tulis test yang gagal** — tambahkan ke `web/tests_motivation.py`:

```python
class ToastRenderTests(TestCase):
    def setUp(self):
        User.objects.create_user("admtoast", password="pw123456", role="supervisor")
        self.toko = Toko.objects.get(key="lbs")

    def test_toast_muncul_di_halaman_kerja(self):
        self.client.login(username="admtoast", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, 'id="motivToast"')

    def test_toast_tidak_muncul_bersama_modal_pengingat(self):
        # follow login => show_toko_reminder aktif (modal pengingat toko tampil)
        r = self.client.post(
            reverse("login"),
            {"username": "admtoast", "password": "pw123456"},
            follow=True,
        )
        self.assertContains(r, "Pastikan toko aktif sudah tepat")  # modal ada
        self.assertNotContains(r, 'id="motivToast"')               # toast ditahan
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

```bash
python manage.py test web.tests_motivation.ToastRenderTests -v2
```
Expected: FAIL — `id="motivToast"` belum ada.

- [ ] **Step 3: Tambah markup toast** — di `app_base.html`, tepat sebelum `{% block scripts %}{% endblock %}` (baris 466), tambahkan (render hanya jika ada kutipan dan modal pengingat TIDAK aktif):

```html
{% if motivation_quote and not show_toko_reminder %}
<div class="motiv-toast" id="motivToast" role="status" aria-live="polite" hidden>
  <span class="mi" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 6.1H3M21 12.1H3M15.1 18H3"/></svg></span>
  <p class="mt">{{ motivation_quote }}</p>
  <button type="button" class="mx" id="motivClose" aria-label="Tutup">&times;</button>
</div>
<script>
(function(){
  var t = document.getElementById('motivToast');
  if(!t) return;
  var KEY = 'toa_motiv_ts', GAP = 60000, LIFE = 7000, tmr;
  try{ if(Date.now() - (+localStorage.getItem(KEY) || 0) < GAP){ t.remove(); return; } }catch(e){}
  function hide(){ t.classList.remove('show'); clearTimeout(tmr); setTimeout(function(){ t.remove(); }, 320); }
  t.hidden = false;
  requestAnimationFrame(function(){ t.classList.add('show'); });
  try{ localStorage.setItem(KEY, Date.now()); }catch(e){}
  tmr = setTimeout(hide, LIFE);
  t.addEventListener('mouseenter', function(){ clearTimeout(tmr); });
  t.addEventListener('mouseleave', function(){ tmr = setTimeout(hide, LIFE); });
  document.getElementById('motivClose').addEventListener('click', hide);
})();
</script>
{% endif %}
```

- [ ] **Step 4: Tambah CSS toast** — di `app_base.html` `<style>` (mis. setelah blok `.reminder-*`, sekitar baris 281), tambahkan:

```css
/* ---- TOAST MOTIVASI (non-blocking) ---- */
.motiv-toast{position:fixed;right:20px;bottom:20px;z-index:70;max-width:340px;display:flex;gap:11px;align-items:flex-start;
  padding:13px 14px;background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow-lg);
  opacity:0;transform:translateY(12px);transition:opacity .3s ease,transform .3s ease}
.motiv-toast.show{opacity:1;transform:none}
.motiv-toast .mi{flex-shrink:0;width:30px;height:30px;border-radius:9px;display:grid;place-items:center;background:var(--info-bg);color:var(--brand)}
.motiv-toast .mi svg{width:16px;height:16px}
.motiv-toast .mt{margin:0;font-size:13px;line-height:1.5;color:var(--ink);font-weight:500}
.motiv-toast .mx{flex-shrink:0;border:none;background:none;color:var(--faint);font-size:18px;line-height:1;cursor:pointer;padding:0 2px}
.motiv-toast .mx:hover{color:var(--ink)}
@media(prefers-reduced-motion:reduce){.motiv-toast{transition:none}}
@media(max-width:640px){.motiv-toast{right:12px;left:12px;bottom:12px;max-width:none}}
```

- [ ] **Step 5: Jalankan test target, pastikan LULUS**

```bash
python manage.py test web.tests_motivation.ToastRenderTests -v2
```
Expected: PASS (2 test).

- [ ] **Step 6: Verifikasi di preview** — `preview_start`/reuse, login `rnd`/`RnD-Audit#2026`.
  - Buka dashboard: toast muncul pojok kanan-bawah, lalu hilang ~7 dtk. `preview_screenshot` saat muncul.
  - Klik `#motivClose` (`preview_click`): toast hilang segera.
  - Reload cepat (`preview_eval` `location.reload()`) dalam <60 dtk: toast **tidak** muncul lagi (throttle). Setelah >60 dtk: muncul lagi.
  - `preview_resize` mobile 375px: toast full-width bawah, tak menutupi konten penting.
  - `preview_console_logs` level error: bersih.

- [ ] **Step 7: Commit**

```bash
git add web/templates/web/app_base.html web/tests_motivation.py
git commit -m "$(printf 'feat(web): toast motivasi non-blocking (auto-hilang, throttle, tak bentrok modal)\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 7: Verifikasi menyeluruh + tutup

**Files:** —

- [ ] **Step 1: Seluruh test suite hijau**

```bash
source .venv/bin/activate && python manage.py test
```
Expected: OK, semua test (410 lama + baru) PASS.

- [ ] **Step 2: Verifikasi akhir di preview (bukti untuk user)** — kumpulkan screenshot: run_detail wide (13 kolom penuh, kolom Mutasi Bank utuh, pager bernomor), toast motivasi tampil, mobile 375px run_detail. Bagikan ke user via SendUserFile.

- [ ] **Step 3: Ringkas & serahkan** — laporkan perubahan, hasil test, dan screenshot. Tawarkan opsi finishing (merge/PR) via superpowers:finishing-a-development-branch.

---

## Self-Review (diisi penulis rencana)

**Spec coverage:**
- §3 Tabel wide + rapatkan → Task 3 ✓
- §4 Pager bernomor reusable + preserve filter → Task 1 + Task 2 ✓
- §5 Make over CSS → Task 4 (+ sebagian Task 3 padat) ✓
- §6 Toast motivasi (pool ~200, processor, markup/CSS/JS, throttle, tak bentrok modal) → Task 5 + Task 6 ✓
- §8 Testing (tag pager, processor, smoke, regresi) → Task 1/2/3/5/6/7 ✓

**Placeholder scan:** Kutipan ≈200 sengaja diminta diperluas dari 35 contoh konkret + aturan mutu + test penjaga (≥150, tanpa duplikat) — konten, bukan logika. Tak ada "TBD/TODO" pada kode/logika.

**Type consistency:** `pager(context, page, on_each_side, on_ends)` → dict `{page,nums,base_qs,ellipsis}` konsisten dipakai `_pager.html`. `random_quote() -> str`, `MOTIVATION` list — konsisten di Task 5/6/test. Class `.content.wide`, `.cell-tr`, `.pg*`, `#motivToast` konsisten antar task.
