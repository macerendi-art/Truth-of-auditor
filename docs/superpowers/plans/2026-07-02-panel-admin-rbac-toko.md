# Panel Admin + RBAC Toko — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin mengelola user (3 peran: admin/supervisor/auditor) dan 16+ toko dari dalam aplikasi; auditor hanya melihat toko yang ditugaskan; admin bisa menghapus upload & laporan rekonsiliasi.

**Architecture:** RBAC lewat satu helper `tokos_for(user)` (web/access.py) yang membatasi `_active_toko`/`set_toko`/dropdown; area `/kelola/…` digate decorator `admin_required`; hapus data memanfaatkan CASCADE yang sudah ada (Upload→Transaction→MatchResult; ReconBatch→MatchRun→MatchResult).

**Tech Stack:** Django 5.2 (function views + manual `request.POST`, TANPA Django Forms — ikuti pola `web/views.py`), template extend `web/app_base.html` dengan design system yang ada, `django.test.TestCase`.

**Spec:** `docs/superpowers/specs/2026-07-02-panel-admin-rbac-toko-design.md`

## Global Constraints

- Python: `.venv/bin/python` (semua perintah manage.py lewat ini).
- Test: `.venv/bin/python manage.py test` — baseline saat ini **54 test OK**; setiap task diakhiri suite hijau penuh.
- Copy UI bahasa Indonesia; istilah "kredit" (bukan "credit") bila muncul.
- Role string persis: `"admin"`, `"supervisor"`, `"auditor"`. Password minimal **8** karakter. Auditor wajib **≥1** toko.
- 16 kode toko (seed, `key`=lowercase, `name`=UPPERCASE): AHK MUL STN LBS W25 M25 MXW HKS BWN LTN WLG SSN CTR SLO G25 K25.
- Commit conventional (`feat:`/`test:`/`docs:` + scope) diakhiri `Co-Authored-By: Claude <noreply@anthropic.com>`; **setiap task diakhiri `git push`** (tim menarik dari GitHub).
- Tanpa hapus permanen user/toko; hapus hanya untuk Upload & ReconBatch, admin-only, via POST.

---

### Task 1: Model — Role SUPERVISOR + `allowed_tokos` M2M

**Files:**
- Modify: `accounts/models.py`
- Modify: `accounts/admin.py`
- Create: `accounts/migrations/0002_user_supervisor_allowed_tokos.py` (via makemigrations)
- Test: `accounts/tests.py` (overwrite — saat ini kosong/boilerplate)

**Interfaces:**
- Produces: `User.Role.SUPERVISOR == "supervisor"`; `user.allowed_tokos` (M2M ke `sources.Toko`, related_name `assigned_users`). Dipakai Task 3+.

- [ ] **Step 1: Tulis failing test**

`accounts/tests.py` (ganti seluruh isi):

```python
from django.contrib.auth import get_user_model
from django.test import TestCase

from sources.models import Toko

User = get_user_model()


class UserRbacModelTests(TestCase):
    def test_supervisor_role_choice(self):
        u = User.objects.create_user("sup", password="pw123456", role="supervisor")
        self.assertEqual(u.get_role_display(), "Supervisor")

    def test_allowed_tokos_m2m(self):
        u = User.objects.create_user("aud1", password="pw123456", role="auditor")
        lbs = Toko.objects.get(key="lbs")
        u.allowed_tokos.add(lbs)
        self.assertEqual(list(u.allowed_tokos.all()), [lbs])
        self.assertIn(u, lbs.assigned_users.all())
```

- [ ] **Step 2: Jalankan test — harus FAIL**

Run: `.venv/bin/python manage.py test accounts -v 1`
Expected: ERROR/FAIL (`allowed_tokos` tidak ada; display "Supervisor" tidak dikenal).

- [ ] **Step 3: Implementasi model**

`accounts/models.py` — ganti class Role dan tambah field (hasil akhir file):

```python
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Anggota tim audit. Akun dibuat admin (tanpa signup publik)."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        SUPERVISOR = "supervisor", "Supervisor"
        AUDITOR = "auditor", "Auditor"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.AUDITOR)
    allowed_tokos = models.ManyToManyField(
        "sources.Toko",
        blank=True,
        related_name="assigned_users",
        help_text="Toko yang boleh diakses (hanya relevan untuk auditor)",
    )

    def __str__(self):
        return self.username
```

`accounts/admin.py` — ganti seluruh isi:

```python
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active")
    filter_horizontal = UserAdmin.filter_horizontal + ("allowed_tokos",)
    fieldsets = UserAdmin.fieldsets + (("Audit", {"fields": ("role", "allowed_tokos")}),)
```

- [ ] **Step 4: Buat & jalankan migration**

Run: `.venv/bin/python manage.py makemigrations accounts -n user_supervisor_allowed_tokos && .venv/bin/python manage.py migrate`
Expected: file `accounts/migrations/0002_user_supervisor_allowed_tokos.py` dibuat (AlterField role + AddField allowed_tokos), migrate OK.

- [ ] **Step 5: Jalankan test — harus PASS, lalu full suite**

Run: `.venv/bin/python manage.py test accounts -v 1` → PASS (2 test).
Run: `.venv/bin/python manage.py test` → 56 test OK.

- [ ] **Step 6: Commit + push**

```bash
git add accounts/ && git commit -m "feat(accounts): role Supervisor + M2M allowed_tokos untuk RBAC toko

Co-Authored-By: Claude <noreply@anthropic.com>" && git push
```

---

### Task 2: Seed 16 toko (data-migration idempotent)

**Files:**
- Create: `sources/migrations/0007_seed_16_toko.py`
- Test: `sources/tests_toko.py` (tambah method di class `TokoModelTests` yang sudah ada)

**Interfaces:**
- Produces: 16 Toko aktif di DB (key lowercase). Task 4+ mengandalkan `Toko.objects.get(key="ahk")` dll.

- [ ] **Step 1: Tulis failing test** — tambahkan ke `sources/tests_toko.py` di dalam `class TokoModelTests(TestCase):`

```python
    def test_seed_16_toko(self):
        keys = {
            "ahk", "mul", "stn", "lbs", "w25", "m25", "mxw", "hks",
            "bwn", "ltn", "wlg", "ssn", "ctr", "slo", "g25", "k25",
        }
        have = set(Toko.objects.values_list("key", flat=True))
        self.assertTrue(keys <= have, f"kurang: {keys - have}")
        self.assertEqual(Toko.objects.get(key="ahk").name, "AHK")
        self.assertEqual(Toko.objects.filter(key="lbs").count(), 1)  # tidak duplikat
```

- [ ] **Step 2: Run — FAIL** (`kurang: {'ahk', ...}`): `.venv/bin/python manage.py test sources.tests_toko -v 1`

- [ ] **Step 3: Buat migration kosong lalu isi**

Run: `.venv/bin/python manage.py makemigrations sources --empty -n seed_16_toko`

