import os, tempfile
from django.test import SimpleTestCase, TestCase
from openpyxl import Workbook
from sources.parsers.base import parse_bank_triplet
from sources.parsers.cor import CORPanelBankParser
from sources.parsers.cor import CORPanelQRISParser
from sources.parsers.cor import CORQRISGatewayParser
from sources import services
from transactions.models import Transaction

class BankTripletTests(SimpleTestCase):
    def test_triplet_bank(self):
        self.assertEqual(parse_bank_triplet("BCA - 2941413058 - BAGAS ARMANDO"),
                         ("BCA", "2941413058", "BAGAS ARMANDO"))

    def test_triplet_ewallet_dengan_slash_di_nama(self):
        self.assertEqual(
            parse_bank_triplet("OTH - 4840394374 - IGNATIUS IVAN / WITHDRAW BCA"),
            ("OTH", "4840394374", "IGNATIUS IVAN / WITHDRAW BCA"))

    def test_triplet_tanpa_spasi(self):
        # Rail QRIS/UNOPAY menulis "KODE-NOREK-NAMA" rapat (tanpa spasi kelilingi
        # '-'), berbeda dari rail bank yang pakai " - ". Harus tetap terpecah 3.
        self.assertEqual(
            parse_bank_triplet("DANA-081261612552-MHD ACHIR FADLI PASARIBU"),
            ("DANA", "081261612552", "MHD ACHIR FADLI PASARIBU"))
        # nama boleh memuat '-' internal -> hanya 2 pemisah pertama yang dipecah
        self.assertEqual(
            parse_bank_triplet("BCA-8295463623-RYAN-GRIFFITH"),
            ("BCA", "8295463623", "RYAN-GRIFFITH"))

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


class CORPanelQRISTests(SimpleTestCase):
    HEADER = ["#", "Approved Date", "Requested Date", "Username",
              "Transaction ID", "Amount", "Bonus", "Status"]

    def test_dp_reference_uuid(self):
        path = _xlsx([
            self.HEADER,
            ["1", "01 Jul 2026 23:59:56", "01 Jul 2026 23:59:19", "zidanhoki11",
             "03f747e8-ac9c-48e0-a", "85000", "", "success"],
        ])
        try:
            rows = CORPanelQRISParser().parse(path, flow="dp")
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["jenis"], "depo")
        self.assertEqual(str(r["amount"]), "85000")
        self.assertEqual(r["reference"], "03f747e8-ac9c-48e0-a")   # kunci exact
        self.assertEqual(r["ticket_no"], "")
        self.assertEqual(r["username"], "zidanhoki11")

    def test_skip_tanpa_txid(self):
        path = _xlsx([self.HEADER,
            ["1", "x", "x", "user", "", "1000", "", "success"]])
        try:
            self.assertEqual(CORPanelQRISParser().parse(path, flow="dp"), [])
        finally:
            os.remove(path)

    # WD QRIS/UNOPAY: Destination Bank rapat "KODE-NOREK-NAMA" (tanpa spasi).
    # Regresi prod 11-07-2026: player_bank memuat string 42+ karakter penuh ->
    # varchar(40) overflow di Postgres. Harus jadi kode bank pendek + nama pemain.
    WD_HEADER = ["#", "Approved Date", "Requested Date", "Username",
                 "Transaction ID", "Destination Bank", "Amount", "Status", "By"]

    def test_wd_destination_bank_rapat(self):
        path = _xlsx([
            self.WD_HEADER,
            ["1", "11 Jul 2026 23:03:05", "11 Jul 2026 23:02:56", "batako87",
             "1d4c8093-f8b0-482a-af1f-dc452ef7ed6a",
             "DANA-081261612552-MHD ACHIR FADLI PASARIBU", "800000", "success",
             "gacor25sub42"],
        ])
        try:
            rows = CORPanelQRISParser().parse(path, flow="wd")
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["jenis"], "wd")
        self.assertEqual(r["player_bank"], "DANA")
        self.assertLessEqual(len(r["player_bank"]), 40)   # tak boleh overflow
        self.assertEqual(r["counterparty"], "MHD ACHIR FADLI PASARIBU")
        self.assertEqual(r["reference"], "1d4c8093-f8b0-482a-af1f-dc452ef7ed6a")


class CORQRISGatewayTests(SimpleTestCase):
    HEADER = ["BranchName", "GrandTotal", "BranchNominal", "OrderId",
              "TransactionTime", "RRN", "IssuerName", "CustomerName",
              "Channel", "Order Id Merchant"]

    def test_gateway_reference_gross_fee(self):
        path = _xlsx([
            self.HEADER,
            ["QRIS-7-Beta-TMG3", "85000", "83980", "03f747e8-ac9c-48e0-a",
             "01-Jul-2026 23:59:56", "1pysbjp67783", "-", "-", "Channel 7",
             "03f747e8-ac9c-48e0-a"],
        ])
        try:
            rows = CORQRISGatewayParser().parse(path, flow="dp")
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["source_type"], "gateway")
        self.assertEqual(r["jenis"], "depo")
        self.assertEqual(str(r["amount"]), "85000")          # gross
        self.assertEqual(str(r["money_delta"]), "85000")
        self.assertEqual(str(r["fee"]), "1020")              # 85000 - 83980
        self.assertEqual(r["reference"], "03f747e8-ac9c-48e0-a")
        self.assertEqual(r["ticket_no"], "")


class IngestBankFieldsTests(TestCase):
    def test_ingest_panel_mengisi_player_bank(self):
        path = _xlsx([
            CORPanelBankTests.HEADER,
            ["1", "01 Jul 2026 23:52:18", "01 Jul 2026 23:50:06", "febri72",
             "DANA - 081270670097 - FEBRIA MEGASARI",
             "BCA - 2941413058 - BAGAS ARMANDO", "200000", "approved", "gacor25sub59"],
        ])
        try:
            services.ingest("cor_panel_bank", path, flow="dp")
        finally:
            os.remove(path)
        t = Transaction.objects.get()
        self.assertEqual(t.player_bank, "DANA")
        self.assertEqual(t.bank_title, "BCA")
