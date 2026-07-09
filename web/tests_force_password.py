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
