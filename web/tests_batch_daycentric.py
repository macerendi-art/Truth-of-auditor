"""Riwayat batch day-centric (F2+F3).

Batch adalah laporan untuk TANGGAL DATA (window), bukan untuk waktu dibuatnya —
ritual harian auditor mikirnya "hari 28 gimana?". Maka: (a) label window tampil
di riwayat & header batch_detail, (b) tiap baris riwayat punya chip status
(✓ final / ⏳ ekor nunggu H+1 / ⚠ selisih real / bukti dihapus) supaya selisih
ekor-malam yang normal tidak terbaca segawat selisih beneran.
"""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.views import _window_label

User = get_user_model()


class WindowLabelTests(TestCase):
    def test_satu_hari(self):
        self.assertEqual(_window_label(date(2026, 6, 28), date(2026, 6, 28)), "28 Jun")

    def test_satu_hari_dengan_tahun(self):
        self.assertEqual(
            _window_label(date(2026, 6, 28), date(2026, 6, 28), with_year=True),
            "28 Jun 2026",
        )

    def test_rentang_sebulan(self):
        self.assertEqual(_window_label(date(2026, 6, 27), date(2026, 6, 29)), "27–29 Jun")

    def test_rentang_lintas_bulan(self):
        self.assertEqual(
            _window_label(date(2026, 6, 30), date(2026, 7, 2)), "30 Jun – 2 Jul"
        )

    def test_tanpa_window(self):
        self.assertEqual(_window_label(None, None), "semua tanggal")


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

    def _mk(self, d=date(2026, 6, 28), buckets=None):
        batch = ReconBatch.objects.create(
            toko=self.lbs, tolerance=self.tol, date_from=d, date_to=d,
            summary={"buckets": buckets or {}},
        )
        run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=batch,
            date_from=d, date_to=d,
        )
        return batch, run

    def _res(self, run, when, reason="no_money", bucket=MatchResult.Bucket.TIDAK):
        self._rh += 1
        tx = Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=self.lbs, jenis="wd",
            amount=Decimal("50000"), money_delta=Decimal("-50000"),
            occurred_at=when, row_hash=f"dc{self._rh}",
        )
        return MatchResult.objects.create(
            run=run, bucket=bucket, left=tx, score=0, reason_code=reason,
        )


class RiwayatBatchTests(_Base):
    def test_kolom_tanggal_data_tampil(self):
        batch, run = self._mk(d=date(2026, 6, 28), buckets={"cocok": 1})
        self._res(run, datetime(2026, 6, 28, 10, 0), reason="", bucket=MatchResult.Bucket.COCOK)
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, "Tanggal data")
        self.assertContains(r, "28 Jun")

    def test_status_final(self):
        batch, run = self._mk(buckets={"cocok": 3, "perlu_tinjau": 0, "tidak_cocok": 0})
        self._res(run, datetime(2026, 6, 28, 10, 0), reason="", bucket=MatchResult.Bucket.COCOK)
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, "final")

    def test_status_ekor_semua_pending(self):
        # 2 tidak_cocok, keduanya malam di hari terakhir window → murni ekor T+1.
        batch, run = self._mk(buckets={"cocok": 0, "perlu_tinjau": 0, "tidak_cocok": 2})
        self._res(run, datetime(2026, 6, 28, 21, 0))
        self._res(run, datetime(2026, 6, 28, 22, 30))
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, "2 ekor")
        self.assertNotContains(r, "selisih real")

    def test_status_campur_ekor_dan_real(self):
        # 1 malam (ekor) + 1 siang (selisih beneran).
        batch, run = self._mk(buckets={"cocok": 0, "perlu_tinjau": 0, "tidak_cocok": 2})
        self._res(run, datetime(2026, 6, 28, 21, 0))
        self._res(run, datetime(2026, 6, 28, 11, 0))
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, "1 ekor")
        self.assertContains(r, "1 selisih real")

    def test_status_rusak_summary_tanpa_bukti(self):
        # Summary bilang ada isi tapi MatchResult 0 → cangkang (upload dihapus).
        self._mk(buckets={"cocok": 100, "perlu_tinjau": 5, "tidak_cocok": 10})
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, "bukti dihapus")

    def test_batch_kosong_tanpa_chip_rusak(self):
        # Batch tanpa hasil DAN summary kosong = hari kosong yang sah, bukan rusak.
        self._mk(buckets={"cocok": 0, "perlu_tinjau": 0, "tidak_cocok": 0})
        r = self.client.get(reverse("reconcile"))
        self.assertNotContains(r, "bukti dihapus")


class BatchDetailHeaderTests(_Base):
    def test_header_pakai_tanggal_data(self):
        batch, run = self._mk(d=date(2026, 6, 28))
        r = self.client.get(reverse("batch_detail", args=[batch.pk]))
        self.assertContains(r, "28 Jun 2026")

    def test_header_tanpa_window(self):
        batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol, summary={})
        r = self.client.get(reverse("batch_detail", args=[batch.pk]))
        self.assertContains(r, "semua tanggal")
