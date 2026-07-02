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
