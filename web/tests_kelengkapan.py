"""Kartu kelengkapan harus jelas soal KONTEKS TANGGAL.

Tiga kali user bingung "kok kosong padahal sudah upload": kartu menghitung di
window tanggal terpilih, tapi tidak bilang itu, dan tidak menunjukkan di
tanggal mana sumber sebenarnya punya data.
"""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


class KelengkapanKonteksTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self._n = 0

    def _tx(self, key, jenis, when):
        self._n += 1
        st = SourceType.objects.get_or_create(key=key, defaults={"name": key.title()})[0]
        up = Upload.objects.create(source_type=st, toko=self.lbs)
        return Transaction.objects.create(
            upload=up, source_type=st, toko=self.lbs, jenis=jenis,
            amount=Decimal("50000"), money_delta=Decimal("50000"),
            occurred_at=when, row_hash=f"kl{self._n}",
        )

    def test_judul_kartu_menyebut_tanggal_window(self):
        self._tx("panel", "depo", datetime(2026, 6, 27, 10, 0))
        r = self.client.get(reverse("reconcile") + "?date_from=2026-06-26&date_to=2026-06-26")
        self.assertContains(r, "Kelengkapan Data — 26 Jun")

    def test_sumber_kosong_di_window_tunjukkan_rentang_data_aktif(self):
        # Panel DP ada di 27-29, window terpilih 26 → "kosong" + hint 27–29 Jun.
        self._tx("panel", "depo", datetime(2026, 6, 27, 10, 0))
        self._tx("panel", "depo", datetime(2026, 6, 29, 10, 0))
        r = self.client.get(reverse("reconcile") + "?date_from=2026-06-26&date_to=2026-06-26")
        self.assertContains(r, "kosong")
        self.assertContains(r, "data ada di 27–29 Jun")

    def test_sumber_tanpa_data_sama_sekali_tanpa_hint(self):
        r = self.client.get(reverse("reconcile") + "?date_from=2026-06-26&date_to=2026-06-26")
        self.assertNotContains(r, "data ada di")
