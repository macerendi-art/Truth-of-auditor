"""Batch era lama (summary tanpa money_gross) tidak boleh menampilkan gross "0"
yang menyesatkan — tampilkan "—" (tidak tercatat)."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import Toko


class LegacyGrossDisplayTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.tol = tol

    def _get(self, summary):
        batch = ReconBatch.objects.create(toko=self.toko, tolerance=self.tol, summary=summary)
        return self.client.get(reverse("batch_detail", args=[batch.pk]))

    def test_summary_legacy_tanpa_gross_tampil_strip(self):
        r = self._get({
            "dp": {"panel": 863773000.0, "money": 4172265821.0, "selisih": -3308492821.0},
            "wd": {"panel": 703592000.0, "money": 3824108280.0, "selisih": -3120516280.0},
            "buckets": {"cocok": 1, "perlu_tinjau": 0, "tidak_cocok": 0},
        })
        self.assertContains(
            r, '<td class="faint">Uang real (gross)</td><td class="faint">—</td>', count=2, html=False,
        )

    def test_summary_baru_gross_nol_tetap_angka(self):
        r = self._get({
            "dp": {"panel": 0.0, "money_gross": 0.0, "money_matched": 0.0, "money": 0.0, "selisih": 0.0},
            "wd": {"panel": 0.0, "money_gross": 0.0, "money_matched": 0.0, "money": 0.0, "selisih": 0.0},
            "buckets": {"cocok": 0, "perlu_tinjau": 0, "tidak_cocok": 0},
        })
        self.assertContains(
            r, '<td class="faint">Uang real (gross)</td><td class="faint">0</td>', count=2, html=False,
        )
