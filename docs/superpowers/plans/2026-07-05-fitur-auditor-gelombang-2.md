# Fitur Auditor Gelombang 2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tambah export terfilter, sorting kolom, drill-down dashboard, tren 30 hari, ringkasan per-bank, halaman antrean tinjau, dan halaman ringkasan antar-toko — semua read-only, tanpa migrasi.

**Architecture:** Semua state lewat querystring ber-whitelist. View di `web/views.py` memakai helper engine yang sudah ada; template pakai design system `app_base.html`. Dua view baru (`review_queue`, `toko_overview`) + dua template baru. Helper sort bersama `_apply_sort` dipakai lintas halaman.

**Tech Stack:** Django 5.2, SQLite (dev), openpyxl (export), htmx (review inline), tanpa dependensi baru.

## Global Constraints

- Bahasa Indonesia untuk semua UI dan komentar (konvensi repo).
- TIDAK ada migrasi skema; `reconciliation/engine.py` perilakunya tidak diubah.
- `USE_TZ = False`; datetime naif WIB. Jangan buat tz-aware.
- Uang ditampilkan `|floatformat:0|intcomma` (pemisah ribuan), angka rata kanan `class="num"`.
- Palet warna hanya dari token CSS di `app_base.html` (jangan hardcode hex).
- Semua parameter querystring di-whitelist; nilai asing jatuh diam-diam ke default (jangan 500).
- Scoping akses selalu lewat `tokos_for(request.user)`.
- Commit lokal per task; JANGAN push ke origin.
- Jalankan test: `source .venv/bin/activate && python manage.py test web`

## File Structure

- `web/views.py` — MODIFY: helper `_apply_sort`; perluas `transactions`, `run_detail`, `batch_uang`, `batch_detail`, `dashboard`; view baru `review_queue`, `toko_overview`.
- `web/urls.py` — MODIFY: rute `tinjau/`, `tokos/`.
- `web/templates/web/transactions.html` — MODIFY: filter tanggal, header sortable, tombol export, chip carry.
- `web/templates/web/run_detail.html` — MODIFY: header sortable.
- `web/templates/web/batch_uang.html` — MODIFY: header sortable.
- `web/templates/web/batch_detail.html` — MODIFY: kartu "Per Sumber Uang".
- `web/templates/web/dashboard.html` — MODIFY: kartu klikabel + tren 30 hari + garis.
- `web/templates/web/_result_row.html` — MODIFY: kolom opsional `show_run_col`.
- `web/templates/web/app_base.html` — MODIFY: menu "Ringkasan Toko", link kartu antrean.
- `web/templates/web/review_queue.html` — CREATE.
- `web/templates/web/toko_overview.html` — CREATE.
- `web/tests_tx_filters.py`, `web/tests_tx_export.py`, `web/tests_tx_carry.py`, `web/tests_run_sort.py`, `web/tests_uang_sort.py`, `web/tests_batch_perbank.py`, `web/tests_review_queue.py`, `web/tests_toko_overview.py`, `web/tests_dashboard_g2.py` — CREATE.

---

### Task 1: Helper `_apply_sort` + Transaksi (filter tanggal + sorting)

**Files:**
- Modify: `web/views.py` (fungsi `transactions`, tambah helper `_apply_sort`)
- Modify: `web/templates/web/transactions.html`
- Test: `web/tests_tx_filters.py` (create)

**Interfaces:**
- Produces: `_apply_sort(request, qs, allowed, default_order, default_active=None) -> (qs, sort_key, direction)`. `allowed` = `{ui_key: orm_field}`; `default_order` = list field ORM saat tak ada sort valid; `default_active` = tuple `(ui_key, "asc"|"desc")` untuk menandai kolom default aktif. Return `sort_key=""`, `direction=""` bila memakai `default_order`.
- Produces (context transactions): `qbase` (querystring tanpa sort/dir/page), `qpage` (tanpa page), `sort`, `dir`, `date_from`, `date_to`.

- [ ] **Step 1: Tulis test yang gagal**

```python
# web/tests_tx_filters.py
"""Transaksi: filter rentang tanggal + sorting kolom server-side (whitelist)."""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()
_seq = iter(range(1, 100000))


class TxFilterSortBase(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.bank, toko=self.lbs)
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def tx(self, amount, when, **kw):
        return Transaction.objects.create(
            upload=self.up, source_type=self.bank, toko=self.lbs, jenis="depo",
            amount=Decimal(str(amount)), money_delta=Decimal(str(amount)),
            occurred_at=when, row_hash=f"f-{next(_seq)}", **kw,
        )


class DateFilterTests(TxFilterSortBase):
    def test_date_from_membatasi(self):
        self.tx(10000, datetime(2026, 6, 20, 9, 0), counterparty="LAMA")
        self.tx(20000, datetime(2026, 6, 28, 9, 0), counterparty="BARU")
        r = self.client.get(reverse("transactions"), {"date_from": "2026-06-25"})
        self.assertContains(r, "BARU")
        self.assertNotContains(r, "LAMA")

    def test_date_to_membatasi(self):
        self.tx(10000, datetime(2026, 6, 20, 9, 0), counterparty="LAMA")
        self.tx(20000, datetime(2026, 6, 28, 9, 0), counterparty="BARU")
        r = self.client.get(reverse("transactions"), {"date_to": "2026-06-25"})
        self.assertContains(r, "LAMA")
        self.assertNotContains(r, "BARU")

    def test_tanggal_invalid_diabaikan(self):
        self.tx(10000, datetime(2026, 6, 20, 9, 0), counterparty="ADA")
        r = self.client.get(reverse("transactions"), {"date_from": "bukan-tanggal"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "ADA")


class SortTests(TxFilterSortBase):
    def setUp(self):
        super().setUp()
        self.tx(30000, datetime(2026, 6, 27, 9, 0), counterparty="TIGA")
        self.tx(10000, datetime(2026, 6, 27, 10, 0), counterparty="SATU")
        self.tx(20000, datetime(2026, 6, 27, 11, 0), counterparty="DUA")

    def _order(self, resp):
        html = resp.content.decode()
        return [n for n in ("SATU", "DUA", "TIGA") if n in html and True], html

    def test_sort_amount_asc(self):
        r = self.client.get(reverse("transactions"), {"sort": "amount", "dir": "asc"})
        html = r.content.decode()
        self.assertLess(html.index("SATU"), html.index("DUA"))
        self.assertLess(html.index("DUA"), html.index("TIGA"))

    def test_sort_amount_desc(self):
        r = self.client.get(reverse("transactions"), {"sort": "amount", "dir": "desc"})
        html = r.content.decode()
        self.assertLess(html.index("TIGA"), html.index("DUA"))
        self.assertLess(html.index("DUA"), html.index("SATU"))

    def test_default_sort_waktu_desc(self):
        r = self.client.get(reverse("transactions"))
        html = r.content.decode()
        # occurred_at terbaru dulu: DUA(11:00) > TIGA(10:00)? DUA=11, SATU=10, TIGA=9
        self.assertLess(html.index("DUA"), html.index("SATU"))
        self.assertLess(html.index("SATU"), html.index("TIGA"))

    def test_sort_asing_fallback_default(self):
        r = self.client.get(reverse("transactions"), {"sort": "rahasia"})
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertLess(html.index("DUA"), html.index("TIGA"))
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `source .venv/bin/activate && python manage.py test web.tests_tx_filters -v 2`
Expected: FAIL (filter tanggal & sort belum ada; urutan tidak sesuai).

- [ ] **Step 3: Tambah helper `_apply_sort` di `web/views.py`**

Sisipkan tepat setelah blok `REL_LABELS = {...}` (sekitar baris 42):

```python
def _apply_sort(request, qs, allowed, default_order, default_active=None):
    """Sort server-side ber-whitelist. `allowed`={ui_key: orm_field}.
    `default_order`=list field ORM saat sort tak valid. `default_active`=(ui_key,dir)
    untuk menandai kolom default aktif. Return (qs, sort_key, direction)."""
    sort = request.GET.get("sort", "")
    direction = request.GET.get("dir", "")
    if sort not in allowed:
        if default_active and default_active[0] in allowed:
            sort, direction = default_active
        else:
            return qs.order_by(*default_order), "", ""
    if direction not in ("asc", "desc"):
        direction = "asc"
    prefix = "" if direction == "asc" else "-"
    return qs.order_by(f"{prefix}{allowed[sort]}", "id"), sort, direction
