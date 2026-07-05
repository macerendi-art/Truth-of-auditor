"""Transaksi ?carry=1: hanya baris kredit yang menunggu settlement."""
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


class TxCarryTests(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)
        self.batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        self.run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=self.batch
        )
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def tx(self, **kw):
        d = dict(
            upload=self.up, source_type=self.panel, toko=self.lbs, jenis="depo",
            amount=Decimal("50000"), money_delta=Decimal("50000"),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash=f"c-{next(_seq)}",
        )
        d.update(kw)
        return Transaction.objects.create(**d)

    def test_carry_hanya_baris_menunggu(self):
        waiting = self.tx(username="MENUNGGU", consumed_by_batch=None)
        self.tx(username="BIASA")
        # hasil no_money AKTIF (menunggu settlement) untuk `waiting`
        MatchResult.objects.create(
            run=self.run, bucket=MatchResult.Bucket.TIDAK,
            reason_code="no_money", left=waiting,
        )
        r = self.client.get(reverse("transactions"), {"carry": "1"})
        self.assertContains(r, "MENUNGGU")
        self.assertNotContains(r, "BIASA")

    def test_carry_kosong_tetap_200(self):
        self.tx(username="BIASA")
        r = self.client.get(reverse("transactions"), {"carry": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "BIASA")

    def test_dashboard_kartu_settlement_link_carry(self):
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "carry=1")
