"""Dashboard gelombang 2: tren 30 hari, judul, kartu rekon-terakhir & uang-D klikabel."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import Toko

User = get_user_model()


class DashboardG2Tests(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def _batch(self, d, selisih):
        return ReconBatch.objects.create(
            toko=self.lbs, tolerance=self.tol, recon_date=d,
            summary={"dp": {"selisih": selisih}, "wd": {"selisih": 0},
                     "unmatched_money": {"d": {"n": 3}}},
        )

    def test_judul_tren_30_hari(self):
        self._batch(date(2026, 6, 27), 1000)
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "30 hari")

    def test_kartu_rekon_terakhir_jadi_anchor(self):
        b = self._batch(date(2026, 6, 27), 1000)
        r = self.client.get(reverse("dashboard"))
        self.assertContains(
            r, f'<a class="card stat click" href="{reverse("batch_detail", args=[b.pk])}">'
        )

    def test_kartu_uang_d_jadi_anchor(self):
        b = self._batch(date(2026, 6, 27), 1000)
        r = self.client.get(reverse("dashboard"))
        self.assertContains(
            r, f'<a class="card stat click" href="{reverse("batch_uang", args=[b.pk])}?k=d">'
        )

    def test_tren_batasi_30_hari(self):
        anchor = date(2026, 6, 27)
        self._batch(anchor, 5000)
        self._batch(anchor - timedelta(days=40), 9999)  # di luar 30 hari
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(len(r.context["tren"]), 1)