Isi `sources/migrations/0007_seed_16_toko.py`:

```python
from django.db import migrations

KODE = [
    "AHK", "MUL", "STN", "LBS", "W25", "M25", "MXW", "HKS",
    "BWN", "LTN", "WLG", "SSN", "CTR", "SLO", "G25", "K25",
]


def seed(apps, schema_editor):
    Toko = apps.get_model("sources", "Toko")
    for k in KODE:
        Toko.objects.get_or_create(key=k.lower(), defaults={"name": k.upper()})


def unseed(apps, schema_editor):
    Toko = apps.get_model("sources", "Toko")
    keep = {"lbs", "slo"}  # seed lama (0004) tetap
    Toko.objects.filter(key__in=[k.lower() for k in KODE if k.lower() not in keep]).delete()


class Migration(migrations.Migration):
    dependencies = [("sources", "0006_backfill_toko")]
    operations = [migrations.RunPython(seed, unseed)]
```

- [ ] **Step 4: Migrate + test PASS**

Run: `.venv/bin/python manage.py migrate && .venv/bin/python manage.py test sources.tests_toko -v 1` → PASS.
Run full: `.venv/bin/python manage.py test` → OK. **Catatan:** bila ada test lama gagal karena kini ada 16 toko (mis. asumsi dropdown), catat — Task 4 memperbaiki test user; JANGAN ubah logika produksi untuk menyenangkan test lama.

- [ ] **Step 5: Commit + push**

```bash
git add sources/ && git commit -m "feat(sources): seed 16 kode toko (idempotent, LBS/SLO tak duplikat)

Co-Authored-By: Claude <noreply@anthropic.com>" && git push
```

---

### Task 3: `web/access.py` — `tokos_for`, `is_admin`, `admin_required`

**Files:**
- Create: `web/access.py`
- Create: `web/tests_access.py`

**Interfaces:**
- Produces:
  - `tokos_for(user) -> QuerySet[Toko]` — toko aktif yang boleh diakses; anonymous → kosong; admin/superuser/supervisor → semua aktif (order by name); auditor → `allowed_tokos` aktif.
  - `is_admin(user) -> bool` — authenticated dan (superuser atau role=="admin").
  - `admin_required(view)` — decorator: belum login → redirect login (perilaku `login_required`); login non-admin → `messages.error("Akses ditolak — khusus admin.")` + redirect `dashboard`.
- Consumes: `User.allowed_tokos` (Task 1), seed toko (Task 2).

- [ ] **Step 1: Tulis failing test** — `web/tests_access.py`:

```python
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import Toko
from web.access import is_admin, tokos_for

User = get_user_model()
N_AKTIF = 16  # hasil seed Task 2


class TokosForTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.admin = User.objects.create_user("adm", password="pw123456", role="admin")
        self.sup = User.objects.create_user("sup", password="pw123456", role="supervisor")
        self.aud = User.objects.create_user("aud1", password="pw123456", role="auditor")
        self.aud.allowed_tokos.add(self.lbs)

    def test_admin_sees_all_active(self):
        self.assertEqual(tokos_for(self.admin).count(), N_AKTIF)

    def test_supervisor_sees_all_active(self):
        self.assertEqual(tokos_for(self.sup).count(), N_AKTIF)

    def test_auditor_sees_only_assigned(self):
        self.assertEqual(list(tokos_for(self.aud)), [self.lbs])

    def test_auditor_loses_inactive_toko(self):
        self.lbs.is_active = False
        self.lbs.save(update_fields=["is_active"])
        self.assertEqual(tokos_for(self.aud).count(), 0)

    def test_is_admin(self):
        self.assertTrue(is_admin(self.admin))
        self.assertFalse(is_admin(self.sup))
        self.assertFalse(is_admin(self.aud))
```

- [ ] **Step 2: Run — FAIL** (`No module named 'web.access'`): `.venv/bin/python manage.py test web.tests_access -v 1`

- [ ] **Step 3: Implementasi** — `web/access.py`:

```python
"""Kontrol akses berbasis peran (RBAC) per Toko."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from sources.models import Toko


def is_admin(user) -> bool:
    return bool(user.is_authenticated and (user.is_superuser or user.role == "admin"))


def tokos_for(user):
    """Queryset Toko aktif yang boleh diakses user — satu-satunya sumber kebenaran RBAC."""
    qs = Toko.objects.filter(is_active=True).order_by("name")
    if not user.is_authenticated:
        return qs.none()
    if user.is_superuser or user.role in ("admin", "supervisor"):
        return qs
    return qs.filter(assigned_users=user)


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not is_admin(request.user):
            messages.error(request, "Akses ditolak — khusus admin.")
            return redirect("dashboard")
        return view(request, *args, **kwargs)

    return wrapper
```

- [ ] **Step 4: Run test PASS** lalu full suite: `.venv/bin/python manage.py test web.tests_access -v 1 && .venv/bin/python manage.py test`

- [ ] **Step 5: Commit + push**

```bash
git add web/access.py web/tests_access.py && git commit -m "feat(web): access.py — tokos_for + admin_required (inti RBAC)

Co-Authored-By: Claude <noreply@anthropic.com>" && git push
```

---

### Task 4: Enforcement RBAC di scoping + empty-state + migrasi test lama

**Files:**
- Modify: `web/context_processors.py`
- Modify: `web/views.py` (`_active_toko`, `set_toko`, guard `active is None` di `dashboard`/`upload`/`transactions`/`reconcile`)
- Create: `web/templates/web/no_toko.html`
- Modify: `web/tests.py`, `web/tests_scope.py`, `web/tests_upload.py`, `web/tests_reconcile.py` (user `aud` → `role="supervisor"`)
- Test: `web/tests_access.py` (tambah class)

**Interfaces:**
- Consumes: `tokos_for`, `is_admin` (Task 3).
- Produces: context template `all_tokos` (terfilter RBAC), `active_toko`, `is_admin_user` (bool — dipakai Task 8/9/10 untuk render kondisional). `_active_toko(request)` bisa mengembalikan `None` → view merender `web/no_toko.html`.

- [ ] **Step 1: Tulis failing test** — tambah di `web/tests_access.py`:

