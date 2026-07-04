"""Laporan penyembuhan terstruktur: _auto_rematch → list dict, panel dari session.

Sebelumnya delta re-match otomatis dikempiskan jadi string flash yang hilang
saat navigasi. Sekarang: dict per batch (delta selisih before→after) di-stash
ke session (pola PRG), dirender sekali sebagai kartu penyembuhan lalu habis.
"""
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import Toko

User = get_user_model()


class _Base(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.user = User.objects.create_superuser("admin", password="x")
        self.client.force_login(self.user)
        s = self.client.session
        s["active_toko_id"] = self.toko.id
        s.save()
        self.tol = ToleranceProfile.objects.get(name="Default")
        d = date.today() - timedelta(days=1)
        self.batch = ReconBatch.objects.create(
            toko=self.toko, tolerance=self.tol, date_from=d, date_to=d,
            summary={"dp": {"selisih": 4200}, "wd": {"selisih": 0},
                     "buckets": {"cocok": 5, "perlu_tinjau": 0, "tidak_cocok": 3}},
        )


class AutoRematchShapeTests(_Base):
    def test_return_terstruktur(self):
        from web.views import _auto_rematch
        with patch("web.views.rematch_batch",
                   return_value={"terpasang": 3, "cocok": 2, "perlu_tinjau": 1, "diperiksa": 5}):
            with patch("web.views._rematch_candidates", return_value=[(self.batch, 1)]):
                out = _auto_rematch(self.toko, ["dummy"], user=None)
        self.assertEqual(len(out), 1)
        d = out[0]
        self.assertEqual(d["level"], "success")
        self.assertEqual(d["terpasang"], 3)
        self.assertEqual(d["batch_pk"], self.batch.pk)
        self.assertEqual(d["batch_no"], 1)
        self.assertEqual(d["selisih_before"], 4200)
        self.assertIn("selisih_after", d)

    def test_error_tidak_menggagalkan(self):
        from web.views import _auto_rematch
        with patch("web.views.rematch_batch", side_effect=RuntimeError("boom")):
            with patch("web.views._rematch_candidates", return_value=[(self.batch, 1)]):
                out = _auto_rematch(self.toko, ["dummy"], user=None)
        self.assertEqual(out[0]["level"], "error")
        self.assertIn("boom", out[0]["error"])


class HealingPanelRenderTests(_Base):
    def _stash(self):
        s = self.client.session
        s["healing_report"] = [{
            "level": "success", "batch_pk": self.batch.pk, "batch_no": 1,
            "terpasang": 3, "cocok": 2, "perlu_tinjau": 1,
            "selisih_before": 4200, "selisih_after": 0,
        }]
        s.save()

    def test_panel_di_upload_sekali_render(self):
        self._stash()
        r = self.client.get(reverse("upload"))
        self.assertContains(r, "tanggal aslinya")  # kalimat edukasi D-1
        self.assertContains(r, "Batch #1")
        r2 = self.client.get(reverse("upload"))
        self.assertNotContains(r2, "tanggal aslinya")

    def test_panel_di_batch_detail(self):
        self._stash()
        r = self.client.get(reverse("batch_detail", args=[self.batch.pk]))
        self.assertContains(r, "tersembuhkan")

    def test_rematch_manual_stash_session(self):
        with patch("web.views.rematch_batch",
                   return_value={"terpasang": 2, "cocok": 2, "perlu_tinjau": 0, "diperiksa": 3}):
            r = self.client.post(reverse("rematch_batch", args=[self.batch.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(self.client.session.get("healing_report"))
