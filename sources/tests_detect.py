import os
import tempfile

import openpyxl
from django.test import SimpleTestCase

from sources.detect import detect_source


def _xlsx(rows):
    fd, p = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    wb.save(p)
    return p


def _csv(text):
    fd, p = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


class DetectTests(SimpleTestCase):
    def test_panel(self):
        p = _xlsx([["HISTORI DP PANEL"], ["Ticket Number", "User Name", "Deposit Amount"]])
        self.assertEqual(detect_source(p, "hist.xlsx")[0]["parser_key"], "panel")

    def test_nxpay_not_confused_with_panel(self):
        p = _xlsx([["NXPAY REPORT"], ["Ticket Number", "Username", "Amount", "Admin Fee", "Account Title"]])
        self.assertEqual(detect_source(p, "nx.xlsx")[0]["parser_key"], "nxpay")

    def test_bracket(self):
        p = _xlsx([["Kategori", "Credit Awal", "Credit Akhir", "Transaction ID"]])
        self.assertEqual(detect_source(p, "fr.xlsx")[0]["parser_key"], "bracket")

    def test_qrflyer(self):
        # header asli QR FLYER: tanpa token "QRIS"/"QR FLYER" di dalam file
        p = _xlsx([[
            "Transaction Date", "Client Reference", "TXN ID",
            "Customer ID / User Account", "Payment Status", "Settlement Time",
            "System Processed At", "Transaction Value",
        ]])
        self.assertEqual(detect_source(p, "MUTASI DP QR FLYER OKE25 28-06.xlsx")[0]["parser_key"], "qrflyer")

    def test_bri_csv(self):
        p = _csv("TGL_TRAN,MUTASI_DEBET,MUTASI_KREDIT,DESK_TRAN\n")
        self.assertEqual(detect_source(p, "bri.csv")[0]["parser_key"], "bri")

    def test_bca_csv(self):
        p = _csv("Rekening\nTanggal,Keterangan,Cabang,Jumlah,,Saldo\n")
        self.assertEqual(detect_source(p, "bca.csv")[0]["parser_key"], "bca_csv")

    def test_pdf_extension(self):
        fd, p = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        self.assertEqual(detect_source(p, "koran.pdf")[0]["parser_key"], "bca_pdf")

    def test_unknown_returns_empty(self):
        p = _xlsx([["Foo", "Bar"]])
        self.assertEqual(detect_source(p, "x.xlsx"), [])
