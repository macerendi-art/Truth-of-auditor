"""Halaman /tinjau/: antrean perlu_tinjau lintas run untuk toko aktif, dengan RBAC."""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()
_seq = iter(range(1, 100000))


class ReviewQueueTests(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def _tinjau(self, toko, ticket):
        up = Upload.objects.create(source_type=self.panel, toko=toko)
        batch = ReconBatch.objects.create(toko=toko, tolerance=self.tol)
        run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=batch
        )
        left = Transaction.objects.create(
            upload=up, source_type=self.panel, toko=toko, jenis="depo",
            amount=Decimal("50000"), occurred_at=datetime(2026, 6, 27, 10, 0),
            ticket_no=ticket, row_hash=f"q-{next(_seq)}", raw={},
        )
        return MatchResult.objects.create(
            run=run, bucket=MatchResult.Bucket.TINJAU, reason_code="amount_mismatch", left=left,
        )

    def test_hanya_bucket_tinjau_toko_aktif(self):
        self._tinjau(self.lbs, "D-LBS")
        self._tinjau(self.slo, "D-SLO")
        r = self.client.get(reverse("review_queue"))
        self.assertContains(r, "D-LBS")
        self.assertNotContains(r, "D-SLO")

    def test_kosong_empty_state(self):
        r = self.client.get(reverse("review_queue"))
        self.assertContains(r, "Antrean kosong")

    def test_rbac_auditor_toko_lain(self):
        User.objects.create_user("a2", "a2@a.co", "pw12345", role="auditor")
        u = User.objects.get(username="a2")
        u.allowed_tokos.set([self.slo])
        self._tinjau(self.lbs, "D-LBS")
        self.client.logout()
        self.client.login(username="a2", password="pw12345")
        self.client.post(reverse("set_toko"), {"toko_id": self.slo.id})
        r = self.client.get(reverse("review_queue"))
        self.assertNotContains(r, "D-LBS")

    def test_aksi_review_dari_antrean(self):
        res = self._tinjau(self.lbs, "D-LBS")
        r = self.client.post(
            reverse("review", args=[res.pk]),
            {"action": "mark_matched", "show_run_col": "1"},
        )
        self.assertEqual(r.status_code, 200)
        res.refresh_from_db()
        self.assertEqual(res.bucket, MatchResult.Bucket.COCOK)
