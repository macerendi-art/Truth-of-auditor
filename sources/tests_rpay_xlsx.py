"""Parser gateway RafflesPay varian XLSX (BBS): DP satu-header, WD dua-tingkat."""
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


class ReadXlsxGridTests(SimpleTestCase):
    def test_grid_mentah_semua_baris(self):
        from sources.parsers.base import read_xlsx_grid
        path = _xlsx([["A", "B"], ["", "sub"], [1, 2]])
        try:
            grid = read_xlsx_grid(path)
        finally:
            os.remove(path)
        self.assertEqual(len(grid), 3)
        self.assertEqual(grid[0][0], "A")
        self.assertEqual(grid[1][1], "sub")
        self.assertEqual(grid[2][1], 2)


DP_HEADER = ["Website", "Date", "Ticket Number", "Player", "Payment Type",
             "Account Title", "Status", "Payment Gateway", "RRN", "Amount (IDR)",
             "Amount (Chip)", "Player Fee", "Agent Fee", "Admin Fee",
             "Player Nett Amount", "Agent Nett Amount", "Ticket Status", "Promotion"]


def _dp_row(ticket="D2553373", status="Success", ticket_status="approved",
            rrn="336884375", amount=30000.0):
    return ["BOBASLOT77", "2026-07-16 00:00:35.002000", ticket, "vivian01", "QR",
            "QRIS", status, "RafflesPay", rrn, amount, amount / 1000, 0.0, 0.0,
            600.0, amount, amount, ticket_status, ""]


class RPayDPXlsxTests(SimpleTestCase):
    def _parse(self, rows, flow=""):
        from sources.parsers.gateways import RPayDPXlsxParser
        path = _xlsx([DP_HEADER] + rows)
        try:
            return RPayDPXlsxParser().parse(path, flow=flow)
        finally:
            os.remove(path)

    def test_dp_sukses_field_lengkap(self):
        rows = self._parse([_dp_row()])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["jenis"], "depo")
        self.assertEqual(str(r["amount"]), "30000")        # rupiah penuh, BUKAN x1000
        self.assertEqual(str(r["money_delta"]), "30000")   # DP = uang masuk
        self.assertEqual(str(r["credit_delta"]), "0")
        self.assertEqual(r["ticket_no"], "D2553373")       # anchor pass-0
        self.assertEqual(r["username"], "vivian01")
        self.assertEqual(str(r["fee"]), "600")
        self.assertEqual(r["reference"], "")               # RRN hanya di raw
        self.assertEqual(r["raw"]["RRN"], "336884375")
        self.assertEqual(r["occurred_at"].year, 2026)
        self.assertEqual(r["occurred_at"].month, 7)
        self.assertEqual(r["occurred_at"].day, 16)

    def test_status_bukan_success_dilewati(self):
        rows = self._parse([_dp_row(status="Pending")])
        self.assertEqual(rows, [])

    def test_ticket_failed_tetap_diambil(self):
        # Uang QR masuk tapi tiket panel gagal -> harus muncul sebagai selisih.
        rows = self._parse([_dp_row(ticket_status="failed")])
        self.assertEqual(len(rows), 1)

    def test_flow_wd_diabaikan_tetap_depo(self):
        rows = self._parse([_dp_row()], flow="wd")
        self.assertEqual(rows[0]["jenis"], "depo")
        self.assertEqual(str(rows[0]["money_delta"]), "30000")

    def test_row_hash_stabil_dan_beda_per_tiket(self):
        a = self._parse([_dp_row()])[0]["row_hash"]
        b = self._parse([_dp_row()])[0]["row_hash"]
        c = self._parse([_dp_row(ticket="D2553374")])[0]["row_hash"]
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


WD_TOP = ["ID", "Website", "Date", "Ticket", "Player", "Source of Funds",
          "Beneficiary", "", "", "Amount", "", "", "Status", "", "", ""]
WD_SUB = ["", "", "", "", "", "", "Bank", "Name", "Number", "Amount",
          "Disbursed Amount", "Fee", "Status", "Approve", "Reject", "Transfer"]


def _wd_row(ticket="W2553796", transfer="success", bank="DANA",
            number="81311189314", amount=1950000.0, disbursed=1950000.0):
    return [6001917, "BOBASLOT77", "2026-07-16 04:45:16", ticket, "Rio171",
            "[BOBASLOT77] [RafflesPay] [577068433908]", bank, "AJRIAN ALANSYAH",
            number, amount, disbursed, 5000.0, "approved", "success", "", transfer]


class RPayWDXlsxTests(SimpleTestCase):
    def _parse(self, rows, flow=""):
        from sources.parsers.gateways import RPayWDXlsxParser
        path = _xlsx([WD_TOP, WD_SUB] + rows)
        try:
            return RPayWDXlsxParser().parse(path, flow=flow)
        finally:
            os.remove(path)

    def test_wd_sukses_field_lengkap(self):
        rows = self._parse([_wd_row()])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["jenis"], "wd")
        self.assertEqual(str(r["amount"]), "1950000")       # Disbursed, rupiah penuh
        self.assertEqual(str(r["money_delta"]), "-1950000")  # WD = uang keluar
        self.assertEqual(str(r["credit_delta"]), "0")
        self.assertEqual(r["ticket_no"], "W2553796")         # anchor pass-0
        self.assertEqual(r["username"], "Rio171")
        self.assertEqual(r["counterparty"], "AJRIAN ALANSYAH")
        self.assertEqual(str(r["fee"]), "5000")
        self.assertEqual(r["reference"], "")
        self.assertEqual(r["raw"]["Number"], "81311189314")  # nomor tujuan utk paket B
        self.assertEqual(r["occurred_at"].hour, 4)

    def test_disbursed_dipakai_bukan_amount(self):
        rows = self._parse([_wd_row(amount=2000000.0, disbursed=1950000.0)])
        self.assertEqual(str(rows[0]["amount"]), "1950000")

    def test_transfer_bukan_success_dilewati(self):
        rows = self._parse([_wd_row(transfer="")])
        self.assertEqual(rows, [])

    def test_flow_dp_diabaikan_tetap_wd(self):
        rows = self._parse([_wd_row()], flow="dp")
        self.assertEqual(rows[0]["jenis"], "wd")
        self.assertEqual(str(rows[0]["money_delta"]), "-1950000")

    def test_row_hash_dari_id_dan_ticket_tanpa_nominal(self):
        a = self._parse([_wd_row(amount=1950000.0)])[0]["row_hash"]
        b = self._parse([_wd_row(amount=1950000.49)])[0]["row_hash"]  # nominal beda
        self.assertEqual(a, b)  # idempoten thd variasi format angka
