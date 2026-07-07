"""Idempotensi row_hash harus dijaga DB (unique constraint), bukan cuma
pengecekan aplikasi — dua proses ingest bersamaan tak boleh bisa duplikat."""
from datetime import datetime
from decimal import Decimal

from django.db import IntegrityError, transaction as db_tx
from django.test import TestCase

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class RowHashUniqueTests(TestCase):
    def setUp(self):
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.lbs = Toko.objects.get(key="lbs")
        self.k25 = Toko.objects.get(key="k25")
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _tx(self, st, toko, rh):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=toko, jenis="depo",
            amount=Decimal("1000"), money_delta=Decimal("1000"),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash=rh,
        )

    def test_duplikat_source_toko_hash_ditolak_db(self):
        self._tx(self.panel, self.lbs, "sama")
        with self.assertRaises(IntegrityError), db_tx.atomic():
            self._tx(self.panel, self.lbs, "sama")

    def test_hash_sama_beda_toko_atau_sumber_boleh(self):
        self._tx(self.panel, self.lbs, "sama")
        self._tx(self.panel, self.k25, "sama")  # beda toko
        self._tx(self.bank, self.lbs, "sama")   # beda sumber
        self.assertEqual(Transaction.objects.filter(row_hash="sama").count(), 3)