```python
class RbacScopeTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.aud = User.objects.create_user("aud1", password="pw123456", role="auditor")
        self.aud.allowed_tokos.add(self.lbs)
        self.client.login(username="aud1", password="pw123456")

    def test_set_toko_denied_for_unassigned(self):
        self.client.post(reverse("set_toko"), {"toko_id": self.slo.id})
        self.assertNotEqual(self.client.session.get("active_toko_id"), self.slo.id)

    def test_set_toko_allowed_for_assigned(self):
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.assertEqual(self.client.session.get("active_toko_id"), self.lbs.id)

    def test_dropdown_only_assigned(self):
        r = self.client.get(reverse("dashboard"))
        self.assertEqual([t.key for t in r.context["all_tokos"]], ["lbs"])

    def test_auditor_without_toko_gets_empty_state(self):
        User.objects.create_user("aud0", password="pw123456", role="auditor")
        self.client.login(username="aud0", password="pw123456")
        for name in ("dashboard", "upload", "transactions", "reconcile"):
            r = self.client.get(reverse(name))
            self.assertContains(r, "Tidak ada toko yang ditugaskan", msg_prefix=name)

    def test_supervisor_dropdown_all(self):
        User.objects.create_user("sup1", password="pw123456", role="supervisor")
        self.client.login(username="sup1", password="pw123456")
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(len(r.context["all_tokos"]), N_AKTIF)

    def test_revoked_session_toko_falls_back(self):
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.aud.allowed_tokos.clear()  # akses dicabut
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "Tidak ada toko yang ditugaskan")
```

- [ ] **Step 2: Run — FAIL**: `.venv/bin/python manage.py test web.tests_access -v 1` (set_toko masih mengizinkan; dropdown berisi 16).

- [ ] **Step 3: Implementasi**

`web/context_processors.py` — ganti seluruh isi:

```python
from web.access import is_admin, tokos_for


def toko(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"all_tokos": [], "active_toko": None, "is_admin_user": False}
    tokos = list(tokos_for(user))
    active_id = request.session.get("active_toko_id")
    active = next((t for t in tokos if t.id == active_id), tokos[0] if tokos else None)
    return {"all_tokos": tokos, "active_toko": active, "is_admin_user": is_admin(user)}
```

`web/views.py` — tambah import `from web.access import tokos_for` (di blok import atas), lalu ganti `_active_toko` + `set_toko`:

```python
def _active_toko(request):
    allowed = tokos_for(request.user)
    tid = request.session.get("active_toko_id")
    t = allowed.filter(id=tid).first() if tid else None
    return t or allowed.first()


@login_required
def set_toko(request):
    if request.method == "POST":
        tid = request.POST.get("toko_id")
        if tid and tokos_for(request.user).filter(id=tid).exists():
            request.session["active_toko_id"] = int(tid)
    return redirect(request.POST.get("next") or "dashboard")
```

Guard empty-state — tambahkan **tepat setelah** `active = _active_toko(request)` di 4 view (`dashboard`, `upload`, `transactions`, `reconcile`):

```python
    if active is None:
        return render(request, "web/no_toko.html")
```

(Catatan `transactions`: saat ini tidak menyimpan `active` ke variabel? Sudah: `active = _active_toko(request)` baris pertama — cukup tambah guard setelahnya.)

Buat `web/templates/web/no_toko.html`:

```html
{% extends "web/app_base.html" %}
{% block title %}Tidak Ada Toko · Truth of Auditor{% endblock %}
{% block crumb %}Tidak ada akses toko{% endblock %}
{% block content %}
<div class="card reveal" style="text-align:center;padding:56px 24px">
  <h2 style="margin:0 0 8px">Tidak ada toko yang ditugaskan</h2>
  <p class="muted" style="margin:0">Akunmu belum punya akses ke toko mana pun. Hubungi admin untuk penugasan toko.</p>
</div>
{% endblock %}
```

Catatan template: `app_base.html` topbar memakai `all_tokos` — saat kosong, dropdown kosong tapi tetap render; tidak perlu diubah.

- [ ] **Step 4: Migrasi test lama** — di 4 file (`web/tests.py`, `web/tests_scope.py`, `web/tests_upload.py` [3 class], `web/tests_reconcile.py` [2 class]) ganti setiap:

```python
User.objects.create_user("aud", "a@a.co", "pw12345")
```
menjadi:
```python
User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
```
(termasuk bentuk `self.u = User.objects.create_user(...)`). Alasan: user test perlu melihat semua toko; `supervisor` = akses semua tanpa hak admin, perilaku scoping lain tak berubah.

- [ ] **Step 5: Run — PASS semua**: `.venv/bin/python manage.py test` → OK (≥63 test).

- [ ] **Step 6: Commit + push**

```bash
git add web/ && git commit -m "feat(web): enforce RBAC toko di scoping + empty-state tanpa toko

Co-Authored-By: Claude <noreply@anthropic.com>" && git push
```

---

### Task 5: Kelola Toko — `/kelola/toko/`

**Files:**
- Create: `web/admin_views.py`
- Create: `web/templates/web/kelola/toko.html`
- Modify: `web/urls.py`
- Create: `web/tests_kelola.py`

**Interfaces:**
- Consumes: `admin_required` (Task 3).
- Produces: URL name `kelola_toko` (dipakai sidebar Task 8). View POST action `create` (field `kode`) dan `toggle` (field `toko_id`).

- [ ] **Step 1: Tulis failing test** — `web/tests_kelola.py`:

```python
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import Toko

User = get_user_model()


class KelolaTokoAccessTests(TestCase):
    def test_auditor_dan_supervisor_ditolak(self):
        for role in ("auditor", "supervisor"):
            User.objects.create_user(f"u_{role}", password="pw123456", role=role)
            self.client.login(username=f"u_{role}", password="pw123456")
            r = self.client.get(reverse("kelola_toko"), follow=True)
            self.assertContains(r, "Akses ditolak")

    def test_admin_diizinkan(self):
        User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        r = self.client.get(reverse("kelola_toko"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Kelola Toko")


class KelolaTokoCrudTests(TestCase):
    def setUp(self):
        User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")

    def test_create_toko(self):
        self.client.post(reverse("kelola_toko"), {"action": "create", "kode": "zz9"})
        t = Toko.objects.get(key="zz9")
        self.assertEqual(t.name, "ZZ9")
        self.assertTrue(t.is_active)

    def test_create_duplikat_ditolak(self):
        self.client.post(reverse("kelola_toko"), {"action": "create", "kode": "LBS"})
        self.assertEqual(Toko.objects.filter(key="lbs").count(), 1)

    def test_create_kode_kosong_ditolak(self):
        n = Toko.objects.count()
        self.client.post(reverse("kelola_toko"), {"action": "create", "kode": "  "})
        self.assertEqual(Toko.objects.count(), n)

    def test_toggle_aktif(self):
        t = Toko.objects.get(key="lbs")
        self.client.post(reverse("kelola_toko"), {"action": "toggle", "toko_id": t.id})
        t.refresh_from_db()
        self.assertFalse(t.is_active)
```

- [ ] **Step 2: Run — FAIL** (`kelola_toko` bukan URL): `.venv/bin/python manage.py test web.tests_kelola -v 1`

- [ ] **Step 3: Implementasi**

`web/admin_views.py` (baru):

