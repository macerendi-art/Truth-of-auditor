"""Koreksi sel FR (paket A): model overlay + agregasi + view popup."""
from datetime import date
from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase

from sources.models import Toko

TGL = date(2026, 7, 1)


class FRKoreksiModelTests(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")

    def _buat(self, **over):
        from web.models import FRKoreksi
        base = dict(toko=self.toko, tanggal=TGL,
                    account="BANK BCA | SUSILAWATI | DEPOSIT",
                    kolom="deposit", nilai=Decimal("123000"),
                    alasan="mistake_cs", catatan="salah input CS")
        base.update(over)
        return FRKoreksi.objects.create(**base)

    def test_buat_dan_str(self):
        k = self._buat()
        self.assertIn("BANK BCA", str(k))
        self.assertIn("deposit", str(k))
        self.assertEqual(k.get_alasan_display(), "Mistake CS")

    def test_satu_koreksi_per_sel(self):
        self._buat()
        with self.assertRaises(IntegrityError):
            self._buat(nilai=Decimal("999"))

    def test_sel_beda_boleh(self):
        self._buat()
        self._buat(kolom="saldo_awal")
        self._buat(tanggal=date(2026, 7, 2))
        from web.models import FRKoreksi
        self.assertEqual(FRKoreksi.objects.count(), 3)
