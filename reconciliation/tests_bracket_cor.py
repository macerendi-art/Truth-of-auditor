from datetime import date, datetime
from decimal import Decimal
from django.test import TestCase
from reconciliation.engine import run_batch, run_match
from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

D = Decimal

def _st(key):
    return SourceType.objects.get_or_create(key=key, defaults={"name": key.title()})[0]

class PanelBracketTicketlessTests(TestCase):
    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1})[0]
        self.toko = Toko.objects.get(key="g25")
        self.panel, self.bracket = _st("panel"), _st("bracket")
        self.up_p = Upload.objects.create(source_type=self.panel, toko=self.toko,
                                          original_name="QRIS_deposit.xlsx")
        self.up_b = Upload.objects.create(source_type=self.bracket, toko=self.toko,
                                          original_name="Finance Report.xlsx")
        self._n = 0

    def tx(self, st, up, amount, dt, *, ticket=""):
        self._n += 1
        md = D(amount)
        return Transaction.objects.create(
            upload=up, source_type=st, toko=self.toko, jenis="depo",
            amount=D(amount), money_delta=md, occurred_at=dt,
            ticket_no=ticket, row_hash=f"h{self._n}")

    def test_panel_tanpa_ticket_tak_emit_no_bracket(self):
        p = self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10))  # no ticket
        run = run_match(MatchRun.Relation.PANEL_BRACKET, self.tol, toko=self.toko)
        self.assertFalse(MatchResult.objects.filter(left=p).exists())

    def test_run_batch_skip_panel_bracket_bila_tak_ada_ticket(self):
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10))       # panel COR
        self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10))     # bracket COR (no ticket)
        batch = run_batch(self.toko, self.tol, date_from=date(2026, 7, 1),
                          date_to=date(2026, 7, 1), recon_date=date(2026, 7, 1))
        rels = [r.relation for r in batch.runs.all()]
        self.assertNotIn(MatchRun.Relation.PANEL_BRACKET, rels)
        self.assertIn(MatchRun.Relation.PANEL_BRACKET.value, batch.summary["skipped"])
