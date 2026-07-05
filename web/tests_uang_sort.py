"""Uang tanpa pasangan: sorting tanggal (default asc) & nominal (abs)."""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()
_seq = iter(range(1, 100000))


class UangSortTests(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.bank, toko=self.lbs)
        self.batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def money(self, delta, when, cp):
        return Transaction.objects.create(
            upload=self.up, source_type=self.bank, toko=self.lbs, jenis="depo",
            amount=Decimal(str(abs(delta))), money_delta=Decimal(str(delta)),
            occurred_at=when, counterparty=cp, consumed_by_batch=self.batch,
            row_hash=f"u-{next(_seq)}", raw={},
        )

    def test_sort_nominal_desc(self):
        self.money(10000, datetime(2026, 6, 27, 9, 0), "KECIL")
        self.money(90000, datetime(2026, 6, 27, 10, 0), "BESAR")
        r = self.client.get(reverse("batch_uang", args=[self.batch.pk]), {"sort": "nominal", "dir": "desc"})
        html = r.content.decode()
        self.assertLess(html.index("BESAR"), html.index("KECIL"))

    def test_default_sort_tanggal_asc(self):
        self.money(10000, datetime(2026, 6, 27, 8, 0), "PAGI")
        self.money(20000, datetime(2026, 6, 27, 20, 0), "MALAM")
        r = self.client.get(reverse("batch_uang", args=[self.batch.pk]))
        html = r.content.decode()
        self.assertLess(html.index("PAGI"), html.index("MALAM"))

    def test_sort_asing_fallback(self):
        self.money(10000, datetime(2026, 6, 27, 8, 0), "ADA")
        r = self.client.get(reverse("batch_uang", args=[self.batch.pk]), {"sort": "zzz"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "ADA")
