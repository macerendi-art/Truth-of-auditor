"""Aturan fee admin bank — nominal tetap + pola deskripsi per bank (bukti prod 18-07)."""
from decimal import Decimal

from django.test import SimpleTestCase

from sources.parsers.fee_rules import is_admin_fee


class AturanFeeTests(SimpleTestCase):
    def test_bri_atmstrprm_6500(self):
        self.assertTrue(is_admin_fee("bri", "ATMSTRPRM 0888123", Decimal("6500")))
        self.assertFalse(is_admin_fee("bri", "ATMSTRPRM 0888123", Decimal("650000")))

    def test_bri_bfst_2500(self):
        self.assertTrue(is_admin_fee("bri", "BFST2061125016 NBMB:...", Decimal("2500")))
        self.assertFalse(is_admin_fee("bri", "BFST2061125016 NBMB:...", Decimal("250000")))

    def test_bri_briva_1000(self):
        self.assertTrue(is_admin_fee("bri", "BRIVA301350882008 NBMB F R N", Decimal("1000")))
        self.assertFalse(is_admin_fee("bri", "BRIVA301350882008 NBMB", Decimal("100000")))

    def test_mandiri_biaya_semua_nominal(self):
        self.assertTrue(is_admin_fee("mandiri", "Biaya transfer BI Fast", Decimal("2500")))
        self.assertTrue(is_admin_fee("mandiri", "Biaya transaksi", Decimal("1000")))
        self.assertTrue(is_admin_fee("mandiri", "biaya transfer", Decimal("6500")))
        self.assertFalse(is_admin_fee("mandiri", "Transfer ke BANK MANDIRI ANDI", Decimal("2500")))

    def test_bca_delegasi_biaya_txn(self):
        self.assertTrue(is_admin_fee("bca", "BI-FAST DB BIAYA TXN 123", Decimal("2500")))
        self.assertFalse(is_admin_fee("bca", "TRSF E-BANKING DB 1707 ANDI", Decimal("2500")))

    def test_bank_lain_dan_desc_kosong_false(self):
        self.assertFalse(is_admin_fee("bni", "BY TRX", Decimal("1000")))  # BNI punya jalur sendiri
        self.assertFalse(is_admin_fee("bri", "", Decimal("2500")))
        self.assertFalse(is_admin_fee("bri", None, Decimal("2500")))


import csv
import os
import tempfile

from sources.parsers.banks import BRIParser


def _bri_csv(rows):
    fd, p = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["NOREK", "SEQ", "TGL_TRAN", "DESK_TRAN",
                    "MUTASI_DEBET", "MUTASI_KREDIT", "SALDO_AKHIR_MUTASI"])
        w.writerows(rows)
    return p


class BRIFeeParserTests(SimpleTestCase):
    def _parse(self, rows):
        p = _bri_csv(rows)
        try:
            return BRIParser().parse(p)
        finally:
            os.remove(p)

    def test_atmstrprm_dan_bfst_jadi_admin(self):
        out = self._parse([
            ["123", "1", "2026-07-17 10:00:00", "ATMSTRPRM 0888555", "6500", "0", "100000"],
            ["123", "2", "2026-07-17 10:01:00", "BFST2061125016 NBMB:X", "2500", "0", "97500"],
            ["123", "3", "2026-07-17 10:02:00", "NBMB SENDER TO RECEIVER ESB", "0", "50000", "147500"],
        ])
        self.assertEqual([r["jenis"] for r in out], ["admin", "admin", "depo"])


from openpyxl import Workbook

from sources.parsers.banks import MandiriParser


def _mandiri_xlsx(rows):
    """e-Statement mini: header kolom Mandiri + baris data (tanpa enkripsi)."""
    wb = Workbook()
    ws = wb.active
    ws.append(["No", "Tanggal", "Keterangan", "Dana Masuk (IDR)",
               "Dana Keluar (IDR)", "Saldo (IDR)"])
    for r in rows:
        ws.append(r)
    fd, p = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    wb.save(p)
    return p


class MandiriFeeParserTests(SimpleTestCase):
    """Wiring is_admin_fee di MandiriParser — baris 'Biaya …' keluar = admin."""

    def _parse(self, rows):
        p = _mandiri_xlsx(rows)
        try:
            return MandiriParser().parse(p)
        finally:
            os.remove(p)

    def test_biaya_jadi_admin_transfer_tetap_wd(self):
        out = self._parse([
            ["1", "16 Jul 2026", "Biaya transfer BI Fast", "", "2.500,00", "97.500,00"],
            ["2", "16 Jul 2026", "Transfer ke BANK MANDIRI ANDI", "", "250.000,00", "", ],
            ["3", "16 Jul 2026", "Transfer BI Fast Dari OCBC BUDI", "1.000.000,00", "", "1.097.500,00"],
        ])
        self.assertEqual([r["jenis"] for r in out], ["admin", "wd", "depo"])
        self.assertEqual(str(out[0]["amount"]), "2500.00")
