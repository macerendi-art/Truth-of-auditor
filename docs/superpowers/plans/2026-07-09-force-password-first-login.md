# Force Ganti Password di Login Pertama — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Paksa setiap user mengganti password sementara (yang dibagikan admin) dengan password pribadi pada login pertama — atau setelah admin me-reset password mereka — sebelum bisa mengakses halaman lain.

**Architecture:** Sebuah flag boolean `must_change_password` pada `accounts.User`. Admin men-set flag `TRUE` saat membuat user baru atau me-reset password user lain. Sebuah middleware global mencegat setiap request dari user ber-flag dan mengalihkannya ke halaman ganti password (satu titik cegat, tidak bisa di-bypass via URL). Halaman ganti password memakai `PasswordChangeForm` (password lama + baru + konfirmasi + validator Django) plus aturan "password baru wajib berbeda dari yang lama"; sukses → flag `FALSE`, sesi dijaga, kembali ke dashboard.

**Tech Stack:** Django 5.2, custom user model `accounts.User`, template Django (extends `web/base.html`), SQLite (dev) / Postgres (prod).

## Global Constraints

- **Bahasa:** UI dan komentar kode dalam Bahasa Indonesia. Identifier Python tetap Inggris (ikuti konvensi codebase, mis. `def dashboard`).
- **Menjalankan test:** worktree ini TIDAK punya `.venv` lokal. Jalankan test dari root worktree dengan interpreter venv repo utama:
  `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test <label> -v2`
  (Django membuat test-DB sendiri dari migrasi termasuk seed Toko — tidak perlu `db.sqlite3`.)
- **Semua test baru** ada di satu modul: `web/tests_force_password.py` (satu `TestCase` per task).
- **Password validator** sudah aktif di settings (`AUTH_PASSWORD_VALIDATORS`: MinimumLength, CommonPassword, NumericPassword, UserAttributeSimilarity). Jangan tambah/ubah.
- **Jangan** perkenalkan datetime tz-aware (`USE_TZ=False`). Tidak relevan di sini tapi patuhi.
- **Konvensi test:** `from django.contrib.auth import get_user_model`, `User = get_user_model()`, pakai `self.client`, `reverse()`, nama test Bahasa Indonesia/Inggris campur seperti file `web/tests_*` yang ada. Password uji yang "kuat" (lolos validator): mis. `"Lama-Kuat#88"`, `"Baru-Beda#99"`.

---

### Task 1: Field `must_change_password` + migrasi

**Files:**
- Modify: `accounts/models.py` (tambah field pada `User`)
- Create: `accounts/migrations/0003_user_must_change_password.py` (via `makemigrations`)
- Test: `web/tests_force_password.py` (baru)

**Interfaces:**
- Consumes: `accounts.User` (AbstractUser + `role`, `allowed_tokos`).
- Produces: `User.must_change_password: BooleanField(default=False)` — dibaca oleh middleware (Task 4) dan di-set oleh admin views (Task 5).

- [ ] **Step 1: Tulis test yang gagal**

Buat file `web/tests_force_password.py`:

```python
"""Force ganti password di login pertama — flag must_change_password."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import Toko

User = get_user_model()


class MustChangePasswordFieldTests(TestCase):
    def test_default_false(self):
        u = User.objects.create_user("baru", password="Lama-Kuat#88", role="supervisor")
        self.assertFalse(u.must_change_password)

    def test_field_bisa_di_set_true(self):
        u = User.objects.create_user("baru2", password="Lama-Kuat#88", role="supervisor")
        u.must_change_password = True
        u.save(update_fields=["must_change_password"])
        u.refresh_from_db()
        self.assertTrue(u.must_change_password)
```

