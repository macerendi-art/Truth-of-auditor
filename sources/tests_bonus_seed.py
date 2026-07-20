"""Seed SourceType bonus + jaminan isolasi dari completeness."""
from django.test import TestCase

from reconciliation.engine import check_completeness
from sources.models import SourceType, Toko, Upload


class SeedBonusSourceTypeTests(TestCase):
    def test_seed_ada(self):
        pb = SourceType.objects.get(key="panel_bonus")
        bb = SourceType.objects.get(key="bracket_bonus")
        self.assertEqual(pb.name, "Panel Bonus")
        self.assertEqual(bb.name, "Bracket Bonus")
        self.assertFalse(pb.is_money_source)
        self.assertFalse(bb.is_money_source)

    def test_completeness_tak_terpengaruh(self):
        """Baris bonus TIDAK membuat panel/bracket dianggap 'ada'."""
        from datetime import date
        from decimal import Decimal
        from transactions.models import Transaction
        toko = Toko.objects.first()
        pb = SourceType.objects.get(key="panel_bonus")
        up = Upload.objects.create(
            source_type=pb, toko=toko, original_name="bonus.xlsx")
        Transaction.objects.create(
            upload=up, source_type=pb,
            toko=toko, jenis="bonus", amount=Decimal("25000"),
            credit_delta=Decimal("-25000"), money_delta=Decimal("0"),
            posted_date=date(2026, 7, 15), username="x", row_hash="seedtest1",
        )
        comp = check_completeness(toko)
        self.assertFalse(comp["panel"])
        self.assertFalse(comp["bracket"])
