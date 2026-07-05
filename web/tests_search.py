"""Quick-search transaksi: nominal + rentang tanggal + kotak cari global navbar.

Pertanyaan lapangan auditor: "nominal 50.000 tanggal 28 itu lewat mana saja?"
— harus terjawab satu kotak cari, lintas sumber.
"""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


class _Base(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)
        self._n = 0

    def _tx(self, amount, username, when):
        self._n += 1
        return Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=self.lbs, jenis="dp",
            amount=Decimal(amount), money_delta=Decimal(amount), username=username,
            occurred_at=when, row_hash=f"qs{self._n}",
        )


class QuickSearchTests(_Base):
    def test_cari_nominal_dengan_titik_ribuan(self):
        self._tx("50000", "targetuser", datetime(2026, 6, 28, 10, 0))
        self._tx("75000", "lainuser", datetime(2026, 6, 28, 11, 0))
        r = self.client.get(reverse("transactions"), {"q": "50.000"})
        self.assertContains(r, "targetuser")
        self.assertNotContains(r, "lainuser")

    def test_cari_nominal_polos(self):
        self._tx("50000", "targetuser", datetime(2026, 6, 28, 10, 0))
        r = self.client.get(reverse("transactions"), {"q": "50000"})
        self.assertContains(r, "targetuser")

    def test_filter_rentang_tanggal(self):
        self._tx("50000", "junipertama", datetime(2026, 6, 1, 10, 0))
        self._tx("60000", "juniakhir", datetime(2026, 6, 28, 10, 0))
        r = self.client.get(
            reverse("transactions"),
            {"date_from": "2026-06-20", "date_to": "2026-06-30"},
        )
        self.assertContains(r, "juniakhir")
        self.assertNotContains(r, "junipertama")

    def test_navbar_punya_kotak_cari_global(self):
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, 'action="/transactions/"')
        self.assertContains(r, 'name="q"')