```python
"""Panel admin: kelola pengguna & toko, hapus data. Semua view digate admin_required."""
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from sources.models import Toko
from web.access import admin_required


@admin_required
def kelola_toko(request):
    if request.method == "POST" and request.POST.get("action") == "create":
        kode = request.POST.get("kode", "").strip()
        if not kode or not kode.isalnum():
            messages.error(request, "Kode toko wajib huruf/angka tanpa spasi.")
        elif Toko.objects.filter(key=kode.lower()).exists():
            messages.error(request, f"Toko {kode.upper()} sudah ada.")
        else:
            Toko.objects.create(key=kode.lower(), name=kode.upper())
            messages.success(request, f"Toko {kode.upper()} ditambahkan.")
        return redirect("kelola_toko")
    if request.method == "POST" and request.POST.get("action") == "toggle":
        t = get_object_or_404(Toko, pk=request.POST.get("toko_id"))
        t.is_active = not t.is_active
        t.save(update_fields=["is_active"])
        messages.success(request, f"Toko {t.name} {'diaktifkan' if t.is_active else 'dinonaktifkan'}.")
        return redirect("kelola_toko")
    tokos = Toko.objects.annotate(
        n_tx=Count("transaction", distinct=True),
        n_up=Count("upload", distinct=True),
    ).order_by("name")
    return render(request, "web/kelola/toko.html", {"tokos": tokos})
```

`web/urls.py` — tambah import + route:

```python
from . import admin_views, views
```
dan di `urlpatterns` tambah:
```python
    path("kelola/toko/", admin_views.kelola_toko, name="kelola_toko"),
```

`web/templates/web/kelola/toko.html` (baru):

```html
{% extends "web/app_base.html" %}
{% load humanize %}
{% block title %}Kelola Toko · Truth of Auditor{% endblock %}
{% block crumb %}Admin · Kelola Toko{% endblock %}
{% block content %}
<div class="page-head reveal">
  <h1>Kelola Toko</h1>
  <p>Tambah kode toko baru atau nonaktifkan yang tidak dipakai. Data per toko tetap tersimpan.</p>
</div>

<div class="card reveal" style="max-width:430px">
  <h3>Tambah Toko</h3>
  <form method="post">
    {% csrf_token %}
    <input type="hidden" name="action" value="create">
    <div class="field"><label>Kode toko (mis. AHK)</label>
      <input name="kode" maxlength="30" placeholder="KODE" required style="text-transform:uppercase"></div>
    <button class="btn primary" type="submit">+ Tambah</button>
  </form>
</div>

<div class="card reveal pad0" style="margin-top:16px">
  <div style="padding:18px 20px 6px"><h3 style="margin:0">Daftar Toko ({{ tokos|length }})</h3></div>
  <div class="twrap" style="border:none">
  <table>
    <thead><tr><th>Kode</th><th class="r">Transaksi</th><th class="r">Upload</th><th>Status</th><th></th></tr></thead>
    <tbody>
    {% for t in tokos %}
      <tr>
        <td style="font-weight:600">{{ t.name }}</td>
        <td class="r num">{{ t.n_tx|intcomma }}</td>
        <td class="r num">{{ t.n_up|intcomma }}</td>
        <td>{% if t.is_active %}<span class="badge ok">aktif</span>{% else %}<span class="badge bad">nonaktif</span>{% endif %}</td>
        <td class="r">
          <form method="post" style="display:inline">
            {% csrf_token %}
            <input type="hidden" name="action" value="toggle">
            <input type="hidden" name="toko_id" value="{{ t.id }}">
            <button class="btn sm" type="submit">{% if t.is_active %}Nonaktifkan{% else %}Aktifkan{% endif %}</button>
          </form>
        </td>
      </tr>
    {% empty %}<tr><td colspan="5" class="faint">Belum ada toko.</td></tr>{% endfor %}
    </tbody>
  </table>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 4: Run test PASS + full suite**: `.venv/bin/python manage.py test web.tests_kelola web -v 1` lalu `.venv/bin/python manage.py test`

- [ ] **Step 5: Commit + push**

```bash
git add web/ && git commit -m "feat(web): panel Kelola Toko — tambah & aktif/nonaktif (admin-only)

Co-Authored-By: Claude <noreply@anthropic.com>" && git push
```

---

### Task 6: Kelola Pengguna — daftar + tambah (`/kelola/user/`)

**Files:**
- Modify: `web/admin_views.py`
- Create: `web/templates/web/kelola/users.html`
- Modify: `web/urls.py`
- Test: `web/tests_kelola.py` (tambah class)

**Interfaces:**
- Consumes: `admin_required`, `User.Role`, `allowed_tokos`.
- Produces: URL name `kelola_user` (sidebar Task 8; redirect Task 7). POST create fields: `username`, `password`, `nama`, `role`, `tokos` (multi).

- [ ] **Step 1: Failing test** — tambah di `web/tests_kelola.py`:

```python
class KelolaUserCreateTests(TestCase):
    def setUp(self):
        User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.lbs = Toko.objects.get(key="lbs")

    def _post(self, **over):
        data = {
            "username": "budi", "password": "rahasia123", "nama": "Budi S",
            "role": "auditor", "tokos": [self.lbs.id],
        }
        data.update(over)
        return self.client.post(reverse("kelola_user"), data)

    def test_create_auditor(self):
        self._post()
        u = User.objects.get(username="budi")
        self.assertEqual(u.first_name, "Budi S")
        self.assertEqual(u.role, "auditor")
        self.assertEqual(list(u.allowed_tokos.all()), [self.lbs])
        self.assertTrue(u.check_password("rahasia123"))

    def test_create_supervisor_tanpa_toko(self):
        self._post(username="sinta", role="supervisor", tokos=[])
        self.assertEqual(User.objects.get(username="sinta").allowed_tokos.count(), 0)

    def test_auditor_tanpa_toko_ditolak(self):
        self._post(username="tono", tokos=[])
        self.assertFalse(User.objects.filter(username="tono").exists())

    def test_password_pendek_ditolak(self):
        self._post(username="tini", password="1234567")
        self.assertFalse(User.objects.filter(username="tini").exists())

    def test_username_duplikat_ditolak(self):
        self._post()
        self._post(nama="Budi 2")
        self.assertEqual(User.objects.filter(username="budi").count(), 1)

    def test_list_tampil(self):
        r = self.client.get(reverse("kelola_user"))
        self.assertContains(r, "adm")
        self.assertContains(r, "Kelola Pengguna")
```

- [ ] **Step 2: Run — FAIL**: `.venv/bin/python manage.py test web.tests_kelola -v 1`

- [ ] **Step 3: Implementasi**

Tambah di `web/admin_views.py`:

```python
VALID_ROLES = ("admin", "supervisor", "auditor")


