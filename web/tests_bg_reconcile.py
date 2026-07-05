"""B5: reconcile besar berjalan di background — worker tidak dibunuh timeout.

Run kecil tetap sinkron (UX: langsung lihat hasil). Di atas ambang baris,
view membuat batch placeholder (status=berjalan), thread mengisi, dan
batch_detail menyegarkan otomatis sampai selesai/gagal.
"""
from datetime import datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


class _Base(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get(name="Default")
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})


class BgReconcileViewTests(_Base):
    def test_di_atas_ambang_jadi_background(self):
        from web import views

        panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        up = Upload.objects.create(source_type=panel, toko=self.lbs)
        Transaction.objects.create(
            upload=up, source_type=panel, toko=self.lbs, jenis="dp",
            amount=Decimal("50000"), money_delta=Decimal("50000"),
            occurred_at=datetime(2026, 6, 28, 10, 0), row_hash="bg1",
        )
        with mock.patch.object(views, "_BG_THRESHOLD", 0), \
             mock.patch.object(views, "_spawn_bg") as spawn:
            r = self.client.post(reverse("reconcile"), {
                "tolerance": "Default",
                "date_from": "2026-06-28", "date_to": "2026-06-28",
            })
        batch = ReconBatch.objects.get()
        self.assertEqual(batch.status, ReconBatch.Status.BERJALAN)
        spawn.assert_called_once_with(batch.pk)
        self.assertRedirects(r, reverse("batch_detail", args=[batch.pk]))

    def test_di_bawah_ambang_tetap_sinkron(self):
        r = self.client.post(reverse("reconcile"), {
            "tolerance": "Default",
            "date_from": "2026-06-28", "date_to": "2026-06-28",
        })
        batch = ReconBatch.objects.get()
        self.assertEqual(batch.status, ReconBatch.Status.SELESAI)
        self.assertRedirects(r, reverse("batch_detail", args=[batch.pk]))


class BatchDetailStatusTests(_Base):
    def _batch(self, status, **kw):
        return ReconBatch.objects.create(
            toko=self.lbs, tolerance=self.tol, summary={}, status=status, **kw
        )

    def test_berjalan_menampilkan_progres_dan_auto_refresh(self):
        b = self._batch(ReconBatch.Status.BERJALAN)
        r = self.client.get(reverse("batch_detail", args=[b.pk]))
        self.assertContains(r, "sedang berjalan")
        self.assertContains(r, "location.reload")

    def test_gagal_menampilkan_error(self):
        b = self._batch(ReconBatch.Status.GAGAL, error_note="kolom aneh di file")
        r = self.client.get(reverse("batch_detail", args=[b.pk]))
        self.assertContains(r, "GAGAL")
        self.assertContains(r, "kolom aneh di file")

    def test_selesai_tanpa_auto_refresh(self):
        b = self._batch(ReconBatch.Status.SELESAI)
        r = self.client.get(reverse("batch_detail", args=[b.pk]))
        self.assertNotContains(r, "location.reload")
