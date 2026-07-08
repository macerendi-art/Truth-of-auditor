"""Tampilan pemilik rekening + keterangan mutasi di baris "Tidak Ada di Panel"."""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


class OwnerDisplayTests(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.toko = Toko.objects.get(key="lbs")
        tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(
            source_type=bank, toko=self.toko,
            original_name="27_JUNI_2026_WD_BCA_HENDI.pdf", owner_name="HENDI",
        )
        batch = ReconBatch.objects.create(toko=self.toko, tolerance=tol)
        self.run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=tol, batch=batch
        )
        tx = Transaction.objects.create(
            upload=self.up, source_type=bank, toko=self.toko, jenis="wd",
            amount=Decimal("250000"), money_delta=Decimal("-250000"),
            occurred_at=datetime(2026, 6, 27, 10, 0),
            counterparty="", description="TRANSFER KE 535 SUPRIADI MyBCA BI-FAST DB",
            raw={}, row_hash="h-owner-1",
        )
        MatchResult.objects.create(
            run=self.run, bucket=MatchResult.Bucket.TIDAK, left=None, right=tx,
            reason_code="no_panel",
        )

    def test_no_panel_render_owner_dan_keterangan(self):
        r = self.client.get(reverse("run_detail", args=[self.run.pk]))
        self.assertContains(r, "BCA a/n HENDI")
        self.assertContains(r, "TRANSFER KE 535 SUPRIADI")

    def test_tanpa_owner_label_brand_saja(self):
        self.up.owner_name = ""
        self.up.save(update_fields=["owner_name"])
        r = self.client.get(reverse("run_detail", args=[self.run.pk]))
        self.assertNotContains(r, "a/n")
        self.assertContains(r, "BCA")
