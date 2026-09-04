"""Hardening produksi Gelombang 1 (04-09-2026): C1 HSTS, C2 CSP, C3 sesi.

Aplikasi memuat data finansial riil — default harus fail-safe: env hilang di
produksi = tetap ketat (HSTS/sesi), bukan diam-diam longgar.

Beberapa setelan (HSTS) hanya benar-benar di-set di dalam blok
`if not DEBUG:` truth_auditor/settings.py. Proses tes ITU SENDIRI selalu
berjalan dengan DEBUG=True (default lokal) — memeriksa `settings.X` langsung
di proses tes tidak pernah menyentuh kode di dalam blok itu. Untuk butir itu,
`_atribut_setelan` mengimpor `truth_auditor.settings` di SUBPROCESS bersih
dengan env terkendali (pola sama dengan `core/tests_settings_guard.py`),
sehingga benar-benar diuji jalur produksi, bukan cuma dibaca dari state
proses tes.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

BASE_DIR = Path(settings.BASE_DIR)

_ENV_DIKONTROL = (
    "SECRET_KEY", "DEBUG", "DATABASE_URL", "RAILWAY_ENVIRONMENT",
    "SECURE_HSTS_SECONDS", "DJANGO_LOG_LEVEL", "SENTRY_DSN",
    "DJANGO_ADMIN_EMAILS", "SERVER_EMAIL",
)
_TAK_ADA = "__TAK_ADA_DI_MODUL__"


def _atribut_setelan(attr, extra_env):
    """Ambil satu atribut modul `truth_auditor.settings` di subprocess bersih.

    `getattr(..., _TAK_ADA)` membedakan "atribut genuinely tidak pernah
    didefinisikan modul" (mis. SECURE_HSTS_SECONDS saat DEBUG=True — blok
    produksi tak jalan sama sekali) dari "atribut ada tapi bernilai None/0".
    """
    env = {k: v for k, v in os.environ.items() if k not in _ENV_DIKONTROL}
    env.update(extra_env)
    env.setdefault("SECRET_KEY", "x" * 60)
    kode = (
        "import json\n"
        "import truth_auditor.settings as s\n"
        f"print(json.dumps(getattr(s, {attr!r}, {_TAK_ADA!r})))\n"
    )
    p = subprocess.run(
        [sys.executable, "-c", kode],
        env=env, capture_output=True, text=True, cwd=BASE_DIR, timeout=60,
    )
    if p.returncode != 0:
        raise AssertionError(f"subprocess gagal mengimpor settings (attr={attr}):\n{p.stderr}")
    return json.loads(p.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- C1: HSTS --

class HstsProduksiTests(SimpleTestCase):
    def test_default_produksi_satu_tahun(self):
        self.assertEqual(
            _atribut_setelan("SECURE_HSTS_SECONDS", {"DEBUG": "False"}),
            31536000,
        )

    def test_subdomains_dan_preload_ikut_menyala(self):
        self.assertTrue(_atribut_setelan("SECURE_HSTS_INCLUDE_SUBDOMAINS", {"DEBUG": "False"}))
        self.assertTrue(_atribut_setelan("SECURE_HSTS_PRELOAD", {"DEBUG": "False"}))

    def test_bisa_ditimpa_env(self):
        self.assertEqual(
            _atribut_setelan("SECURE_HSTS_SECONDS", {"DEBUG": "False", "SECURE_HSTS_SECONDS": "3600"}),
            3600,
        )

    def test_dev_lokal_tak_pernah_kena_hsts(self):
        # DEBUG default True tanpa RAILWAY_ENVIRONMENT — blok produksi (yang
        # men-set SECURE_HSTS_SECONDS) tak pernah dieksekusi; atribut ini
        # genuinely tak pernah didefinisikan di modul (bukan Django default 0).
        self.assertEqual(_atribut_setelan("SECURE_HSTS_SECONDS", {}), _TAK_ADA)


# --------------------------------------------------------------- C2: CSP ---

class CspHeaderTests(TestCase):
    def test_csp_header_terpasang_di_halaman_login(self):
        r = self.client.get(reverse("login"))
        csp = r.headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("frame-ancestors 'none'", csp)

    def test_middleware_terdaftar_setelah_security_sebelum_whitenoise(self):
        mw = settings.MIDDLEWARE
        i_sec = mw.index("django.middleware.security.SecurityMiddleware")
        i_csp = mw.index("core.middleware.ContentSecurityPolicyMiddleware")
        i_wn = mw.index("whitenoise.middleware.WhiteNoiseMiddleware")
        self.assertTrue(i_sec < i_csp < i_wn)

    def test_rantai_auth_geoblock_forcepassword_ipallowlist_tak_terganggu(self):
        # Preseden yang sudah dipin web/tests_ip_allowlist.py — menyisipkan
        # CSP di AWAL daftar (dekat SecurityMiddleware) hanya menggeser semua
        # indeks sesudahnya dengan konstanta yang sama; urutan RELATIF ini
        # harus tetap bertahan.
        mw = settings.MIDDLEWARE
        i_auth = mw.index("django.contrib.auth.middleware.AuthenticationMiddleware")
        i_geo = mw.index("web.middleware.GeoBlockMiddleware")
        i_force = mw.index("web.middleware.ForcePasswordChangeMiddleware")
        i_ip = mw.index("web.middleware.IPAllowlistMiddleware")
        self.assertTrue(i_auth < i_geo < i_force < i_ip)


# ------------------------------------------------------------- C3: sesi ----

class SesiHardeningTests(SimpleTestCase):
    def test_sesi_8_jam_rolling_expire_saat_browser_tutup(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 8 * 3600)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
