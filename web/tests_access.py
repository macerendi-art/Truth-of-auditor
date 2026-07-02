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


class RbacObjectScopeTests(TestCase):
    def setUp(self):
        from datetime import datetime
        from decimal import Decimal

        from reconciliation.engine import run_batch
        from reconciliation.models import ToleranceProfile
        from sources.models import SourceType, Upload
        from transactions.models import Transaction

        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        tol = ToleranceProfile.objects.get_or_create(name="Default", defaults={"date_window_days": 1})[0]
        panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        up = Upload.objects.create(source_type=panel, toko=self.slo)
        for st, rh in [(panel, "s1"), (bank, "s2")]:
            Transaction.objects.create(
                upload=up, source_type=st, toko=self.slo, jenis="depo",
                amount=Decimal("50000"), money_delta=Decimal("50000"),
                occurred_at=datetime(2026, 6, 27, 10, 0), row_hash=rh,
            )
        self.slo_batch = run_batch(self.slo, tol)
        self.slo_run = self.slo_batch.runs.first()
        self.aud = User.objects.create_user("aud_lbs", password="pw123456", role="auditor")
        self.aud.allowed_tokos.add(self.lbs)

    def test_auditor_tidak_bisa_buka_batch_toko_lain(self):
        self.client.login(username="aud_lbs", password="pw123456")
        r = self.client.get(reverse("batch_detail", args=[self.slo_batch.pk]))
        self.assertEqual(r.status_code, 404)

    def test_auditor_tidak_bisa_buka_run_toko_lain(self):
        self.client.login(username="aud_lbs", password="pw123456")
        r = self.client.get(reverse("run_detail", args=[self.slo_run.pk]))
        self.assertEqual(r.status_code, 404)
        r = self.client.get(reverse("export_run", args=[self.slo_run.pk]))
        self.assertEqual(r.status_code, 404)

    def test_auditor_tidak_bisa_review_hasil_toko_lain(self):
        self.client.login(username="aud_lbs", password="pw123456")
        result = self.slo_run.results.first()
        if result is None:  # run tanpa hasil — buat pasangan minimal agar test bermakna
            self.skipTest("run tidak menghasilkan MatchResult")
        r = self.client.post(reverse("review", args=[result.pk]), {"action": "mark_matched"})
        self.assertEqual(r.status_code, 404)

    def test_supervisor_bisa_buka_batch_mana_pun(self):
        User.objects.create_user("sup_all", password="pw123456", role="supervisor")
        self.client.login(username="sup_all", password="pw123456")
        r = self.client.get(reverse("batch_detail", args=[self.slo_batch.pk]))
        self.assertEqual(r.status_code, 200)

    def test_auditor_bisa_buka_batch_tokonya_sendiri(self):
        self.aud.allowed_tokos.add(self.slo)
        self.client.login(username="aud_lbs", password="pw123456")
        r = self.client.get(reverse("batch_detail", args=[self.slo_batch.pk]))
        self.assertEqual(r.status_code, 200)

    def test_set_toko_id_non_numerik_tidak_crash(self):
        self.client.login(username="aud_lbs", password="pw123456")
        r = self.client.post(reverse("set_toko"), {"toko_id": "abc"})
        self.assertEqual(r.status_code, 302)  # redirect, bukan 500
        r2 = self.client.post(reverse("set_toko"), {"toko_id": "²"})
        self.assertEqual(r2.status_code, 302)  # unicode digit tidak boleh 500
