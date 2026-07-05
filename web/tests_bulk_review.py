"""Bulk review: setujui banyak hasil sekaligus dengan jejak ReviewAction per baris."""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.engine import run_match
from reconciliation.models import (
    MatchResult,
    MatchRun,
    ReconBatch,
    ReviewAction,
    ToleranceProfile,
)
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class BulkReviewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        up = Upload.objects.create(source_type=panel, toko=self.toko,
                                   original_name="P.xlsx")
        upb = Upload.objects.create(source_type=bank, toko=self.toko,
                                    original_name="B.csv")
        for i in range(3):
            Transaction.objects.create(
                upload=up, source_type=panel, toko=self.toko, jenis="wd",
                amount=Decimal("50000"), money_delta=Decimal("-50000"),
                occurred_at=datetime(2026, 6, 27, 9 + i), ticket_no=f"W{i}",
                counterparty=f"ORANG {i}", row_hash=f"p{i}",
            )
            Transaction.objects.create(
                upload=upb, source_type=bank, toko=self.toko, jenis="wd",
                amount=Decimal("50000"), money_delta=Decimal("-50000"),
                occurred_at=datetime(2026, 6, 27, 10 + i),
                counterparty=f"BEDA {i}", row_hash=f"b{i}",
            )
        batch = ReconBatch.objects.create(toko=self.toko, tolerance=self.tol)
        self.run = run_match(MatchRun.Relation.PANEL_BANK, self.tol, toko=self.toko,
                             batch=batch)

    def test_bulk_setujui(self):
        tinjau = list(MatchResult.objects.filter(run=self.run, bucket="perlu_tinjau"))
        self.assertGreaterEqual(len(tinjau), 2)
        ids = [str(r.pk) for r in tinjau[:2]]
        r = self.client.post(reverse("bulk_review", args=[self.run.pk]),
                             {"action": "mark_matched", "result_ids": ids})
        self.assertEqual(r.status_code, 302)
        for pk in ids:
            res = MatchResult.objects.get(pk=pk)
            self.assertEqual(res.bucket, MatchResult.Bucket.COCOK)
            self.assertEqual(res.reason_code, "manual_override")
        self.assertEqual(ReviewAction.objects.filter(result_id__in=ids).count(), 2)

    def test_bulk_aksi_tak_dikenal_ditolak(self):
        r = self.client.post(reverse("bulk_review", args=[self.run.pk]),
                             {"action": "hapus_semua", "result_ids": []})
        self.assertEqual(r.status_code, 400)

    def test_filter_reason_di_run_detail(self):
        r = self.client.get(reverse("run_detail", args=[self.run.pk]) + "?reason=weak_name")
        self.assertEqual(r.status_code, 200)
