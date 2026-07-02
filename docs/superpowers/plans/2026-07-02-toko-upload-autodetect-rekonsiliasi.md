# Toko, Upload Auto-Detect, & Rekonsiliasi Paralel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tambahkan dimensi Toko, ubah Upload jadi satu drop-zone multi-file auto-detect dengan preview + history, dan buat Rekonsiliasi berjalan paralel (Panel↔Bracket & Panel↔Bank/Gateway) dengan pra-cek kelengkapan.

**Architecture:** Model `Toko` menandai `Upload`/`Transaction`/`Account`. Modul `sources/detect.py` mengklasifikasi file dari tanda-tangan header. Upload memakai alur dua fase (analyze → preview → commit) di atas `ingest()` yang sudah ada. Rekonsiliasi memakai `ReconBatch` yang menjalankan relasi yang datanya tersedia lewat `MATCHERS` yang sudah ada, ditambah filter toko. Halaman kerja pindah ke layout terang bersidebar (`app_base.html`); login tetap dark.

**Tech Stack:** Django 5.2, Python 3.11, openpyxl, pdfplumber, rapidfuzz, HTMX (CDN), GSAP/Lenis (login). DB: SQLite (dev) / Postgres (prod). Test: `python manage.py test` (bukan pytest).

## Global Constraints

- Semua nilai uang di `Transaction` sudah dinormalisasi ke RUPIAH (Panel ×1000 lewat parser). Jangan skala ulang.
- FK Toko baru harus `null=True, blank=True` di level DB agar data & test lama tidak pecah; "wajib" ditegakkan di level view/form.
- Idempotensi ingest via `row_hash` sudah ada — jangan tambah dedup berat.
- Pencocokan TIDAK boleh lintas-toko: setiap `sides()` matcher difilter `toko` bila diberikan.
- Test framework: `python manage.py test`. Pure-function → `SimpleTestCase`; yang menyentuh DB → `TestCase`.
- Jalankan perintah dari root repo dengan venv aktif: `source .venv/bin/activate`.
- Parser baru (BNI, Credit Bonus, Panel Provider lain) DI LUAR lingkup — tunggu contoh file.

---

## Phase A — Fondasi (Toko + layout)

### Task A1: Model `Toko` + admin + seed

**Files:**
- Modify: `sources/models.py` (tambah class `Toko`)
- Modify: `sources/admin.py` (registrasi)
- Create: `sources/migrations/0003_toko.py` (auto) + `sources/migrations/0004_seed_toko.py` (data)
- Test: `sources/tests_toko.py` (baru)

**Interfaces:**
- Produces: `sources.models.Toko` dengan field `key: SlugField(unique)`, `name: CharField`, `is_active: BooleanField`. Seed: `lbs`→"LBS", `slo`→"SLO".

- [ ] **Step 1: Write the failing test**

```python
# sources/tests_toko.py
from django.test import TestCase
from sources.models import Toko


class TokoModelTests(TestCase):
    def test_str_returns_name(self):
        t = Toko.objects.create(key="xyz", name="XYZ")
        self.assertEqual(str(t), "XYZ")

    def test_seed_creates_lbs_and_slo(self):
        self.assertTrue(Toko.objects.filter(key="lbs").exists())
        self.assertTrue(Toko.objects.filter(key="slo").exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test sources.tests_toko -v2`
Expected: FAIL — `ImportError: cannot import name 'Toko'`.

- [ ] **Step 3: Add the model**

```python
# sources/models.py — tambahkan di bawah import yang ada (butuh TimeStampedModel yang sudah di-import)
class Toko(TimeStampedModel):
    """Merek/situs operator (mis. LBS, SLO). Data dipisah per toko."""

    key = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name
```

- [ ] **Step 4: Register in admin**

```python
# sources/admin.py — tambahkan
from .models import Toko  # gabungkan dengan import model lain yang sudah ada

admin.site.register(Toko)
```

- [ ] **Step 5: Create schema migration**

Run: `python manage.py makemigrations sources`
Expected: membuat `sources/migrations/0003_toko.py` (CreateModel Toko).

- [ ] **Step 6: Create the data (seed) migration**

Run: `python manage.py makemigrations sources --empty --name seed_toko`
Then isi filenya:

```python
# sources/migrations/0004_seed_toko.py
from django.db import migrations


def seed(apps, schema_editor):
    Toko = apps.get_model("sources", "Toko")
    for key, name in [("lbs", "LBS"), ("slo", "SLO")]:
        Toko.objects.get_or_create(key=key, defaults={"name": name})


def unseed(apps, schema_editor):
    apps.get_model("sources", "Toko").objects.filter(key__in=["lbs", "slo"]).delete()


class Migration(migrations.Migration):
    dependencies = [("sources", "0003_toko")]
    operations = [migrations.RunPython(seed, unseed)]
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python manage.py test sources.tests_toko -v2`
Expected: PASS (2 tests).

- [ ] **Step 8: Commit**

```bash
git add sources/models.py sources/admin.py sources/migrations/0003_toko.py sources/migrations/0004_seed_toko.py sources/tests_toko.py
git commit -m "feat(sources): model Toko + seed LBS/SLO"
```

---

### Task A2: FK Toko/provider di Upload/Transaction/Account + backfill + wiring ingest

**Files:**
- Modify: `sources/models.py` (`Upload`, `Account`)
- Modify: `transactions/models.py` (`Transaction`)
- Modify: `sources/services.py` (`ingest`)
- Create: migration skema (auto) + `sources/migrations/00XX_backfill_toko.py` (data)
- Test: `sources/tests_toko.py` (tambah `IngestTokoTests`)

**Interfaces:**
- Consumes: `sources.models.Toko` (Task A1).
- Produces: `ingest(parser_key, file_path, recon_date=None, account=None, flow="", user=None, toko=None, provider="")` — men-set `Upload.toko`, `Upload.provider`, dan `Transaction.toko`. Field baru: `Upload.toko` (FK Toko, null), `Upload.provider` (CharField), `Transaction.toko` (FK Toko, null), `Account.toko` (FK Toko, null).

- [ ] **Step 1: Write the failing test**

```python
# sources/tests_toko.py — tambahkan
from unittest.mock import patch
from datetime import datetime
from decimal import Decimal

from sources import services
from sources.models import SourceType, Toko
from transactions.models import Transaction

_CANON = {
    "occurred_at": datetime(2026, 6, 27, 10, 0), "posted_date": None, "jenis": "depo",
    "amount": Decimal("50000"), "credit_delta": Decimal("-50000"), "money_delta": Decimal("50000"),
    "fee": Decimal("0"), "bonus": Decimal("0"), "balance_after": None,
    "ticket_no": "D1", "username": "budi", "reference": "", "counterparty": "",
    "description": "", "raw": {}, "row_hash": "hash-a2-1",
}


class _DummyBracket:
    source_key = "bracket"

    def parse(self, path, flow=""):
        return [dict(_CANON)]


class IngestTokoTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})

    def test_ingest_sets_toko_and_provider(self):
        with patch.dict(services.PARSERS, {"dummy": _DummyBracket}, clear=False):
            up, created, dup = services.ingest("dummy", "/nofile", toko=self.lbs, provider="Nexus")
        self.assertEqual(up.toko, self.lbs)
        self.assertEqual(up.provider, "Nexus")
        self.assertEqual(created, 1)
        self.assertEqual(Transaction.objects.get().toko, self.lbs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test sources.tests_toko.IngestTokoTests -v2`
Expected: FAIL — `ingest() got an unexpected keyword argument 'toko'`.

- [ ] **Step 3: Add fields to models**

```python
# sources/models.py — di dalam class Upload, tambahkan setelah field 'account':
    toko = models.ForeignKey(
        "sources.Toko", on_delete=models.PROTECT, null=True, blank=True
    )
    provider = models.CharField(max_length=50, blank=True, help_text="Panel provider, mis. Nexus")

# sources/models.py — di dalam class Account, tambahkan:
    toko = models.ForeignKey(
        "sources.Toko", on_delete=models.SET_NULL, null=True, blank=True
    )
```

```python
# transactions/models.py — di dalam class Transaction, setelah field 'account':
    toko = models.ForeignKey(
        "sources.Toko", on_delete=models.PROTECT, null=True, blank=True
    )
```

- [ ] **Step 4: Wire `ingest()`**

