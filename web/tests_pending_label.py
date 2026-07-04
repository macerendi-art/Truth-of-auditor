"""Label ekor vs selisih beneran.

`tidak_cocok` mencampur dua makna: (a) transaksi malam di hari terakhir window
yang uangnya baru datang di file besok (ekor T+1 — normal, akan tertutup
auto re-match), dan (b) selisih nyata. Heuristik: `no_money` + occurred_at di
tanggal `date_to` window + jam >= 17 → badge "menunggu mutasi H+1" di run_detail
dan hitungan di batch_detail. Tanpa window (date_to None) → tak ada label.
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

LABEL = "menunggu mutasi H+1"


class _Base(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get(name="Default")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _mk(self, date_to=date(2026, 6, 27)):
        batch = ReconBatch.objects.create(
            toko=self.lbs, tolerance=self.tol,
            date_from=date(2026, 6, 27), date_to=date_to,
        )
        run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=batch,
            date_from=date(2026, 6, 27), date_to=date_to,
        )
        return batch, run

    def _res(self, run, when, reason="no_money", bucket=MatchResult.Bucket.TIDAK, rh="p1"):
        tx = Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=self.lbs, jenis="wd",
            amount=Decimal("50000"), money_delta=Decimal("-50000"),
            occurred_at=when, row_hash=rh,
        )
        return MatchResult.objects.create(
            run=run, bucket=bucket, left=tx, score=0, reason_code=reason,
        )


class RunDetailPendingLabelTests(_Base):
    def test_no_money_malam_di_hari_terakhir_dapat_label(self):
        _, run = self._mk()
        self._res(run, datetime(2026, 6, 27, 21, 0))
        r = self.client.get(reverse("run_detail", args=[run.pk]))
        self.assertContains(r, LABEL)

    def test_no_money_siang_tanpa_label(self):
        _, run = self._mk()
        self._res(run, datetime(2026, 6, 27, 10, 0))
        r = self.client.get(reverse("run_detail", args=[run.pk]))
        self.assertNotContains(r, LABEL)

    def test_reason_lain_malam_tanpa_label(self):
        _, run = self._mk()
        self._res(run, datetime(2026, 6, 27, 21, 0), reason="weak_name",
                  bucket=MatchResult.Bucket.TINJAU)
        r = self.client.get(reverse("run_detail", args=[run.pk]))
        self.assertNotContains(r, LABEL)

    def test_window_none_tanpa_label(self):
        _, run = self._mk(date_to=None)
        self._res(run, datetime(2026, 6, 27, 21, 0))
        r = self.client.get(reverse("run_detail", args=[run.pk]))
        self.assertNotContains(r, LABEL)


class BatchDetailPendingCountTests(_Base):
    def test_batch_detail_hitung_ekor_malam(self):
        batch, run = self._mk()
        self._res(run, datetime(2026, 6, 27, 21, 0), rh="p1")
        self._res(run, datetime(2026, 6, 27, 22, 0), rh="p2")
        self._res(run, datetime(2026, 6, 27, 10, 0), rh="p3")  # siang → bukan ekor
        r = self.client.get(reverse("batch_detail", args=[batch.pk]))
        self.assertContains(r, LABEL)
        self.assertContains(r, "2")

    def test_batch_detail_tanpa_ekor_tanpa_baris_info(self):
        batch, run = self._mk()
        self._res(run, datetime(2026, 6, 27, 10, 0))
        r = self.client.get(reverse("batch_detail", args=[batch.pk]))
        self.assertNotContains(r, LABEL)
