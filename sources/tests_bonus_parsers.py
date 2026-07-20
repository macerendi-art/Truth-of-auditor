"""Parser bonus: panel Credit Balance & bracket Credit/Non-Credit Bonus."""
import os
import tempfile

from django.test import SimpleTestCase
from openpyxl import Workbook


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    wb.save(path)
    return path


# --- Panel Credit Balance (bonus) ---------------------------------------

PANEL_HEADER = ["No.", "Brand", "Date & Time", "Description", "Remarks",
                "Payment Type", "Payment Details", "Amt.", "Current Credit Balance"]

PANEL_ROWS = [
    [1, "M77", "15-Jul-2026 00:00:09.927", "Deposit M77Aaa", "",
     "Bank Transfer", "", 500, 10000],
    [2, "M77", "15-Jul-2026 00:05:00.000", "Withdraw M77Bbb", "",
     "Bank Transfer", "", -200, 9800],
    [3, "M77", "15-Jul-2026 00:00:00.000", "Opening Balance", "",
     "", "", 0, 10000],
    [4, "M77", "15-Jul-2026 01:00:00.000",
     "Offset M77ccc Lucky Draw Agent: ...", "", "", "", 50, 10050],
    [5, "M77", "15-Jul-2026 01:00:05.000",
     "Lucky Draw Agent: Gold Ticket - Event X M77Ccc", "", "", "", -50, 10000],
    [6, "M77", "15-Jul-2026 02:00:00.000",
     "Redemption Coupon: CREDIT 15.000 - x:1 M77Ddd", "", "", "", -15, 9985],
    [7, "M77", "15-Jul-2026 03:00:00.000",
     "Promotion Claim: BONUS NEW MEMBER 30% SLOT - [D123] - M77Eee", "",
     "", "", -15, 9970],
    [8, "M77", "15-Jul-2026 04:00:00.000", "Adjustment: M77Fff", "K-BCR3",
     "", "", -5, 9965],
]


class PanelBonusParserTests(SimpleTestCase):
    def _parse(self):
        from sources.parsers.bonus import PanelBonusParser
        path = _xlsx([["Credit Balance Report"], PANEL_HEADER] + PANEL_ROWS)
        try:
            return PanelBonusParser().parse(path)
        finally:
            os.remove(path)

    def test_hanya_baris_bonus_yang_diambil(self):
        rows = self._parse()
        self.assertEqual(len(rows), 4)

    def test_field_umum_setiap_baris(self):
        for r in self._parse():
            self.assertEqual(r["jenis"], "bonus")
            self.assertEqual(str(r["money_delta"]), "0")
            self.assertEqual(r["ticket_no"], "")
            self.assertLess(r["credit_delta"], 0)
            self.assertIsNotNone(r["posted_date"])
            self.assertEqual(r["posted_date"].day, 15)

    def test_lucky_draw(self):
        r = next(r for r in self._parse() if r["raw"]["Kategori"] == "Lucky Draw")
        self.assertEqual(r["username"], "Ccc")
        self.assertEqual(str(r["amount"]), "50000")
        self.assertEqual(str(r["credit_delta"]), "-50000")

    def test_redemption_coupon(self):
        r = next(r for r in self._parse()
                 if r["raw"]["Kategori"] == "Redemption Coupon")
        self.assertEqual(r["username"], "Ddd")
        self.assertEqual(str(r["amount"]), "15000")

    def test_promotion_claim(self):
        r = next(r for r in self._parse()
                 if r["raw"]["Kategori"] == "Promotion Claim")
        self.assertEqual(r["username"], "Eee")
        self.assertEqual(str(r["amount"]), "15000")

    def test_adjustment(self):
        r = next(r for r in self._parse() if r["raw"]["Kategori"] == "Adjustment")
        self.assertEqual(r["username"], "Fff")
        self.assertEqual(str(r["amount"]), "5000")

    def test_offset_deposit_withdraw_opening_dilewati(self):
        kategoris = {r["raw"]["Kategori"] for r in self._parse()}
        self.assertEqual(
            kategoris, {"Lucky Draw", "Redemption Coupon", "Promotion Claim", "Adjustment"})

    def test_row_hash_stabil(self):
        a = self._parse()
        b = self._parse()
        self.assertEqual([r["row_hash"] for r in a], [r["row_hash"] for r in b])


# --- Bracket Credit/Non-Credit Bonus -------------------------------------

BRACKET_HEADER_TANPA_CATEGORY = ["Transaction ID", "Date", "Description",
                                  "Nominal", "Deleted", "Created By"]
BRACKET_HEADER_LENGKAP = ["Transaction ID", "Date", "Category", "Description",
                           "Nominal", "Deleted", "Created By"]


class BracketBonusParserNonCreditTests(SimpleTestCase):
    """Varian TANPA kolom Category — kode di Description (K-BLD = Lucky Draw)."""

    def _parse(self, rows):
        from sources.parsers.bonus import BracketBonusParser
        path = _xlsx([BRACKET_HEADER_TANPA_CATEGORY] + rows)
        try:
            return BracketBonusParser().parse(path)
        finally:
            os.remove(path)

    def test_deleted_dilewati(self):
        rows = self._parse([
            ["TID1", "15-Jul-2026 05:00:00", "K-BLD\nPlayer: skip", 1000,
             "Yes", "adminx"],
        ])
        self.assertEqual(rows, [])

    def test_kode_bld_lucky_draw(self):
        rows = self._parse([
            ["TID2", "15-Jul-2026 05:05:00", "K-BLD\nPlayer: Ggg", 30000,
             "No", "adminx"],
        ])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["raw"]["Kategori"], "Lucky Draw")
        self.assertEqual(r["username"], "Ggg")
        self.assertEqual(str(r["amount"]), "30000")
        self.assertEqual(str(r["credit_delta"]), "-30000")
        self.assertEqual(r["jenis"], "bonus")
        self.assertEqual(str(r["money_delta"]), "0")


class BracketBonusParserCreditTests(SimpleTestCase):
    """Varian LENGKAP dengan kolom Category — kategori dipakai verbatim."""

    def _parse(self, rows):
        from sources.parsers.bonus import BracketBonusParser
        path = _xlsx([BRACKET_HEADER_LENGKAP] + rows)
        try:
            return BracketBonusParser().parse(path)
        finally:
            os.remove(path)

    def test_category_verbatim_dan_nominal_tanpa_x1000(self):
        rows = self._parse([
            ["TID3", "15-Jul-2026 06:00:00", "BONUS LOYALTY MURAH (BL1)",
             "Some header text\nPlayer: hhh", 25000, "No", "adminx"],
        ])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["raw"]["Kategori"], "BONUS LOYALTY MURAH (BL1)")
        self.assertEqual(r["username"], "hhh")
        self.assertEqual(str(r["amount"]), "25000")
        self.assertEqual(str(r["credit_delta"]), "-25000")