@admin_required
def kelola_user(request):
    User = get_user_model()
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        nama = request.POST.get("nama", "").strip()
        role = request.POST.get("role", "auditor")
        toko_ids = request.POST.getlist("tokos")
        err = None
        if not username:
            err = "Username wajib diisi."
        elif User.objects.filter(username=username).exists():
            err = f"Username {username} sudah dipakai."
        elif len(password) < 8:
            err = "Password minimal 8 karakter."
        elif role not in VALID_ROLES:
            err = "Role tidak dikenal."
        elif role == "auditor" and not toko_ids:
            err = "Auditor wajib ditugaskan minimal 1 toko."
        if err:
            messages.error(request, err)
        else:
            u = User.objects.create_user(username=username, password=password, first_name=nama, role=role)
            if role == "auditor":
                u.allowed_tokos.set(Toko.objects.filter(id__in=toko_ids, is_active=True))
            messages.success(request, f"User {username} ({role}) dibuat.")
        return redirect("kelola_user")
    users = User.objects.prefetch_related("allowed_tokos").order_by("username")
    return render(request, "web/kelola/users.html", {
        "users": users,
        "tokos": Toko.objects.filter(is_active=True).order_by("name"),
        "roles": User.Role.choices,
    })
```

`web/urls.py` — tambah:
```python
    path("kelola/user/", admin_views.kelola_user, name="kelola_user"),
```

`web/templates/web/kelola/users.html` (baru):

```html
{% extends "web/app_base.html" %}
{% block title %}Kelola Pengguna · Truth of Auditor{% endblock %}
{% block crumb %}Admin · Kelola Pengguna{% endblock %}
{% block content %}
<div class="page-head reveal">
  <h1>Kelola Pengguna</h1>
  <p>Tambah admin, supervisor, atau auditor. Auditor hanya melihat toko yang dicentang.</p>
</div>

<div class="card reveal">
  <h3>Tambah Pengguna</h3>
  <form method="post">
    {% csrf_token %}
    <div class="row">
      <div class="field"><label>Username</label><input name="username" required autocomplete="off"></div>
      <div class="field"><label>Password (min. 8)</label><input name="password" type="password" minlength="8" required autocomplete="new-password"></div>
      <div class="field"><label>Nama</label><input name="nama" placeholder="Nama lengkap"></div>
      <div class="field"><label>Role</label>
        <select name="role" class="f" id="roleSel">
          {% for val, label in roles %}<option value="{{ val }}" {% if val == 'auditor' %}selected{% endif %}>{{ label }}</option>{% endfor %}
        </select></div>
    </div>
    <div class="field" id="tokoPick" style="margin-top:8px">
      <label>Toko untuk auditor (wajib ≥1)</label>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(90px,1fr));gap:8px">
        {% for t in tokos %}
        <label style="display:flex;gap:7px;align-items:center;font-weight:500;color:var(--ink);margin:0">
          <input type="checkbox" name="tokos" value="{{ t.id }}" style="width:auto"> {{ t.name }}
        </label>
        {% endfor %}
      </div>
    </div>
    <button class="btn primary" type="submit" style="margin-top:12px">+ Buat User</button>
  </form>
</div>
<script>
(function(){var s=document.getElementById('roleSel'),p=document.getElementById('tokoPick');
  function sync(){p.style.display = s.value==='auditor' ? '' : 'none';}
  s.addEventListener('change',sync);sync();})();
</script>

<div class="card reveal pad0" style="margin-top:16px">
  <div style="padding:18px 20px 6px"><h3 style="margin:0">Daftar Pengguna</h3></div>
  <div class="twrap" style="border:none">
  <table>
    <thead><tr><th>Username</th><th>Nama</th><th>Role</th><th>Toko</th><th>Status</th><th>Login terakhir</th><th></th></tr></thead>
    <tbody>
    {% for u in users %}
      <tr>
        <td style="font-weight:600">{{ u.username }}</td>
        <td>{{ u.first_name|default:"—" }}</td>
        <td><span class="badge src plain">{{ u.get_role_display }}</span></td>
        <td class="faint">{% if u.role == 'auditor' %}{{ u.allowed_tokos.all|join:", "|default:"—" }}{% else %}semua{% endif %}</td>
        <td>{% if u.is_active %}<span class="badge ok">aktif</span>{% else %}<span class="badge bad">nonaktif</span>{% endif %}</td>
        <td class="faint">{{ u.last_login|date:"d/m H:i"|default:"—" }}</td>
        <td class="r"><a class="btn sm" href="{% url 'kelola_user_edit' u.pk %}">Kelola →</a></td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  </div>
</div>
{% endblock %}
```

**Catatan:** link `kelola_user_edit` baru ada di Task 7 — supaya Task 6 hijau mandiri, buat stub route sekarang di `web/urls.py`:
```python
    path("kelola/user/<int:pk>/", admin_views.kelola_user_edit, name="kelola_user_edit"),
```
dan stub view minimal di `web/admin_views.py` (Task 7 melengkapinya):
```python
@admin_required
def kelola_user_edit(request, pk):
    User = get_user_model()
    target = get_object_or_404(User, pk=pk)
    return render(request, "web/kelola/user_edit.html", {
        "target": target,
        "tokos": Toko.objects.filter(is_active=True).order_by("name"),
        "roles": User.Role.choices,
        "target_toko_ids": set(target.allowed_tokos.values_list("id", flat=True)),
    })
```
beserta template `user_edit.html` versi Task 7 (lihat bawah — tulis sekaligus di task ini bila mempermudah, form-nya baru berfungsi setelah Task 7).

- [ ] **Step 4: Run PASS + full suite.**

- [ ] **Step 5: Commit + push**

```bash
git add web/ && git commit -m "feat(web): panel Kelola Pengguna — daftar + tambah user 3 peran

Co-Authored-By: Claude <noreply@anthropic.com>" && git push
```

---

### Task 7: Kelola Pengguna — edit, reset password, aktif/nonaktif, self-protection

**Files:**
- Modify: `web/admin_views.py` (lengkapi `kelola_user_edit`)
- Create/Modify: `web/templates/web/kelola/user_edit.html`
- Test: `web/tests_kelola.py` (tambah class)

**Interfaces:**
- Consumes: stub Task 6 (`kelola_user_edit` route), `update_session_auth_hash` (sudah diimport Task 5).
- Produces: POST actions di `/kelola/user/<pk>/`: `save` (nama/role/tokos), `reset_password` (password), `toggle`.

- [ ] **Step 1: Failing test** — tambah di `web/tests_kelola.py`:

```python
class KelolaUserEditTests(TestCase):
    def setUp(self):
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.target = User.objects.create_user("budi", password="rahasia123", role="auditor")
        self.target.allowed_tokos.add(self.lbs)
        self.url = reverse("kelola_user_edit", args=[self.target.pk])

    def test_save_ubah_nama_role_toko(self):
        self.client.post(self.url, {
            "action": "save", "nama": "Budi Baru", "role": "auditor",
            "tokos": [self.lbs.id, self.slo.id],
        })
        self.target.refresh_from_db()
        self.assertEqual(self.target.first_name, "Budi Baru")
        self.assertEqual(self.target.allowed_tokos.count(), 2)

    def test_save_auditor_tanpa_toko_ditolak(self):
        self.client.post(self.url, {"action": "save", "nama": "X", "role": "auditor", "tokos": []})
        self.target.refresh_from_db()
        self.assertEqual(self.target.allowed_tokos.count(), 1)  # tak berubah

    def test_naik_ke_supervisor_mengosongkan_toko(self):
        self.client.post(self.url, {"action": "save", "nama": "", "role": "supervisor", "tokos": []})
        self.target.refresh_from_db()
        self.assertEqual(self.target.role, "supervisor")
        self.assertEqual(self.target.allowed_tokos.count(), 0)

    def test_reset_password(self):
        self.client.post(self.url, {"action": "reset_password", "password": "barubanget9"})
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("barubanget9"))

    def test_reset_password_pendek_ditolak(self):
        self.client.post(self.url, {"action": "reset_password", "password": "1234567"})
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("rahasia123"))

    def test_toggle_nonaktif_lalu_login_gagal(self):
        self.client.post(self.url, {"action": "toggle"})
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        c2 = self.client.__class__()
        self.assertFalse(c2.login(username="budi", password="rahasia123"))

    def test_tidak_bisa_nonaktifkan_diri_sendiri(self):
        url_self = reverse("kelola_user_edit", args=[self.adm.pk])
        self.client.post(url_self, {"action": "toggle"})
        self.adm.refresh_from_db()
        self.assertTrue(self.adm.is_active)

    def test_tidak_bisa_turunkan_role_sendiri(self):
        url_self = reverse("kelola_user_edit", args=[self.adm.pk])
        self.client.post(url_self, {"action": "save", "nama": "", "role": "auditor", "tokos": [self.lbs.id]})
        self.adm.refresh_from_db()
        self.assertEqual(self.adm.role, "admin")
