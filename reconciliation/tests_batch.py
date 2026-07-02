from django.test import TestCase

from reconciliation.models import MatchRun, ReconBatch, ToleranceProfile
from sources.models import Toko


class ReconBatchModelTests(TestCase):
    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(name="Default", defaults={"date_window_days": 1})[0]
        self.lbs = Toko.objects.get(key="lbs")

    def test_batch_links_runs(self):
        batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        run = MatchRun.objects.create(relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=batch)
        self.assertEqual(list(batch.runs.all()), [run])
        self.assertEqual(str(batch), f"Batch #{batch.pk}")