```python
# sources/services.py — ubah signature & body
def ingest(parser_key, file_path, recon_date=None, account=None, flow="", user=None, toko=None, provider=""):
    if parser_key not in PARSERS:
        raise ValueError(f"Parser '{parser_key}' tidak dikenal. Pilihan: {', '.join(PARSERS)}")

    parser = PARSERS[parser_key]()
    rows = parser.parse(file_path, flow=flow)
    st = SourceType.objects.get(key=parser.source_key)

    with db_tx.atomic():
        up = Upload.objects.create(
            source_type=st,
            account=account,
            toko=toko,
            provider=provider,
            flow=flow or "",
            recon_date=recon_date,
            original_name=Path(file_path).name,
            status=Upload.PARSED,
            uploaded_by=user,
        )
        existing = set(
            Transaction.objects.filter(source_type=st).values_list("row_hash", flat=True)
        )
        objs, seen, dup = [], set(), 0
        for row in rows:
            rh = row["row_hash"]
            if rh in existing or rh in seen:
                dup += 1
                continue
            seen.add(rh)
            objs.append(
                Transaction(
                    upload=up,
                    source_type=st,
                    account=account,
                    toko=toko,
                    occurred_at=row["occurred_at"],
                    posted_date=row["posted_date"],
                    jenis=row["jenis"],
                    amount=row["amount"],
                    credit_delta=row["credit_delta"],
                    money_delta=row["money_delta"],
                    fee=row["fee"],
                    bonus=row["bonus"],
                    balance_after=row["balance_after"],
                    ticket_no=row["ticket_no"],
                    username=row["username"],
                    reference=row["reference"],
                    counterparty=row["counterparty"],
                    description=row["description"],
                    raw=row["raw"],
                    row_hash=rh,
                )
            )
        Transaction.objects.bulk_create(objs, batch_size=1000)
        up.rows_parsed = len(objs)
        up.rows_duplicate = dup
        up.save(update_fields=["rows_parsed", "rows_duplicate"])

    return up, len(objs), dup
```

- [ ] **Step 5: Create schema migrations**

Run: `python manage.py makemigrations sources transactions`
Expected: migration `sources` (add `Upload.toko`, `Upload.provider`, `Account.toko`) + migration `transactions` (add `Transaction.toko`).

- [ ] **Step 6: Create backfill data migration**

Run: `python manage.py makemigrations sources --empty --name backfill_toko`
Isi (sesuaikan nomor dependency ke migration skema Upload dari Step 5 dan migration `transactions` yang menambah `Transaction.toko`):

```python
# sources/migrations/00XX_backfill_toko.py
from django.db import migrations


def backfill(apps, schema_editor):
    Toko = apps.get_model("sources", "Toko")
    Upload = apps.get_model("sources", "Upload")
    Transaction = apps.get_model("transactions", "Transaction")
    lbs = Toko.objects.filter(key="lbs").first()
    if not lbs:
        return
    Upload.objects.filter(toko__isnull=True).update(toko=lbs)
    Transaction.objects.filter(toko__isnull=True).update(toko=lbs)


class Migration(migrations.Migration):
    dependencies = [
        ("sources", "0005_seed_toko"),  # ganti ke migration skema Upload.toko dari Step 5
        ("transactions", "0002_transaction_toko"),  # ganti ke nama sebenarnya
    ]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
```

- [ ] **Step 7: Run tests**

Run: `python manage.py test sources.tests_toko -v2`
Expected: PASS (semua).

- [ ] **Step 8: Regression — pastikan test lama masih lulus**

Run: `python manage.py test sources reconciliation -v2`
Expected: PASS (test parser & engine yang sudah ada tidak pecah).

- [ ] **Step 9: Commit**

```bash
git add sources/models.py transactions/models.py sources/services.py sources/migrations/*.py transactions/migrations/*.py sources/tests_toko.py
git commit -m "feat(sources): FK Toko/provider di Upload/Transaction/Account + wiring ingest + backfill"
```

---

### Task A3: Layout aplikasi terang + selektor Toko global

**Files:**
- Create: `web/templates/web/app_base.html` (layout terang bersidebar)
- Create: `web/context_processors.py`
- Modify: `truth_auditor/settings.py` (daftarkan context processor)
- Modify: `web/views.py` (tambah `set_toko` + helper `_active_toko`)
- Modify: `web/urls.py` (route `set_toko`)
- Modify: `web/templates/web/dashboard.html` (extend `app_base.html`)
- Test: `web/tests.py`

**Interfaces:**
- Consumes: `sources.models.Toko`.
- Produces: context vars `all_tokos`, `active_toko` di semua template; view `set_toko` (name=`set_toko`); helper `web.views._active_toko(request) -> Toko | None`; template dasar `web/app_base.html` dengan block `content`, `title`.

- [ ] **Step 1: Write the failing test**

```python
# web/tests.py — ganti isi file dengan
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import Toko


class TokoSelectorTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.u = User.objects.create_user("aud", "a@a.co", "pw12345")
        self.client.login(username="aud", password="pw12345")

    def test_set_toko_updates_session(self):
        slo = Toko.objects.get(key="slo")
        self.client.post(reverse("set_toko"), {"toko_id": slo.id, "next": reverse("dashboard")})
        self.assertEqual(self.client.session["active_toko_id"], slo.id)

    def test_dashboard_renders_toko_selector(self):
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "LBS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test web.tests.TokoSelectorTests -v2`
Expected: FAIL — `NoReverseMatch: 'set_toko'`.

- [ ] **Step 3: Add context processor**

```python
# web/context_processors.py
from sources.models import Toko


def toko(request):
    tokos = list(Toko.objects.filter(is_active=True).order_by("name"))
    active_id = request.session.get("active_toko_id")
    active = next((t for t in tokos if t.id == active_id), tokos[0] if tokos else None)
    return {"all_tokos": tokos, "active_toko": active}
```

- [ ] **Step 4: Register the context processor**

```python
# truth_auditor/settings.py — di TEMPLATES[0]["OPTIONS"]["context_processors"], tambahkan baris:
                "web.context_processors.toko",
```

- [ ] **Step 5: Add view + helper + URL**

```python
# web/views.py — tambahkan import di atas
from sources.models import SourceType, Upload, Toko  # tambah Toko ke import yang sudah ada


def _active_toko(request):
    tid = request.session.get("active_toko_id")
    t = Toko.objects.filter(id=tid, is_active=True).first() if tid else None
    return t or Toko.objects.filter(is_active=True).order_by("name").first()


@login_required
def set_toko(request):
    if request.method == "POST":
        tid = request.POST.get("toko_id")
        if tid and Toko.objects.filter(id=tid, is_active=True).exists():
            request.session["active_toko_id"] = int(tid)
    return redirect(request.POST.get("next") or "dashboard")
```

```python
# web/urls.py — tambahkan ke urlpatterns
    path("set-toko/", views.set_toko, name="set_toko"),
```

- [ ] **Step 6: Create the light app layout**

```html
<!-- web/templates/web/app_base.html -->
{% load static %}
<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}Truth of Auditor{% endblock %}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://unpkg.com/htmx.org@1.9.12"></script>
<style>
:root{--bg:#f6f7fb;--panel:#fff;--border:#e6e8ef;--text:#0f1424;--muted:#6b7280;
  --brand:#2563eb;--ok:#16a34a;--warn:#d97706;--bad:#dc2626;--radius:12px;}
*{box-sizing:border-box}html,body{margin:0}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);display:flex;min-height:100vh}
a{color:inherit;text-decoration:none}
.side{width:210px;background:var(--panel);border-right:1px solid var(--border);display:flex;flex-direction:column;padding:16px 12px;position:sticky;top:0;height:100vh}
.side .brand{font-weight:700;font-size:16px;padding:6px 10px 16px}
.side a.link{display:block;padding:9px 12px;border-radius:9px;color:var(--muted);font-weight:500;font-size:14px;margin-bottom:2px}
.side a.link:hover{background:var(--bg)}
.side a.link.active{background:#eef2ff;color:var(--brand)}
.side .spacer{flex:1}
.side .user{font-size:12px;color:var(--muted);padding:10px}
.main{flex:1;min-width:0;display:flex;flex-direction:column}
.topbar{display:flex;align-items:center;gap:12px;padding:14px 26px;border-bottom:1px solid var(--border);background:var(--panel)}
.topbar .spacer{flex:1}
.topbar select{padding:8px 12px;border:1px solid var(--border);border-radius:9px;background:#fff;font-size:14px}
.content{padding:26px;max-width:1200px;width:100%}
.page-head h1{margin:0 0 4px;font-size:24px}
.page-head p{margin:0 0 20px;color:var(--muted);font-size:14px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:18px;margin-bottom:16px}
.grid{display:grid;gap:14px}.cols-2{grid-template-columns:1fr 1fr}.cols-4{grid-template-columns:repeat(4,1fr)}
label{display:block;font-size:13px;color:var(--muted);margin-bottom:5px}
.field{margin-bottom:14px}
input,select.f,.f{padding:9px 11px;border:1px solid var(--border);border-radius:9px;font-size:14px;width:100%;background:#fff}
.btn{display:inline-flex;align-items:center;gap:6px;padding:9px 16px;border-radius:9px;border:1px solid var(--border);background:#fff;font-weight:600;font-size:14px;cursor:pointer}
.btn.primary{background:var(--brand);color:#fff;border-color:var(--brand)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--border)}
th{color:var(--muted);font-weight:600}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600}
.badge.ok{background:#dcfce7;color:var(--ok)}.badge.warn{background:#fef3c7;color:var(--warn)}.badge.bad{background:#fee2e2;color:var(--bad)}
.msg{padding:10px 14px;border-radius:9px;margin-bottom:10px;font-size:14px}
.msg.success{background:#dcfce7}.msg.error{background:#fee2e2}
.faint{color:var(--muted)}
</style>
</head>
<body>
<aside class="side">
  <div class="brand">Truth of Auditor</div>
  <a class="link" href="{% url 'dashboard' %}">Dashboard</a>
  <a class="link" href="{% url 'upload' %}">Upload</a>
  <a class="link" href="{% url 'transactions' %}">Transaksi</a>
  <a class="link" href="{% url 'reconcile' %}">Rekonsiliasi</a>
  <div class="spacer"></div>
  <div class="user">{{ request.user.username }}<br><a class="faint" href="/admin/logout/">Keluar</a></div>
</aside>
<div class="main">
  <div class="topbar">
    <div class="spacer"></div>
    <form method="post" action="{% url 'set_toko' %}">
      {% csrf_token %}
      <input type="hidden" name="next" value="{{ request.path }}">
      <select name="toko_id" class="f" onchange="this.form.submit()">
        {% for t in all_tokos %}
        <option value="{{ t.id }}" {% if active_toko and t.id == active_toko.id %}selected{% endif %}>{{ t.name }}</option>
        {% endfor %}
      </select>
    </form>
  </div>
  <div class="content">
    {% if messages %}{% for m in messages %}<div class="msg {{ m.tags }}">{{ m }}</div>{% endfor %}{% endif %}
    {% block content %}{% endblock %}
  </div>
</div>
</body>
</html>
```