```

- [ ] **Step 2: Run — FAIL**: `.venv/bin/python manage.py test web.tests_kelola.KelolaUserEditTests -v 1`

- [ ] **Step 3: Implementasi** — ganti stub `kelola_user_edit` di `web/admin_views.py`:

```python
@admin_required
def kelola_user_edit(request, pk):
    User = get_user_model()
    target = get_object_or_404(User, pk=pk)
    action = request.POST.get("action", "") if request.method == "POST" else ""

    if action == "save":
        nama = request.POST.get("nama", "").strip()
        role = request.POST.get("role", target.role)
        toko_ids = request.POST.getlist("tokos")
        if role not in VALID_ROLES:
            messages.error(request, "Role tidak dikenal.")
        elif target == request.user and role != "admin":
            messages.error(request, "Tidak bisa menurunkan role akunmu sendiri.")
        elif role == "auditor" and not toko_ids:
            messages.error(request, "Auditor wajib ditugaskan minimal 1 toko.")
        else:
            target.first_name = nama
            target.role = role
            target.save(update_fields=["first_name", "role"])
            target.allowed_tokos.set(
                Toko.objects.filter(id__in=toko_ids, is_active=True) if role == "auditor" else []
            )
            messages.success(request, f"User {target.username} diperbarui.")
            return redirect("kelola_user")
    elif action == "reset_password":
        pw = request.POST.get("password", "")
        if len(pw) < 8:
            messages.error(request, "Password minimal 8 karakter.")
        else:
            target.set_password(pw)
            target.save()
            if target == request.user:
                update_session_auth_hash(request, target)
            messages.success(request, f"Password {target.username} di-reset.")
            return redirect("kelola_user")
    elif action == "toggle":
        if target == request.user:
            messages.error(request, "Tidak bisa menonaktifkan akunmu sendiri.")
        else:
            target.is_active = not target.is_active
            target.save(update_fields=["is_active"])
            messages.success(
                request,
                f"User {target.username} {'diaktifkan' if target.is_active else 'dinonaktifkan'}.",
            )
        return redirect("kelola_user")

    return render(request, "web/kelola/user_edit.html", {
        "target": target,
        "tokos": Toko.objects.filter(is_active=True).order_by("name"),
        "roles": User.Role.choices,
        "target_toko_ids": set(target.allowed_tokos.values_list("id", flat=True)),
    })
```

`web/templates/web/kelola/user_edit.html` (isi final):

```html
{% extends "web/app_base.html" %}
{% block title %}Kelola {{ target.username }} · Truth of Auditor{% endblock %}
{% block crumb %}Admin · Pengguna · {{ target.username }}{% endblock %}
{% block content %}
<div class="page-head reveal">
  <h1>{{ target.username }}</h1>
  <p>{{ target.get_role_display }} — {% if target.is_active %}aktif{% else %}nonaktif{% endif %} · <a href="{% url 'kelola_user' %}" class="grad-text" style="font-weight:600">← kembali</a></p>
</div>

<div class="grid cols-2">
  <div class="card reveal">
    <h3>Data &amp; Akses</h3>
    <form method="post">
      {% csrf_token %}
      <input type="hidden" name="action" value="save">
      <div class="field"><label>Nama</label><input name="nama" value="{{ target.first_name }}"></div>
      <div class="field"><label>Role</label>
        <select name="role" class="f" id="roleSel">
          {% for val, label in roles %}<option value="{{ val }}" {% if val == target.role %}selected{% endif %}>{{ label }}</option>{% endfor %}
        </select></div>
      <div class="field" id="tokoPick">
        <label>Toko untuk auditor (wajib ≥1)</label>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(90px,1fr));gap:8px">
          {% for t in tokos %}
          <label style="display:flex;gap:7px;align-items:center;font-weight:500;color:var(--ink);margin:0">
            <input type="checkbox" name="tokos" value="{{ t.id }}" {% if t.id in target_toko_ids %}checked{% endif %} style="width:auto"> {{ t.name }}
          </label>
          {% endfor %}
        </div>
      </div>
      <button class="btn primary" type="submit">Simpan</button>
    </form>
  </div>

  <div>
    <div class="card reveal">
      <h3>Reset Password</h3>
      <form method="post">
        {% csrf_token %}
        <input type="hidden" name="action" value="reset_password">
        <div class="field"><label>Password baru (min. 8)</label><input name="password" type="password" minlength="8" required autocomplete="new-password"></div>
        <button class="btn" type="submit">Reset Password</button>
      </form>
    </div>
    <div class="card reveal" style="margin-top:16px">
      <h3>Status Akun</h3>
      <form method="post" onsubmit="return confirm('{% if target.is_active %}Nonaktifkan{% else %}Aktifkan{% endif %} {{ target.username }}?')">
        {% csrf_token %}
        <input type="hidden" name="action" value="toggle">
        <button class="btn" type="submit">{% if target.is_active %}Nonaktifkan Akun{% else %}Aktifkan Akun{% endif %}</button>
      </form>
    </div>
  </div>
</div>
<script>
(function(){var s=document.getElementById('roleSel'),p=document.getElementById('tokoPick');
  function sync(){p.style.display = s.value==='auditor' ? '' : 'none';}
  s.addEventListener('change',sync);sync();})();
