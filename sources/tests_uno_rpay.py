"""Parser gateway UNO WD (QRIS withdrawal Vigor/TMG) & RPay (QRIS DP Nexus/MUL)."""
import os, tempfile
from django.test import SimpleTestCase
from openpyxl import Workbook


def _xlsx(rows):
    wb = Workbook(); ws = wb.active
    for r in rows:
        ws.append(r)
    fd, path = tempfile.mkstemp(suffix=".xlsx"); os.close(fd)
    wb.save(path)
    return path


UNO_WD_HEADER = ["Merchant Name", "Order ID (Merchant)", "AccountNumber",
                 "RecipientName", "Grand Total", "Amount", "Fee", "Remark",
                 "TransactionTime", "Status"]


class UnoWDGatewayTests(SimpleTestCase):
    def _parse(self, rows):
        from sources.parsers.cor import CORQRISWDGatewayParser
        path = _xlsx([UNO_WD_HEADER] + rows)
        try:
            return CORQRISWDGatewayParser().parse(path)
        finally:
            os.remove(path)

    def test_wd_sukses_field_lengkap(self):
        rows = self._parse([
            ["Omega Vig66", "fd1a26d3-5dbe-411b-9f32-96e97184fe31", "081270553953",
             "081270553953", "800900", "800000", "900", "[via-api] ",
             "2026-07-03 23:54:40", "SUCCESS"],
        ])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["jenis"], "wd")
        self.assertEqual(str(r["amount"]), "800000")       # nett = angka panel
        self.assertEqual(str(r["money_delta"]), "-800000")
        self.assertEqual(str(r["credit_delta"]), "0")
        self.assertEqual(str(r["fee"]), "900")
        self.assertEqual(r["reference"], "fd1a26d3-5dbe-411b-9f32-96e97184fe31")
        self.assertEqual(r["counterparty"], "")            # recipient == account (telepon)
        self.assertEqual(r["occurred_at"].hour, 23)
        self.assertIn("081270553953", r["raw"]["AccountNumber"])

    def test_refund_dilewati(self):
        rows = self._parse([
            ["Omega Vig66", "6f2ebccd-9da1-47be-8986-36065e520fc2", "901829968671",
             "901829968671", "412110", "410610", "1500", "[via-api] ",
             "2026-07-03 23:11:52", "REFUND"],
        ])
        self.assertEqual(rows, [])

    def test_transfer_manual_non_uuid_tetap_diambil(self):
        rows = self._parse([
            ["Omega Vig66", "ee4c1d014ae6451891ad", "058801037091503",
             "MAULANA IQBAL AILA", "30001500", "30000000", "1500", "0",
             "2026-07-03 21:20:14", "SUCCESS"],
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["counterparty"], "MAULANA IQBAL AILA")

    def test_row_hash_stabil(self):
        baris = ["Omega Vig66", "fd1a26d3-5dbe-411b-9f32-96e97184fe31", "081270553953",
                 "081270553953", "800900", "800000", "900", "", "2026-07-03 23:54:40", "SUCCESS"]
        a = self._parse([baris])[0]["row_hash"]
        b = self._parse([baris])[0]["row_hash"]
        self.assertEqual(a, b)


class UnoWDRegistrationTests(SimpleTestCase):
    def test_terdaftar_di_parsers(self):
        from sources.services import PARSERS
        from sources.parsers.cor import CORQRISWDGatewayParser
        self.assertIs(PARSERS.get("cor_qris_wd_gateway"), CORQRISWDGatewayParser)

    def test_terdeteksi_dari_header(self):
        from sources.detect import detect_source
        path = _xlsx([UNO_WD_HEADER,
                      ["Omega Vig66", "fd1a26d3-5dbe-411b-9f32-96e97184fe31",
                       "081270553953", "081270553953", "800900", "800000", "900",
                       "", "2026-07-03 23:54:40", "SUCCESS"]])
        try:
            ranked = detect_source(path, "MUTASI WD QR UNO SLO 03-07.xlsx")
        finally:
            os.remove(path)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["parser_key"], "cor_qris_wd_gateway")
        self.assertGreaterEqual(ranked[0]["confidence"], 0.9)
