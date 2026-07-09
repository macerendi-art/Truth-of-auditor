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