- [ ] **Step 2: Jalankan test — pastikan GAGAL**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_force_password.MustChangePasswordFieldTests -v2`
Expected: FAIL/ERROR — `AttributeError` atau `TypeError` karena field `must_change_password` belum ada.

- [ ] **Step 3: Tambah field ke model**

Di `accounts/models.py`, di dalam `class User(AbstractUser)`, setelah field `allowed_tokos = models.ManyToManyField(...)` dan sebelum `def __str__`, tambahkan:

```python
    must_change_password = models.BooleanField(
        default=False,
        help_text="Wajib ganti password saat login berikutnya (password sementara dari admin).",
    )
```

- [ ] **Step 4: Buat migrasi**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py makemigrations accounts`
Expected: membuat `accounts/migrations/0003_user_must_change_password.py`. Isi harus setara:

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_user_supervisor_allowed_tokos"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="must_change_password",
            field=models.BooleanField(
                default=False,
                help_text="Wajib ganti password saat login berikutnya (password sementara dari admin).",
            ),
        ),
    ]
```

- [ ] **Step 5: Jalankan test — pastikan LULUS**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_force_password.MustChangePasswordFieldTests -v2`
Expected: PASS (2 test).

- [ ] **Step 6: Commit**

```bash
git add accounts/models.py accounts/migrations/0003_user_must_change_password.py web/tests_force_password.py
git commit -m "feat(accounts): field must_change_password pada User + migrasi

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Form `GantiPasswordForm`

**Files:**
- Create: `web/forms.py`
- Test: `web/tests_force_password.py` (tambah class)

**Interfaces:**
- Consumes: `django.contrib.auth.forms.PasswordChangeForm` (field `old_password`, `new_password1`, `new_password2`; menjalankan `AUTH_PASSWORD_VALIDATORS`).
- Produces: `web.forms.GantiPasswordForm(user=<User>, data=<dict>)` — valid hanya bila old benar, new1==new2, new lolos validator, dan `new1 != old`.

- [ ] **Step 1: Tulis test yang gagal**

Tambahkan ke `web/tests_force_password.py`:

```python
class GantiPasswordFormTests(TestCase):
    def setUp(self):
        from web.forms import GantiPasswordForm
        self.Form = GantiPasswordForm
        self.u = User.objects.create_user("form_u", password="Lama-Kuat#88", role="supervisor")

    def _form(self, old, n1, n2):
        return self.Form(user=self.u, data={
            "old_password": old, "new_password1": n1, "new_password2": n2,
        })

    def test_ganti_valid(self):
        self.assertTrue(self._form("Lama-Kuat#88", "Baru-Beda#99", "Baru-Beda#99").is_valid())

    def test_old_salah_ditolak(self):
        f = self._form("salah-banget", "Baru-Beda#99", "Baru-Beda#99")
        self.assertFalse(f.is_valid())
        self.assertIn("old_password", f.errors)

    def test_konfirmasi_tak_cocok_ditolak(self):
        f = self._form("Lama-Kuat#88", "Baru-Beda#99", "Beda-Lain#00")
        self.assertFalse(f.is_valid())
        self.assertIn("new_password2", f.errors)

    def test_baru_sama_dengan_lama_ditolak(self):
        f = self._form("Lama-Kuat#88", "Lama-Kuat#88", "Lama-Kuat#88")
        self.assertFalse(f.is_valid())
        self.assertIn("new_password1", f.errors)

    def test_baru_lemah_ditolak(self):
        # "password" = umum → ditolak validator (error nempel di new_password2)
        f = self._form("Lama-Kuat#88", "password", "password")
        self.assertFalse(f.is_valid())
        self.assertIn("new_password2", f.errors)
```

- [ ] **Step 2: Jalankan test — pastikan GAGAL**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_force_password.GantiPasswordFormTests -v2`
Expected: ERROR — `ModuleNotFoundError: No module named 'web.forms'` (import di `setUp` gagal).

- [ ] **Step 3: Buat form**

Buat `web/forms.py`:

