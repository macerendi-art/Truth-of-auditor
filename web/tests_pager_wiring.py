from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


class PagerWiringTests(TestCase):
    def setUp(self):
        User.objects.create_user("admpg", password="pw123456", role="admin")
        self.client.login(username="admpg", password="pw123456")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.batch = ReconBatch.objects.create(toko=self.toko, tolerance=self.tol)
        self.run = MatchRun.objects.create(
            batch=self.batch, tolerance=self.tol,
            relation=MatchRun.Relation.PANEL_BANK, summary={"left": 60},
        )
        up = Upload.objects.create(source_type=self.panel, toko=self.toko)
        # 60 hasil TIDAK (left ada) -> >40 => multi-halaman
        for i in range(60):
            tx = Transaction.objects.create(
                source_type=self.panel, toko=self.toko, upload=up,
                jenis="depo", occurred_at=datetime(2026, 7, 1, 10, 0),
                amount=Decimal("50000"), credit_delta=Decimal("-50000"),
                money_delta=Decimal("50000"), username=f"user{i}",
                player_bank="BCA", ticket_no=f"D{i:07d}", row_hash=f"h{i}",
            )
            MatchResult.objects.create(
                run=self.run, left=tx, bucket=MatchResult.Bucket.TIDAK,
                reason_code="no_money", score=0,
            )

    def test_run_detail_pager_preserves_bank_filter(self):
        url = reverse("run_detail", args=[self.run.pk])
        r = self.client.get(url, {"bucket": "tidak_cocok", "bank": "BCA"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Navigasi halaman")
        # href halaman berikut wajib membawa bank=BCA (bukan hanya page=)
        self.assertContains(r, "bank=BCA")
        self.assertContains(r, "page=2")

    def test_run_detail_pakai_wide_mode(self):
        r = self.client.get(reverse("run_detail", args=[self.run.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'class="content wide"')
