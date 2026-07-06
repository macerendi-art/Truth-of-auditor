"""Backfill player_bank/bank_title untuk baris panel/bracket lama."""
from datetime import datetime
from decimal import Decimal

from django.test import TestCase

from sources.models import SourceType, Toko, Upload
from transactions.bankfields import backfill_bank_fields
from transactions.models import Transaction


class BackfillBankFieldsTests(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bracket = SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.toko)

    def _tx(self, st, rh, raw):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.toko, jenis="depo",
            amount=Decimal("1000"), occurred_at=datetime(2026, 6, 27, 10, 0),
            row_hash=rh, raw=raw,
        )

    def test_isi_panel_bracket_biarkan_bank(self):
        p = self._tx(self.panel, "p1", {"Player Bank": "DANA|A|08", "Bank Title": "QRIS|Q|1"})
        b = self._tx(self.bracket, "b1", {"No. Rek Bank Member": "BCA 712", "Bank": "BANK BCA | X"})
        k = self._tx(self.bank, "k1", {"NOREK": "123"})

        n = backfill_bank_fields(Transaction)

        p.refresh_from_db(); b.refresh_from_db(); k.refresh_from_db()
        self.assertEqual((p.player_bank, p.bank_title), ("DANA", "QRIS"))
        self.assertEqual((b.player_bank, b.bank_title), ("BCA", "BANK BCA"))
        self.assertEqual((k.player_bank, k.bank_title), ("", ""))
        self.assertEqual(n, 2)  # hanya panel + bracket yang berubah

    def test_idempoten_run_kedua_tanpa_perubahan(self):
        self._tx(self.panel, "p1", {"Player Bank": "DANA|A|08", "Bank Title": "QRIS|Q|1"})
        backfill_bank_fields(Transaction)
        self.assertEqual(backfill_bank_fields(Transaction), 0)
