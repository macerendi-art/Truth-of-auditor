"""Hardening produksi: CSP, sesi, cap upload, SECRET_KEY fail-hard.

Aplikasi memuat data finansial riil — default harus fail-safe: env hilang di
produksi = mati saat boot, bukan diam-diam jalan dengan konfigurasi insecure.
"""
from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from sources.models import Toko
from truth_auditor.security import resolve_secret_key

User = get_user_model()


class SecretKeyTests(TestCase):
    def test_produksi_tanpa_secret_key_mati(self):
        with self.assertRaises(ImproperlyConfigured):
            resolve_secret_key(env={}, debug=False)

    def test_produksi_dengan_secret_key_jalan(self):
        self.assertEqual(
            resolve_secret_key(env={"SECRET_KEY": "abc"}, debug=False), "abc"
        )

    def test_dev_tanpa_secret_key_pakai_fallback(self):
        key = resolve_secret_key(env={}, debug=True)
        self.assertTrue(key.startswith("django-insecure-"))


from django.test import override_settings


@override_settings(AXES_ENABLED=True)
class BruteForceTests(TestCase):
    """django-axes: 5x salah password = akun+IP dikunci sementara (429)."""

    def setUp(self):
        User.objects.create_user("adm", password="pw123456", role="admin")

    def test_lockout_setelah_5_gagal(self):
        url = reverse("login")
        for _ in range(5):
            r = self.client.post(url, {"username": "adm", "password": "salah"})
        # Percobaan ke-6 dengan password BENAR pun ditolak — lockout aktif.
        r = self.client.post(url, {"username": "adm", "password": "pw123456"})
        self.assertEqual(r.status_code, 429)

    def test_di_bawah_limit_tetap_bisa_login(self):
        url = reverse("login")
        for _ in range(3):
            self.client.post(url, {"username": "adm", "password": "salah"})
        r = self.client.post(url, {"username": "adm", "password": "pw123456"})
        self.assertEqual(r.status_code, 302)  # sukses → redirect


class ClientIpTests(TestCase):
    """Di belakang proxy Railway REMOTE_ADDR = IP internal load balancer yang
    berganti-ganti — lockout kombo username+IP tak pernah akumulasi. IP klien
    diambil dari hop TERAKHIR X-Forwarded-For (ditulis edge Railway; entri
    kiriman penyerang berada di depannya dan tidak dipercaya)."""

    def _req(self, **meta):
        from django.test import RequestFactory

        r = RequestFactory().get("/")
        r.META.update(meta)
        return r

    def test_xff_spoof_diabaikan_ambil_hop_terakhir(self):
        from truth_auditor.security import client_ip

        r = self._req(HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.9",
                      REMOTE_ADDR="100.64.0.3")
        self.assertEqual(client_ip(r), "203.0.113.9")

    def test_tanpa_xff_pakai_remote_addr(self):
        from truth_auditor.security import client_ip

        r = self._req(REMOTE_ADDR="127.0.0.1")
        self.assertEqual(client_ip(r), "127.0.0.1")


class CspHeaderTests(TestCase):
    def test_csp_header_terpasang(self):
        r = self.client.get(reverse("login"))
        csp = r.headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)


class SessionHardeningTests(TestCase):
    def test_sesi_kadaluarsa_8_jam(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 8 * 3600)
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)

    def test_folder_besar_tidak_ditolak_django(self):
        # Picker folder bisa kirim ratusan file sekaligus; default Django 100.
        self.assertGreaterEqual(settings.DATA_UPLOAD_MAX_NUMBER_FILES, 300)


class StagingSweepTests(TestCase):
    """File staging yatim (analyze tanpa commit) tidak boleh menumpuk di volume."""

    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def test_file_lama_disapu_file_baru_selamat(self):
        import os
        import time

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        lama = default_storage.save("staging/yatim-lama.csv", ContentFile(b"a,b"))
        baru = default_storage.save("staging/baru.csv", ContentFile(b"a,b"))
        kemarin = time.time() - 25 * 3600
        os.utime(default_storage.path(lama), (kemarin, kemarin))
        try:
            self.client.post(reverse("upload"), {"action": "analyze"})
            self.assertFalse(default_storage.exists(lama))
            self.assertTrue(default_storage.exists(baru))
        finally:
            for p in (lama, baru):
                if default_storage.exists(p):
                    default_storage.delete(p)


class UploadCapTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def test_file_melebihi_cap_ditolak(self):
        from web import views

        asli = views._FILE_MAX_BYTES
        views._FILE_MAX_BYTES = 10
        try:
            f = SimpleUploadedFile("besar.csv", b"x" * 100)
            r = self.client.post(
                reverse("upload"), {"action": "analyze", "files": [f]}, follow=True
            )
            self.assertContains(r, "terlalu besar")
        finally:
            views._FILE_MAX_BYTES = asli

    def test_total_request_melebihi_cap_ditolak(self):
        from web import views

        asli = views._REQ_MAX_BYTES
        views._REQ_MAX_BYTES = 10
        try:
            f = SimpleUploadedFile("a.csv", b"x" * 100)
            r = self.client.post(
                reverse("upload"), {"action": "analyze", "files": [f]}, follow=True
            )
            self.assertContains(r, "terlalu besar")
        finally:
            views._REQ_MAX_BYTES = asli