</script>
{% endblock %}
```

- [ ] **Step 4: Run PASS + full suite.**

- [ ] **Step 5: Commit + push**

```bash
git add web/ && git commit -m "feat(web): edit user — role/toko/reset password/nonaktif + self-protection

Co-Authored-By: Claude <noreply@anthropic.com>" && git push
```

---

### Task 8: Sidebar seksi Admin (render hanya untuk admin)

**Files:**
- Modify: `web/templates/web/app_base.html` (di dalam blok `{% with p=request.path %}`, setelah link Rekonsiliasi)
- Test: `web/tests_kelola.py` (tambah class)

**Interfaces:**
- Consumes: `is_admin_user` dari context processor (Task 4); URL `kelola_user`/`kelola_toko` (Task 5/6).

- [ ] **Step 1: Failing test** — tambah di `web/tests_kelola.py`:

```python
class SidebarAdminTests(TestCase):
    def test_admin_melihat_menu_admin(self):
        User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, 'href="/kelola/user/"')
        self.assertContains(r, 'href="/kelola/toko/"')

    def test_supervisor_tidak_melihat_menu_admin(self):
        u = User.objects.create_user("sup", password="pw123456", role="supervisor")
        self.client.login(username="sup", password="pw123456")
        r = self.client.get(reverse("dashboard"))
        self.assertNotContains(r, 'href="/kelola/user/"')
```

- [ ] **Step 2: Run — FAIL**: `.venv/bin/python manage.py test web.tests_kelola.SidebarAdminTests -v 1`

- [ ] **Step 3: Implementasi** — di `web/templates/web/app_base.html`, tepat SETELAH link Rekonsiliasi (baris `</svg>Rekonsiliasi</a>`) dan SEBELUM `{% endwith %}`, sisipkan:

```html
  {% if is_admin_user %}
  <div class="sec">Admin</div>
  <a class="link {% if '/kelola/user' in p %}active{% endif %}" href="{% url 'kelola_user' %}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>Pengguna</a>
  <a class="link {% if '/kelola/toko' in p %}active{% endif %}" href="{% url 'kelola_toko' %}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l1.5-5h15L21 9"/><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9"/><path d="M3 9h18"/></svg>Toko</a>
  {% endif %}
```

- [ ] **Step 4: Run PASS + full suite.**

- [ ] **Step 5: Commit + push**

```bash
git add web/templates/web/app_base.html web/tests_kelola.py && git commit -m "feat(web): seksi Admin di sidebar (render khusus admin)

Co-Authored-By: Claude <noreply@anthropic.com>" && git push
```

---

### Task 9: Hapus Upload (admin-only, file storage ikut)

**Files:**
- Modify: `web/admin_views.py`, `web/urls.py`
- Modify: `web/templates/web/upload.html` (kolom Aksi di riwayat)
- Create: `web/tests_delete.py`

**Interfaces:**
- Consumes: `admin_required`; `Upload.transactions` (CASCADE); `is_admin_user` context.
- Produces: URL `delete_upload` (`upload/<pk>/delete/`, POST only).

- [ ] **Step 1: Failing test** — `web/tests_delete.py`:

```python
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


def _mk_upload(toko, with_file=False):
    st = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
    up = Upload.objects.create(source_type=st, toko=toko, original_name="f.xlsx")
    if with_file:
        up.file.save("f.xlsx", ContentFile(b"data"), save=True)
    return up, st


class DeleteUploadTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        User.objects.create_user("adm", password="pw123456", role="admin")

    def test_admin_hapus_upload_beserta_tx_dan_file(self):
        from datetime import datetime
        from decimal import Decimal
        up, st = _mk_upload(self.lbs, with_file=True)
        path = up.file.name
        Transaction.objects.create(
            upload=up, source_type=st, toko=self.lbs, jenis="depo",
            amount=Decimal("1"), money_delta=Decimal("1"),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash="del-1",
        )
        self.client.login(username="adm", password="pw123456")
        r = self.client.post(reverse("delete_upload", args=[up.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Upload.objects.filter(pk=up.pk).exists())
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertFalse(default_storage.exists(path))

    def test_auditor_ditolak(self):
        up, _ = _mk_upload(self.lbs)
        aud = User.objects.create_user("aud1", password="pw123456", role="auditor")
        aud.allowed_tokos.add(self.lbs)
        self.client.login(username="aud1", password="pw123456")
        self.client.post(reverse("delete_upload", args=[up.pk]))
        self.assertTrue(Upload.objects.filter(pk=up.pk).exists())

    def test_get_tidak_menghapus(self):
        up, _ = _mk_upload(self.lbs)
        self.client.login(username="adm", password="pw123456")
        self.client.get(reverse("delete_upload", args=[up.pk]))
        self.assertTrue(Upload.objects.filter(pk=up.pk).exists())

    def test_tombol_hanya_untuk_admin(self):
        _mk_upload(self.lbs)
        aud = User.objects.create_user("aud2", password="pw123456", role="auditor")
        aud.allowed_tokos.add(self.lbs)
        self.client.login(username="aud2", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.get(reverse("upload"))
        self.assertNotContains(r, "/delete/")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.get(reverse("upload"))
        self.assertContains(r, "/delete/")
```

- [ ] **Step 2: Run — FAIL**: `.venv/bin/python manage.py test web.tests_delete -v 1`

- [ ] **Step 3: Implementasi**

Tambah di `web/admin_views.py` (import `Upload` dari `sources.models` — gabungkan ke import yang ada):

```python
from sources.models import Toko, Upload  # ganti baris import Toko yang ada


@admin_required
def delete_upload(request, pk):
    up = get_object_or_404(Upload, pk=pk)
    if request.method == "POST":
        name = up.original_name or f"Upload #{up.pk}"
        n_tx = up.transactions.count()
        if up.file:
            up.file.delete(save=False)
        up.delete()
        messages.success(request, f"{name} dihapus — {n_tx} transaksi ikut terhapus.")
    return redirect("upload")
```

`web/urls.py` — tambah:
```python
    path("upload/<int:pk>/delete/", admin_views.delete_upload, name="delete_upload"),
```

`web/templates/web/upload.html` — di tabel riwayat:
1. Header (baris `<thead>`): setelah `<th>Waktu</th>` tambah `{% if is_admin_user %}<th></th>{% endif %}`
2. Baris data: setelah `<td class="faint">{{ u.created_at|date:"d/m H:i" }}</td>` tambah:
```html
        {% if is_admin_user %}
        <td class="r">
          <form method="post" action="{% url 'delete_upload' u.pk %}" style="display:inline"
                onsubmit="return confirm('Hapus {{ u.original_name|default:u.pk }}? {{ u.rows_parsed }} baris transaksi ikut terhapus. Tidak bisa dibatalkan.')">
            {% csrf_token %}
            <button class="btn sm ghost" type="submit" style="color:var(--bad)">Hapus</button>
          </form>
        </td>
        {% endif %}
```
3. Baris kosong: `colspan="9"` → `colspan="{% if is_admin_user %}10{% else %}9{% endif %}"`

- [ ] **Step 4: Run PASS + full suite.**

- [ ] **Step 5: Commit + push**

```bash
git add web/ && git commit -m "feat(web): hapus upload admin-only — transaksi & file storage ikut bersih

Co-Authored-By: Claude <noreply@anthropic.com>" && git push
```

---

### Task 10: Hapus Laporan (ReconBatch) admin-only

**Files:**
- Modify: `web/admin_views.py`, `web/urls.py`
- Modify: `web/templates/web/reconcile.html` (kolom Aksi), `web/templates/web/batch_detail.html` (tombol di page-head)
- Test: `web/tests_delete.py` (tambah class)

**Interfaces:**
- Consumes: `ReconBatch.runs` (CASCADE), `admin_required`, `is_admin_user`.
- Produces: URL `delete_batch` (`batch/<pk>/delete/`, POST only).

- [ ] **Step 1: Failing test** — tambah di `web/tests_delete.py`:

```python
class DeleteBatchTests(TestCase):
    def setUp(self):
        from reconciliation.engine import run_batch
        from reconciliation.models import ToleranceProfile
        self.lbs = Toko.objects.get(key="lbs")
        tol = ToleranceProfile.objects.get_or_create(name="Default", defaults={"date_window_days": 1})[0]
        self.batch = run_batch(self.lbs, tol)
        User.objects.create_user("adm", password="pw123456", role="admin")

    def test_admin_hapus_batch_transaksi_utuh(self):
        from datetime import datetime
        from decimal import Decimal
        from reconciliation.models import MatchRun, ReconBatch
        st = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        up = Upload.objects.create(source_type=st, toko=self.lbs)
        Transaction.objects.create(
            upload=up, source_type=st, toko=self.lbs, jenis="depo",
            amount=Decimal("1"), money_delta=Decimal("1"),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash="keep-1",
        )
        self.client.login(username="adm", password="pw123456")
        r = self.client.post(reverse("delete_batch", args=[self.batch.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(ReconBatch.objects.filter(pk=self.batch.pk).exists())
        self.assertEqual(MatchRun.objects.filter(batch_id=self.batch.pk).count(), 0)
        self.assertEqual(Transaction.objects.count(), 1)  # transaksi TIDAK ikut terhapus

    def test_supervisor_ditolak(self):
        from reconciliation.models import ReconBatch
        User.objects.create_user("sup", password="pw123456", role="supervisor")
        self.client.login(username="sup", password="pw123456")
        self.client.post(reverse("delete_batch", args=[self.batch.pk]))
        self.assertTrue(ReconBatch.objects.filter(pk=self.batch.pk).exists())
```

- [ ] **Step 2: Run — FAIL**: `.venv/bin/python manage.py test web.tests_delete.DeleteBatchTests -v 1`

- [ ] **Step 3: Implementasi**

`web/admin_views.py` — tambah import & view:

```python
from reconciliation.models import ReconBatch


@admin_required
def delete_batch(request, pk):
    batch = get_object_or_404(ReconBatch, pk=pk)
    if request.method == "POST":
        n_runs = batch.runs.count()
        batch.delete()
        messages.success(request, f"Batch #{pk} dihapus — {n_runs} run ikut terhapus. Transaksi tetap utuh.")
    return redirect("reconcile")
```

`web/urls.py` — tambah:
```python
    path("batch/<int:pk>/delete/", admin_views.delete_batch, name="delete_batch"),
```

`web/templates/web/reconcile.html` — tabel Riwayat Batch:
1. `<thead>`: setelah `<th>Cocok</th>` tambah `{% if is_admin_user %}<th></th>{% endif %}`
2. Baris data: setelah sel badge Cocok tambah:
```html
        {% if is_admin_user %}
        <td class="r">
          <form method="post" action="{% url 'delete_batch' b.pk %}" style="display:inline"
                onsubmit="return confirm('Hapus Batch #{{ b.pk }}? Semua hasil rekonsiliasinya terhapus (transaksi tetap utuh).')">
            {% csrf_token %}
            <button class="btn sm ghost" type="submit" style="color:var(--bad)">Hapus</button>
          </form>
        </td>
        {% endif %}
```
3. Baris kosong: `colspan="5"` → `colspan="{% if is_admin_user %}6{% else %}5{% endif %}"`

`web/templates/web/batch_detail.html` — ganti blok `page-head` menjadi:

```html
<div class="page-head reveal" style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px">
  <div>
    <h1>Batch #{{ batch.pk }} — {{ batch.toko.name }}</h1>
    <p>{{ batch.created_at|date:"d/m/Y H:i" }} · Toleransi {{ batch.tolerance.name }}</p>
  </div>
  {% if is_admin_user %}
  <form method="post" action="{% url 'delete_batch' batch.pk %}"
        onsubmit="return confirm('Hapus Batch #{{ batch.pk }}? Semua hasil rekonsiliasinya terhapus (transaksi tetap utuh).')">
    {% csrf_token %}
    <button class="btn" type="submit" style="color:var(--bad)">Hapus Laporan</button>
  </form>
  {% endif %}
</div>
```

- [ ] **Step 4: Run PASS + full suite.**

- [ ] **Step 5: Commit + push**

```bash
git add web/ && git commit -m "feat(web): hapus laporan batch admin-only — hasil bersih, transaksi utuh

Co-Authored-By: Claude <noreply@anthropic.com>" && git push
```

---

### Task 11: Verifikasi akhir menyeluruh

**Files:** tidak ada perubahan kode (kecuali perbaikan bila ada temuan).

- [ ] **Step 1: Full suite**: `.venv/bin/python manage.py test` → Expected: **≥85 test, OK** (54 baseline + ±31 baru).
- [ ] **Step 2: Django check**: `.venv/bin/python manage.py check` → 0 issues; `.venv/bin/python manage.py makemigrations --check --dry-run` → "No changes detected".
- [ ] **Step 3: Smoke manual via test client** (opsional cepat): login admin → GET `/kelola/user/`, `/kelola/toko/` = 200.
- [ ] **Step 4: Push final** — pastikan `git status` bersih dan `git push` up-to-date.

---

## Self-review (sudah dijalankan penulis plan)

- **Spec coverage:** §3 peran→Task 1; §4 model+seed→Task 1-2; §5 enforcement+empty state→Task 3-4; §6.1 user CRUD+validasi+self-protection→Task 6-7; §6.2 toko→Task 5; §6.3 hapus→Task 9-10; sidebar→Task 8; §9 testing→tersebar per task. Lengkap.
- **Placeholder:** tidak ada TBD/TODO; semua step berisi kode utuh.
- **Konsistensi tipe/nama:** `tokos_for`, `is_admin`, `admin_required`, `is_admin_user`, `kelola_user`, `kelola_user_edit`, `kelola_toko`, `delete_upload`, `delete_batch`, related_name `assigned_users` — dipakai konsisten lintas task.
