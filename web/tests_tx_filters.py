"""Transaksi: filter rentang tanggal + sorting kolom server-side (whitelist)."""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()
_seq = iter(range(1, 100000))


class TxFilterSortBase(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.bank, toko=self.lbs)
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def tx(self, amount, when, **kw):
        return Transaction.objects.create(
            upload=self.up, source_type=self.bank, toko=self.lbs, jenis="depo",
            amount=Decimal(str(amount)), money_delta=Decimal(str(amount)),
            occurred_at=when, row_hash=f"f-{next(_seq)}", **kw,
        )


class DateFilterTests(TxFilterSortBase):
    def test_date_from_membatasi(self):
        self.tx(10000, datetime(2026, 6, 20, 9, 0), counterparty="LAMA")
        self.tx(20000, datetime(2026, 6, 28, 9, 0), counterparty="BARU")
        r = self.client.get(reverse("transactions"), {"date_from": "2026-06-25"})
        self.assertContains(r, "BARU")
        self.assertNotContains(r, "LAMA")

    def test_date_to_membatasi(self):
        self.tx(10000, datetime(2026, 6, 20, 9, 0), counterparty="LAMA")
        self.tx(20000, datetime(2026, 6, 28, 9, 0), counterparty="BARU")
        r = self.client.get(reverse("transactions"), {"date_to": "2026-06-25"})
        self.assertContains(r, "LAMA")
        self.assertNotContains(r, "BARU")

    def test_tanggal_invalid_diabaikan(self):
        self.tx(10000, datetime(2026, 6, 20, 9, 0), counterparty="ADA")
        r = self.client.get(reverse("transactions"), {"date_from": "bukan-tanggal"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "ADA")


class SortTests(TxFilterSortBase):
    def setUp(self):
        super().setUp()
        self.tx(30000, datetime(2026, 6, 27, 9, 0), counterparty="TIGA")
        self.tx(10000, datetime(2026, 6, 27, 10, 0), counterparty="SATU")
        self.tx(20000, datetime(2026, 6, 27, 11, 0), counterparty="DUA")

    def test_sort_amount_asc(self):
        r = self.client.get(reverse("transactions"), {"sort": "amount", "dir": "asc"})
        html = r.content.decode()
        self.assertLess(html.index("SATU"), html.index("DUA"))
        self.assertLess(html.index("DUA"), html.index("TIGA"))

    def test_sort_amount_desc(self):
        r = self.client.get(reverse("transactions"), {"sort": "amount", "dir": "desc"})
        html = r.content.decode()
        self.assertLess(html.index("TIGA"), html.index("DUA"))
        self.assertLess(html.index("DUA"), html.index("SATU"))

    def test_default_sort_waktu_desc(self):
        r = self.client.get(reverse("transactions"))
        html = r.content.decode()
        # occurred_at terbaru dulu: DUA(11:00) > SATU(10:00) > TIGA(9:00)
        self.assertLess(html.index("DUA"), html.index("SATU"))
        self.assertLess(html.index("SATU"), html.index("TIGA"))

    def test_sort_asing_fallback_default(self):
        r = self.client.get(reverse("transactions"), {"sort": "rahasia"})
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertLess(html.index("DUA"), html.index("TIGA"))
