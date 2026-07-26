"""Gerbang PANEL_BRACKET (`panel_in_scope`) & pemilihan MODE join harus menilai
baris DALAM scope tanggal run.

Sejarah: gerbang lama (`panel_has_ticket`) melewati relasi sepenuhnya untuk hari
bergaya COR (panel tanpa ticket), dan modul ini memaku "sisa baris panel
ber-ticket lama di luar scope tak boleh memicu relasi". Sejak matcher punya mode
username (Gelombang 10) relasi memang HARUS jalan untuk hari seperti itu — yang
tetap harus dijaga adalah: baris ber-ticket di LUAR scope (atau baris carried)
tidak boleh memaksa mode "ticket", karena mode ticket membuat seluruh baris panel
tanpa ticket sunyi (tak berhasil, tak gagal). Kedua tes di bawah ditulis ulang
untuk memaku invarian itu."""
from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase

from reconciliation.engine import run_batch
from reconciliation.models import MatchResult, MatchRun, ToleranceProfile
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

    def _tx(self, st, dt, rh, ticket="", username=""):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.toko, jenis="depo",
            amount=Decimal("50000"), money_delta=Decimal("50000"),
            occurred_at=dt, ticket_no=ticket, username=username, row_hash=rh,
        )

    def test_ticket_di_luar_scope_tak_memaksa_mode_ticket(self):
        # Sisa lama (10 Jun, AKTIF, ber-ticket) — DI LUAR scope run 27 Jun.
        lama = self._tx(self.panel, datetime(2026, 6, 10, 9, 0), "lama",
                        ticket="D111111", username="budi")
        # Hari berjalan gaya COR: panel TANPA ticket + bracket + bank.
        self._tx(self.panel, datetime(2026, 6, 27, 10, 0), "p27", username="budi")
        self._tx(self.bracket, datetime(2026, 6, 27, 10, 5), "b27",
                 ticket="D222222", username="budi")
        self._tx(self.bank, datetime(2026, 6, 27, 11, 0), "m27")
        batch = run_batch(
            self.toko, self.tol,
            date_from=date(2026, 6, 27), date_to=date(2026, 6, 27),
        )
        run = batch.runs.get(relation=MatchRun.Relation.PANEL_BRACKET)
        self.assertEqual(run.summary["mode"], "username")   # bukan "ticket"
        self.assertEqual(run.summary["cocok"], 1)
        self.assertFalse(MatchResult.objects.filter(left=lama).exists())

    def test_panel_hanya_di_luar_scope_relasi_dilewati(self):
        # Tak ada baris panel DALAM scope → tak ada yang bisa dicocokkan.
        self._tx(self.panel, datetime(2026, 6, 10, 9, 0), "lama2",
                 ticket="D111111", username="budi")
        self._tx(self.bracket, datetime(2026, 6, 27, 10, 5), "b27b", username="budi")
        self._tx(self.bank, datetime(2026, 6, 27, 11, 0), "m27b")
        batch = run_batch(
            self.toko, self.tol,
            date_from=date(2026, 6, 27), date_to=date(2026, 6, 27),
        )
        self.assertIn(MatchRun.Relation.PANEL_BRACKET.value, batch.summary["skipped"])
        self.assertFalse(batch.runs.filter(relation=MatchRun.Relation.PANEL_BRACKET).exists())
        self.assertIn("Panel", batch.summary["skipped_detail"]["panel_bracket"])

    def test_ticket_dalam_scope_tetap_memicu(self):
        self._tx(self.panel, datetime(2026, 6, 27, 10, 0), "p27t", ticket="D333333")
        self._tx(self.bracket, datetime(2026, 6, 27, 10, 5), "b27t", ticket="D333333")
        self._tx(self.bank, datetime(2026, 6, 27, 11, 0), "m27t")
        batch = run_batch(
            self.toko, self.tol,
            date_from=date(2026, 6, 27), date_to=date(2026, 6, 27),
        )
        run = batch.runs.get(relation=MatchRun.Relation.PANEL_BRACKET)
        self.assertEqual(run.summary["mode"], "ticket")


class PanelHasTicketCarriedTests(TestCase):
    """Jalur auto-run melebarkan date_from ke baris carried. Baris carried
    ber-ticket tetap DIKECUALIKAN dari pencocokan Panel↔Bracket — dan karena
    dikecualikan, ia juga tidak boleh ikut menentukan mode join."""

    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bracket = SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.toko)

    def _tx(self, st, dt, rh, ticket="", username=""):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.toko, jenis="depo",
            amount=Decimal("50000"), money_delta=Decimal("50000"),
            occurred_at=dt, ticket_no=ticket, username=username, row_hash=rh,
        )

    def test_carried_berticket_tak_memaksa_mode_ticket(self):
        # Hari 1 (26/6): panel ber-ticket tanpa uang → no_money, tetap aktif (carry).
        carried_tx = self._tx(self.panel, datetime(2026, 6, 26, 9, 0), "c26",
                              ticket="D111111", username="budi")
        run_batch(self.toko, self.tol,
                  date_from=date(2026, 6, 26), date_to=date(2026, 6, 26),
                  recon_date=date(2026, 6, 26))
        carried_tx.refresh_from_db()
        self.assertIsNone(carried_tx.consumed_by_batch)  # menunggu settlement
        # Hari 2 (27/6) gaya COR: panel tanpa ticket + bracket + bank; scope
        # dilebarkan ke 26/6 (seperti run_batches_auto).
        self._tx(self.panel, datetime(2026, 6, 27, 10, 0), "p27x", username="andi")
        self._tx(self.bracket, datetime(2026, 6, 27, 10, 5), "b27x", username="andi")
        self._tx(self.bank, datetime(2026, 6, 27, 11, 0), "m27x")
        b2 = run_batch(self.toko, self.tol,
                       date_from=date(2026, 6, 26), date_to=date(2026, 6, 27),
                       recon_date=date(2026, 6, 27))
        run = b2.runs.get(relation=MatchRun.Relation.PANEL_BRACKET)
        self.assertEqual(run.summary["mode"], "username")
        self.assertEqual(run.summary["cocok"], 1)
        # Baris carried tetap tak menghasilkan apa pun di batch baru.
        self.assertFalse(MatchResult.objects.filter(run=run, left=carried_tx).exists())
