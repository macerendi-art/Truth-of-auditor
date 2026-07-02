from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from sources import services
from sources.models import SourceType, Toko
from transactions.models import Transaction


class TokoModelTests(TestCase):
    def test_str_returns_name(self):
        t = Toko.objects.create(key="xyz", name="XYZ")
        self.assertEqual(str(t), "XYZ")

    def test_seed_creates_lbs_and_slo(self):
        self.assertTrue(Toko.objects.filter(key="lbs").exists())
        self.assertTrue(Toko.objects.filter(key="slo").exists())

    def test_seed_16_toko(self):
        keys = {
            "ahk", "mul", "stn", "lbs", "w25", "m25", "mxw", "hks",
            "bwn", "ltn", "wlg", "ssn", "ctr", "slo", "g25", "k25",
        }
        have = set(Toko.objects.values_list("key", flat=True))
        self.assertTrue(keys <= have, f"kurang: {keys - have}")
        self.assertEqual(Toko.objects.get(key="ahk").name, "AHK")
        self.assertEqual(Toko.objects.filter(key="lbs").count(), 1)  # tidak duplikat


_CANON = {
    "occurred_at": datetime(2026, 6, 27, 10, 0), "posted_date": None, "jenis": "depo",
    "amount": Decimal("50000"), "credit_delta": Decimal("-50000"), "money_delta": Decimal("50000"),
    "fee": Decimal("0"), "bonus": Decimal("0"), "balance_after": None,
    "ticket_no": "D1", "username": "budi", "reference": "", "counterparty": "",
    "description": "", "raw": {}, "row_hash": "hash-a2-1",
}


class _DummyBracket:
    source_key = "bracket"

    def parse(self, path, flow=""):
        return [dict(_CANON)]


class IngestTokoTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})

    def test_ingest_sets_toko_and_provider(self):
        with patch.dict(services.PARSERS, {"dummy": _DummyBracket}, clear=False):
            up, created, dup = services.ingest("dummy", "/nofile", toko=self.lbs, provider="Nexus")
        self.assertEqual(up.toko, self.lbs)
        self.assertEqual(up.provider, "Nexus")
        self.assertEqual(created, 1)
        self.assertEqual(Transaction.objects.get().toko, self.lbs)
