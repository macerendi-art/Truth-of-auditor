"""Dashboard: strip 'Ringkasan Panel' (jumlah & nilai trx DP/WD dari batch terakhir)."""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


class DashboardPanelSumTests(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.panel = SourceType.objects.get(key="panel")
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _batch(self, toko=None, d=date(2026, 6, 27)):
        return ReconBatch.objects.create(
            toko=toko or self.lbs, tolerance=self.tol, recon_date=d,
        )

    def _tx(self, toko, jenis, amount, rh, batch, is_duplicate=False, upload=None):
        return Transaction.objects.create(
            upload=upload or self.up, source_type=self.panel, toko=toko, jenis=jenis,
            amount=Decimal(amount), occurred_at=datetime(2026, 6, 27, 10, 0),
            row_hash=rh, consumed_by_batch=batch, is_duplicate=is_duplicate,
        )

    def test_panel_sum_terhitung(self):
        batch = self._batch()
        self._tx(self.lbs, "depo", "100000", "d1", batch)
        self._tx(self.lbs, "depo", "50000", "d2", batch)
        self._tx(self.lbs, "wd", "30000", "w1", batch)
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(
            r.context["panel_sum"],
            {"dp": {"n": 2, "v": 150000.0}, "wd": {"n": 1, "v": 30000.0},
             "total_n": 3, "net": 120000.0},
        )
        self.assertContains(r, "Ringkasan Panel")

    def test_tanpa_batch_none(self):
        # toko aktif belum punya batch sama sekali.
        r = self.client.get(reverse("dashboard"))
        self.assertIsNone(r.context["panel_sum"])
        self.assertNotContains(r, "Ringkasan Panel")

    def test_baris_toko_lain_tak_ikut(self):
        slo = Toko.objects.get(key="slo")
        up_slo = Upload.objects.create(source_type=self.panel, toko=slo)
        batch_lbs = self._batch(toko=self.lbs)
        batch_slo = self._batch(toko=slo)
        self._tx(self.lbs, "depo", "40000", "d1", batch_lbs)
        # baris toko lain, batch lain — tidak boleh ikut terhitung di panel_sum lbs.
        self._tx(slo, "depo", "999999", "d2", batch_slo, upload=up_slo)
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(
            r.context["panel_sum"],
            {"dp": {"n": 1, "v": 40000.0}, "wd": {"n": 0, "v": 0.0},
             "total_n": 1, "net": 40000.0},
        )

    def test_duplikat_tak_ikut(self):
        batch = self._batch()
        self._tx(self.lbs, "depo", "77777", "d1", batch, is_duplicate=True)
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(
            r.context["panel_sum"],
            {"dp": {"n": 0, "v": 0.0}, "wd": {"n": 0, "v": 0.0},
             "total_n": 0, "net": 0.0},
        )
