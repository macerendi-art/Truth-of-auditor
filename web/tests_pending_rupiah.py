"""Split rupiah pending vs real (F5).

Banner ekor T+1 di batch_detail tidak cukup hitung BARIS — pertanyaan pagi
auditor adalah "berapa RUPIAH selisih yang tinggal nunggu file besok, berapa
yang beneran harus dikejar?". Banner memuat jumlah rupiah ekor per arah (DP/WD)
dan sisa selisih di luar ekor.
"""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


class _Base(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get(name="Default")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)
        self._rh = 0

    def _mk(self, summary=None, d=date(2026, 6, 28)):
        batch = ReconBatch.objects.create(
            toko=self.lbs, tolerance=self.tol, date_from=d, date_to=d,
            summary=summary or {},
        )
        run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=batch,
            date_from=d, date_to=d,
        )
        return batch, run

    def _pending(self, run, jenis, amount, when=datetime(2026, 6, 28, 21, 0)):
        self._rh += 1
        tx = Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=self.lbs, jenis=jenis,
            amount=Decimal(amount), money_delta=Decimal(amount),
            occurred_at=when, row_hash=f"pr{self._rh}",
        )
        return MatchResult.objects.create(
            run=run, bucket=MatchResult.Bucket.TIDAK, left=tx, score=0,
            reason_code="no_money",
        )


class PendingRupiahTests(_Base):
    def test_banner_memuat_rupiah_ekor_per_arah(self):
        batch, run = self._mk()
        self._pending(run, "wd", "50000")
        self._pending(run, "wd", "50000", when=datetime(2026, 6, 28, 22, 0))
        self._pending(run, "dp", "75000")
        r = self.client.get(reverse("batch_detail", args=[batch.pk]))
        self.assertContains(r, "menunggu mutasi H+1")
        self.assertContains(r, "100,000")  # WD ekor
        self.assertContains(r, "75,000")   # DP ekor

    def test_banner_memuat_sisa_di_luar_ekor(self):
        # Selisih DP 150k, ekor DP 100k → sisa real 50k yang harus dikejar.
        batch, run = self._mk(summary={"dp": {"selisih": 150000}, "wd": {"selisih": 0}})
        self._pending(run, "dp", "100000")
        r = self.client.get(reverse("batch_detail", args=[batch.pk]))
        self.assertContains(r, "50,000")
        self.assertContains(r, "di luar ekor")

    def test_tanpa_ekor_tanpa_banner(self):
        batch, run = self._mk(summary={"dp": {"selisih": 150000}})
        self._pending(run, "dp", "100000", when=datetime(2026, 6, 28, 10, 0))  # siang
        r = self.client.get(reverse("batch_detail", args=[batch.pk]))
        self.assertNotContains(r, "menunggu mutasi H+1")