```python
"""Form kustom aplikasi web."""
from django.contrib.auth.forms import PasswordChangeForm


class GantiPasswordForm(PasswordChangeForm):
    """Ganti password wajib (login pertama / setelah reset admin).

    Mewarisi field password lama + baru + konfirmasi dan validator Django penuh
    (panjang minimum, password umum, semua-angka, kemiripan atribut user).
    Tambahan aturan: password baru WAJIB berbeda dari password lama (sementara),
    supaya user tidak sekadar mengetik ulang password shared.
    """

    def clean(self):
        cleaned = super().clean()
        old = cleaned.get("old_password")
        new = cleaned.get("new_password1")
        if old and new and old == new:
            self.add_error(
                "new_password1",
                "Password baru harus berbeda dari password lama.",
            )
        return cleaned
```

- [ ] **Step 4: Jalankan test — pastikan LULUS**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_force_password.GantiPasswordFormTests -v2`
Expected: PASS (5 test).

- [ ] **Step 5: Commit**

```bash
git add web/forms.py web/tests_force_password.py
git commit -m "feat(web): GantiPasswordForm — lama+baru+konfirmasi, baru wajib beda

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: View + URL + template halaman ganti password

**Files:**
- Modify: `web/views.py` (tambah import + view `ganti_password`)
- Modify: `web/urls.py` (tambah route `ganti_password`)
- Create: `web/templates/registration/ganti_password.html`
- Test: `web/tests_force_password.py` (tambah class)

**Interfaces:**
- Consumes: `web.forms.GantiPasswordForm` (Task 2), `User.must_change_password` (Task 1).
- Produces: URL name `ganti_password` → path `/ganti-password/`; view `web.views.ganti_password`. Sukses POST → set flag `False`, jaga sesi, `redirect("dashboard")`.

- [ ] **Step 1: Tulis test yang gagal**

Tambahkan ke `web/tests_force_password.py`:

```python
class GantiPasswordViewTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("ganti_u", password="Lama-Kuat#88", role="supervisor")
        self.u.must_change_password = True
        self.u.save(update_fields=["must_change_password"])
        self.client.login(username="ganti_u", password="Lama-Kuat#88")

    def _post(self, old="Lama-Kuat#88", n1="Baru-Beda#99", n2="Baru-Beda#99"):
        return self.client.post(reverse("ganti_password"), {
            "old_password": old, "new_password1": n1, "new_password2": n2,
        })

    def test_halaman_tampil(self):
        r = self.client.get(reverse("ganti_password"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "password baru")

    def test_sukses_flag_false_password_ganti_sesi_terjaga(self):
        r = self._post()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("dashboard"))
        self.u.refresh_from_db()
        self.assertFalse(self.u.must_change_password)
        self.assertTrue(self.u.check_password("Baru-Beda#99"))
        self.assertIn("_auth_user_id", self.client.session)  # tetap login

    def test_old_salah_flag_tetap_true(self):
        r = self._post(old="salah-banget")
        self.assertEqual(r.status_code, 200)  # form dirender ulang
        self.u.refresh_from_db()
        self.assertTrue(self.u.must_change_password)
        self.assertTrue(self.u.check_password("Lama-Kuat#88"))  # tak berubah

    def test_baru_sama_lama_flag_tetap_true(self):
        r = self._post(n1="Lama-Kuat#88", n2="Lama-Kuat#88")
        self.assertEqual(r.status_code, 200)
        self.u.refresh_from_db()
        self.assertTrue(self.u.must_change_password)
```

