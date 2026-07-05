"""Batch detail: ringkasan per sumber uang (n, dp, wd, berpasangan/tidak)."""
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


class BatchPerBankTests(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        self.run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=self.batch
        )
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def money(self, up, delta, cp, paired=False):
        t = Transaction.objects.create(
            upload=up, source_type=self.bank, toko=self.lbs, jenis="depo",
            amount=Decimal(str(abs(delta))), money_delta=Decimal(str(delta)),
            occurred_at=datetime(2026, 6, 27, 10, 0), counterparty=cp,
            consumed_by_batch=self.batch, row_hash=f"b-{next(_seq)}", raw={},
        )
        if paired:
            left = Transaction.objects.create(
                upload=up, source_type=self.panel, toko=self.lbs, jenis="depo",
                amount=Decimal(str(abs(delta))), occurred_at=datetime(2026, 6, 27, 10, 0),
                ticket_no=f"D{next(_seq)}", row_hash=f"bp-{next(_seq)}", raw={},
            )
            MatchResult.objects.create(
                run=self.run, bucket=MatchResult.Bucket.COCOK, reason_code="ticket",
                left=left, right=t,
            )
        return t

    def test_ringkasan_per_bank_muncul(self):
        up_bca = Upload.objects.create(
            source_type=self.bank, toko=self.lbs, original_name="27_JUNI_2026_WD_BCA_HENDI.pdf"
        )
        up_bri = Upload.objects.create(
            source_type=self.bank, toko=self.lbs, original_name="27 JUN 2026 DP BRI MARGANI.csv"
        )
        self.money(up_bca, 50000, "HENDI", paired=True)
        self.money(up_bca, 30000, "HENDI2", paired=False)
        self.money(up_bri, 20000, "MARGANI", paired=True)
        r = self.client.get(reverse("batch_detail", args=[self.batch.pk]))
        self.assertContains(r, "Per Sumber Uang")
        self.assertContains(r, "BCA")
        self.assertContains(r, "BRI")
        per_bank = {row["label"]: row for row in r.context["per_bank"]}
        self.assertEqual(per_bank["BCA"]["n"], 2)
        self.assertEqual(per_bank["BCA"]["paired"], 1)
        self.assertEqual(per_bank["BCA"]["unpaired"], 1)
        self.assertEqual(per_bank["BRI"]["n"], 1)

    def test_batch_tanpa_uang_tanpa_kartu(self):
        r = self.client.get(reverse("batch_detail", args=[self.batch.pk]))
        self.assertNotContains(r, "Per Sumber Uang")
