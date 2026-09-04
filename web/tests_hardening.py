"""Hardening produksi Gelombang 1 (04-09-2026): C1 HSTS, C2 CSP, C3 sesi,
B2 pelacak error, B4 format logging.

Aplikasi memuat data finansial riil — default harus fail-safe: env hilang di
produksi = tetap ketat (HSTS/sesi), bukan diam-diam longgar; pelacak error
mati total tanpa env (nol ketergantungan SaaS berbayar tanpa opt-in
eksplisit); log punya waktu/level/logger supaya bisa dibaca ops.

Beberapa setelan (HSTS, level log) hanya benar-benar di-set di dalam blok
`if not DEBUG:` truth_auditor/settings.py, atau lewat env yang dibaca SEKALI
saat modul diimpor. Proses tes ITU SENDIRI selalu berjalan dengan DEBUG=True
(default lokal) — memeriksa `settings.X` langsung di proses tes tidak pernah
menyentuh kode di dalam blok itu. Untuk butir-butir itu, `_atribut_setelan`
mengimpor `truth_auditor.settings` di SUBPROCESS bersih dengan env
terkendali (pola sama dengan `core/tests_settings_guard.py`), sehingga
benar-benar diuji jalur produksi, bukan cuma dibaca dari state proses tes.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from truth_auditor.security import configure_sentry

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


# ------------------------------------------------------ B2: pelacak error --

class SentryOpsionalTests(SimpleTestCase):
    def test_tanpa_dsn_tidak_memanggil_sentry_init(self):
        with mock.patch("sentry_sdk.init") as m:
            hasil = configure_sentry({}, debug=False)
        m.assert_not_called()
        self.assertFalse(hasil)

    def test_dengan_dsn_memanggil_sentry_init_sekali(self):
        with mock.patch("sentry_sdk.init") as m:
            hasil = configure_sentry(
                {"SENTRY_DSN": "https://abc@example.com/1"}, debug=False
            )
        m.assert_called_once()
        self.assertTrue(hasil)
        _, kwargs = m.call_args
        self.assertEqual(kwargs["dsn"], "https://abc@example.com/1")
        self.assertFalse(kwargs["send_default_pii"])

    def test_boot_tanpa_env_apa_pun_tetap_sah(self):
        # settings.py memanggil configure_sentry(...) di LEVEL MODUL saat
        # diimpor. Subprocess bersih tanpa SENTRY_DSN membuktikan boot tetap
        # sukses (returncode 0) — kalau configure_sentry diam-diam mengimpor
        # sentry_sdk walau DSN kosong, dan suatu lingkungan belum memasang
        # paketnya, ini akan gagal.
        self.assertIn(_atribut_setelan("DEBUG", {}), (True, False))


class AdminsEmailTests(SimpleTestCase):
    def test_default_kosong_tanpa_env(self):
        self.assertEqual(settings.ADMINS, [])
        self.assertEqual(settings.SERVER_EMAIL, "root@localhost")

    def test_admins_dari_env(self):
        admins = _atribut_setelan(
            "ADMINS", {"DJANGO_ADMIN_EMAILS": "budi@x.com,sari@y.com"}
        )
        self.assertEqual(admins, [["budi", "budi@x.com"], ["sari", "sari@y.com"]])

    def test_email_default_identik_bawaan_django(self):
        # Nol env = nol perubahan perilaku dari default Django sendiri. Dibaca
        # lewat subprocess (bukan `settings.EMAIL_BACKEND` langsung) karena
        # test runner Django MENIMPA EMAIL_BACKEND ke locmem selama suite tes
        # berjalan — itu perilaku standar Django, tak ada hubungannya dgn
        # perubahan ini, dan akan menyesatkan kalau dibaca dari proses tes.
        self.assertEqual(
            _atribut_setelan("EMAIL_BACKEND", {}),
            "django.core.mail.backends.smtp.EmailBackend",
        )
        self.assertEqual(_atribut_setelan("EMAIL_HOST", {}), "localhost")
        self.assertEqual(_atribut_setelan("EMAIL_PORT", {}), 25)
        self.assertFalse(_atribut_setelan("EMAIL_USE_TLS", {}))


# ------------------------------------------------------ B4: format logging -

class LoggingFormatTests(SimpleTestCase):
    def test_formatter_console_punya_waktu_level_logger_pesan(self):
        fmt = settings.LOGGING["formatters"]["ringkas"]["format"]
        for token in ("%(asctime)s", "%(levelname)s", "%(name)s", "%(message)s"):
            self.assertIn(token, fmt)
        self.assertEqual(settings.LOGGING["handlers"]["console"]["formatter"], "ringkas")

    def test_mail_admins_handler_ada_di_django_request(self):
        handlers = settings.LOGGING["loggers"]["django.request"]["handlers"]
        self.assertIn("mail_admins", handlers)
        self.assertEqual(
            settings.LOGGING["handlers"]["mail_admins"]["class"],
            "django.utils.log.AdminEmailHandler",
        )

    def test_root_level_default_warning_tak_berubah(self):
        # Kontrak lama: root WARNING supaya logger.info() lain tak
        # membanjiri log — jangan berubah tanpa keputusan eksplisit terpisah.
        self.assertEqual(settings.LOGGING["root"]["level"], "WARNING")

    def test_level_bisa_dinaikkan_lewat_env_tanpa_deploy_ulang(self):
        cfg = _atribut_setelan("LOGGING", {"DJANGO_LOG_LEVEL": "INFO"})
        self.assertEqual(cfg["root"]["level"], "INFO")

    def test_level_env_tak_sah_jatuh_ke_warning(self):
        cfg = _atribut_setelan("LOGGING", {"DJANGO_LOG_LEVEL": "OMONGKOSONG"})
        self.assertEqual(cfg["root"]["level"], "WARNING")

    def test_tidak_ada_konfigurasi_debug_sql_logging(self):
        # django.db.backends di level DEBUG akan membanjiri log dengan query
        # analitik panjang di atas 8,8 juta baris data — sengaja tak diberi
        # entri khusus sama sekali (root WARNING sudah cukup menahannya).
        self.assertNotIn("django.db.backends", settings.LOGGING.get("loggers", {}))

    def test_penjaga_dan_tambah_index_aman_tetap_terlihat(self):
        # web/penjaga.py & core/db_ops.py (TambahIndexAman) logger.warning()
        # harus tetap lolos lewat handler console default (root WARNING).
        import logging as _logging

        for nama in ("web.penjaga", "core.db_ops"):
            with self.subTest(logger=nama):
                self.assertTrue(_logging.getLogger(nama).isEnabledFor(_logging.WARNING))