- [ ] **Step 2: Jalankan test — pastikan GAGAL**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_force_password.GantiPasswordViewTests -v2`
Expected: ERROR — `NoReverseMatch: 'ganti_password' is not a valid view function or pattern name`.

- [ ] **Step 3: Tambah import di `web/views.py`**

Ubah baris import auth yang ada:

```python
from django.contrib.auth import logout as auth_logout
```

menjadi:

```python
from django.contrib.auth import logout as auth_logout, update_session_auth_hash
```

Lalu tambahkan (dekat import lokal `web` lainnya, mis. setelah `from web.access import is_admin, tokos_for`):

```python
from web.forms import GantiPasswordForm
```

- [ ] **Step 4: Tambah view di `web/views.py`**

Tambahkan fungsi berikut (mis. tepat setelah view `set_toko`, sebelum `dashboard`):

```python
@login_required
def ganti_password(request):
    """Halaman wajib ganti password (login pertama / setelah reset admin).

    @login_required: bila sesi kedaluwarsa saat di sini, submit terlempar ke
    /login/?next=... — menutup edge case sesi expired.
    """
    if request.method == "POST":
        form = GantiPasswordForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()  # set_password + simpan
            user.must_change_password = False
            user.save(update_fields=["must_change_password"])
            update_session_auth_hash(request, user)  # jaga sesi, jangan ter-logout
            messages.success(request, "Password berhasil diganti. Selamat bekerja!")
            return redirect("dashboard")
    else:
        form = GantiPasswordForm(user=request.user)
    return render(request, "registration/ganti_password.html", {"form": form})
```

- [ ] **Step 5: Tambah route di `web/urls.py`**

Tambahkan baris ini ke `urlpatterns` (mis. tepat setelah `path("set-toko/", ...)`):

```python
    path("ganti-password/", views.ganti_password, name="ganti_password"),
```

- [ ] **Step 6: Buat template**

Buat `web/templates/registration/ganti_password.html`:

```html
{% extends "web/base.html" %}
{% block title %}Ganti Password · Truth of Auditor{% endblock %}