- [ ] **Step 7: Point dashboard at the new layout**

```html
<!-- web/templates/web/dashboard.html — ubah baris pertama saja -->
{% extends "web/app_base.html" %}
```
(biarkan isi block `content` yang sudah ada; hanya ganti template induk dari `web/base.html` ke `web/app_base.html`.)

- [ ] **Step 8: Run tests**

Run: `python manage.py test web.tests.TokoSelectorTests -v2`
Expected: PASS (2 tests).

- [ ] **Step 9: Commit**

```bash
git add web/templates/web/app_base.html web/context_processors.py truth_auditor/settings.py web/views.py web/urls.py web/templates/web/dashboard.html web/tests.py
git commit -m "feat(web): layout terang bersidebar + selektor Toko global"
```

---

## Phase B — Upload auto-detect

### Task B1: Registry deteksi sumber

**Files:**
- Create: `sources/detect.py`
- Test: `sources/tests_detect.py`

**Interfaces:**
- Produces: `sources.detect.detect_source(path, filename="") -> list[dict]` di mana tiap item `{"parser_key": str, "confidence": float}` terurut menurun. `parser_key` ∈ kunci `sources.services.PARSERS`.

- [ ] **Step 1: Write the failing test**

```python
# sources/tests_detect.py
import csv
import os
import tempfile

import openpyxl
from django.test import SimpleTestCase

from sources.detect import detect_source


def _xlsx(rows):
    fd, p = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    wb.save(p)
    return p


def _csv(text):
    fd, p = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


class DetectTests(SimpleTestCase):
    def test_panel(self):
        p = _xlsx([["HISTORI DP PANEL"], ["Ticket Number", "User Name", "Deposit Amount"]])
        self.assertEqual(detect_source(p, "hist.xlsx")[0]["parser_key"], "panel")

    def test_nxpay_not_confused_with_panel(self):
        p = _xlsx([["NXPAY REPORT"], ["Ticket Number", "Username", "Amount", "Admin Fee", "Account Title"]])
        self.assertEqual(detect_source(p, "nx.xlsx")[0]["parser_key"], "nxpay")

    def test_bracket(self):
        p = _xlsx([["Kategori", "Credit Awal", "Credit Akhir", "Transaction ID"]])
        self.assertEqual(detect_source(p, "fr.xlsx")[0]["parser_key"], "bracket")

    def test_bri_csv(self):
        p = _csv("TGL_TRAN,MUTASI_DEBET,MUTASI_KREDIT,DESK_TRAN\n")
        self.assertEqual(detect_source(p, "bri.csv")[0]["parser_key"], "bri")

    def test_bca_csv(self):
        p = _csv("Rekening\nTanggal,Keterangan,Cabang,Jumlah,,Saldo\n")
        self.assertEqual(detect_source(p, "bca.csv")[0]["parser_key"], "bca_csv")

    def test_pdf_extension(self):
        fd, p = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        self.assertEqual(detect_source(p, "koran.pdf")[0]["parser_key"], "bca_pdf")

    def test_unknown_returns_empty(self):
        p = _xlsx([["Foo", "Bar"]])
        self.assertEqual(detect_source(p, "x.xlsx"), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test sources.tests_detect -v2`
Expected: FAIL — `ModuleNotFoundError: No module named 'sources.detect'`.

- [ ] **Step 3: Implement the detector**

```python
# sources/detect.py
"""Auto-deteksi jenis sumber file dari tanda-tangan header/isi.

detect_source(path, filename) -> [{"parser_key", "confidence"}] terurut menurun.
parser_key mengacu ke kunci sources.services.PARSERS.
"""
import os

import openpyxl


def _ext(filename):
    return os.path.splitext(filename)[1].lower()


def _xlsx_tokens(path, max_rows=3):
    toks = set()
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if i > max_rows:
                break
            for c in row:
                if c is not None:
                    toks.add(str(c).strip().lower())
        wb.close()
    except Exception:
        pass
    return toks


def _csv_text(path, n=6):
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            return "\n".join(line.strip().lower() for _, line in zip(range(n), f))
    except Exception:
        return ""


def _has(toks, needle):
    return any(needle in t for t in toks)


def detect_source(path, filename=""):
    filename = filename or os.path.basename(path)
    ext = _ext(filename)
    fn = filename.lower()
    scored = {}

    def add(key, conf):
        scored[key] = max(scored.get(key, 0.0), conf)

    if ext in (".xlsx", ".xls"):
        t = _xlsx_tokens(path)
        if _has(t, "ticket number") and _has(t, "user name") and (_has(t, "deposit amount") or _has(t, "withdrawal amount")):
            add("panel", 0.95)
        if _has(t, "ticket number") and (_has(t, "admin fee") or _has(t, "account title")) and not _has(t, "deposit amount"):
            add("nxpay", 0.90)
        if _has(t, "kategori") and (_has(t, "credit awal") or _has(t, "credit akhir")):
            add("bracket", 0.95)
        if _has(t, "qris") or _has(t, "qr flyer") or "qrflyer" in fn or "qris" in fn:
            add("qrflyer", 0.85)
        if _has(t, "e-statement") or _has(t, "rekening koran") or "mandiri" in fn:
            add("mandiri", 0.80)
    elif ext == ".csv":
        c = _csv_text(path)
        if "mutasi_debet" in c or "mutasi_kredit" in c or "tgl_tran" in c:
            add("bri", 0.95)
        if ("cabang" in c and "keterangan" in c and "saldo" in c) or "bca" in fn:
            add("bca_csv", 0.85)
    elif ext == ".pdf":
        add("bca_pdf", 0.75)

    ranked = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)
    return [{"parser_key": k, "confidence": c} for k, c in ranked]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test sources.tests_detect -v2`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add sources/detect.py sources/tests_detect.py
git commit -m "feat(sources): registry auto-deteksi jenis file (detect_source)"
```

---

### Task B2: Upload — fase analyze (multi-file → preview)

**Files:**
- Modify: `web/views.py` (`upload`)
- Modify: `web/templates/web/upload.html` (form multi-file + tabel preview)
- Test: `web/tests_upload.py` (baru)

**Interfaces:**
- Consumes: `_active_toko` (A3), `detect_source` (B1), `detect_flow` (sudah ada di `sources.management.commands.ingest`), `PARSERS` (sudah ada).
- Produces: `upload` view menangani `POST action=analyze` → context `preview` = list `{"name","staged","parser_key","confidence","needs_confirm","flow"}`; file di-stage ke `staging/<name>` via `default_storage`.

- [ ] **Step 1: Write the failing test**

```python
# web/tests_upload.py
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse


class UploadAnalyzeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345")
        self.client.login(username="aud", password="pw12345")

    def test_analyze_detects_bri(self):
        f = SimpleUploadedFile(
            "bri.csv",
            b"TGL_TRAN,MUTASI_DEBET,MUTASI_KREDIT,DESK_TRAN\n",
            content_type="text/csv",
        )
        r = self.client.post(reverse("upload"), {"action": "analyze", "files": [f]})
        self.assertEqual(r.status_code, 200)
        preview = r.context["preview"]
        self.assertEqual(len(preview), 1)
        self.assertEqual(preview[0]["parser_key"], "bri")
        self.assertFalse(preview[0]["needs_confirm"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test web.tests_upload.UploadAnalyzeTests -v2`
Expected: FAIL — `KeyError: 'preview'` (view belum menangani analyze).

- [ ] **Step 3: Implement the analyze branch**

```python
# web/views.py — tambah import
from sources.detect import detect_source

# web/views.py — ganti seluruh fungsi upload dengan:
@login_required
def upload(request):
    active = _active_toko(request)
    if request.method == "POST" and request.POST.get("action") == "analyze":
        preview = []
        for f in request.FILES.getlist("files"):
            saved = default_storage.save(f"staging/{f.name}", f)
            cands = detect_source(default_storage.path(saved), f.name)
            top = cands[0] if cands else None
            preview.append({
                "name": f.name,
                "staged": saved,
                "parser_key": top["parser_key"] if top else "",
                "confidence": round(top["confidence"] * 100) if top else 0,
                "needs_confirm": (top is None) or top["confidence"] < 0.8,
                "flow": detect_flow(f.name),
            })
        return render(request, "web/upload.html", {
            "preview": preview, "parsers": sorted(PARSERS.keys()),
            "flows": ["", "dp", "wd"], "active_toko": active,
            "uploads": Upload.objects.filter(toko=active).select_related("source_type").order_by("-id")[:20],
        })
    return render(request, "web/upload.html", {
        "parsers": sorted(PARSERS.keys()), "active_toko": active,
        "uploads": Upload.objects.filter(toko=active).select_related("source_type").order_by("-id")[:20],
    })
```

- [ ] **Step 4: Rewrite the upload template**

```html
<!-- web/templates/web/upload.html -->
{% extends "web/app_base.html" %}
{% block title %}Upload · Truth of Auditor{% endblock %}
{% block content %}
<div class="page-head">
  <h1>Upload &amp; Parse</h1>
  <p>Lempar beberapa file sekaligus untuk <b>{{ active_toko.name }}</b> — sistem menentukan jenisnya otomatis.</p>
</div>

<div class="card">
  <form method="post" enctype="multipart/form-data">
    {% csrf_token %}
    <input type="hidden" name="action" value="analyze">
    <div class="field">
      <label>File (xlsx / csv / pdf) — bisa banyak</label>
      <input type="file" name="files" multiple required accept=".xlsx,.xls,.csv,.pdf,.CSV,.PDF">
    </div>
    <button class="btn primary" type="submit">Analisa File →</button>
  </form>
</div>

{% if preview %}
<div class="card">
  <h3 style="margin:0 0 12px">Preview — konfirmasi jenis sebelum simpan</h3>
  <form method="post">
    {% csrf_token %}
    <input type="hidden" name="action" value="commit">
    <table>
      <thead><tr><th>File</th><th>Jenis terdeteksi</th><th>Keyakinan</th><th>DP/WD</th></tr></thead>
      <tbody>
      {% for p in preview %}
      <tr>
        <td>{{ p.name }}<input type="hidden" name="staged" value="{{ p.staged }}"></td>
        <td>
          <select name="parser_key" class="f">
            {% for pk in parsers %}<option value="{{ pk }}" {% if pk == p.parser_key %}selected{% endif %}>{{ pk }}</option>{% endfor %}
          </select>
        </td>
        <td>{% if p.needs_confirm %}<span class="badge warn">{{ p.confidence }}% — cek</span>{% else %}<span class="badge ok">{{ p.confidence }}%</span>{% endif %}</td>
        <td>
          <select name="flow" class="f">
            <option value="" {% if p.flow == '' %}selected{% endif %}>otomatis</option>
            <option value="dp" {% if p.flow == 'dp' %}selected{% endif %}>DP</option>
            <option value="wd" {% if p.flow == 'wd' %}selected{% endif %}>WD</option>
          </select>
        </td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
    <div class="field" style="margin-top:12px;max-width:260px">
      <label>Panel Provider (opsional)</label>
      <input type="text" name="provider" placeholder="mis. Nexus">
    </div>
    <button class="btn primary" type="submit">Simpan &amp; Parse ({{ preview|length }} file)</button>
  </form>
</div>
{% endif %}

{% block upload_history %}{% endblock %}
{% endblock %}
```

- [ ] **Step 5: Run tests**

Run: `python manage.py test web.tests_upload.UploadAnalyzeTests -v2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/views.py web/templates/web/upload.html web/tests_upload.py
git commit -m "feat(web): upload fase analyze — multi-file auto-detect + preview"
```

---

### Task B3: Upload — fase commit (ingest file ter-stage)

**Files:**
- Modify: `web/views.py` (`upload`, cabang commit)
- Test: `web/tests_upload.py` (tambah `UploadCommitTests`)

**Interfaces:**
- Consumes: `ingest` (A2), staged path dari B2.
- Produces: `upload` view menangani `POST action=commit` dengan list paralel `staged[]`, `parser_key[]`, `flow[]` + `provider` → memanggil `ingest(..., toko=active, provider=...)`, menghapus file staging, lalu redirect ke `upload`.

- [ ] **Step 1: Write the failing test**

```python
# web/tests_upload.py — tambahkan
from unittest.mock import patch
from datetime import datetime
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from sources import services
from sources.models import SourceType, Toko, Upload


_ROW = {
    "occurred_at": datetime(2026, 6, 27, 10, 0), "posted_date": None, "jenis": "depo",
    "amount": Decimal("50000"), "credit_delta": Decimal("-50000"), "money_delta": Decimal("50000"),
    "fee": Decimal("0"), "bonus": Decimal("0"), "balance_after": None, "ticket_no": "D1",
    "username": "budi", "reference": "", "counterparty": "", "description": "", "raw": {},
    "row_hash": "commit-row-1",
}


class _DummyBracket:
    source_key = "bracket"

    def parse(self, path, flow=""):
        return [dict(_ROW)]


class UploadCommitTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345")
        self.client.login(username="aud", password="pw12345")
        SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})
        self.lbs = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def test_commit_ingests_and_sets_toko(self):
        staged = default_storage.save("staging/x.csv", ContentFile(b"dummy"))
        with patch.dict(services.PARSERS, {"dummy": _DummyBracket}, clear=False):
            r = self.client.post(reverse("upload"), {
                "action": "commit", "staged": [staged],
                "parser_key": ["dummy"], "flow": [""], "provider": "Nexus",
            })
        self.assertEqual(r.status_code, 302)
        up = Upload.objects.latest("id")
        self.assertEqual(up.toko, self.lbs)
        self.assertEqual(up.provider, "Nexus")
        self.assertEqual(up.rows_parsed, 1)
        self.assertFalse(default_storage.exists(staged))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test web.tests_upload.UploadCommitTests -v2`
Expected: FAIL — tidak ada `Upload` terbaru / commit belum ditangani.

- [ ] **Step 3: Implement the commit branch**

```python
# web/views.py — di dalam upload(), tambahkan SEBELUM cabang analyze:
    if request.method == "POST" and request.POST.get("action") == "commit":
        staged = request.POST.getlist("staged")
        keys = request.POST.getlist("parser_key")
        flows = request.POST.getlist("flow")
        provider = request.POST.get("provider", "")
        n_ok = n_err = 0
        for path_rel, key, flow in zip(staged, keys, flows):
            if key not in PARSERS:
                n_err += 1
                continue
            try:
                ingest(
                    key, default_storage.path(path_rel), flow=flow,
                    user=request.user, toko=active, provider=provider,
                )
                n_ok += 1
            except Exception as e:  # noqa: BLE001 - tampilkan error parse ke user
                messages.error(request, f"{path_rel}: {e}")
                n_err += 1
            finally:
                if default_storage.exists(path_rel):
                    default_storage.delete(path_rel)
        messages.success(request, f"{n_ok} file diproses, {n_err} gagal.")
        return redirect("upload")
```

(`active` sudah didefinisikan di awal `upload()` dari Task B2.)

- [ ] **Step 4: Run tests**

Run: `python manage.py test web.tests_upload -v2`
Expected: PASS (analyze + commit).

- [ ] **Step 5: Commit**

```bash
git add web/views.py web/tests_upload.py
git commit -m "feat(web): upload fase commit — ingest file ter-stage per Toko"
```

---

### Task B4: Riwayat upload (tabel + filter Toko)

**Files:**
- Modify: `web/templates/web/upload.html` (isi block `upload_history`)
- Test: `web/tests_upload.py` (tambah `UploadHistoryTests`)

**Interfaces:**
- Consumes: context `uploads` (di-set di B2, sudah difilter `toko=active`).
- Produces: tabel riwayat di halaman upload menampilkan `original_name`, `source_type`, `provider`, `flow`, `rows_parsed`, `rows_duplicate`, `status`, `uploaded_by`, `created_at`.

- [ ] **Step 1: Write the failing test**

```python
# web/tests_upload.py — tambahkan
from sources.models import SourceType as ST


class UploadHistoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.u = User.objects.create_user("aud", "a@a.co", "pw12345")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.bracket = ST.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})[0]

    def test_history_scoped_to_active_toko(self):
        Upload.objects.create(source_type=self.bracket, toko=self.lbs, original_name="lbs-file.xlsx", uploaded_by=self.u)
        Upload.objects.create(source_type=self.bracket, toko=self.slo, original_name="slo-file.xlsx", uploaded_by=self.u)
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.get(reverse("upload"))
        self.assertContains(r, "lbs-file.xlsx")
        self.assertNotContains(r, "slo-file.xlsx")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test web.tests_upload.UploadHistoryTests -v2`
Expected: FAIL — halaman belum menampilkan `original_name`.

- [ ] **Step 3: Render the history table**

```html
<!-- web/templates/web/upload.html — ganti baris {% block upload_history %}{% endblock %} dengan: -->
{% load humanize %}
<div class="card">
  <h3 style="margin:0 0 12px">Riwayat Upload — {{ active_toko.name }}</h3>
  <table>
    <thead><tr><th>File</th><th>Jenis</th><th>Provider</th><th>DP/WD</th><th>Baris</th><th>Dup</th><th>Status</th><th>Oleh</th><th>Waktu</th></tr></thead>
    <tbody>
    {% for u in uploads %}
      <tr>
        <td>{{ u.original_name|default:u.pk }}</td>
        <td>{{ u.source_type.name }}</td>
        <td>{{ u.provider|default:"—" }}</td>
        <td>{{ u.flow|default:"—" }}</td>
        <td>{{ u.rows_parsed|intcomma }}</td>
        <td>{{ u.rows_duplicate|intcomma }}</td>
        <td>{% if u.status == 'parsed' %}<span class="badge ok">parsed</span>{% elif u.status == 'error' %}<span class="badge bad">error</span>{% else %}<span class="badge warn">{{ u.status }}</span>{% endif %}</td>
        <td>{{ u.uploaded_by.username|default:"—" }}</td>
        <td class="faint">{{ u.created_at|date:"d/m H:i" }}</td>
      </tr>
    {% empty %}
      <tr><td colspan="9" class="faint">Belum ada upload untuk toko ini.</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div>
```

- [ ] **Step 4: Run tests**

Run: `python manage.py test web.tests_upload -v2`
Expected: PASS (semua).

- [ ] **Step 5: Commit**

```bash
git add web/templates/web/upload.html web/tests_upload.py
git commit -m "feat(web): tabel riwayat upload difilter per Toko"
```

---

## Phase C — Rekonsiliasi paralel

### Task C1: Model `ReconBatch` + FK `MatchRun.batch`

**Files:**
- Modify: `reconciliation/models.py` (class `ReconBatch` + field `MatchRun.batch`)
- Modify: `reconciliation/admin.py` (registrasi)
- Create: migration skema (auto)
- Test: `reconciliation/tests_batch.py` (baru)

**Interfaces:**
- Consumes: `sources.models.Toko`, `ToleranceProfile`.
- Produces: `ReconBatch(toko, tolerance, date_from, date_to, summary: JSON, completeness: JSON, created_by)`; `MatchRun.batch -> FK(ReconBatch, related_name="runs", null=True)`.

- [ ] **Step 1: Write the failing test**

```python
# reconciliation/tests_batch.py
from django.test import TestCase

from reconciliation.models import MatchRun, ReconBatch, ToleranceProfile
from sources.models import Toko


class ReconBatchModelTests(TestCase):
    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(name="Default", defaults={"date_window_days": 1})[0]
        self.lbs = Toko.objects.get(key="lbs")

    def test_batch_links_runs(self):
        batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        run = MatchRun.objects.create(relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=batch)
        self.assertEqual(list(batch.runs.all()), [run])
        self.assertEqual(str(batch), f"Batch #{batch.pk}")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test reconciliation.tests_batch -v2`
Expected: FAIL — `ImportError: cannot import name 'ReconBatch'`.

- [ ] **Step 3: Add model + FK**

```python
# reconciliation/models.py — tambahkan field ke class MatchRun (setelah 'created_by'):
    batch = models.ForeignKey(
        "ReconBatch", on_delete=models.CASCADE, null=True, blank=True, related_name="runs"
    )

# reconciliation/models.py — tambahkan class baru di akhir file:
class ReconBatch(TimeStampedModel):
    """Satu sesi rekonsiliasi paralel untuk satu Toko + periode."""

    toko = models.ForeignKey("sources.Toko", on_delete=models.PROTECT, null=True, blank=True)
    tolerance = models.ForeignKey(ToleranceProfile, on_delete=models.PROTECT)
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
    summary = models.JSONField(default=dict)
    completeness = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True
    )

    def __str__(self):
        return f"Batch #{self.pk}"
```

- [ ] **Step 4: Register in admin**

```python
# reconciliation/admin.py — tambahkan
from .models import ReconBatch  # gabung dengan import yang ada

