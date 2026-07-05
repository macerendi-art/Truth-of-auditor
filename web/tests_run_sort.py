"""Run detail: sorting kolom amount/skor/waktu (whitelist), default bucket,-score."""
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


class RunSortTests(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)
        self.batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        self.run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=self.batch
        )
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def _res(self, amount, ticket):
        left = Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=self.lbs, jenis="depo",
            amount=Decimal(str(amount)), occurred_at=datetime(2026, 6, 27, 10, 0),
            ticket_no=ticket, row_hash=f"r-{next(_seq)}", raw={},
        )
        return MatchResult.objects.create(
            run=self.run, bucket=MatchResult.Bucket.COCOK, reason_code="ticket", left=left,
        )

    def test_sort_amount_asc(self):
        self._res(30000, "D30")
        self._res(10000, "D10")
        self._res(20000, "D20")
        r = self.client.get(reverse("run_detail", args=[self.run.pk]), {"sort": "amount", "dir": "asc"})
        html = r.content.decode()
        self.assertLess(html.index("D10"), html.index("D20"))
        self.assertLess(html.index("D20"), html.index("D30"))

    def test_sort_asing_fallback(self):
        self._res(10000, "D10")
        r = self.client.get(reverse("run_detail", args=[self.run.pk]), {"sort": "xxx"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "D10")
