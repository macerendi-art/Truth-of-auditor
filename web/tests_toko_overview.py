"""Halaman /tokos/: ringkasan semua toko (scoped), urut selisih, tombol Buka."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import Toko

User = get_user_model()


class TokoOverviewTests(TestCase):
    def setUp(self):
        User.objects.create_user("adm", password="pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")

    def _batch(self, toko, dp_selisih, d):
        return ReconBatch.objects.create(
            toko=toko, tolerance=self.tol, recon_date=d,
            summary={"dp": {"selisih": dp_selisih}, "wd": {"selisih": 0}},
        )

    def test_urut_selisih_terbesar_dulu(self):
        self._batch(self.lbs, 1000, date(2026, 6, 27))
        self._batch(self.slo, 9_000_000, date(2026, 6, 27))
        r = self.client.get(reverse("toko_overview"))
        html = r.content.decode()
        # target sel tabel (<b>…</b>), bukan dropdown toko di topbar
        self.assertLess(html.index("<b>SLO</b>"), html.index("<b>LBS</b>"))

    def test_toko_tanpa_batch_belum_rekon(self):
        r = self.client.get(reverse("toko_overview"))
        self.assertContains(r, "belum rekon")

    def test_rbac_auditor_hanya_tokonya(self):
        u = User.objects.create_user("a2", password="pw12345", role="auditor")
        u.allowed_tokos.set([self.lbs])
        self.client.logout()
        self.client.login(username="a2", password="pw12345")
        r = self.client.get(reverse("toko_overview"))
        self.assertContains(r, ">LBS<")
        self.assertNotContains(r, ">SLO<")

    def test_tombol_buka_ganti_toko(self):
        self._batch(self.lbs, 0, date(2026, 6, 27))
        r = self.client.get(reverse("toko_overview"))
        self.assertContains(r, reverse("set_toko"))


class TokoOverviewDateFilterTests(TokoOverviewTests):
    """Filter tanggal: rentang membatasi batch yang dihitung (selisih = agregat
    rentang, 'rekon terakhir' = batch terakhir DALAM rentang)."""

    def test_filter_satu_hari_ambil_batch_hari_itu(self):
        self._batch(self.lbs, 1000, date(2026, 6, 27))
        self._batch(self.lbs, 5000, date(2026, 6, 28))
        r = self.client.get(reverse("toko_overview"),
                            {"from": "2026-06-28", "to": "2026-06-28"})
        self.assertContains(r, "28/06/2026")   # rekon terakhir dalam rentang
        self.assertContains(r, ">5.000<")      # selisih hanya dari batch 28
        self.assertNotContains(r, ">1.000<")
        self.assertNotContains(r, ">6.000<")

    def test_filter_rentang_agregat_selisih(self):
        self._batch(self.lbs, 1000, date(2026, 6, 27))
        self._batch(self.lbs, 5000, date(2026, 6, 28))
        r = self.client.get(reverse("toko_overview"),
                            {"from": "2026-06-27", "to": "2026-06-28"})
        self.assertContains(r, ">6.000<")      # 1.000 + 5.000

    def test_filter_tanpa_batch_dalam_rentang(self):
        self._batch(self.lbs, 1000, date(2026, 6, 27))
        r = self.client.get(reverse("toko_overview"),
                            {"from": "2026-06-29", "to": "2026-06-30"})
        # batch 27/06 di luar rentang: tak boleh tampil sebagai rekon terakhir
        self.assertNotContains(r, "27/06/2026")
        self.assertNotContains(r, ">1.000<")

    def test_filter_invalid_diabaikan(self):
        self._batch(self.lbs, 1000, date(2026, 6, 27))
        r = self.client.get(reverse("toko_overview"), {"from": "bukan-tanggal"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, ">1.000<")      # fallback perilaku tanpa filter