```

- [ ] **Step 4: Perbarui fungsi `transactions`**

Ganti blok filter awal (baris ~245-283) mulai dari `qs = (` s/d pembuatan `page = Paginator(...)` dengan versi ini (tambah tanggal + sort + qbase/qpage; hapus `.order_by("-occurred_at")` lama karena sort helper yang mengatur):

```python
    qs = (
        Transaction.objects.filter(toko=active)
        .select_related("source_type", "account", "upload", "upload__account")
    )
    src = request.GET.get("source", "")
    jenis = request.GET.get("jenis", "")
    q = request.GET.get("q", "").strip()
    bank = request.GET.get("bank", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    if src:
        qs = qs.filter(source_type__key=src)
    if jenis:
        qs = qs.filter(jenis=jenis)
    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(ticket_no__icontains=q)
            | Q(reference__icontains=q)
            | Q(counterparty__icontains=q)
        )
    try:
        if date_from:
            qs = qs.filter(occurred_at__date__gte=date_cls.fromisoformat(date_from))
    except ValueError:
        date_from = ""
    try:
        if date_to:
            qs = qs.filter(occurred_at__date__lte=date_cls.fromisoformat(date_to))
    except ValueError:
        date_to = ""

    # Tombol filter per-bank: label diturunkan dari data upload toko ini
    bank_options = []
    if src in ("bank", "gateway"):
        ups = Upload.objects.filter(toko=active, source_type__key=src).select_related("account")
        label_by_upload = {
            u.id: specific_source_label(src, account=u.account, upload=u) for u in ups
        }
        fallback = src.capitalize()
        bank_options = sorted({lbl for lbl in label_by_upload.values() if lbl and lbl != fallback})
        if bank:
            qs = qs.filter(
                upload_id__in=[uid for uid, lbl in label_by_upload.items() if lbl == bank]
            )
    else:
        bank = ""

    qs, sort, sort_dir = _apply_sort(
        request, qs,
        allowed={
            "waktu": "occurred_at", "amount": "amount", "delta": "money_delta",
            "sumber": "source_type__key", "jenis": "jenis",
        },
        default_order=["-occurred_at", "id"],
        default_active=("waktu", "desc"),
    )

    params = request.GET.copy()
    for k in ("sort", "dir", "page"):
        params.pop(k, None)
    qbase = params.urlencode()
    params_page = request.GET.copy()
    params_page.pop("page", None)
    qpage = params_page.urlencode()

    page = Paginator(qs, 40).get_page(request.GET.get("page"))
```

Lalu tambahkan ke `ctx` (setelah `"total": page.paginator.count,`):

```python
        "date_from": date_from, "date_to": date_to,
        "sort": sort, "dir": sort_dir,
        "qbase": qbase, "qpage": qpage,
```

- [ ] **Step 5: Perbarui template `transactions.html` — filter bar + header sortable**

Di filter bar `<form method="get" class="row">`, tambahkan dua field tanggal sebelum tombol Filter (setelah field "Cari"):

```html
    <div class="field"><label>Dari tanggal</label><input type="date" name="date_from" value="{{ date_from }}"></div>
    <div class="field"><label>Sampai tanggal</label><input type="date" name="date_to" value="{{ date_to }}"></div>
```

Ganti baris `<thead>` tabel dengan header sortable (kolom sortable jadi link; simpan param lain via `qbase`):

```html
    <thead><tr>
      <th><a class="th-sort" href="?{{ qbase }}&sort=waktu&dir={% if sort == 'waktu' and dir == 'asc' %}desc{% else %}asc{% endif %}">Waktu{% if sort == 'waktu' %} {% if dir == 'asc' %}▲{% else %}▼{% endif %}{% endif %}</a></th>
      <th><a class="th-sort" href="?{{ qbase }}&sort=sumber&dir={% if sort == 'sumber' and dir == 'asc' %}desc{% else %}asc{% endif %}">Sumber{% if sort == 'sumber' %} {% if dir == 'asc' %}▲{% else %}▼{% endif %}{% endif %}</a></th>
      <th><a class="th-sort" href="?{{ qbase }}&sort=jenis&dir={% if sort == 'jenis' and dir == 'asc' %}desc{% else %}asc{% endif %}">Jenis{% if sort == 'jenis' %} {% if dir == 'asc' %}▲{% else %}▼{% endif %}{% endif %}</a></th>
      <th class="num"><a class="th-sort" href="?{{ qbase }}&sort=amount&dir={% if sort == 'amount' and dir == 'asc' %}desc{% else %}asc{% endif %}">Amount{% if sort == 'amount' %} {% if dir == 'asc' %}▲{% else %}▼{% endif %}{% endif %}</a></th>
      <th class="num"><a class="th-sort" href="?{{ qbase }}&sort=delta&dir={% if sort == 'delta' and dir == 'asc' %}desc{% else %}asc{% endif %}">Δ Uang{% if sort == 'delta' %} {% if dir == 'asc' %}▲{% else %}▼{% endif %}{% endif %}</a></th>
      <th>Ticket</th><th>Username</th><th>Nama Lengkap</th><th>Counterparty</th>
    </tr></thead>
```

Perbarui link pager (bawah) agar pakai `qpage`:

```html
{% if page.has_other_pages %}
<div class="pager">
  {% if page.has_previous %}<a class="btn sm" href="?{{ qpage }}&page={{ page.previous_page_number }}">← Sebelumnya</a>{% endif %}
  <span>Halaman {{ page.number }} / {{ page.paginator.num_pages }}</span>
  {% if page.has_next %}<a class="btn sm" href="?{{ qpage }}&page={{ page.next_page_number }}">Berikutnya →</a>{% endif %}
</div>
{% endif %}
```

Tambah style header sort di `app_base.html` (setelah blok `thead th{...}`):

```css
.th-sort{color:inherit;display:inline-flex;align-items:center;gap:3px}
.th-sort:hover{color:var(--ink)}
```

- [ ] **Step 6: Jalankan test sampai lulus**

Run: `source .venv/bin/activate && python manage.py test web.tests_tx_filters -v 2`
Expected: PASS (semua test).

Jalankan juga regresi halaman transaksi lama:
Run: `python manage.py test web.tests_transactions_page`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/views.py web/templates/web/transactions.html web/templates/web/app_base.html web/tests_tx_filters.py
git commit -m "feat(web): filter tanggal + sorting kolom server-side di Transaksi

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Export Excel terfilter di Transaksi

**Files:**
- Modify: `web/views.py` (fungsi `transactions` — cabang `export`), konstanta `TX_EXPORT_LIMIT`
- Modify: `web/templates/web/transactions.html` (tombol Export di page-head)
- Test: `web/tests_tx_export.py` (create)

**Interfaces:**
- Consumes: queryset terfilter+tersortir dari Task 1 (variabel `qs` sebelum paginasi).
- Produces: konstanta modul `TX_EXPORT_LIMIT = 100_000` (bisa dipatch test).

- [ ] **Step 1: Tulis test yang gagal**

```python
# web/tests_tx_export.py
"""Export Excel Transaksi mengikuti filter aktif + guard batas baris."""
from datetime import datetime
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()
_seq = iter(range(1, 100000))


class TxExportTests(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.bank, toko=self.lbs)
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def tx(self, amount, **kw):
        return Transaction.objects.create(
            upload=self.up, source_type=self.bank, toko=self.lbs, jenis="depo",
            amount=Decimal(str(amount)), money_delta=Decimal(str(amount)),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash=f"e-{next(_seq)}", **kw,
        )

    def _wb(self, resp):
        return load_workbook(BytesIO(resp.content))

    def test_export_menghormati_filter_q(self):
        self.tx(10000, counterparty="ANDI")
        self.tx(20000, counterparty="BUDI")
        r = self.client.get(reverse("transactions"), {"export": "1", "q": "ANDI"})
        self.assertEqual(
            r["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        ws = self._wb(r).active
        vals = [c[0] for c in ws.iter_rows(min_row=2, values_only=True)]  # kolom pertama
        body = list(ws.iter_rows(min_row=2, values_only=True))
        joined = "\n".join(str(row) for row in body)
        self.assertIn("ANDI", joined)
        self.assertNotIn("BUDI", joined)

    def test_header_kolom_benar(self):
        self.tx(10000, counterparty=" X")
        r = self.client.get(reverse("transactions"), {"export": "1"})
        ws = self._wb(r).active
        header = [c.value for c in ws[1]]
        self.assertEqual(
            header,
            ["Waktu", "Sumber", "Jenis", "Amount", "Δ Uang", "Ticket",
             "Username", "Nama Lengkap", "Counterparty"],
        )

    def test_export_kosong_hanya_header(self):
        r = self.client.get(reverse("transactions"), {"export": "1", "q": "TIDAKADA"})
        ws = self._wb(r).active
        self.assertEqual(ws.max_row, 1)

    def test_guard_batas_baris(self):
        from web import views
        self.tx(10000, counterparty="A")
        self.tx(20000, counterparty="B")
        orig = views.TX_EXPORT_LIMIT
        views.TX_EXPORT_LIMIT = 1
        try:
            r = self.client.get(reverse("transactions"), {"export": "1"}, follow=True)
        finally:
            views.TX_EXPORT_LIMIT = orig
        self.assertContains(r, "persempit")  # pesan minta persempit filter
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `source .venv/bin/activate && python manage.py test web.tests_tx_export -v 2`
Expected: FAIL (cabang export belum ada).

- [ ] **Step 3: Tambah konstanta + cabang export di `transactions`**

Di dekat atas `web/views.py` (setelah `BUCKET_META`), tambah:

```python
TX_EXPORT_LIMIT = 100_000
```

Di fungsi `transactions`, sisipkan cabang export SETELAH `qs, sort, sort_dir = _apply_sort(...)` dan SEBELUM blok `params = request.GET.copy()`:

```python
    if request.GET.get("export"):
        n = qs.count()
        if n > TX_EXPORT_LIMIT:
            messages.error(
                request,
                f"{n:,} baris terlalu banyak untuk diekspor — persempit filter dulu "
                f"(maks {TX_EXPORT_LIMIT:,}).",
            )
            # buang param export agar redirect tidak memicu export lagi (loop)
            redir = request.GET.copy()
            redir.pop("export", None)
            return redirect(f"{reverse('transactions')}?{redir.urlencode()}")
        return _export_transactions(qs, active)
```

Tambah fungsi helper export di bawah `transactions` (memakai matched_panel seperti tabel: ambil pasangan panel untuk baris money):

```python
def _export_transactions(qs, active):
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Font

    rows = list(qs)
    money_ids = [t.id for t in rows if t.source_type.key in ("bank", "gateway")]
    best = {}
    if money_ids:
        results = (
            MatchResult.objects.filter(right_id__in=money_ids, left__isnull=False)
            .exclude(bucket=MatchResult.Bucket.TIDAK)
            .select_related("left")
        )
        for r in results:
            rank = (r.bucket == MatchResult.Bucket.COCOK, r.score or 0, r.run_id, r.id)
            if r.right_id not in best or rank > best[r.right_id][0]:
                best[r.right_id] = (rank, r.left)

    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Transaksi")
    bold = Font(bold=True)
    from openpyxl.cell import WriteOnlyCell

    def hcell(v):
        c = WriteOnlyCell(ws, value=v)
        c.font = bold
        return c

    ws.append([hcell(h) for h in [
        "Waktu", "Sumber", "Jenis", "Amount", "Δ Uang", "Ticket",
        "Username", "Nama Lengkap", "Counterparty",
    ]])
    for t in rows:
        mp = best.get(t.id, (None, None))[1]
        is_money = t.source_type.key in ("bank", "gateway")
        ticket = t.ticket_no or (f"≈ {mp.ticket_no}" if mp and mp.ticket_no else "")
        username = t.username or (f"≈ {mp.username}" if mp and mp.username else "")
        nama = ""
        if is_money:
            nama = f"≈ {mp.counterparty}" if mp and mp.counterparty else ""
        else:
            nama = t.counterparty or ""
        ws.append([
            t.occurred_at.strftime("%d/%m/%Y %H:%M") if t.occurred_at else "",
            t.source_label,
            t.get_jenis_display(),
            float(t.amount),
            float(t.money_delta),
            ticket, username, nama, t.counterparty or "",
        ])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    from datetime import datetime as _dt

    resp = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    fname = f"transaksi_{active.name}_{_dt.now():%Y%m%d-%H%M}.xlsx"
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp
```

Catatan: `t.source_label` dan `t.get_jenis_display()` sudah dipakai template transaksi — properti/metode ada di model `Transaction`.

- [ ] **Step 4: Tambah tombol Export di page-head `transactions.html`**

Ubah `page-head` menjadi (tambah `actions` berisi tombol Export yang membawa filter aktif via `qpage`):

```html
<div class="page-head reveal">
  <div>
    <h1>Transaksi</h1>
    <p>{{ total|intcomma }} baris kanonik untuk <b>{{ active_toko.name }}</b>.</p>
  </div>
  <div class="actions">
    <a class="btn" href="?{{ qpage }}&export=1">⬇ Export Excel</a>
  </div>
</div>
```

- [ ] **Step 5: Jalankan test sampai lulus**

Run: `source .venv/bin/activate && python manage.py test web.tests_tx_export -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/views.py web/templates/web/transactions.html web/tests_tx_export.py
git commit -m "feat(web): export Excel Transaksi mengikuti filter aktif + guard batas baris

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Filter carry-over di Transaksi + drill-down kartu settlement

**Files:**
- Modify: `web/views.py` (fungsi `transactions` — cabang `carry`)
- Modify: `web/templates/web/transactions.html` (chip filter carry)
- Modify: `web/templates/web/dashboard.html` (kartu "Menunggu settlement" jadi link)
- Test: `web/tests_tx_carry.py` (create)

**Interfaces:**
- Consumes: `_carried_results(toko)` dari `reconciliation.engine` (dict `left_id -> MatchResult`).

- [ ] **Step 1: Tulis test yang gagal**

```python
# web/tests_tx_carry.py
"""Transaksi ?carry=1: hanya baris kredit yang menunggu settlement."""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()
_seq = iter(range(1, 100000))


class TxCarryTests(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)
        self.batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        self.run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=self.batch
        )
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def tx(self, **kw):
        d = dict(
            upload=self.up, source_type=self.panel, toko=self.lbs, jenis="depo",
            amount=Decimal("50000"), money_delta=Decimal("50000"),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash=f"c-{next(_seq)}",
        )
        d.update(kw)
        return Transaction.objects.create(**d)

    def test_carry_hanya_baris_menunggu(self):
        waiting = self.tx(username="MENUNGGU", consumed_by_batch=None)
        other = self.tx(username="BIASA")
        # hasil no_money AKTIF (menunggu settlement) untuk `waiting`
        MatchResult.objects.create(
            run=self.run, bucket=MatchResult.Bucket.TIDAK,
            reason_code="no_money", left=waiting,
        )
        r = self.client.get(reverse("transactions"), {"carry": "1"})
        self.assertContains(r, "MENUNGGU")
        self.assertNotContains(r, "BIASA")

    def test_carry_kosong_tetap_200(self):
        self.tx(username="BIASA")
        r = self.client.get(reverse("transactions"), {"carry": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "BIASA")

    def test_dashboard_kartu_settlement_link_carry(self):
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "carry=1")
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `source .venv/bin/activate && python manage.py test web.tests_tx_carry -v 2`
Expected: FAIL.

- [ ] **Step 3: Tambah cabang carry di `transactions`**

Di fungsi `transactions`, setelah blok filter `q` dan sebelum filter tanggal, tambah:

```python
    carry = request.GET.get("carry") == "1"
    if carry:
        from reconciliation.engine import _carried_results

        qs = qs.filter(id__in=list(_carried_results(active).keys()))
```

Tambahkan `"carry": carry,` ke `ctx`.

- [ ] **Step 4: Chip filter carry di `transactions.html`**

Tepat setelah `<div class="card reveal" style="margin-bottom:18px">` pembuka (di atas form filter), tambah banner chip bila carry aktif:

```html
  {% if carry %}
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
    <span class="badge warn">Menunggu settlement</span>
    <a class="btn sm ghost" href="{% url 'transactions' %}">✕ hapus filter</a>
  </div>
  {% endif %}
```

- [ ] **Step 5: Kartu settlement dashboard jadi link**

Di `dashboard.html`, bungkus kartu "Menunggu settlement". Ganti blok `<div class="card stat">` untuk kartu itu menjadi anchor:

```html
  <a class="card stat click" href="{% url 'transactions' %}?carry=1">
    <div class="top"><span class="k">Menunggu settlement</span>
      <span class="ic a"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg></span></div>
    <div class="v {% if pending %}a{% endif %}">{{ pending|intcomma }}</div>
    <div class="sub">kredit menunggu uang tiba di run berikutnya</div>
  </a>
```

(pastikan `</div>` penutup kartu lama diganti `</a>`).

- [ ] **Step 6: Jalankan test sampai lulus**

Run: `source .venv/bin/activate && python manage.py test web.tests_tx_carry -v 2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/views.py web/templates/web/transactions.html web/templates/web/dashboard.html web/tests_tx_carry.py
git commit -m "feat(web): filter carry-over di Transaksi + kartu settlement dashboard klikabel

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Sorting di Run detail

**Files:**
- Modify: `web/views.py` (fungsi `run_detail`)
- Modify: `web/templates/web/run_detail.html`
- Test: `web/tests_run_sort.py` (create)

**Interfaces:**
- Consumes: `_apply_sort` (Task 1).

- [ ] **Step 1: Tulis test yang gagal**

```python
# web/tests_run_sort.py
"""Run detail: sorting kolom amount/skor/waktu (whitelist), default bucket,-score."""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()
_seq = iter(range(1, 100000))


class RunSortTests(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)
        self.batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        self.run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=self.batch
        )
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def _res(self, amount, ticket):
        left = Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=self.lbs, jenis="depo",
            amount=Decimal(str(amount)), occurred_at=datetime(2026, 6, 27, 10, 0),
            ticket_no=ticket, row_hash=f"r-{next(_seq)}", raw={},
        )
        return MatchResult.objects.create(
            run=self.run, bucket=MatchResult.Bucket.COCOK, reason_code="ticket", left=left,
        )

    def test_sort_amount_asc(self):
        self._res(30000, "D30")
        self._res(10000, "D10")
        self._res(20000, "D20")
        r = self.client.get(reverse("run_detail", args=[self.run.pk]), {"sort": "amount", "dir": "asc"})
        html = r.content.decode()
        self.assertLess(html.index("D10"), html.index("D20"))
        self.assertLess(html.index("D20"), html.index("D30"))

    def test_sort_asing_fallback(self):
        self._res(10000, "D10")
        r = self.client.get(reverse("run_detail", args=[self.run.pk]), {"sort": "xxx"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "D10")
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `source .venv/bin/activate && python manage.py test web.tests_run_sort -v 2`
Expected: FAIL.

- [ ] **Step 3: Perbarui `run_detail`**

Ganti baris `qs = MatchResult.objects.filter(run=run)...order_by("bucket", "-score")` dan blok setelahnya sampai `page = ...` menjadi:

```python
    qs = MatchResult.objects.filter(run=run).select_related("left", "right")
    bucket = request.GET.get("bucket", "")
    if bucket:
        qs = qs.filter(bucket=bucket)
    reasons = list(
        qs.values("reason_code").annotate(n=Count("id")).order_by("-n")
    )
    reason = request.GET.get("reason", "")
    if reason:
        qs = qs.filter(reason_code=reason)
    qs, sort, sort_dir = _apply_sort(
        request, qs,
        allowed={"amount": "left__amount", "skor": "score", "waktu": "left__occurred_at"},
        default_order=["bucket", "-score", "id"],
    )
    params = request.GET.copy()
    for k in ("sort", "dir", "page"):
        params.pop(k, None)
    qbase = params.urlencode()
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
```

Tambahkan ke `ctx`: `"sort": sort, "dir": sort_dir, "qbase": qbase,`.

- [ ] **Step 4: Header sortable di `run_detail.html`**

Ganti tiga `<th>` yang relevan (Amount kiri, Amount kanan tidak di-sort; kolom "Alasan" untuk skor). Ubah header `<th class="num">Amount</th>` (kolom kiri, ke-9) menjadi link amount, dan kolom "Alasan" tetap; tambahkan sort skor di header Alasan. Ganti seluruh `<thead>`:

```html
    <thead><tr><th style="width:28px"></th><th>Status</th><th>{{ left_label }}</th><th>User ID</th><th>Full Name</th><th>Player Bank</th><th>Bank Title</th><th>Handler</th>
      <th class="num"><a class="th-sort" href="?bucket={{ bucket }}&reason={{ reason }}&sort=amount&dir={% if sort == 'amount' and dir == 'asc' %}desc{% else %}asc{% endif %}">Amount{% if sort == 'amount' %} {% if dir == 'asc' %}▲{% else %}▼{% endif %}{% endif %}</a></th>
      <th>{{ right_label }}</th><th class="num">Amount</th>
      <th><a class="th-sort" href="?bucket={{ bucket }}&reason={{ reason }}&sort=skor&dir={% if sort == 'skor' and dir == 'asc' %}desc{% else %}asc{% endif %}">Alasan{% if sort == 'skor' %} {% if dir == 'asc' %}▲{% else %}▼{% endif %}{% endif %}</a></th>
      <th style="text-align:center">Aksi</th></tr></thead>
```

Perbarui link pager di `run_detail.html` agar menyertakan sort:

```html
  {% if page.has_previous %}<a class="btn sm" href="?bucket={{ bucket }}&reason={{ reason }}&sort={{ sort }}&dir={{ dir }}&page={{ page.previous_page_number }}">← Sebelumnya</a>{% endif %}
```
```html
  {% if page.has_next %}<a class="btn sm" href="?bucket={{ bucket }}&reason={{ reason }}&sort={{ sort }}&dir={{ dir }}&page={{ page.next_page_number }}">Berikutnya →</a>{% endif %}
```

- [ ] **Step 5: Jalankan test sampai lulus**

Run: `source .venv/bin/activate && python manage.py test web.tests_run_sort web.tests_run_columns -v 2`
Expected: PASS (test baru + regresi kolom run).

- [ ] **Step 6: Commit**

```bash
git add web/views.py web/templates/web/run_detail.html web/tests_run_sort.py
git commit -m "feat(web): sorting kolom amount/skor/waktu di Run detail

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Sorting di Uang Tanpa Pasangan

**Files:**
- Modify: `web/views.py` (fungsi `batch_uang`)
- Modify: `web/templates/web/batch_uang.html`
- Test: `web/tests_uang_sort.py` (create)

**Interfaces:**
- Consumes: list `rows` (Transaction) yang sudah diklasifikasi kategori a/b/c/d.

- [ ] **Step 1: Tulis test yang gagal**

```python
# web/tests_uang_sort.py
"""Uang tanpa pasangan: sorting tanggal (default asc) & nominal (abs)."""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()
_seq = iter(range(1, 100000))


class UangSortTests(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.bank, toko=self.lbs)
        self.batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def money(self, delta, when, cp):
        return Transaction.objects.create(
            upload=self.up, source_type=self.bank, toko=self.lbs, jenis="depo",
            amount=Decimal(str(abs(delta))), money_delta=Decimal(str(delta)),
            occurred_at=when, counterparty=cp, consumed_by_batch=self.batch,
            row_hash=f"u-{next(_seq)}", raw={},
        )

    def test_sort_nominal_desc(self):
        self.money(10000, datetime(2026, 6, 27, 9, 0), "KECIL")
        self.money(90000, datetime(2026, 6, 27, 10, 0), "BESAR")
        r = self.client.get(reverse("batch_uang", args=[self.batch.pk]), {"sort": "nominal", "dir": "desc"})
        html = r.content.decode()
        self.assertLess(html.index("BESAR"), html.index("KECIL"))

    def test_default_sort_tanggal_asc(self):
        self.money(10000, datetime(2026, 6, 27, 8, 0), "PAGI")
        self.money(20000, datetime(2026, 6, 27, 20, 0), "MALAM")
        r = self.client.get(reverse("batch_uang", args=[self.batch.pk]))
        html = r.content.decode()
        self.assertLess(html.index("PAGI"), html.index("MALAM"))

    def test_sort_asing_fallback(self):
        self.money(10000, datetime(2026, 6, 27, 8, 0), "ADA")
        r = self.client.get(reverse("batch_uang", args=[self.batch.pk]), {"sort": "zzz"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "ADA")
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `source .venv/bin/activate && python manage.py test web.tests_uang_sort -v 2`
Expected: FAIL.

- [ ] **Step 3: Sorting list di `batch_uang`**

Setelah blok yang memfilter `rows` per kategori (`if kat in KATEGORI_UANG:`) dan SEBELUM cabang export, tambahkan sort in-memory:

```python
    sort = request.GET.get("sort", "")
    sort_dir = request.GET.get("dir", "")
    if sort == "nominal":
        rows.sort(key=lambda t: abs(float(t.money_delta)), reverse=(sort_dir == "desc"))
    elif sort == "tanggal":
        rows.sort(key=lambda t: (t.occurred_at or datetime.min), reverse=(sort_dir == "desc"))
    else:
        sort, sort_dir = "tanggal", "asc"  # default: tanggal naik
        rows.sort(key=lambda t: (t.occurred_at or datetime.min))
```

Pastikan import `datetime` tersedia di fungsi. Tambah di atas fungsi `batch_uang` blok import: gunakan `from datetime import datetime` (fungsi ini sudah punya import lokal; tambahkan bila belum). Tambahkan `"sort": sort, "dir": sort_dir,` ke context `render`.

- [ ] **Step 4: Header sortable di `batch_uang.html`**

Ganti `<thead>`:

```html
    <thead>
      <tr><th>Kat</th>
        <th><a class="th-sort" href="?k={{ kat }}&sort=tanggal&dir={% if sort == 'tanggal' and dir == 'asc' %}desc{% else %}asc{% endif %}">Tanggal{% if sort == 'tanggal' %} {% if dir == 'asc' %}▲{% else %}▼{% endif %}{% endif %}</a></th>
        <th>Sumber</th><th>File/Rekening</th><th>Ticket</th><th>Username</th><th>Pengirim/Penerima</th>
        <th class="num"><a class="th-sort" href="?k={{ kat }}&sort=nominal&dir={% if sort == 'nominal' and dir == 'asc' %}desc{% else %}asc{% endif %}">Nominal{% if sort == 'nominal' %} {% if dir == 'asc' %}▲{% else %}▼{% endif %}{% endif %}</a></th></tr>
    </thead>
```

Perbarui link pager `batch_uang.html` agar bawa sort:

```html
  {% if page.has_previous %}<a class="btn sm" href="?k={{ kat }}&sort={{ sort }}&dir={{ dir }}&page={{ page.previous_page_number }}">← Sebelumnya</a>{% endif %}
```
```html
  {% if page.has_next %}<a class="btn sm" href="?k={{ kat }}&sort={{ sort }}&dir={{ dir }}&page={{ page.next_page_number }}">Berikutnya →</a>{% endif %}
```

- [ ] **Step 5: Jalankan test sampai lulus**

Run: `source .venv/bin/activate && python manage.py test web.tests_uang_sort web.tests_uang -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/views.py web/templates/web/batch_uang.html web/tests_uang_sort.py
git commit -m "feat(web): sorting tanggal/nominal di Uang Tanpa Pasangan

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Ringkasan per sumber uang di Batch detail

**Files:**
- Modify: `web/views.py` (fungsi `batch_detail`)
- Modify: `web/templates/web/batch_detail.html`
- Test: `web/tests_batch_perbank.py` (create)

**Interfaces:**
- Produces (context): `per_bank` = list dict `{label, n, dp, wd, paired, unpaired}`.

- [ ] **Step 1: Tulis test yang gagal**

```python
# web/tests_batch_perbank.py
"""Batch detail: ringkasan per sumber uang (n, dp, wd, berpasangan/tidak)."""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()
_seq = iter(range(1, 100000))


class BatchPerBankTests(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        self.run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=self.batch
        )
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def money(self, up, delta, cp, paired=False):
        t = Transaction.objects.create(
            upload=up, source_type=self.bank, toko=self.lbs, jenis="depo",
            amount=Decimal(str(abs(delta))), money_delta=Decimal(str(delta)),
            occurred_at=datetime(2026, 6, 27, 10, 0), counterparty=cp,
            consumed_by_batch=self.batch, row_hash=f"b-{next(_seq)}", raw={},
        )
        if paired:
            left = Transaction.objects.create(
                upload=up, source_type=self.panel, toko=self.lbs, jenis="depo",
                amount=Decimal(str(abs(delta))), occurred_at=datetime(2026, 6, 27, 10, 0),
                ticket_no=f"D{next(_seq)}", row_hash=f"bp-{next(_seq)}", raw={},
            )
            MatchResult.objects.create(
                run=self.run, bucket=MatchResult.Bucket.COCOK, reason_code="ticket",
                left=left, right=t,
            )
        return t

    def test_ringkasan_per_bank_muncul(self):
        up_bca = Upload.objects.create(
            source_type=self.bank, toko=self.lbs, original_name="27_JUNI_2026_WD_BCA_HENDI.pdf"
        )
        up_bri = Upload.objects.create(
            source_type=self.bank, toko=self.lbs, original_name="27 JUN 2026 DP BRI MARGANI.csv"
        )
        self.money(up_bca, 50000, "HENDI", paired=True)
        self.money(up_bca, 30000, "HENDI2", paired=False)
        self.money(up_bri, 20000, "MARGANI", paired=True)
        r = self.client.get(reverse("batch_detail", args=[self.batch.pk]))
        self.assertContains(r, "Per Sumber Uang")
        self.assertContains(r, "BCA")
        self.assertContains(r, "BRI")
        # BCA: 2 transaksi, 1 berpasangan, 1 tanpa pasangan
        per_bank = {row["label"]: row for row in r.context["per_bank"]}
        self.assertEqual(per_bank["BCA"]["n"], 2)
        self.assertEqual(per_bank["BCA"]["paired"], 1)
        self.assertEqual(per_bank["BCA"]["unpaired"], 1)
        self.assertEqual(per_bank["BRI"]["n"], 1)

    def test_batch_tanpa_uang_tanpa_kartu(self):
        r = self.client.get(reverse("batch_detail", args=[self.batch.pk]))
        self.assertNotContains(r, "Per Sumber Uang")
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `source .venv/bin/activate && python manage.py test web.tests_batch_perbank -v 2`
Expected: FAIL.

- [ ] **Step 3: Hitung `per_bank` di `batch_detail`**

Di fungsi `batch_detail`, sebelum `return render(...)`, tambah:

```python
    from django.db.models import Exists, OuterRef

    from transactions.models import specific_source_label

    paired_q = MatchResult.objects.filter(left__isnull=False, right_id=OuterRef("id"))
    money_rows = (
        Transaction.objects.filter(
            consumed_by_batch=batch, source_type__key__in=["bank", "gateway"]
        )
        .exclude(jenis="admin")
        .annotate(berpasangan=Exists(paired_q))
        .select_related("source_type", "upload", "upload__account")
    )
    agg = {}
    for t in money_rows:
        label = specific_source_label(
            t.source_type.key, account=t.upload.account if t.upload else None,
            upload=t.upload,
        )
        row = agg.setdefault(
            label, {"label": label, "n": 0, "dp": 0.0, "wd": 0.0, "paired": 0, "unpaired": 0}
        )
        row["n"] += 1
        md = float(t.money_delta)
        if md > 0:
            row["dp"] += md
        elif md < 0:
            row["wd"] += -md
        if t.berpasangan:
            row["paired"] += 1
        else:
            row["unpaired"] += 1
    per_bank = sorted(agg.values(), key=lambda r: r["label"])
```

Tambahkan `"per_bank": per_bank,` ke dict `render`.

- [ ] **Step 4: Kartu "Per Sumber Uang" di `batch_detail.html`**

Sisipkan setelah blok kartu DP/WD (`<div class="grid cols-2">...</div>` yang berisi Deposit & Withdraw), sebelum blok `{% if s.unmatched_money %}`:

```html
{% if per_bank %}
<div class="card pad0 reveal" style="margin-top:16px">
  <div class="card-head"><h3>Per Sumber Uang</h3><span class="sub">{{ per_bank|length }} sumber</span></div>
  <div class="twrap" style="border:none">
  <table>
    <thead><tr><th>Sumber</th><th class="num">Transaksi</th><th class="num">DP masuk</th><th class="num">WD keluar</th><th class="num">Berpasangan</th><th class="num">Tanpa pasangan</th></tr></thead>
    <tbody>
    {% for b in per_bank %}
      <tr>
        <td><span class="badge src plain">{{ b.label }}</span></td>
        <td class="num mono">{{ b.n|intcomma }}</td>
        <td class="num mono">{{ b.dp|floatformat:0|intcomma }}</td>
        <td class="num mono">{{ b.wd|floatformat:0|intcomma }}</td>
        <td class="num mono" style="color:var(--ok)">{{ b.paired|intcomma }}</td>
        <td class="num mono">{% if b.unpaired %}<a href="{% url 'batch_uang' batch.pk %}">{{ b.unpaired|intcomma }}</a>{% else %}0{% endif %}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  </div>
</div>
{% endif %}
```

- [ ] **Step 5: Jalankan test sampai lulus**

Run: `source .venv/bin/activate && python manage.py test web.tests_batch_perbank web.tests_consume_ui -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/views.py web/templates/web/batch_detail.html web/tests_batch_perbank.py
git commit -m "feat(web): ringkasan per sumber uang di Batch detail

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Halaman Antrean Tinjau `/tinjau/`

**Files:**
- Modify: `web/urls.py`
- Modify: `web/views.py` (view `review_queue`; view `review` teruskan flag kolom)
- Create: `web/templates/web/review_queue.html`
- Modify: `web/templates/web/_result_row.html` (kolom opsional `show_run_col`)
- Modify: `web/templates/web/app_base.html` (badge menu & kartu antrean menaut `/tinjau/`)
- Modify: `web/templates/web/dashboard.html` (kartu "Antrean tinjau" → `/tinjau/`)
- Test: `web/tests_review_queue.py` (create)

**Interfaces:**
- Consumes: endpoint `review` (POST htmx) yang sudah ada.
- Produces: url name `review_queue` → `/tinjau/`.
- `_result_row.html` menerima `show_run_col` (bool) dari context; bila True render kolom "Batch/Run" berisi `r.home_no`/link run.

- [ ] **Step 1: Tulis test yang gagal**

```python
# web/tests_review_queue.py
"""Halaman /tinjau/: antrean perlu_tinjau lintas run untuk toko aktif, dengan RBAC."""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()
_seq = iter(range(1, 100000))


class ReviewQueueTests(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def _tinjau(self, toko, ticket):
        up = Upload.objects.create(source_type=self.panel, toko=toko)
        batch = ReconBatch.objects.create(toko=toko, tolerance=self.tol)
        run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=batch
        )
        left = Transaction.objects.create(
            upload=up, source_type=self.panel, toko=toko, jenis="depo",
            amount=Decimal("50000"), occurred_at=datetime(2026, 6, 27, 10, 0),
            ticket_no=ticket, row_hash=f"q-{next(_seq)}", raw={},
        )
        return MatchResult.objects.create(
            run=run, bucket=MatchResult.Bucket.TINJAU, reason_code="amount_mismatch", left=left,
        )

    def test_hanya_bucket_tinjau_toko_aktif(self):
        self._tinjau(self.lbs, "D-LBS")
        self._tinjau(self.slo, "D-SLO")
        r = self.client.get(reverse("review_queue"))
        self.assertContains(r, "D-LBS")
        self.assertNotContains(r, "D-SLO")

    def test_kosong_empty_state(self):
        r = self.client.get(reverse("review_queue"))
        self.assertContains(r, "Antrean kosong")

    def test_rbac_auditor_toko_lain(self):
        User.objects.create_user("a2", "a2@a.co", "pw12345", role="auditor")
        u = User.objects.get(username="a2")
        u.allowed_tokos.set([self.slo])
        self._tinjau(self.lbs, "D-LBS")
        self.client.logout()
        self.client.login(username="a2", password="pw12345")
        self.client.post(reverse("set_toko"), {"toko_id": self.slo.id})
        r = self.client.get(reverse("review_queue"))
        self.assertNotContains(r, "D-LBS")

    def test_aksi_review_dari_antrean(self):
        res = self._tinjau(self.lbs, "D-LBS")
        r = self.client.post(
            reverse("review", args=[res.pk]),
            {"action": "mark_matched", "show_run_col": "1"},
        )
        self.assertEqual(r.status_code, 200)
        res.refresh_from_db()
        self.assertEqual(res.bucket, MatchResult.Bucket.COCOK)
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `source .venv/bin/activate && python manage.py test web.tests_review_queue -v 2`
Expected: FAIL (rute belum ada).

- [ ] **Step 3: Tambah rute**

Di `web/urls.py`, tambah sebelum rute `kelola/`:

```python
    path("tinjau/", views.review_queue, name="review_queue"),
```

- [ ] **Step 4: View `review_queue` + flag di `review`**

Tambah view baru di `web/views.py` (setelah `run_detail`):

```python
@login_required
def review_queue(request):
    """Antrean semua hasil perlu-tinjau toko aktif, lintas batch/run."""
    active = _active_toko(request)
    if active is None:
        return render(request, "web/no_toko.html")
    qs = (
        MatchResult.objects.filter(
            run__batch__toko=active, bucket=MatchResult.Bucket.TINJAU
        )
        .select_related("left", "right", "run", "run__batch")
        .order_by("-run__batch__recon_date", "-score", "id")
    )
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    # nomor batch per-toko untuk tiap hasil di halaman ini
    for r in page.object_list:
        b = r.run.batch
        r.home_no = (
            ReconBatch.objects.filter(toko=active, id__lte=b.id).count() if b else None
        )
        left_lbl, right_lbl = REL_LABELS.get(r.run.relation, ("Kiri", "Kanan"))
        r.left_label, r.right_label = left_lbl, right_lbl
    return render(request, "web/review_queue.html", {
        "page": page, "active_toko": active,
    })
```

Perbarui view `review` agar baris pengganti htmx tahu apakah menampilkan kolom run. Ganti baris `return render(request, "web/_result_row.html", {"r": r, "bucket_meta": BUCKET_META})` menjadi:

```python
    show_run_col = request.POST.get("show_run_col") == "1"
    if show_run_col:
        b = r.run.batch
        r.home_no = (
            ReconBatch.objects.filter(toko=r.run.batch.toko, id__lte=b.id).count() if b else None
        )
    return render(request, "web/_result_row.html", {
        "r": r, "bucket_meta": BUCKET_META, "show_run_col": show_run_col,
    })
```

- [ ] **Step 5: Kolom opsional di `_result_row.html`**

Di `_result_row.html`, sebelum `<td>` Aksi terakhir (`<td>\n    <div style="display:flex;gap:6px;...`), sisipkan kolom run bila diminta:

```html
  {% if show_run_col %}<td style="font-size:12px"><a class="grad-text" style="font-weight:600" href="{% url 'run_detail' r.run_id %}">#{{ r.home_no }}</a><div class="faint">{{ r.run.get_relation_display }}</div></td>{% endif %}
```

Pada dua tombol htmx di baris itu, tambahkan `show_run_col` ke `hx-vals` agar swap balik memuat kolom yang sama. Ubah `hx-vals` kedua tombol:

```html
hx-vals='{"action":"mark_matched","show_run_col":"{% if show_run_col %}1{% else %}0{% endif %}"}'
```
```html
hx-vals='{"action":"mark_review","show_run_col":"{% if show_run_col %}1{% else %}0{% endif %}"}'
```

- [ ] **Step 6: Template `review_queue.html`**

```html
{% extends "web/app_base.html" %}
{% load humanize %}
{% block title %}Antrean Tinjau · Truth of Auditor{% endblock %}
{% block crumb %}Rekonsiliasi · Antrean Tinjau{% endblock %}
{% block content %}
<div class="page-head reveal">
  <div>
    <h1>Antrean Tinjau</h1>
    <p>Semua hasil perlu ditinjau untuk <b>{{ active_toko.name }}</b> — lintas batch, satu tempat.</p>
  </div>
</div>

<form id="bulk-form">{% csrf_token %}</form>
<div class="card pad0 reveal">
  <div class="table-wrap tall" style="border:none">
  <table>
    <thead><tr><th style="width:28px"></th><th>Status</th><th>Panel</th><th>User ID</th><th>Full Name</th><th>Player Bank</th><th>Bank Title</th><th>Handler</th><th class="num">Amount</th><th>Bank/Gateway</th><th class="num">Amount</th><th>Alasan</th><th>Batch/Run</th><th style="text-align:center">Aksi</th></tr></thead>
    <tbody>
    {% for r in page %}{% include "web/_result_row.html" with show_run_col=1 %}{% empty %}
      <tr><td colspan="14" class="cell-empty">Antrean kosong — semua hasil sudah ditinjau. ✓</td></tr>{% endfor %}
    </tbody>
  </table>
  </div>
</div>

{% if page.has_other_pages %}
<div class="pager">
  {% if page.has_previous %}<a class="btn sm" href="?page={{ page.previous_page_number }}">← Sebelumnya</a>{% endif %}
  <span>Halaman {{ page.number }} / {{ page.paginator.num_pages }}</span>
  {% if page.has_next %}<a class="btn sm" href="?page={{ page.next_page_number }}">Berikutnya →</a>{% endif %}
</div>
{% endif %}
{% endblock %}
```

Catatan: `_result_row.html` memakai checkbox `form="bulk-form"`; form kosong `bulk-form` disediakan agar tidak yatim (tanpa bulk action di gelombang ini).

- [ ] **Step 7: Kartu & badge menaut `/tinjau/`**

Di `dashboard.html`, jadikan kartu "Antrean tinjau" anchor ke `/tinjau/`. Ganti blok `<div class="card stat">` kartu itu:

```html
  <a class="card stat click" href="{% url 'review_queue' %}">
    <div class="top"><span class="k">Antrean tinjau</span>
      <span class="ic {% if pending_review_count %}a{% else %}g{% endif %}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg></span></div>
    <div class="v {% if pending_review_count %}a{% else %}g{% endif %}">{{ pending_review_count|intcomma }}</div>
    <div class="sub">hasil perlu mata manusia</div>
  </a>
```

Di `app_base.html`, jadikan badge angka di menu Rekonsiliasi menaut `/tinjau/`. Cari `{% if pending_review_count %}<span class="cnt ...">{{ pending_review_count }}</span>{% endif %}` di dalam `<a class="link ..." href="{% url 'reconcile' %}">`. Biarkan link Rekonsiliasi apa adanya, tetapi tambahkan sub-link "Antrean" di seksi Menu setelah item Rekonsiliasi:

```html
  {% if pending_review_count %}
  <a class="link {% if '/tinjau' in p %}active{% endif %}" href="{% url 'review_queue' %}" style="padding-left:38px;font-size:12.5px">
    Antrean tinjau <span class="cnt {% if pending_review_count > 200 %}hot{% endif %}">{{ pending_review_count }}</span></a>
  {% endif %}
```

- [ ] **Step 8: Jalankan test sampai lulus**

Run: `source .venv/bin/activate && python manage.py test web.tests_review_queue web.tests_run_columns web.tests_bulk_review -v 2`
Expected: PASS (antrean + regresi baris hasil + bulk review lama).

- [ ] **Step 9: Commit**

```bash
git add web/urls.py web/views.py web/templates/web/review_queue.html web/templates/web/_result_row.html web/templates/web/app_base.html web/templates/web/dashboard.html web/tests_review_queue.py
git commit -m "feat(web): halaman Antrean Tinjau /tinjau/ lintas batch + drill-down kartu/badge

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Halaman Ringkasan Toko `/tokos/`

**Files:**
- Modify: `web/urls.py`
- Modify: `web/views.py` (view `toko_overview`)
- Create: `web/templates/web/toko_overview.html`
- Modify: `web/templates/web/app_base.html` (menu "Ringkasan Toko" bila >1 toko)
- Test: `web/tests_toko_overview.py` (create)

**Interfaces:**
- Consumes: `tokos_for`, `pending_settlement_count`.
- Produces: url name `toko_overview` → `/tokos/`.

- [ ] **Step 1: Tulis test yang gagal**

```python
# web/tests_toko_overview.py
"""Halaman /tokos/: ringkasan semua toko (scoped), urut selisih, tombol Buka."""
from datetime import date
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import Toko

User = get_user_model()


class TokoOverviewTests(TestCase):
    def setUp(self):
        User.objects.create_user("adm", password="pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")

    def _batch(self, toko, dp_selisih, d):
        return ReconBatch.objects.create(
            toko=toko, tolerance=self.tol, recon_date=d,
            summary={"dp": {"selisih": dp_selisih}, "wd": {"selisih": 0}},
        )

    def test_urut_selisih_terbesar_dulu(self):
        self._batch(self.lbs, 1000, date(2026, 6, 27))
        self._batch(self.slo, 9_000_000, date(2026, 6, 27))
        r = self.client.get(reverse("toko_overview"))
        html = r.content.decode()
        self.assertLess(html.index(">SLO<"), html.index(">LBS<"))

    def test_toko_tanpa_batch_belum_rekon(self):
        r = self.client.get(reverse("toko_overview"))
        self.assertContains(r, "belum rekon")

    def test_rbac_auditor_hanya_tokonya(self):
        u = User.objects.create_user("a2", password="pw12345", role="auditor")
        u.allowed_tokos.set([self.lbs])
        self.client.logout()
        self.client.login(username="a2", password="pw12345")
        r = self.client.get(reverse("toko_overview"))
        self.assertContains(r, ">LBS<")
        self.assertNotContains(r, ">SLO<")

    def test_tombol_buka_ganti_toko(self):
        self._batch(self.lbs, 0, date(2026, 6, 27))
        r = self.client.get(reverse("toko_overview"))
        self.assertContains(r, reverse("set_toko"))
```

Catatan: `>LBS<` / `>SLO<` mengasumsikan nama toko dirender dalam elemen (mis. `<b>LBS</b>`). Template di Step 4 memenuhi ini.

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `source .venv/bin/activate && python manage.py test web.tests_toko_overview -v 2`
Expected: FAIL.

- [ ] **Step 3: Rute + view**

Di `web/urls.py`, tambah setelah rute `tinjau/`:

```python
    path("tokos/", views.toko_overview, name="toko_overview"),
```

View baru di `web/views.py` (setelah `review_queue`):

```python
@login_required
def toko_overview(request):
    """Ringkasan lintas toko (scoped RBAC): status rekon terakhir, selisih,
    antrean tinjau, menunggu settlement, uang periksa D."""
    from reconciliation.engine import pending_settlement_count

    tokos = tokos_for(request.user)
    rows = []
    for t in tokos:
        last = (
            ReconBatch.objects.filter(toko=t, recon_date__isnull=False)
            .order_by("recon_date")
            .last()
        )
        s = (last.summary or {}) if last else {}
        dp = abs((s.get("dp") or {}).get("selisih") or 0)
        wd = abs((s.get("wd") or {}).get("selisih") or 0)
        total = dp + wd
        st = "" if last is None else ("ok" if total == 0 else ("warn" if total < 10_000_000 else "bad"))
        tinjau = MatchResult.objects.filter(
            run__batch__toko=t, bucket=MatchResult.Bucket.TINJAU
        ).count()
        um = (s.get("unmatched_money") or {}).get("d") or {}
        rows.append({
            "toko": t, "last": last, "selisih": total, "status": st,
            "tinjau": tinjau, "pending": pending_settlement_count(t),
            "uang_d": um.get("n") or 0,
            "has_batch": last is not None,
        })
    # selisih terbesar dulu; toko tanpa batch di bawah
    rows.sort(key=lambda r: (r["has_batch"], r["selisih"]), reverse=True)
    return render(request, "web/toko_overview.html", {"rows": rows})
```

- [ ] **Step 4: Template `toko_overview.html`**

```html
{% extends "web/app_base.html" %}
{% load humanize %}
{% block title %}Ringkasan Toko · Truth of Auditor{% endblock %}
{% block crumb %}Ringkasan Toko{% endblock %}
{% block content %}
<div class="page-head reveal">
  <div>
    <h1>Ringkasan Toko</h1>
    <p>Status rekonsiliasi semua toko yang kamu akses — prioritaskan selisih terbesar.</p>
  </div>
</div>

<div class="card pad0 reveal">
  <div class="card-head"><h3>Toko <span class="faint" style="font-weight:500">({{ rows|length }})</span></h3></div>
  <div class="twrap" style="border:none">
  <table>
    <thead><tr><th>Toko</th><th>Rekon terakhir</th><th class="num">Selisih (DP+WD)</th><th class="num">Antrean tinjau</th><th class="num">Menunggu settlement</th><th class="num">Uang periksa (D)</th><th class="r">Aksi</th></tr></thead>
    <tbody>
    {% for r in rows %}
      <tr>
        <td><span style="display:flex;align-items:center;gap:9px"><span class="avatar-ini">{{ r.toko.name|first|upper }}</span><b>{{ r.toko.name }}</b></span></td>
        <td>
          {% if r.last %}
            <a href="{% url 'batch_detail' r.last.pk %}">{{ r.last.recon_date|date:"d/m/Y" }}</a>
          {% else %}<span class="badge muted">belum rekon</span>{% endif %}
        </td>
        <td class="num mono">
          {% if not r.has_batch %}<span class="faint">—</span>
          {% elif r.selisih == 0 %}<span class="badge ok plain">0 ✓</span>
          {% else %}<span class="badge {{ r.status }} plain">{{ r.selisih|floatformat:0|intcomma }}</span>{% endif %}
        </td>
        <td class="num mono">{% if r.tinjau %}<a href="{% url 'set_toko' %}">{{ r.tinjau|intcomma }}</a>{% else %}0{% endif %}</td>
        <td class="num mono">{{ r.pending|intcomma }}</td>
        <td class="num mono">{% if r.uang_d %}<span style="color:var(--bad)">{{ r.uang_d|intcomma }}</span>{% else %}0{% endif %}</td>
        <td class="r">
          <form method="post" action="{% url 'set_toko' %}" style="display:inline">
            {% csrf_token %}
            <input type="hidden" name="toko_id" value="{{ r.toko.id }}">
            <input type="hidden" name="next" value="{% url 'dashboard' %}">
            <button class="btn sm" type="submit">Buka →</button>
          </form>
        </td>
      </tr>
    {% empty %}<tr><td colspan="7" class="cell-empty">Tidak ada toko.</td></tr>{% endfor %}
    </tbody>
  </table>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Menu sidebar "Ringkasan Toko" (bila >1 toko)**

Di `app_base.html`, di seksi `<div class="sec">Menu</div>`, tambahkan item setelah Dashboard (hanya bila user akses >1 toko):

```html
  {% if all_tokos|length > 1 %}
  <a class="link {% if '/tokos' in p %}active{% endif %}" href="{% url 'toko_overview' %}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>Ringkasan Toko</a>
  {% endif %}
```

- [ ] **Step 6: Jalankan test sampai lulus**

Run: `source .venv/bin/activate && python manage.py test web.tests_toko_overview -v 2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/urls.py web/views.py web/templates/web/toko_overview.html web/templates/web/app_base.html web/tests_toko_overview.py
git commit -m "feat(web): halaman Ringkasan Toko /tokos/ (scoped RBAC) + menu sidebar

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Dashboard — tren 30 hari + garis selisih + kartu klikabel sisa

**Files:**
- Modify: `web/views.py` (fungsi `dashboard` — jendela tren + data garis)
- Modify: `web/templates/web/dashboard.html` (judul tren, data garis, kartu "Rekon terakhir" & "Uang periksa D" jadi link)
- Test: `web/tests_dashboard_g2.py` (create)

**Interfaces:**
- Consumes: struktur `tren` (list dict) yang sudah ada; tambah field `htot`, `tot`.

- [ ] **Step 1: Tulis test yang gagal**

```python
# web/tests_dashboard_g2.py
"""Dashboard gelombang 2: tren 30 hari, judul, kartu rekon-terakhir & uang-D klikabel."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()
_seq = iter(range(1, 100000))


class DashboardG2Tests(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def _batch(self, d, selisih):
        return ReconBatch.objects.create(
            toko=self.lbs, tolerance=self.tol, recon_date=d,
            summary={"dp": {"selisih": selisih}, "wd": {"selisih": 0},
                     "unmatched_money": {"d": {"n": 3}}},
        )

    def test_judul_tren_30_hari(self):
        self._batch(date(2026, 6, 27), 1000)
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "30 hari")

    def test_kartu_rekon_terakhir_jadi_anchor(self):
        # Kartu (bukan sekadar kalender) kini anchor .card.stat.click ke batch_detail.
        b = self._batch(date(2026, 6, 27), 1000)
        r = self.client.get(reverse("dashboard"))
        self.assertContains(
            r, f'<a class="card stat click" href="{reverse("batch_detail", args=[b.pk])}">'
        )

    def test_kartu_uang_d_jadi_anchor(self):
        b = self._batch(date(2026, 6, 27), 1000)
        r = self.client.get(reverse("dashboard"))
        self.assertContains(
            r, f'<a class="card stat click" href="{reverse("batch_uang", args=[b.pk])}?k=d">'
        )

    def test_tren_batasi_30_hari(self):
        anchor = date(2026, 6, 27)
        self._batch(anchor, 5000)
        self._batch(anchor - timedelta(days=40), 9999)  # di luar 30 hari
        r = self.client.get(reverse("dashboard"))
        # data tren hanya memuat batch dalam 30 hari
        self.assertEqual(len(r.context["tren"]), 1)
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `source .venv/bin/activate && python manage.py test web.tests_dashboard_g2 -v 2`
Expected: FAIL.

- [ ] **Step 3: Perbarui jendela tren di `dashboard`**

Ganti blok `# --- tren selisih 14 batch terakhir ...` (`tren_src = batches[-14:]` … loop membangun `tren`) menjadi versi 30-hari kalender + field garis:

```python
    # --- tren selisih 30 hari kalender terakhir (bar DP/WD + garis total) ---
    tren_cutoff = anchor - timedelta(days=29)
    tren_src = [b for b in batches if b.recon_date and b.recon_date >= tren_cutoff]
    mx = max((selisih(b) for b in tren_src), default=0) or 1
    tren = []
    for b in tren_src:
        s = b.summary or {}
        dp = abs((s.get("dp") or {}).get("selisih") or 0)
        wd = abs((s.get("wd") or {}).get("selisih") or 0)
        tren.append({
            "b": b, "dp": dp, "wd": wd,
            "hdp": round(100 * dp / mx), "hwd": round(100 * wd / mx),
            "tot": dp + wd, "htot": round(100 * (dp + wd) / mx),
        })
```

- [ ] **Step 4: Template dashboard — judul, data garis, JS polyline**

Ubah judul kartu tren: `<h3>Tren selisih per batch</h3>` → `<h3>Tren selisih — 30 hari</h3>`.

Perbarui data hidden agar menyertakan htot & tot (indeks 5,6):

```html
    <div id="tren-data" hidden>{% for t in tren %}{{ t.b.recon_date|date:"d/m" }}|{{ t.hdp }}|{{ t.hwd }}|{{ t.dp|floatformat:0 }}|{{ t.wd|floatformat:0 }}|{{ t.htot }}|{{ t.tot|floatformat:0 }};{% endfor %}</div>
```

Perbarui blok `<script>` builder SVG (di `{% block scripts %}`) untuk menggambar garis total. Ganti isi fungsi loop dan tambahkan polyline setelah loop bar:

```javascript
  var W=300, H=100, n=rows.length, gw=W/n, html='', pts=[];
  rows.forEach(function(r,i){
    var x=i*gw, bw=Math.max(3,(gw-8)/2);
    var hdp=Math.max(2, r[1]*0.86), hwd=Math.max(2, r[2]*0.86);
    var htot=Math.max(1, r[5]*0.86);
    html+='<g><rect x="'+(x+3)+'" y="'+(H-9-hdp)+'" width="'+bw+'" height="'+hdp+'" rx="2" style="fill:var(--brand)" opacity=".9"><title>'+r[0]+' · DP '+Number(r[3]).toLocaleString('id-ID')+'</title></rect>';
    html+='<rect x="'+(x+5+bw)+'" y="'+(H-9-hwd)+'" width="'+bw+'" height="'+hwd+'" rx="2" style="fill:var(--warn)" opacity=".85"><title>'+r[0]+' · WD '+Number(r[4]).toLocaleString('id-ID')+'</title></rect>';
    html+='<text x="'+(x+gw/2)+'" y="'+(H-1)+'" font-size="7" text-anchor="middle" style="fill:var(--faint)">'+r[0]+'</text></g>';
    pts.push((x+gw/2)+','+(H-9-htot));
  });
  if(pts.length > 1){
    html+='<polyline points="'+pts.join(' ')+'" fill="none" style="stroke:var(--ink)" stroke-width="1" opacity=".55"/>';
  }
  svg.innerHTML = html;
```

- [ ] **Step 5: Kartu "Rekon terakhir" & "Uang periksa (D)" jadi link**

Kartu "Rekon terakhir": ubah `<div class="card stat">` menjadi anchor bila ada batch:

```html
  {% if last %}<a class="card stat click" href="{% url 'batch_detail' last.pk %}">{% else %}<div class="card stat">{% endif %}
    <div class="top"><span class="k">Rekon terakhir</span>
      <span class="ic {% if last_sel == 0 %}g{% elif last_sel < 10000000 %}a{% else %}r{% endif %}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M8 2v4M16 2v4M3 10h18"/><rect x="3" y="4" width="18" height="18" rx="2"/></svg></span></div>
    {% if last %}
    <div class="v">{{ last.recon_date|date:"d M" }}</div>
    <div class="sub">Batch #{{ last_no }} · selisih {{ last_sel|floatformat:0|intcomma }}</div>
    </a>
    {% else %}<div class="v faint">—</div><div class="sub">belum ada rekonsiliasi</div></div>{% endif %}
```

Kartu "Uang periksa (D)": ubah menjadi anchor bila ada batch:

```html
  {% if last %}<a class="card stat click" href="{% url 'batch_uang' last.pk %}?k=d">{% else %}<div class="card stat">{% endif %}
    <div class="top"><span class="k">Uang periksa (D)</span>
      <span class="ic {% if um_d.n %}r{% else %}g{% endif %}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg></span></div>
    <div class="v {% if um_d.n %}r{% else %}g{% endif %}">{{ um_d.n|default:0|intcomma }}</div>
    <div class="sub">{% if last %}uang tanpa catatan panel →{% else %}—{% endif %}</div>
  {% if last %}</a>{% else %}</div>{% endif %}
```

- [ ] **Step 6: Jalankan test sampai lulus**

Run: `source .venv/bin/activate && python manage.py test web.tests_dashboard_g2 -v 2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/views.py web/templates/web/dashboard.html web/tests_dashboard_g2.py
git commit -m "feat(web): dashboard tren 30 hari + garis selisih + kartu rekon/uang-D klikabel

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: Regresi penuh + verifikasi visual

**Files:** tidak ada perubahan kode; verifikasi lintas fitur.

- [ ] **Step 1: Jalankan SELURUH test suite**

Run: `source .venv/bin/activate && python manage.py test`
Expected: OK (≥ 309 test lama + test baru gelombang 2 semuanya PASS).

- [ ] **Step 2: Verifikasi visual via preview**

Jalankan server preview (`preview_start` config `auditor-ui`), login admin sementara, kunjungi:
`/transactions/` (klik header sort, tombol Export, filter tanggal), `/transactions/?carry=1`,
`/run/<pk>/` (header sort), `/batch/<pk>/uang/` (header sort), `/batch/<pk>/` (kartu Per Sumber Uang),
`/tinjau/`, `/tokos/`, `/` (kartu klikabel + tren 30 hari). Ambil screenshot bukti tiap halaman.
Cek `preview_console_logs` bersih. Hapus user sementara setelah selesai.

- [ ] **Step 3: Commit (bila ada perbaikan dari verifikasi)**

```bash
git add -A
git commit -m "test: verifikasi visual gelombang 2 + perbaikan kecil temuan preview

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Catatan implementasi

- Impor: `date_cls` sudah diimpor di `web/views.py` (`from datetime import date as date_cls`). Untuk `_export_transactions` dan `batch_uang` sorting, tambahkan `from datetime import datetime` lokal di fungsi bila belum ada (jangan ubah import modul secara global bila menimbulkan bentrok nama).
- `t.source_label` dan `t.get_jenis_display()` adalah anggota model `Transaction` yang sudah dipakai `transactions.html` — aman dipakai di export.
- Semua header sortable memakai kelas `.th-sort` (ditambahkan di Task 1). Bila Task dikerjakan tak berurutan, pastikan style itu sudah ada di `app_base.html`.
- `_result_row.html` kini menerima `show_run_col`; halaman `run_detail.html` memanggil `{% include %}` tanpa flag (default falsy) sehingga kolom run tidak muncul di sana — tidak perlu perubahan `run_detail.html` untuk itu.
