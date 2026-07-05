"""Reminder ritual harian di dashboard.

saran == hari ini itu normal (file mutasi hari ini belum lengkap — nunggu
besok). saran < hari ini = ritual TERTUNDA → banner menonjol + CTA.
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import Toko

User = get_user_model()


class ReminderRitualTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get(name="Default")
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def _batch_sampai(self, d):
        ReconBatch.objects.create(
            toko=self.lbs, tolerance=self.tol, date_from=d, date_to=d, summary={},
        )

    def test_tertunda_muncul_banner(self):
        self._batch_sampai(date.today() - timedelta(days=4))  # saran = 3 hari lalu
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "Ritual tertunda")

    def test_saran_hari_ini_tanpa_banner(self):
        self._batch_sampai(date.today() - timedelta(days=1))  # saran = hari ini
        r = self.client.get(reverse("dashboard"))
        self.assertNotContains(r, "Ritual tertunda")
