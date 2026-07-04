"""KPI kesehatan audit di dashboard: selisih terbuka, ekor, tren 7 hari, donat.

Dashboard lama hanya menghitung inventaris (jumlah transaksi/file/run) — tidak
menjawab pertanyaan ritual harian: ada selisih terbuka? berapa hari tertunda?
Konteks `health` merangkum summary 30 batch terakhir tanpa menyentuh engine.
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import Toko
from web.templatetags.web_extras import sparkline_points

User = get_user_model()


def _batch(toko, tol, d, dp_selisih=0, wd_selisih=0, tidak=0):
    return ReconBatch.objects.create(
        toko=toko, tolerance=tol, date_from=d, date_to=d,
        summary={
            "dp": {"selisih": dp_selisih}, "wd": {"selisih": wd_selisih},
            "buckets": {"cocok": 5, "perlu_tinjau": 1, "tidak_cocok": tidak},
        },
    )


class DashboardHealthTests(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.user = User.objects.create_superuser("admin", password="x")
        self.client.force_login(self.user)
        s = self.client.session
        s["active_toko_id"] = self.toko.id
        s.save()
        self.tol = ToleranceProfile.objects.get(name="Default")

    def test_health_context(self):
        today = date.today()
        _batch(self.toko, self.tol, today - timedelta(days=1), dp_selisih=4200, tidak=3)
        _batch(self.toko, self.tol, today - timedelta(days=2), wd_selisih=-500)
        r = self.client.get(reverse("dashboard"))
        h = r.context["health"]
        self.assertEqual(h["selisih_terbuka"], 4700)  # |4200| + |-500|
        self.assertEqual(h["ekor_terbuka"], 1)
        self.assertEqual(h["buckets_agg"]["cocok"], 10)
        self.assertEqual(len(h["selisih_trend"]), 7)
        self.assertEqual(h["selisih_trend"][-2], 4200)  # kemarin
        self.assertContains(r, "Selisih terbuka")

    def test_health_kosong(self):
        r = self.client.get(reverse("dashboard"))
        h = r.context["health"]
        self.assertEqual(h["selisih_terbuka"], 0)
        self.assertEqual(h["ekor_terbuka"], 0)


class SparklineTests(TestCase):
    def test_points(self):
        pts = sparkline_points([0, 10, 5])
        pairs = pts.split()
        self.assertEqual(len(pairs), 3)
        self.assertTrue(all("," in p for p in pairs))

    def test_kosong(self):
        self.assertEqual(sparkline_points([]), "")
