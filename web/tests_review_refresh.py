"""Override manual (review/bulk_review) harus MENYEGARKAN summary run & batch —
kartu "Cocok/Perlu Ditinjau" tidak boleh basi terhadap chip yang dihitung live."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import Toko


class ReviewRefreshSummaryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.lbs = Toko.objects.get(key="lbs")
        self.batch = ReconBatch.objects.create(
            toko=self.lbs, tolerance=self.tol,
            summary={"buckets": {"cocok": 0, "perlu_tinjau": 2, "tidak_cocok": 0},
                     "dp": {"panel": 0.0}, "wd": {"panel": 0.0}},
        )
        self.run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=self.batch,
            summary={"cocok": 0, "perlu_tinjau": 2, "tidak_cocok": 0},
        )
        self.r1 = MatchResult.objects.create(
            run=self.run, bucket=MatchResult.Bucket.TINJAU, reason_code="weak_name"
        )
        self.r2 = MatchResult.objects.create(
            run=self.run, bucket=MatchResult.Bucket.TINJAU, reason_code="weak_name"
        )

    def test_review_tunggal_menyegarkan_summary_run_dan_batch(self):
        r = self.client.post(
            reverse("review", args=[self.r1.pk]), {"action": "mark_matched"}
        )
        self.assertEqual(r.status_code, 200)
        self.run.refresh_from_db()
        self.assertEqual(self.run.summary["cocok"], 1)
        self.assertEqual(self.run.summary["perlu_tinjau"], 1)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.summary["buckets"]["cocok"], 1)
        self.assertEqual(self.batch.summary["buckets"]["perlu_tinjau"], 1)

    def test_bulk_review_menyegarkan_summary_run_dan_batch(self):
        r = self.client.post(
            reverse("bulk_review", args=[self.run.pk]),
            {"action": "mark_matched", "result_ids": [self.r1.pk, self.r2.pk]},
        )
        self.assertEqual(r.status_code, 302)
        self.run.refresh_from_db()
        self.assertEqual(self.run.summary["cocok"], 2)
        self.assertEqual(self.run.summary["perlu_tinjau"], 0)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.summary["buckets"]["cocok"], 2)
        self.assertEqual(self.batch.summary["buckets"]["perlu_tinjau"], 0)
