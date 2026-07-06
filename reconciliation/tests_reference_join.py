from datetime import datetime
from decimal import Decimal
from django.test import TestCase
from reconciliation.engine import run_match
from reconciliation.models import MatchResult, MatchRun, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

D = Decimal

def _st(key):
    return SourceType.objects.get_or_create(key=key, defaults={"name": key.title()})[0]

class ReferenceJoinTests(TestCase):
    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1})[0]
        self.toko = Toko.objects.get(key="g25")
        self.panel, self.gw = _st("panel"), _st("gateway")
        self.up_p = Upload.objects.create(source_type=self.panel, toko=self.toko,
                                           original_name="QRIS_deposit.xlsx")
        self.up_g = Upload.objects.create(source_type=self.gw, toko=self.toko,
                                          original_name="DP_QRIS_TRANSACTION.xlsx")
        self._n = 0

    def tx(self, st, up, amount, md, dt, *, ref="", ticket=""):
        self._n += 1
        return Transaction.objects.create(
            upload=up, source_type=st, toko=self.toko, jenis="depo",
            amount=D(amount), money_delta=D(md), occurred_at=dt,
            reference=ref, ticket_no=ticket, row_hash=f"h{self._n}")

    def test_reference_sama_nominal_sama_cocok(self):
        p = self.tx(self.panel, self.up_p, "85000", "85000",
                    datetime(2026, 7, 1, 23, 59), ref="03f747e8-ac9c-48e0-a")
        g = self.tx(self.gw, self.up_g, "85000", "85000",
                    datetime(2026, 7, 1, 23, 59), ref="03f747e8-ac9c-48e0-a")
        run = run_match(MatchRun.Relation.PANEL_BANK, self.tol, toko=self.toko)
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.right_id, g.id)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.reason_code, "reference")

    def test_reference_asing_tidak_fuzzy(self):
        # gateway ref tak dikenal panel + nominal sama → JANGAN direbut fuzzy.
        p = self.tx(self.panel, self.up_p, "50000", "50000",
                    datetime(2026, 7, 1, 10), ref="known-uuid")
        g = self.tx(self.gw, self.up_g, "50000", "50000",
                    datetime(2026, 7, 1, 10), ref="ASING-uuid")
        run_match(MatchRun.Relation.PANEL_BANK, self.tol, toko=self.toko)
        r = MatchResult.objects.get(left=p)
        self.assertIsNone(r.right_id)   # p tak dapat uang (ref beda), g diblok fuzzy
