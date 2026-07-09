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