admin.site.register(ReconBatch)
```

- [ ] **Step 5: Create migration**

Run: `python manage.py makemigrations reconciliation`
Expected: CreateModel ReconBatch + AddField MatchRun.batch.

- [ ] **Step 6: Run tests**

Run: `python manage.py test reconciliation.tests_batch -v2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add reconciliation/models.py reconciliation/admin.py reconciliation/migrations/*.py reconciliation/tests_batch.py
git commit -m "feat(reconciliation): model ReconBatch + FK MatchRun.batch"
```

---

### Task C2: Scoping Toko di matcher + `check_completeness`

**Files:**
- Modify: `reconciliation/engine.py` (`_toko_filter`, `sides()`, `run_match`, `check_completeness`)
- Test: `reconciliation/tests_batch.py` (tambah `CompletenessTests`, `TokoScopeTests`)

**Interfaces:**
- Consumes: `Transaction.toko` (A2), `ReconBatch` (C1).
- Produces:
  - `run_match(relation, tolerance=None, date_from=None, date_to=None, user=None, toko=None, batch=None) -> MatchRun` (dua param baru).
  - `matcher.sides(dfrom, dto, toko=None)` (semua matcher).
  - `check_completeness(toko, date_from=None, date_to=None) -> dict` dengan kunci `panel_dp, panel_wd, panel, bracket, bank, gateway, minimum_met` (semua bool).

- [ ] **Step 1: Write the failing test**

```python
# reconciliation/tests_batch.py — tambahkan
from datetime import datetime
from decimal import Decimal

from reconciliation.engine import check_completeness, run_match
from sources.models import SourceType, Upload
from transactions.models import Transaction


class CompletenessTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _tx(self, st, jenis, money, rh):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.lbs, jenis=jenis,
            amount=Decimal("50000"), money_delta=Decimal(money),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash=rh,
        )

    def test_minimum_met_with_panel_and_bank(self):
        self._tx(self.panel, "depo", "50000", "c1")
        self._tx(self.bank, "depo", "50000", "c2")
        comp = check_completeness(self.lbs)
        self.assertTrue(comp["panel_dp"])
        self.assertTrue(comp["bank"])
        self.assertFalse(comp["bracket"])
        self.assertTrue(comp["minimum_met"])

    def test_minimum_not_met_panel_only(self):
        self._tx(self.panel, "depo", "50000", "c3")
        comp = check_completeness(self.lbs)
        self.assertFalse(comp["minimum_met"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test reconciliation.tests_batch.CompletenessTests -v2`
Expected: FAIL — `cannot import name 'check_completeness'`.

- [ ] **Step 3: Add toko scoping + completeness**

```python
# reconciliation/engine.py — tambahkan helper setelah _date_filter:
def _toko_filter(qs, toko):
    return qs.filter(toko=toko) if toko is not None else qs


def check_completeness(toko, date_from=None, date_to=None):
    qs = _toko_filter(Transaction.objects.filter(is_duplicate=False), toko)
    qs = _date_filter(qs, date_from, date_to)

    def has(**kw):
        return qs.filter(**kw).exists()

    comp = {
        "panel_dp": has(source_type__key="panel", jenis="depo"),
        "panel_wd": has(source_type__key="panel", jenis="wd"),
        "bracket": has(source_type__key="bracket"),
        "bank": has(source_type__key="bank"),
        "gateway": has(source_type__key="gateway"),
    }
    comp["panel"] = comp["panel_dp"] or comp["panel_wd"]
    comp["minimum_met"] = comp["panel"] and (comp["bank"] or comp["gateway"])
    return comp
```

```python
# reconciliation/engine.py — di PanelBracketMatcher.sides, tambahkan param toko & filter:
    def sides(self, dfrom, dto, toko=None):
        left = _date_filter(
            _toko_filter(Transaction.objects.filter(source_type__key="panel", is_duplicate=False), toko), dfrom, dto
        )
        right = _date_filter(
            _toko_filter(Transaction.objects.filter(source_type__key="bracket", is_duplicate=False).exclude(ticket_no=""), toko),
            dfrom, dto,
        )
        return list(left), list(right)
```

```python
# reconciliation/engine.py — di _MoneyMatcher.sides, tambahkan param toko & filter:
    def sides(self, dfrom, dto, toko=None):
        left = _date_filter(
            _toko_filter(
                Transaction.objects.filter(source_type__key=self.left_key, is_duplicate=False).filter(jenis__in=["depo", "wd"]),
                toko,
            ),
            dfrom, dto,
        )
        right = _date_filter(
            _toko_filter(Transaction.objects.filter(source_type__key__in=MONEY_SOURCES, is_duplicate=False), toko), dfrom, dto
        )
        return list(left), list(right)
```

```python
# reconciliation/engine.py — ganti signature & body run_match:
def run_match(relation, tolerance=None, date_from=None, date_to=None, user=None, toko=None, batch=None):
    tolerance = tolerance or ToleranceProfile.objects.get(name="Default")
    matcher = MATCHERS[relation]()
    run = MatchRun.objects.create(
        relation=relation, tolerance=tolerance, date_from=date_from, date_to=date_to,
        created_by=user, batch=batch,
    )
    left, right = matcher.sides(date_from, date_to, toko)
    results = matcher.match(run, left, right)
    with db_tx.atomic():
        MatchResult.objects.bulk_create(results, batch_size=2000)
    c = Counter(r.bucket for r in results)
    run.summary = {
        "left": len(left), "right": len(right),
        "cocok": c.get("cocok", 0),
        "perlu_tinjau": c.get("perlu_tinjau", 0),
        "tidak_cocok": c.get("tidak_cocok", 0),
    }
    run.save(update_fields=["summary"])
    return run
```

- [ ] **Step 4: Add the toko-scope test**

```python
# reconciliation/tests_batch.py — tambahkan
class TokoScopeTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.up = Upload.objects.create(source_type=self.panel)

    def test_completeness_isolated_per_toko(self):
        Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=self.lbs, jenis="depo",
            amount=Decimal("1"), money_delta=Decimal("1"),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash="lbs-only",
        )
        self.assertTrue(check_completeness(self.lbs)["panel_dp"])
        self.assertFalse(check_completeness(self.slo)["panel_dp"])
```

- [ ] **Step 5: Run tests**

Run: `python manage.py test reconciliation -v2`
Expected: PASS (test engine lama tetap lulus karena `toko=None` default = tanpa filter, dan `sides()` param baru punya default).

- [ ] **Step 6: Commit**

```bash
git add reconciliation/engine.py reconciliation/tests_batch.py
git commit -m "feat(reconciliation): scoping Toko di matcher + check_completeness"
```

---

### Task C3: Orkestrasi `run_batch` + agregasi ringkasan

**Files:**
- Modify: `reconciliation/engine.py` (`run_batch`, `_aggregate_batch`)
- Test: `reconciliation/tests_batch.py` (tambah `RunBatchTests`)

**Interfaces:**
- Consumes: `check_completeness`, `run_match`, `ReconBatch`, `MatchRun.Relation`.
- Produces: `run_batch(toko, tolerance=None, date_from=None, date_to=None, user=None) -> ReconBatch`. `batch.summary` = `{"dp": {"panel","money","selisih"}, "wd": {...}, "buckets": {"cocok","perlu_tinjau","tidak_cocok"}, "relations": [...], "skipped": [...]}`. Panel↔Bracket dilewati bila `completeness["bracket"]` false; Panel↔Bank dilewati bila tak ada bank & gateway.

- [ ] **Step 1: Write the failing test**

```python
# reconciliation/tests_batch.py — tambahkan
from reconciliation.engine import run_batch


class RunBatchTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(name="Default", defaults={"date_window_days": 1})[0]
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bracket = SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _tx(self, st, jenis, amount, money, ticket, rh, **kw):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.lbs, jenis=jenis,
            amount=Decimal(amount), money_delta=Decimal(money), ticket_no=ticket,
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash=rh, **kw,
        )

    def test_runs_both_relations_when_data_present(self):
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p1", username="budi")
        self._tx(self.bracket, "depo", "50000", "50000", "D1", "b1", username="budi")
        self._tx(self.bank, "depo", "50000", "50000", "", "k1", username="budi")
        batch = run_batch(self.lbs, self.tol)
        self.assertEqual(batch.runs.count(), 2)
        self.assertEqual(batch.summary["skipped"], [])
        self.assertEqual(batch.summary["dp"]["panel"], 50000.0)

    def test_skips_panel_bracket_when_no_bracket(self):
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p2", username="budi")
        self._tx(self.bank, "depo", "50000", "50000", "", "k2", username="budi")
        batch = run_batch(self.lbs, self.tol)
        self.assertEqual(batch.runs.count(), 1)
        self.assertIn("panel_bracket", batch.summary["skipped"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test reconciliation.tests_batch.RunBatchTests -v2`
Expected: FAIL — `cannot import name 'run_batch'`.

- [ ] **Step 3: Implement orchestration + aggregation**

```python
# reconciliation/engine.py — tambahkan import di atas
from django.db.models import Sum

# reconciliation/engine.py — tambahkan ReconBatch ke import model
from .models import MatchResult, MatchRun, ReconBatch, ToleranceProfile

# reconciliation/engine.py — tambahkan di akhir file:
def _aggregate_batch(toko, date_from, date_to, runs, skipped):
    tx = _date_filter(_toko_filter(Transaction.objects.filter(is_duplicate=False), toko), date_from, date_to)

    def total(qs, field):
        return float(qs.aggregate(x=Sum(field))["x"] or 0)

    panel = tx.filter(source_type__key="panel")
    money = tx.filter(source_type__key__in=MONEY_SOURCES)
    dp_panel = total(panel.filter(jenis="depo"), "amount")
    dp_money = total(money.filter(money_delta__gt=0), "money_delta")
    wd_panel = total(panel.filter(jenis="wd"), "amount")
    wd_money = abs(total(money.filter(money_delta__lt=0), "money_delta"))

    buckets = {"cocok": 0, "perlu_tinjau": 0, "tidak_cocok": 0}
    for r in runs:
        for k in buckets:
            buckets[k] += (r.summary or {}).get(k, 0)

    return {
        "dp": {"panel": dp_panel, "money": dp_money, "selisih": dp_panel - dp_money},
        "wd": {"panel": wd_panel, "money": wd_money, "selisih": wd_panel - wd_money},
        "buckets": buckets,
        "relations": [r.relation for r in runs],
        "skipped": skipped,
    }


def run_batch(toko, tolerance=None, date_from=None, date_to=None, user=None):
    tolerance = tolerance or ToleranceProfile.objects.get(name="Default")
    comp = check_completeness(toko, date_from, date_to)
    batch = ReconBatch.objects.create(
        toko=toko, tolerance=tolerance, date_from=date_from, date_to=date_to,
        created_by=user, completeness=comp,
    )
    relations, skipped = [], []
    if comp["bracket"]:
        relations.append(MatchRun.Relation.PANEL_BRACKET)
    else:
        skipped.append(MatchRun.Relation.PANEL_BRACKET.value)
    if comp["bank"] or comp["gateway"]:
        relations.append(MatchRun.Relation.PANEL_BANK)
    else:
        skipped.append(MatchRun.Relation.PANEL_BANK.value)

    runs = [
        run_match(rel, tolerance, date_from, date_to, user=user, toko=toko, batch=batch)
        for rel in relations
    ]
    batch.summary = _aggregate_batch(toko, date_from, date_to, runs, skipped)
    batch.save(update_fields=["summary"])
    return batch
```

- [ ] **Step 4: Run tests**

Run: `python manage.py test reconciliation.tests_batch -v2`
Expected: PASS (semua).

- [ ] **Step 5: Commit**

```bash
git add reconciliation/engine.py reconciliation/tests_batch.py
git commit -m "feat(reconciliation): run_batch paralel + agregasi selisih DP/WD"
```

---

### Task C4: Halaman Rekonsiliasi (checklist kelengkapan + jalankan batch)

**Files:**
- Modify: `web/views.py` (`reconcile`)
- Modify: `web/templates/web/reconcile.html`
- Test: `web/tests_reconcile.py` (baru)

**Interfaces:**
- Consumes: `_active_toko`, `check_completeness`, `run_batch`, `ReconBatch`, `ToleranceProfile`.
- Produces: `reconcile` view — GET menampilkan checklist `completeness` + form + riwayat `batches`; POST menjalankan `run_batch` lalu redirect ke `batch_detail`.

- [ ] **Step 1: Write the failing test**

```python
# web/tests_reconcile.py
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class ReconcileViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345")
        self.client.login(username="aud", password="pw12345")
        ToleranceProfile.objects.get_or_create(name="Default", defaults={"date_window_days": 1})
        self.lbs = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        up = Upload.objects.create(source_type=panel, toko=self.lbs)
        for st, rh in [(panel, "r1"), (bank, "r2")]:
            Transaction.objects.create(
                upload=up, source_type=st, toko=self.lbs, jenis="depo",
                amount=Decimal("50000"), money_delta=Decimal("50000"),
                occurred_at=datetime(2026, 6, 27, 10, 0), row_hash=rh,
            )

    def test_get_shows_completeness(self):
        r = self.client.get(reverse("reconcile"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["completeness"]["minimum_met"])

    def test_post_runs_batch_and_redirects(self):
        r = self.client.post(reverse("reconcile"), {"tolerance": "Default"})
        self.assertEqual(r.status_code, 302)
        batch = ReconBatch.objects.latest("id")
        self.assertEqual(r.url, reverse("batch_detail", args=[batch.pk]))
        self.assertEqual(batch.toko, self.lbs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test web.tests_reconcile -v2`
Expected: FAIL — `NoReverseMatch: 'batch_detail'` / view lama tak punya `completeness`.

- [ ] **Step 3: Rewrite the reconcile view**

```python
# web/views.py — tambah import
from reconciliation.engine import check_completeness, run_batch

# web/views.py — ganti seluruh fungsi reconcile dengan:
@login_required
def reconcile(request):
    active = _active_toko(request)
    if request.method == "POST":
        tol = ToleranceProfile.objects.get(name=request.POST.get("tolerance", "Default"))
        batch = run_batch(
            active, tol,
            request.POST.get("date_from") or None,
            request.POST.get("date_to") or None,
            user=request.user,
        )
        messages.success(request, f"Rekonsiliasi selesai (Batch #{batch.pk}).")
        return redirect("batch_detail", pk=batch.pk)

    df = request.GET.get("date_from") or None
    dt = request.GET.get("date_to") or None
    ctx = {
        "active_toko": active,
        "completeness": check_completeness(active, df, dt),
        "tolerances": ToleranceProfile.objects.all(),
        "batches": ReconBatch.objects.filter(toko=active).order_by("-id")[:20],
        "date_from": df or "", "date_to": dt or "",
    }
    return render(request, "web/reconcile.html", ctx)
```

Tambahkan `ReconBatch` ke import reconciliation.models yang sudah ada di atas file:
```python
from reconciliation.models import MatchResult, MatchRun, ReconBatch, ReviewAction, ToleranceProfile
```

- [ ] **Step 4: Rewrite the reconcile template**

```html
<!-- web/templates/web/reconcile.html -->
{% extends "web/app_base.html" %}
{% load humanize %}
{% block title %}Rekonsiliasi · Truth of Auditor{% endblock %}
{% block content %}
<div class="page-head">
  <h1>Rekonsiliasi — {{ active_toko.name }}</h1>
  <p>Jalankan Panel↔Bracket &amp; Panel↔Bank/Gateway sekaligus. Cek kelengkapan dulu.</p>
</div>

<div class="grid cols-2">
  <div class="card">
    <h3 style="margin:0 0 12px">Kelengkapan Data</h3>
    {% with c=completeness %}
    <table>
      <tr><td>Panel Deposit</td><td>{% if c.panel_dp %}<span class="badge ok">ada</span>{% else %}<span class="badge bad">kosong</span>{% endif %}</td></tr>
      <tr><td>Panel Withdraw</td><td>{% if c.panel_wd %}<span class="badge ok">ada</span>{% else %}<span class="badge bad">kosong</span>{% endif %}</td></tr>
      <tr><td>Bracket / FR</td><td>{% if c.bracket %}<span class="badge ok">ada</span>{% else %}<span class="badge warn">tidak ada → Panel↔Bracket dilewati</span>{% endif %}</td></tr>
      <tr><td>Bank</td><td>{% if c.bank %}<span class="badge ok">ada</span>{% else %}<span class="badge bad">kosong</span>{% endif %}</td></tr>
      <tr><td>Gateway</td><td>{% if c.gateway %}<span class="badge ok">ada</span>{% else %}<span class="badge warn">kosong</span>{% endif %}</td></tr>
    </table>
    {% if not c.minimum_met %}<div class="msg error" style="margin-top:12px">⚠ Minimum belum terpenuhi (butuh Panel + minimal 1 Bank/Gateway). Kamu masih boleh menjalankan.</div>{% endif %}
    {% endwith %}
  </div>

  <div class="card">
    <h3 style="margin:0 0 12px">Jalankan</h3>
    <form method="post">
      {% csrf_token %}
      <div class="field"><label>Profil Toleransi</label>
        <select name="tolerance" class="f">{% for t in tolerances %}<option value="{{ t.name }}">{{ t.name }} (±{{ t.date_window_days }} hari)</option>{% endfor %}</select></div>
      <div class="grid cols-2">
        <div class="field"><label>Dari tanggal</label><input type="date" name="date_from" value="{{ date_from }}"></div>
        <div class="field"><label>Sampai tanggal</label><input type="date" name="date_to" value="{{ date_to }}"></div>
      </div>
      <button class="btn primary" type="submit">▶ Jalankan Rekonsiliasi</button>
    </form>
  </div>
</div>

<div class="card">
  <h3 style="margin:0 0 12px">Riwayat Batch</h3>
  <table>
    <thead><tr><th>Batch</th><th>Waktu</th><th>DP selisih</th><th>WD selisih</th><th>Cocok</th></tr></thead>
    <tbody>
    {% for b in batches %}
      <tr>
        <td><a href="{% url 'batch_detail' b.pk %}">#{{ b.pk }}</a></td>
        <td class="faint">{{ b.created_at|date:"d/m H:i" }}</td>
        <td>{{ b.summary.dp.selisih|default:0|floatformat:0|intcomma }}</td>
        <td>{{ b.summary.wd.selisih|default:0|floatformat:0|intcomma }}</td>
        <td>{{ b.summary.buckets.cocok|default:0|intcomma }}</td>
      </tr>
    {% empty %}<tr><td colspan="5" class="faint">Belum ada batch.</td></tr>{% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests** (butuh `batch_detail` dari Task C5 agar `NoReverseMatch` hilang)

Run: `python manage.py test web.tests_reconcile -v2`
Expected: masih FAIL pada `NoReverseMatch: 'batch_detail'` — akan lulus setelah Task C5. Lanjut ke C5 sebelum commit gabungan, ATAU commit view/template dulu dan tandai test xfail sementara. **Rekomendasi:** kerjakan C5 lalu jalankan test C4+C5 bersama.

- [ ] **Step 6: Commit**

```bash
git add web/views.py web/templates/web/reconcile.html web/tests_reconcile.py
git commit -m "feat(web): halaman rekonsiliasi — checklist kelengkapan + jalankan batch"
```

---

### Task C5: Halaman detail Batch

**Files:**
- Modify: `web/views.py` (`batch_detail`)
- Modify: `web/urls.py` (route `batch_detail`)
- Create: `web/templates/web/batch_detail.html`
- Test: `web/tests_reconcile.py` (tambah `BatchDetailTests`)

**Interfaces:**
- Consumes: `ReconBatch` + `batch.summary` (C3), `run_detail`/`export_run` (sudah ada).
- Produces: view `batch_detail(request, pk)` (name=`batch_detail`); halaman menampilkan kartu DP/WD (panel/money/selisih), total bucket, tautan ke tiap `run_detail`, dan relasi yang dilewati.

- [ ] **Step 1: Write the failing test**

```python
# web/tests_reconcile.py — tambahkan
from reconciliation.engine import run_batch


class BatchDetailTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345")
        self.client.login(username="aud", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(name="Default", defaults={"date_window_days": 1})[0]
        self.lbs = Toko.objects.get(key="lbs")
        panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        up = Upload.objects.create(source_type=panel, toko=self.lbs)
        for st, rh in [(panel, "d1"), (bank, "d2")]:
            Transaction.objects.create(
                upload=up, source_type=st, toko=self.lbs, jenis="depo",
                amount=Decimal("50000"), money_delta=Decimal("50000"),
                occurred_at=datetime(2026, 6, 27, 10, 0), row_hash=rh,
            )

    def test_batch_detail_renders(self):
        batch = run_batch(self.lbs, self.tol)
        r = self.client.get(reverse("batch_detail", args=[batch.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Deposit")
        self.assertContains(r, "Withdraw")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test web.tests_reconcile.BatchDetailTests -v2`
Expected: FAIL — `NoReverseMatch: 'batch_detail'`.

- [ ] **Step 3: Add view + URL**

```python
# web/views.py — tambahkan
@login_required
def batch_detail(request, pk):
    batch = get_object_or_404(ReconBatch, pk=pk)
    return render(request, "web/batch_detail.html", {
        "batch": batch, "s": batch.summary or {}, "runs": batch.runs.all(),
    })
```

```python
# web/urls.py — tambahkan ke urlpatterns
    path("batch/<int:pk>/", views.batch_detail, name="batch_detail"),
```

- [ ] **Step 4: Create the template**

```html
<!-- web/templates/web/batch_detail.html -->
{% extends "web/app_base.html" %}
{% load humanize %}
{% block title %}Batch #{{ batch.pk }} · Rekonsiliasi{% endblock %}
{% block content %}
<div class="page-head">
  <h1>Batch #{{ batch.pk }} — {{ batch.toko.name }}</h1>
  <p>{{ batch.created_at|date:"d/m/Y H:i" }} · Toleransi {{ batch.tolerance.name }}</p>
</div>

<div class="grid cols-2">
  <div class="card">
    <h3 style="margin:0 0 12px">Deposit (DP)</h3>
    <table>
      <tr><td>Panel (koin)</td><td>{{ s.dp.panel|default:0|floatformat:0|intcomma }}</td></tr>
      <tr><td>Uang real</td><td>{{ s.dp.money|default:0|floatformat:0|intcomma }}</td></tr>
      <tr><td><b>Selisih</b></td><td>{% if s.dp.selisih == 0 %}<span class="badge ok">Balanced ✓</span>{% else %}<span class="badge warn">{{ s.dp.selisih|floatformat:0|intcomma }}</span>{% endif %}</td></tr>
    </table>
  </div>
  <div class="card">
    <h3 style="margin:0 0 12px">Withdraw (WD)</h3>
    <table>
      <tr><td>Panel (koin)</td><td>{{ s.wd.panel|default:0|floatformat:0|intcomma }}</td></tr>
      <tr><td>Uang real</td><td>{{ s.wd.money|default:0|floatformat:0|intcomma }}</td></tr>
      <tr><td><b>Selisih</b></td><td>{% if s.wd.selisih == 0 %}<span class="badge ok">Balanced ✓</span>{% else %}<span class="badge warn">{{ s.wd.selisih|floatformat:0|intcomma }}</span>{% endif %}</td></tr>
    </table>
  </div>
</div>

<div class="card">
  <h3 style="margin:0 0 12px">Ringkasan Bucket</h3>
  <span class="badge ok">{{ s.buckets.cocok|default:0|intcomma }} cocok</span>
  <span class="badge warn">{{ s.buckets.perlu_tinjau|default:0|intcomma }} tinjau</span>
  <span class="badge bad">{{ s.buckets.tidak_cocok|default:0|intcomma }} tidak cocok</span>
  {% if s.skipped %}<p class="faint" style="margin-top:10px">Dilewati (data tidak ada): {{ s.skipped|join:", " }}</p>{% endif %}
</div>

<div class="card">
  <h3 style="margin:0 0 12px">Relasi</h3>
  <table>
    <thead><tr><th>Relasi</th><th>Cocok</th><th>Tinjau</th><th>Tidak</th><th></th></tr></thead>
    <tbody>
    {% for run in runs %}
      <tr>
        <td>{{ run.get_relation_display }}</td>
        <td>{{ run.summary.cocok|default:0|intcomma }}</td>
        <td>{{ run.summary.perlu_tinjau|default:0|intcomma }}</td>
        <td>{{ run.summary.tidak_cocok|default:0|intcomma }}</td>
        <td><a class="btn" href="{% url 'run_detail' run.pk %}">Detail →</a> <a class="btn" href="{% url 'export_run' run.pk %}">Excel</a></td>
      </tr>
    {% empty %}<tr><td colspan="5" class="faint">Tidak ada relasi dijalankan.</td></tr>{% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

- [ ] **Step 5: Run C4 + C5 tests together**

Run: `python manage.py test web.tests_reconcile -v2`
Expected: PASS (ReconcileViewTests + BatchDetailTests).

- [ ] **Step 6: Full regression**

Run: `python manage.py test -v1`
Expected: PASS (semua app).

- [ ] **Step 7: Commit**

```bash
git add web/views.py web/urls.py web/templates/web/batch_detail.html web/tests_reconcile.py
git commit -m "feat(web): halaman detail batch — kartu DP/WD selisih + bucket + relasi"
```

---

## Phase D — Konsistensi Toko di halaman lain

### Task D1: Scope Transaksi & Dashboard ke Toko aktif + template terang

**Files:**
- Modify: `web/views.py` (`dashboard`, `transactions` — filter `toko=active`)
- Modify: `web/templates/web/transactions.html` (extend `app_base.html`)
- Modify: `web/templates/web/run_detail.html` (extend `app_base.html`)
- Test: `web/tests_scope.py` (baru)

**Interfaces:**
- Consumes: `_active_toko`.
- Produces: `dashboard` & `transactions` menghitung/menampilkan hanya data toko aktif.

- [ ] **Step 1: Write the failing test**

```python
# web/tests_scope.py
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class ScopeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        up = Upload.objects.create(source_type=panel, toko=self.lbs)
        Transaction.objects.create(
            upload=up, source_type=panel, toko=self.lbs, jenis="depo", username="lbsuser",
            amount=Decimal("1"), money_delta=Decimal("1"),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash="lbs-tx",
        )
        Transaction.objects.create(
            upload=up, source_type=panel, toko=self.slo, jenis="depo", username="slouser",
            amount=Decimal("1"), money_delta=Decimal("1"),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash="slo-tx",
        )

    def test_transactions_scoped_to_active_toko(self):
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.get(reverse("transactions"))
        self.assertContains(r, "lbsuser")
        self.assertNotContains(r, "slouser")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test web.tests_scope -v2`
Expected: FAIL — `slouser` ikut tampil (belum difilter toko).

- [ ] **Step 3: Filter both views by active toko**

```python
# web/views.py — di dashboard(), tambahkan di awal:
    active = _active_toko(request)
# lalu tambahkan `.filter(toko=active)` pada queryset Transaction, Upload, dan MatchRun/ReconBatch relevan, mis:
#   Transaction.objects.filter(toko=active)...  (by_source & tx_total)
#   Upload.objects.filter(toko=active)...
# dan tambahkan "active_toko": active ke ctx.

# web/views.py — di transactions(), ganti baris qs awal menjadi:
    active = _active_toko(request)
    qs = Transaction.objects.filter(toko=active).select_related("source_type").order_by("-occurred_at")
```

- [ ] **Step 4: Point remaining working templates at the light layout**

```html
<!-- web/templates/web/transactions.html — ganti baris pertama menjadi -->
{% extends "web/app_base.html" %}
```
```html
<!-- web/templates/web/run_detail.html — ganti baris pertama menjadi -->
{% extends "web/app_base.html" %}
```

- [ ] **Step 5: Run tests**

Run: `python manage.py test web.tests_scope -v2`
Expected: PASS.

- [ ] **Step 6: Full regression**

Run: `python manage.py test -v1`
Expected: PASS (semua app).

- [ ] **Step 7: Commit**

```bash
git add web/views.py web/templates/web/transactions.html web/templates/web/run_detail.html web/tests_scope.py
git commit -m "feat(web): scope Dashboard & Transaksi ke Toko aktif + layout terang"
```

---

## Self-Review (untuk penulis rencana — sudah dijalankan)

**Spec coverage:**
- Model Toko → A1; FK di Upload/Transaction/Account + provider → A2; selektor Toko global → A3.
- Upload satu drop-zone multi-file auto-detect → B1 (detektor) + B2 (analyze/preview); commit → B3; history → B4; fallback "tebak + konfirmasi" → B2 (`needs_confirm` + dropdown editable).
- ReconBatch → C1; scoping Toko + completeness → C2; run_batch paralel + skip Bracket + agregasi selisih → C3; halaman checklist + soft-gate → C4; detail batch (DP/WD/bucket/nilai/relasi) → C5.
- Tema terang + scoping halaman lain → A3 + D1.
- Non-goals (BNI/Credit Bonus/Panel Provider parser, halaman turunan) tidak dibuatkan task — sesuai spec.

**Placeholder scan:** tidak ada TBD/TODO; semua step berisi kode nyata. Nomor migration di A2 Step 6 sengaja ditandai "ganti ke nama sebenarnya" karena bergantung output `makemigrations` lokal — ini instruksi eksplisit, bukan placeholder kode.

**Type consistency:** `detect_source` mengembalikan `[{"parser_key","confidence"}]` (B1) dan dipakai konsisten di B2. `check_completeness` kunci dipakai sama di C2/C3/C4. `run_batch(toko, tolerance, date_from, date_to, user)` dipakai identik di C3/C4/C5. `batch.summary` bentuknya sama antara C3 (produsen) dan C4/C5 (konsumen).

**Catatan urutan:** Task C4 baru lulus test setelah C5 (butuh route `batch_detail`) — didokumentasikan di C4 Step 5. Kerjakan C4→C5 berurutan, jalankan test bersama di C5 Step 5.
