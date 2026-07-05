"""run_batch atomic + lock per-toko.

Dua auditor menjalankan reconcile toko yang sama bersamaan tidak boleh saling
mengonsumsi uang yang sama; dan gagal di tengah tidak boleh meninggalkan batch
cangkang (batch ada, hasil tidak ada).
"""
from unittest import mock

from django.test import TestCase

from reconciliation import engine
from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import Toko


class RunBatchAtomicTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get(name="Default")

    def test_gagal_di_tengah_ditandai_gagal_tanpa_isi(self):
        with mock.patch.object(
            engine, "_aggregate_batch", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                engine.run_batch(self.lbs, self.tol, "2026-06-28", "2026-06-28")
        # Isi (runs/hasil/konsumsi) rollback total; batch tersisa sebagai
        # penanda GAGAL yang terlihat — bukan cangkang setengah jadi.
        batch = ReconBatch.objects.get()
        self.assertEqual(batch.status, ReconBatch.Status.GAGAL)
        self.assertIn("boom", batch.error_note)
        self.assertEqual(batch.runs.count(), 0)

    def test_run_batch_normal_selesai(self):
        batch = engine.run_batch(self.lbs, self.tol, "2026-06-28", "2026-06-28")
        self.assertIsNotNone(batch.pk)
        self.assertEqual(batch.status, ReconBatch.Status.SELESAI)
