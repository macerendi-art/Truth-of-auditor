"""Bulk marking lintas-run di Area Pengecekan (/tinjau/bulk-review/)."""
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


class BulkReviewQueueTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.other_toko = Toko.objects.get(key="slo")
        panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]

        def buat_run(toko, tanggal, prefix):
            up = Upload.objects.create(source_type=panel, toko=toko,
                                       original_name=f"P{prefix}.xlsx")
            upb = Upload.objects.create(source_type=bank, toko=toko,
                                        original_name=f"B{prefix}.csv")
            # Nama sengaja "mirip tapi kepotong bank" (skor pita 60-84) supaya
            # jatuh ke perlu_tinjau 'name_partial' — bahan uji setujui massal.
            for i in range(2):
                Transaction.objects.create(
                    upload=up, source_type=panel, toko=toko, jenis="wd",
                    amount=Decimal("50000"), money_delta=Decimal("-50000"),
                    occurred_at=datetime(2026, tanggal.month, tanggal.day, 9 + i),
                    ticket_no=f"W{prefix}{i}",
                    counterparty="Muhammad Aditya Firmansyah", row_hash=f"p{prefix}{i}",
                )
                Transaction.objects.create(
                    upload=upb, source_type=bank, toko=toko, jenis="wd",
                    amount=Decimal("50000"), money_delta=Decimal("-50000"),
                    occurred_at=datetime(2026, tanggal.month, tanggal.day, 10 + i),
                    counterparty="M ADITYA FIRMANSYA", row_hash=f"b{prefix}{i}",
                )
            batch = ReconBatch.objects.create(toko=toko, tolerance=self.tol,
                                              recon_date=tanggal)
            return run_match(MatchRun.Relation.PANEL_BANK, self.tol, toko=toko,
                             batch=batch)

        self.run1 = buat_run(self.toko, datetime(2026, 6, 27), "a")
        self.run2 = buat_run(self.toko, datetime(2026, 6, 28), "b")
        self.run_other = buat_run(self.other_toko, datetime(2026, 6, 27), "c")

    def test_bulk_setujui_lintas_run(self):
        t1 = MatchResult.objects.filter(run=self.run1, bucket="perlu_tinjau").first()
        t2 = MatchResult.objects.filter(run=self.run2, bucket="perlu_tinjau").first()
        self.assertIsNotNone(t1)
        self.assertIsNotNone(t2)
        ids = [str(t1.pk), str(t2.pk)]
        r = self.client.post(reverse("bulk_review_queue"),
                             {"action": "mark_matched", "result_ids": ids,
                              "next": reverse("review_queue")})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("review_queue"))
        for pk in ids:
            res = MatchResult.objects.get(pk=pk)
            self.assertEqual(res.bucket, MatchResult.Bucket.COCOK)
            self.assertEqual(res.reason_code, "manual_override")
        self.assertEqual(ReviewAction.objects.filter(result_id__in=ids).count(), 2)
        self.run1.batch.refresh_from_db()
        self.run2.batch.refresh_from_db()
        self.assertGreaterEqual(self.run1.batch.summary.get("buckets", {}).get("cocok", 0), 1)
        self.assertGreaterEqual(self.run2.batch.summary.get("buckets", {}).get("cocok", 0), 1)

    def test_bulk_result_toko_lain_tak_berubah(self):
        User = get_user_model()
        aud = User.objects.create_user("aud2", "b@a.co", "pw12345", role="auditor")
        aud.allowed_tokos.add(self.toko)
        self.client.logout()
        self.client.login(username="aud2", password="pw12345")
        other = MatchResult.objects.filter(run=self.run_other, bucket="perlu_tinjau").first()
        self.assertIsNotNone(other)
        r = self.client.post(reverse("bulk_review_queue"),
                             {"action": "mark_matched", "result_ids": [str(other.pk)]})
        self.assertEqual(r.status_code, 302)
        other.refresh_from_db()
        self.assertEqual(other.bucket, "perlu_tinjau")
        self.assertEqual(ReviewAction.objects.filter(result_id=other.pk).count(), 0)

    def test_bulk_aksi_tak_dikenal_ditolak(self):
        r = self.client.post(reverse("bulk_review_queue"),
                             {"action": "hapus_semua", "result_ids": []})
        self.assertEqual(r.status_code, 400)

    def test_bulk_get_ditolak(self):
        r = self.client.get(reverse("bulk_review_queue"))
        self.assertEqual(r.status_code, 405)