{% block head %}
<style>
  body{overflow:auto}
  .auth{min-height:100vh;display:grid;place-items:center;padding:24px}
  .auth-card{width:100%;max-width:430px;background:rgba(18,15,11,.82);backdrop-filter:blur(14px);
    border:1px solid var(--border2);border-radius:var(--radius);padding:30px 32px;
    box-shadow:0 44px 130px -30px rgba(0,0,0,.85),inset 0 1px 0 rgba(233,228,214,.06)}
  .auth-card .brand{display:flex;align-items:center;gap:11px;font-weight:700;font-size:19px}
  .auth-card h1{font-size:25px;margin:16px 0 8px;line-height:1.15}
  .auth-card .sub{color:var(--muted);font-size:14px;margin:0 0 22px;line-height:1.5}
  .auth-card .btn.primary{width:100%;justify-content:center;padding:13px;font-size:15px;margin-top:4px}
  .err{background:rgba(208,106,92,.12);color:#E8A493;border:1px solid rgba(208,106,92,.35);
    padding:10px 13px;border-radius:var(--radius-sm);font-size:13px;margin-bottom:16px}
  .field .fe{color:#E8A493;font-size:12px;margin-top:4px;line-height:1.4}
  .foot{margin-top:20px;padding-top:14px;border-top:1px solid var(--border);text-align:center;font-size:12.5px;color:var(--faint)}
  .foot button{background:none;border:none;color:var(--muted);text-decoration:underline;cursor:pointer;font:inherit;padding:0}
</style>
{% endblock %}

{% block chrome %}{% endblock %}

{% block main %}
<div class="auth">
  <div class="auth-card">
    <div class="brand"><span class="dot"></span> Truth of <span class="grad-text">Auditor</span></div>
    <h1>Buat <span class="grad-text">password baru</span></h1>
    <p class="sub">Demi keamanan, ganti password sementara dari admin dengan password pribadimu sebelum melanjutkan.</p>
    {% if form.non_field_errors %}<div class="err">{{ form.non_field_errors|join:" " }}</div>{% endif %}
    <form method="post" novalidate>
      {% csrf_token %}
      <div class="field">
        <label for="id_old_password">Password lama (sementara)</label>
        <input type="password" name="old_password" id="id_old_password" autocomplete="current-password" autofocus required>
        {% for e in form.old_password.errors %}<div class="fe">{{ e }}</div>{% endfor %}
      </div>
      <div class="field">
        <label for="id_new_password1">Password baru</label>
        <input type="password" name="new_password1" id="id_new_password1" autocomplete="new-password" required>
        {% for e in form.new_password1.errors %}<div class="fe">{{ e }}</div>{% endfor %}
      </div>
      <div class="field">
        <label for="id_new_password2">Konfirmasi password baru</label>
        <input type="password" name="new_password2" id="id_new_password2" autocomplete="new-password" required>
        {% for e in form.new_password2.errors %}<div class="fe">{{ e }}</div>{% endfor %}
      </div>
      <button class="btn primary" type="submit">Simpan &amp; lanjut &rarr;</button>
    </form>
    <div class="foot">
      Bukan kamu?
      <form method="post" action="{% url 'logout' %}" style="display:inline">{% csrf_token %}<button type="submit">Keluar</button></form>
    </div>
  </div>
</div>
{% endblock %}

{% block scripts %}{% endblock %}
```

- [ ] **Step 7: Jalankan test — pastikan LULUS**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_force_password.GantiPasswordViewTests -v2`
Expected: PASS (4 test).

- [ ] **Step 8: Commit**

```bash
git add web/views.py web/urls.py web/templates/registration/ganti_password.html web/tests_force_password.py
git commit -m "feat(web): halaman ganti-password (view+url+template), sukses jaga sesi

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Middleware gerbang (tidak bisa di-bypass)

**Files:**
- Create: `web/middleware.py`
- Modify: `truth_auditor/settings.py` (daftarkan middleware)
- Test: `web/tests_force_password.py` (tambah class)

**Interfaces:**
- Consumes: `User.must_change_password` (Task 1), URL name `ganti_password` & `logout`.
- Produces: `web.middleware.ForcePasswordChangeMiddleware` — untuk user login ber-flag `True`, semua request di luar allowlist (`ganti_password`, `logout`, aset `STATIC_URL`/`MEDIA_URL`) dialihkan ke `ganti_password`.

- [ ] **Step 1: Tulis test yang gagal**

Tambahkan ke `web/tests_force_password.py`:

```python
class ForcePasswordChangeMiddlewareTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("gate_u", password="Lama-Kuat#88", role="supervisor")

    def _login(self, flag):
        self.u.must_change_password = flag
        self.u.save(update_fields=["must_change_password"])
        self.client.login(username="gate_u", password="Lama-Kuat#88")

    def test_flag_true_dialihkan_dari_dashboard(self):
        self._login(True)
        r = self.client.get(reverse("dashboard"))
        self.assertRedirects(r, reverse("ganti_password"))

    def test_flag_true_dialihkan_dari_url_dalam(self):
        self._login(True)
        r = self.client.get(reverse("transactions"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("ganti_password"))

    def test_flag_true_boleh_buka_halaman_ganti(self):
        self._login(True)
        r = self.client.get(reverse("ganti_password"))
        self.assertEqual(r.status_code, 200)

    def test_flag_true_boleh_logout(self):
        self._login(True)
        r = self.client.post(reverse("logout"))
        self.assertRedirects(r, reverse("login"), fetch_redirect_response=False)

    def test_flag_false_akses_normal(self):
        self._login(False)
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
```

- [ ] **Step 2: Jalankan test — pastikan GAGAL**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_force_password.ForcePasswordChangeMiddlewareTests -v2`
Expected: FAIL — `test_flag_true_dialihkan_dari_dashboard` / `_url_dalam` gagal karena belum ada gerbang (dashboard balas 200, bukan redirect ke ganti_password).

- [ ] **Step 3: Buat middleware**

Buat `web/middleware.py`:

```python
"""Middleware gerbang: paksa user ber-flag must_change_password ke halaman ganti password."""
from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """Selama flag menyala, semua halaman selain allowlist dialihkan ke
    halaman ganti password — tidak bisa di-bypass dengan mengetik URL langsung.

    Allowlist: halaman ganti password itu sendiri (hindari loop), logout
    (user harus bisa keluar), dan aset statis/media (agar CSS/font halaman termuat).
    Harus dipasang SETELAH AuthenticationMiddleware (butuh request.user).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "must_change_password", False):
            path = request.path
            allowed = (reverse("ganti_password"), reverse("logout"))
            asset_prefixes = tuple(p for p in (settings.STATIC_URL, settings.MEDIA_URL) if p)
            if path not in allowed and not path.lstrip("/").startswith(asset_prefixes):
                return redirect("ganti_password")
        return self.get_response(request)
```

- [ ] **Step 4: Daftarkan middleware di settings**

Di `truth_auditor/settings.py`, dalam list `MIDDLEWARE`, tambahkan baris tepat SETELAH `AuthenticationMiddleware`. Hasil akhir blok:

```python
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'web.middleware.ForcePasswordChangeMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
```

- [ ] **Step 5: Jalankan test — pastikan LULUS**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_force_password.ForcePasswordChangeMiddlewareTests -v2`
Expected: PASS (5 test).

- [ ] **Step 6: Commit**

```bash
git add web/middleware.py truth_auditor/settings.py web/tests_force_password.py
git commit -m "feat(web): ForcePasswordChangeMiddleware — gerbang wajib ganti password

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Admin men-set flag saat buat user & reset password

**Files:**
- Modify: `web/admin_views.py` (`kelola_user` create; `kelola_user_edit` reset_password)
- Test: `web/tests_force_password.py` (tambah class)

**Interfaces:**
- Consumes: `User.must_change_password` (Task 1).
- Produces: user baru via `kelola_user` → flag `True`; `reset_password` atas user LAIN → flag `True`; `reset_password` atas DIRI SENDIRI → flag tetap `False`.

- [ ] **Step 1: Tulis test yang gagal**

Tambahkan ke `web/tests_force_password.py`:

```python
class MustChangePasswordTriggerTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("adm", password="Adm-Kuat#88", role="admin")
        self.client.login(username="adm", password="Adm-Kuat#88")
        self.lbs = Toko.objects.get(key="lbs")

    def test_buat_user_baru_flag_true(self):
        self.client.post(reverse("kelola_user"), {
            "username": "budi", "password": "Budi-Kuat#88", "nama": "Budi",
            "role": "auditor", "tokos": [self.lbs.id],
        })
        u = User.objects.get(username="budi")
        self.assertTrue(u.must_change_password)

    def test_reset_user_lain_flag_true(self):
        target = User.objects.create_user("someone", password="Lama-Kuat#88", role="supervisor")
        self.assertFalse(target.must_change_password)
        self.client.post(reverse("kelola_user_edit", args=[target.pk]), {
            "action": "reset_password", "password": "Baru-Kuat#99",
        })
        target.refresh_from_db()
        self.assertTrue(target.must_change_password)

    def test_reset_diri_sendiri_flag_tetap_false(self):
        self.client.post(reverse("kelola_user_edit", args=[self.admin.pk]), {
            "action": "reset_password", "password": "Adm-Baru#99",
        })
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.must_change_password)
```

- [ ] **Step 2: Jalankan test — pastikan GAGAL**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_force_password.MustChangePasswordTriggerTests -v2`
Expected: FAIL — `test_buat_user_baru_flag_true` dan `test_reset_user_lain_flag_true` gagal (flag masih `False`).

- [ ] **Step 3: Set flag saat buat user (`kelola_user`)**

Di `web/admin_views.py`, di dalam `kelola_user`, pada cabang sukses, ubah baris:

```python
            u = User.objects.create_user(username=username, password=password, first_name=nama, role=role)
```

menjadi:

```python
            u = User.objects.create_user(
                username=username, password=password, first_name=nama, role=role,
                must_change_password=True,  # wajib ganti password sementara saat login pertama
            )
```

- [ ] **Step 4: Set flag saat reset password (`kelola_user_edit`)**

Di `web/admin_views.py`, di dalam `kelola_user_edit`, cabang `action == "reset_password"` sukses, ubah:

```python
            target.set_password(pw)
            target.save()
            if target == request.user:
                update_session_auth_hash(request, target)
```

menjadi:

```python
            target.set_password(pw)
            # reset oleh admin = password sementara → wajib ganti; kecuali admin
            # me-reset password DIRINYA SENDIRI (dia memilih passwordnya sendiri).
            target.must_change_password = target != request.user
            target.save()
            if target == request.user:
                update_session_auth_hash(request, target)
```

(`target.save()` tanpa `update_fields` menyimpan semua field termasuk `must_change_password`.)

- [ ] **Step 5: Jalankan test — pastikan LULUS**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_force_password.MustChangePasswordTriggerTests -v2`
Expected: PASS (3 test).

- [ ] **Step 6: Commit**

```bash
git add web/admin_views.py web/tests_force_password.py
git commit -m "feat(web): admin set must_change_password saat buat user & reset (bukan reset diri sendiri)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Regresi penuh — pastikan tidak ada yang rusak

**Files:** (tidak ada perubahan kode; verifikasi menyeluruh)

- [ ] **Step 1: Jalankan seluruh modul fitur ini**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_force_password -v2`
Expected: PASS (semua 19 test: 2+5+4+5+3).

- [ ] **Step 2: Jalankan seluruh test suite proyek**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test`
Expected: PASS (≈495 test lama + 19 baru; tidak ada kegagalan). Perhatikan khusus: `web.tests_auth`, `web.tests_kelola`, `web.tests_password_policy` — mereka membuat user & login; middleware baru tidak boleh mematahkannya (user di test itu default flag `False`).

- [ ] **Step 3: Bila ada test lama yang gagal**

Kemungkinan penyebab: sebuah test lama mengandalkan user login yang tanpa sengaja ber-flag `True`, atau test membuat user via `kelola_user` lalu login sebagai user itu. Diagnosa dengan `-v2`, perbaiki test/atau logika sesuai temuan (jangan longgarkan gerbang). Ulangi Step 2 sampai hijau.

- [ ] **Step 4: Commit (bila Step 3 mengubah sesuatu)**

```bash
git add -A
git commit -m "test: perbaiki regresi setelah gerbang wajib ganti password

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Verifikasi manual (setelah semua task hijau)

Opsional tapi disarankan sebelum merge/deploy (butuh `db.sqlite3` dev — salin dari checkout utama bila perlu, lihat CLAUDE.md):

1. `python manage.py runserver`, login sebagai admin.
2. Kelola User → buat user baru (mis. `demo` / `Demo-Kuat#88`, auditor, 1 toko).
3. Logout, login sebagai `demo`. **Harus** langsung dialihkan ke `/ganti-password/`.
4. Coba ketik URL `/transactions/` langsung → tetap dialihkan ke ganti password.
5. Isi form: password lama benar, baru = lama → error "harus berbeda". Baru lemah → error validator. Konfirmasi beda → error. Baru kuat & beda → sukses, masuk dashboard, tidak lagi diminta ganti.
6. Sebagai admin, Kelola User → reset password `demo`. Logout & login `demo` → diminta ganti lagi. Reset password **admin sendiri** → admin TIDAK diminta ganti.

## Ringkasan file

| File | Aksi | Tanggung jawab |
|---|---|---|
| `accounts/models.py` | modif | Field flag `must_change_password` |
| `accounts/migrations/0003_user_must_change_password.py` | baru | Migrasi field |
| `web/forms.py` | baru | `GantiPasswordForm` (validasi + wajib beda) |
| `web/views.py` | modif | View `ganti_password` (+ import) |
| `web/urls.py` | modif | Route `ganti-password/` |
| `web/templates/registration/ganti_password.html` | baru | Halaman ganti password (standalone) |
| `web/middleware.py` | baru | Gerbang `ForcePasswordChangeMiddleware` |
| `truth_auditor/settings.py` | modif | Daftarkan middleware |
| `web/admin_views.py` | modif | Set flag saat buat user & reset (bukan diri sendiri) |
| `web/tests_force_password.py` | baru | 19 test (model, form, view, middleware, trigger) |
