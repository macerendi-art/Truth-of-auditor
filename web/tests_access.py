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


class RbacScopeTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.aud = User.objects.create_user("aud1", password="pw123456", role="auditor")
        self.aud.allowed_tokos.add(self.lbs)
        self.client.login(username="aud1", password="pw123456")

    def test_set_toko_denied_for_unassigned(self):
        self.client.post(reverse("set_toko"), {"toko_id": self.slo.id})
        self.assertNotEqual(self.client.session.get("active_toko_id"), self.slo.id)

    def test_set_toko_allowed_for_assigned(self):
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.assertEqual(self.client.session.get("active_toko_id"), self.lbs.id)

    def test_dropdown_only_assigned(self):
        r = self.client.get(reverse("dashboard"))
        self.assertEqual([t.key for t in r.context["all_tokos"]], ["lbs"])

    def test_auditor_without_toko_gets_empty_state(self):
        User.objects.create_user("aud0", password="pw123456", role="auditor")
        self.client.login(username="aud0", password="pw123456")
        for name in ("dashboard", "upload", "transactions", "reconcile"):
            r = self.client.get(reverse(name))
            self.assertContains(r, "Tidak ada toko yang ditugaskan", msg_prefix=name)

    def test_supervisor_dropdown_all(self):
        User.objects.create_user("sup1", password="pw123456", role="supervisor")
        self.client.login(username="sup1", password="pw123456")
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(len(r.context["all_tokos"]), N_AKTIF)

    def test_revoked_session_toko_falls_back(self):
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.aud.allowed_tokos.clear()  # akses dicabut
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "Tidak ada toko yang ditugaskan")
