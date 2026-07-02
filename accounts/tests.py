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
