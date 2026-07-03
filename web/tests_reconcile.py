from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.engine import run_batch
from reconciliation.models import (
    MatchResult,
    MatchRun,
    ReconBatch,
    ReviewAction,
    ToleranceProfile,
)
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class ReconcileViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
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

    def test_post_unknown_tolerance_returns_404(self):
        n = ReconBatch.objects.count()
        r = self.client.post(reverse("reconcile"), {"tolerance": "nope"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(ReconBatch.objects.count(), n)  # tak ada batch dibuat


class BatchDetailTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
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


class ReviewViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.lbs = Toko.objects.get(key="lbs")
        batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=batch
        )
        self.result = MatchResult.objects.create(
            run=run, bucket=MatchResult.Bucket.TINJAU, reason_code="init"
        )
        self.url = reverse("review", args=[self.result.pk])

    def test_get_returns_405_and_no_side_effects(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 405)
        self.assertEqual(ReviewAction.objects.count(), 0)
        self.result.refresh_from_db()
        self.assertEqual(self.result.bucket, MatchResult.Bucket.TINJAU)
        self.assertEqual(self.result.reason_code, "init")

    def test_post_invalid_action_returns_400_and_no_side_effects(self):
        r = self.client.post(self.url, {"action": "explode"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(ReviewAction.objects.count(), 0)
        self.result.refresh_from_db()
        self.assertEqual(self.result.bucket, MatchResult.Bucket.TINJAU)
        self.assertEqual(self.result.reason_code, "init")

    def test_post_missing_action_returns_400_and_no_side_effects(self):
        r = self.client.post(self.url, {})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(ReviewAction.objects.count(), 0)
        self.result.refresh_from_db()
        self.assertEqual(self.result.bucket, MatchResult.Bucket.TINJAU)

    def test_post_valid_action_updates_and_logs(self):
        r = self.client.post(self.url, {"action": "mark_matched"})
        self.assertEqual(r.status_code, 200)
        self.result.refresh_from_db()
        self.assertEqual(self.result.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(self.result.reason_code, "manual_override")
        self.assertEqual(ReviewAction.objects.count(), 1)
        ra = ReviewAction.objects.get()
        self.assertEqual(ra.action, "mark_matched")
