"""Bracket/FR DP·WD ↔ Mutasi Bank (relasi fr_bank) — selaras panel_bank."""
from datetime import datetime
from decimal import Decimal

from django.test import TestCase

from reconciliation.engine import FrBankMatcher, run_batch, run_match
from reconciliation.models import MatchResult, MatchRun, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class FrBankMatcherTests(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"}
        )[0]
        self.bank = SourceType.objects.get_or_create(
            key="bank", defaults={"name": "Bank"}
        )[0]
        self.panel = SourceType.objects.get_or_create(
            key="panel", defaults={"name": "Panel"}
        )[0]
        self.up_fr = Upload.objects.create(
            source_type=self.bracket, toko=self.toko, original_name="fr.xlsx"
        )
        self.up_bank = Upload.objects.create(
            source_type=self.bank, toko=self.toko, original_name="bca.csv",
            owner_name="CM1",
        )
        self.up_panel = Upload.objects.create(
            source_type=self.panel, toko=self.toko, original_name="panel.xlsx"
        )

    def _tx(self, up, st, *, jenis="depo", amount="100000", money=None,
            ticket="", username="", counterparty="", description="", raw=None,
            rh=""):
        md = Decimal(money if money is not None else amount)
        if jenis == "wd" and md > 0:
            md = -md
        return Transaction.objects.create(
            upload=up, source_type=st, toko=self.toko, jenis=jenis,
            amount=Decimal(amount), money_delta=md,
            ticket_no=ticket, username=username, counterparty=counterparty,
            description=description, raw=raw or {},
            occurred_at=datetime(2026, 8, 26, 12, 0),
            posted_date=datetime(2026, 8, 26).date(),
            row_hash=rh or f"frb-{ticket or username}-{amount}-{jenis}",
        )

    def test_fr_depo_cocok_username_nominal(self):
        self._tx(
            self.up_fr, self.bracket, jenis="depo", amount="150000",
            username="budi99", counterparty="BUDI SANTOSO",
            raw={"Kategori": "Deposit", "Bank": "QRIS HOKI", "Username": "budi99"},
            rh="fr1",
        )
        self._tx(
            self.up_bank, self.bank, jenis="depo", amount="150000",
            username="budi99", counterparty="BUDI SANTOSO",
            description="TRSF BUDI SANTOSO", rh="m1",
        )
        run = run_match(
            MatchRun.Relation.FR_BANK, self.tol, toko=self.toko,
        )
        cocok = MatchResult.objects.filter(run=run, bucket="cocok")
        self.assertEqual(cocok.count(), 1)
        self.assertEqual(cocok.get().left.username, "budi99")
        self.assertEqual(cocok.get().right.username, "budi99")

    def test_fr_sesama_cm_tidak_masuk_left(self):
        """Sesama CM (jenis=lainnya) bukan sisi kiri fr_bank."""
        self._tx(
            self.up_fr, self.bracket, jenis="lainnya", amount="500000",
            username="", counterparty="",
            raw={"Kategori": "Sesama CM", "Bank": "BANK BCA | CM"},
            rh="frs",
        )
        self._tx(
            self.up_bank, self.bank, jenis="depo", amount="500000",
            counterparty="X", rh="m2",
        )
        left, right = FrBankMatcher().sides(None, None, toko=self.toko)
        self.assertEqual(len(left), 0)

    def test_run_batch_menyertakan_fr_bank(self):
        self._tx(
            self.up_panel, self.panel, jenis="depo", amount="10000",
            ticket="D9", username="u1", rh="p1",
        )
        self._tx(
            self.up_fr, self.bracket, jenis="depo", amount="10000",
            ticket="D9", username="u1",
            raw={"Kategori": "Deposit"}, rh="b1",
        )
        self._tx(
            self.up_bank, self.bank, jenis="depo", amount="10000",
            username="u1", rh="k1",
        )
        batch = run_batch(self.toko, self.tol)
        rels = set(batch.runs.values_list("relation", flat=True))
        self.assertIn("fr_bank", rels)
        self.assertIn("panel_bank", rels)
        self.assertIn("panel_bracket", rels)
        self.assertIn("bracket_bank", rels)  # Sesama CM (boleh 0 cocok)
        self.assertEqual(batch.runs.count(), 4)
        fr = batch.runs.get(relation="fr_bank")
        self.assertEqual(fr.get_relation_display(), "Bracket ↔ Mutasi Bank")
        self.assertGreaterEqual(fr.summary.get("cocok", 0), 1)
