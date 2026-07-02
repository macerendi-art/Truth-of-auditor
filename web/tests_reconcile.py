from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.engine import run_batch
from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class ReconcileViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345")
        self.client.login(username="aud", password="pw12345")
        ToleranceProfile.objects.get_or_create(name="Default", defaults={"date_window_days": 1})
        self.lbs = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        up = Upload.objects.create(source_type=panel, toko=self.lbs)
        for st, rh in [(panel, "r1"), (bank, "r2")]:
            Transaction.objects.create(
                upload=up, source_type=st, toko=self.lbs, jenis="depo",
                amount=Decimal("50000"), money_delta=Decimal("50000"),
                occurred_at=datetime(2026, 6, 27, 10, 0), row_hash=rh,
            )

    def test_get_shows_completeness(self):
        r = self.client.get(reverse("reconcile"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["completeness"]["minimum_met"])

    def test_post_runs_batch_and_redirects(self):
        r = self.client.post(reverse("reconcile"), {"tolerance": "Default"})
        self.assertEqual(r.status_code, 302)
        batch = ReconBatch.objects.latest("id")
        self.assertEqual(r.url, reverse("batch_detail", args=[batch.pk]))
        self.assertEqual(batch.toko, self.lbs)


class BatchDetailTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345")
        self.client.login(username="aud", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(name="Default", defaults={"date_window_days": 1})[0]
        self.lbs = Toko.objects.get(key="lbs")
        panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        up = Upload.objects.create(source_type=panel, toko=self.lbs)
        for st, rh in [(panel, "d1"), (bank, "d2")]:
            Transaction.objects.create(
                upload=up, source_type=st, toko=self.lbs, jenis="depo",
                amount=Decimal("50000"), money_delta=Decimal("50000"),
                occurred_at=datetime(2026, 6, 27, 10, 0), row_hash=rh,
            )

    def test_batch_detail_renders(self):
        batch = run_batch(self.lbs, self.tol)
        r = self.client.get(reverse("batch_detail", args=[batch.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Deposit")
        self.assertContains(r, "Withdraw")
