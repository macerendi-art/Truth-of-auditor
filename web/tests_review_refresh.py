"""F7 — review manual harus meng-update summary (stat kartu tidak boleh basi).

`review` (per-baris) dan `review_bulk` mengubah MatchResult.bucket, tapi kalau
run.summary & batch.summary['buckets'] tidak ikut disinkronkan, kartu stat di
run_detail/batch_detail bohong sesaat setelah review manual.
"""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


class _Base(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get(name="Default")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.batch = ReconBatch.objects.create(
            toko=self.lbs, tolerance=self.tol,
            summary={"buckets": {"cocok": 0, "perlu_tinjau": 0, "tidak_cocok": 3}},
        )
        self.run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=self.batch,
            summary={"left": 3, "right": 3, "cocok": 0, "perlu_tinjau": 0, "tidak_cocok": 3},
        )
        up = Upload.objects.create(source_type=self.panel, toko=self.lbs)
        self.results = []
        for i in range(3):
            tx = Transaction.objects.create(
                upload=up, source_type=self.panel, toko=self.lbs, jenis="depo",
                amount=Decimal("50000"), money_delta=Decimal("-50000"),
                occurred_at=datetime(2026, 6, 27, 21, 0), row_hash=f"rr{i}",
            )
            self.results.append(MatchResult.objects.create(
                run=self.run, bucket=MatchResult.Bucket.TIDAK, left=tx,
                score=0, reason_code="no_money",
            ))


class ReviewRowRefreshTests(_Base):
    def test_review_satu_baris_update_summary(self):
        r = self.client.post(
            reverse("review", args=[self.results[0].pk]),
            {"action": "mark_matched"},
        )
        self.assertEqual(r.status_code, 200)
        self.run.refresh_from_db()
        self.batch.refresh_from_db()
        self.assertEqual(self.run.summary["cocok"], 1)
        self.assertEqual(self.run.summary["tidak_cocok"], 2)
        self.assertEqual(self.batch.summary["buckets"]["cocok"], 1)
        self.assertEqual(self.batch.summary["buckets"]["tidak_cocok"], 2)

    def test_review_tidak_sentuh_field_summary_lain(self):
        self.client.post(
            reverse("review", args=[self.results[0].pk]),
            {"action": "mark_matched"},
        )
        self.run.refresh_from_db()
        self.assertEqual(self.run.summary["left"], 3)
        self.assertEqual(self.run.summary["right"], 3)


class ReviewBulkRefreshTests(_Base):
    def test_bulk_dua_baris_update_summary(self):
        r = self.client.post(reverse("review_bulk"), {
            "result_ids": [self.results[0].pk, self.results[1].pk],
            "action": "mark_matched",
        })
        self.assertEqual(r.status_code, 302)
        self.run.refresh_from_db()
        self.batch.refresh_from_db()
        self.assertEqual(self.run.summary["cocok"], 2)
        self.assertEqual(self.run.summary["tidak_cocok"], 1)
        self.assertEqual(self.batch.summary["buckets"]["cocok"], 2)
        self.assertEqual(self.batch.summary["buckets"]["tidak_cocok"], 1)
