import os, tempfile
from django.test import SimpleTestCase
from openpyxl import Workbook
from sources.parsers.base import parse_bank_triplet
from sources.parsers.cor import CORPanelBankParser

class BankTripletTests(SimpleTestCase):
    def test_triplet_bank(self):
        self.assertEqual(parse_bank_triplet("BCA - 2941413058 - BAGAS ARMANDO"),
                         ("BCA", "2941413058", "BAGAS ARMANDO"))

    def test_triplet_ewallet_dengan_slash_di_nama(self):
        self.assertEqual(
            parse_bank_triplet("OTH - 4840394374 - IGNATIUS IVAN / WITHDRAW BCA"),
            ("OTH", "4840394374", "IGNATIUS IVAN / WITHDRAW BCA"))

    def test_triplet_kosong(self):
        self.assertEqual(parse_bank_triplet(""), ("", "", ""))
        self.assertEqual(parse_bank_triplet(None), ("", "", ""))


def _xlsx(rows):
    wb = Workbook(); ws = wb.active
    for r in rows:
        ws.append(r)
    fd, path = tempfile.mkstemp(suffix=".xlsx"); os.close(fd)
    wb.save(path)
    return path


class CORPanelBankTests(SimpleTestCase):
    HEADER = ["#", "Approved Date", "Requested Date", "Username", "From Bank",
              "Destination Bank", "Amount", "Status", "By"]

    def test_dp_rupiah_dan_bank_fields(self):
        path = _xlsx([
            self.HEADER,
            ["1", "01 Jul 2026 23:52:18", "01 Jul 2026 23:50:06", "febri72",
             "DANA - 081270670097 - FEBRIA MEGASARI",
             "BCA - 2941413058 - BAGAS ARMANDO", "200000", "approved", "gacor25sub59"],
        ])
        try:
            rows = CORPanelBankParser().parse(path, flow="dp")
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["jenis"], "depo")
        self.assertEqual(str(r["amount"]), "200000")        # RUPIAH, tanpa x1000
        self.assertEqual(str(r["money_delta"]), "200000")
        self.assertEqual(str(r["credit_delta"]), "-200000")
        self.assertEqual(r["counterparty"], "FEBRIA MEGASARI")   # pemain = From Bank
        self.assertEqual(r["player_bank"], "DANA")
        self.assertEqual(r["bank_title"], "BCA")                 # operator = Destination
        self.assertEqual(r["ticket_no"], "")
        self.assertIn("081270670097", r["raw"]["Player Bank"])   # utk phone-match

    def test_wd_membalik_sisi_dan_tanda(self):
        path = _xlsx([
            self.HEADER,
            ["1", "01 Jul 2026 23:57:08", "01 Jul 2026 23:56:43", "zhaa1234",
             "OTH - 4840394374 - IGNATIUS IVAN / WITHDRAW BCA",
             "DANA - 082112822248 - RUSMAN", "350000", "approved", "gacor25sub40"],
        ])
        try:
            rows = CORPanelBankParser().parse(path, flow="wd")
        finally:
            os.remove(path)
        r = rows[0]
        self.assertEqual(r["jenis"], "wd")
        self.assertEqual(str(r["money_delta"]), "-350000")
        self.assertEqual(str(r["credit_delta"]), "350000")
        self.assertEqual(r["counterparty"], "RUSMAN")            # pemain = Destination (WD)
        self.assertEqual(r["player_bank"], "DANA")

    def test_skip_non_approved(self):
        path = _xlsx([self.HEADER,
            ["1", "01 Jul 2026 00:00:00", "01 Jul 2026 00:00:00", "x",
             "BCA - 1 - A", "BCA - 2 - B", "1000", "pending", "op"]])
        try:
            self.assertEqual(CORPanelBankParser().parse(path, flow="dp"), [])
        finally:
            os.remove(path)
