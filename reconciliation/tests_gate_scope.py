"""Gate PANEL_BRACKET (panel_has_ticket) harus menilai baris DALAM scope tanggal
run — sisa baris panel ber-ticket lama di luar scope tak boleh memicu relasi
untuk hari bergaya COR (panel tanpa ticket)."""
from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase

from reconciliation.engine import run_batch
from reconciliation.models import MatchRun, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class PanelHasTicketScopeTests(TestCase):
    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bracket = SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.toko)

    def _tx(self, st, dt, rh, ticket=""):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.toko, jenis="depo",
            amount=Decimal("50000"), money_delta=Decimal("50000"),
            occurred_at=dt, ticket_no=ticket, row_hash=rh,
        )

    def test_ticket_di_luar_scope_tak_memicu_panel_bracket(self):
        # Sisa lama (10 Jun, AKTIF, ber-ticket) — DI LUAR scope run 27 Jun.
        self._tx(self.panel, datetime(2026, 6, 10, 9, 0), "lama", ticket="D111111")
        # Hari berjalan gaya COR: panel TANPA ticket + bracket + bank.
        self._tx(self.panel, datetime(2026, 6, 27, 10, 0), "p27")
        self._tx(self.bracket, datetime(2026, 6, 27, 10, 5), "b27", ticket="D222222")
        self._tx(self.bank, datetime(2026, 6, 27, 11, 0), "m27")
        batch = run_batch(
            self.toko, self.tol,
            date_from=date(2026, 6, 27), date_to=date(2026, 6, 27),
        )
        self.assertIn(MatchRun.Relation.PANEL_BRACKET.value, batch.summary["skipped"])
        self.assertFalse(batch.runs.filter(relation=MatchRun.Relation.PANEL_BRACKET).exists())

    def test_ticket_dalam_scope_tetap_memicu(self):
        self._tx(self.panel, datetime(2026, 6, 27, 10, 0), "p27t", ticket="D333333")
        self._tx(self.bracket, datetime(2026, 6, 27, 10, 5), "b27t", ticket="D333333")
        self._tx(self.bank, datetime(2026, 6, 27, 11, 0), "m27t")
        batch = run_batch(
            self.toko, self.tol,
            date_from=date(2026, 6, 27), date_to=date(2026, 6, 27),
        )
        self.assertTrue(batch.runs.filter(relation=MatchRun.Relation.PANEL_BRACKET).exists())


class PanelHasTicketCarriedTests(TestCase):
    """Jalur auto-run melebarkan date_from ke baris carried — baris carried
    ber-ticket TIDAK boleh memicu PANEL_BRACKET untuk hari bergaya COR
    (PANEL_BRACKET memang mengecualikan carried dari pencocokan, jadi hasilnya
    hanya noise no_panel)."""

    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bracket = SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.toko)

    def _tx(self, st, dt, rh, ticket=""):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.toko, jenis="depo",
            amount=Decimal("50000"), money_delta=Decimal("50000"),
            occurred_at=dt, ticket_no=ticket, row_hash=rh,
        )

    def test_carried_berticket_tak_memicu_panel_bracket(self):
        # Hari 1 (26/6): panel ber-ticket tanpa uang → no_money, tetap aktif (carry).
        self._tx(self.panel, datetime(2026, 6, 26, 9, 0), "c26", ticket="D111111")
        b1 = run_batch(self.toko, self.tol,
                       date_from=date(2026, 6, 26), date_to=date(2026, 6, 26),
                       recon_date=date(2026, 6, 26))
        carried = Transaction.objects.get(row_hash="c26")
        self.assertIsNone(carried.consumed_by_batch)  # menunggu settlement
        # Hari 2 (27/6) gaya COR: panel tanpa ticket + bracket + bank; scope
        # dilebarkan ke 26/6 (seperti run_batches_auto).
        self._tx(self.panel, datetime(2026, 6, 27, 10, 0), "p27x")
        self._tx(self.bracket, datetime(2026, 6, 27, 10, 5), "b27x", ticket="D222222")
        self._tx(self.bank, datetime(2026, 6, 27, 11, 0), "m27x")
        b2 = run_batch(self.toko, self.tol,
                       date_from=date(2026, 6, 26), date_to=date(2026, 6, 27),
                       recon_date=date(2026, 6, 27))
        self.assertIn(MatchRun.Relation.PANEL_BRACKET.value, b2.summary["skipped"])
