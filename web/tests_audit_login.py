"""C6: login/logout/gagal-login diaudit.

`User.last_login` cuma satu kolom yang ditimpa tiap login — bukan riwayat.
`web/signals.py` menambah receiver untuk `user_logged_in`/`user_logged_out`/
`user_login_failed` yang menulis satu `AuditLog` per kejadian lewat
`core.audit.catat()`. Yang mudah salah dan sengaja diuji di sini: kata sandi
percobaan TIDAK PERNAH ikut tersimpan, `user_logged_out` bisa dipanggil
dengan `user=None`, dan `user_login_failed` tidak selalu membawa `request`.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_out, user_login_failed
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.models import AuditLog

User = get_user_model()


class LoginLogoutAuditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "pemakai", password="Pw-Kuat#88", role="auditor"
        )

    def test_login_sukses_tercatat(self):
        r = self.client.post(
            reverse("login"), {"username": "pemakai", "password": "Pw-Kuat#88"}
        )
        self.assertEqual(r.status_code, 302)  # login berhasil → redirect
        log = AuditLog.objects.filter(aksi="login").latest("id")
        self.assertEqual(log.username, "pemakai")
        self.assertEqual(log.user_id, self.user.pk)

    def test_logout_tercatat(self):
        self.client.login(username="pemakai", password="Pw-Kuat#88")
        self.client.post(reverse("logout"))
        log = AuditLog.objects.filter(aksi="logout").latest("id")
        self.assertEqual(log.username, "pemakai")
        self.assertEqual(log.user_id, self.user.pk)

    def test_login_gagal_tercatat_dan_password_tidak_tersimpan(self):
        self.client.post(
            reverse("login"), {"username": "pemakai", "password": "salah-total-99"}
        )
        log = AuditLog.objects.filter(aksi="login_gagal").latest("id")
        self.assertEqual(log.objek, "pemakai")
        self.assertIsNone(log.user)  # tak ada user yang berhasil terautentikasi
        # kata sandi percobaan TIDAK BOLEH ikut tersimpan di kolom mana pun
        self.assertNotIn("salah-total-99", log.objek)
        self.assertNotIn("salah-total-99", str(log.detail))

    def test_login_gagal_username_tak_dikenal_tetap_tercatat(self):
        self.client.post(
            reverse("login"), {"username": "tidak-terdaftar", "password": "apa-saja"}
        )
        log = AuditLog.objects.filter(aksi="login_gagal").latest("id")
        self.assertEqual(log.objek, "tidak-terdaftar")
        self.assertIsNone(log.user)

    def test_login_gagal_merekam_ip(self):
        self.client.post(
            reverse("login"),
            {"username": "pemakai", "password": "salah-lagi"},
            REMOTE_ADDR="203.0.113.20",
        )
        log = AuditLog.objects.filter(aksi="login_gagal").latest("id")
        self.assertEqual(log.ip, "203.0.113.20")


class SignalEdgeCaseTests(TestCase):
    """Jalur signal yang tidak selalu dilalui test client biasa."""

    def test_login_gagal_tanpa_kwarg_request_tidak_melempar(self):
        # Beberapa jalur Django mengirim user_login_failed TANPA kwarg
        # `request` sama sekali (bukan request=None) — receiver harus tetap
        # aman dan tidak menggagalkan proses autentikasi.
        user_login_failed.send(
            sender=self.__class__,
            credentials={"username": "siapa", "password": "rahasia123"},
        )
        log = AuditLog.objects.filter(aksi="login_gagal").latest("id")
        self.assertEqual(log.objek, "siapa")
        self.assertIsNone(log.ip)
        self.assertNotIn("rahasia123", str(log.detail))
        self.assertNotIn("rahasia123", log.objek)

    def test_login_gagal_credentials_bukan_dict_tidak_melempar(self):
        user_login_failed.send(sender=self.__class__, credentials=None)
        log = AuditLog.objects.filter(aksi="login_gagal").latest("id")
        self.assertEqual(log.objek, "(tidak diketahui)")

    def test_logout_dengan_user_none_tidak_melempar(self):
        req = RequestFactory().post("/logout/")
        user_logged_out.send(sender=self.__class__, request=req, user=None)
        log = AuditLog.objects.filter(aksi="logout").latest("id")
        self.assertEqual(log.objek, "(anonim)")
        self.assertIsNone(log.user)
