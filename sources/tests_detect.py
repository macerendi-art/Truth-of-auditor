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


class DetectMultiBrandTests(SimpleTestCase):
    def _mk(self, header, name):
        path = _xlsx([header, ["x"] * len(header)])
        return path, name

    def test_deteksi_cor_qris_gateway(self):
        path = _xlsx([["BranchName", "GrandTotal", "BranchNominal", "OrderId",
                       "TransactionTime", "RRN"], ["a", "1", "1", "u", "t", "r"]])
        try:
            keys = [d["parser_key"] for d in detect_source(path, "01 DP_QRIS_TRANSACTION.xlsx")]
        finally:
            os.remove(path)
        self.assertEqual(keys[0], "cor_qris_gateway")

    def test_deteksi_qhoki(self):
        path = _xlsx([["Member ID", "Whitelabel Transaction ID", "NMID",
                       "Transaction ID", "Status", "Amount"], ["m", "D1", "", "u", "Success", "1"]])
        try:
            keys = [d["parser_key"] for d in detect_source(path, "DP QH MUL.xlsx")]
        finally:
            os.remove(path)
        self.assertIn("qhoki", keys)

    def test_deteksi_cor_panel_bank(self):
        path = _xlsx([["Approved Date", "Requested Date", "Username", "From Bank",
                       "Destination Bank", "Amount", "Status"], ["a"] * 7])
        try:
            keys = [d["parser_key"] for d in detect_source(path, "BANK_approved_deposit.xlsx")]
        finally:
            os.remove(path)
        self.assertIn("cor_panel_bank", keys)

    def test_deteksi_cor_panel_qris(self):
        path = _xlsx([["#", "Approved Date", "Requested Date", "Username",
                       "Transaction ID", "Amount", "Bonus", "Status"],
                      ["1", "a", "a", "u", "t", "1", "", "success"]])
        try:
            keys = [d["parser_key"] for d in detect_source(path, "DP_QRIS_PANEL.xlsx")]
        finally:
            os.remove(path)
        self.assertIn("cor_panel_qris", keys)

    def test_deteksi_cor_panel_qris_withdraw_tanpa_bonus(self):
        path = _xlsx([["#","Approved Date","Requested Date","Username","Transaction ID",
                       "Destination Bank","Amount","Status","By"],
                      ["1","x","x","user1","uuid-1","BCA - 1 - A","50000","success","op"]])
        try:
            keys = [d["parser_key"] for d in detect_source(path, "QRIS_withdraw_transactions.xlsx")]
        finally:
            os.remove(path)
        self.assertEqual(keys[0], "cor_panel_qris")

    def test_qhoki_dan_cor_panel_qris_tidak_tabrakan(self):
        # Header asli QHoki (Task 8 brief): py qhoki punya "transaction id" + "nmid",
        # TANPA "bonus" -> tidak boleh ikut kena deteksi cor_panel_qris.
        path = _xlsx([["Transaction Date", "Paid Date", "Finished Date", "Settlement Date",
                       "Settled At", "Member ID", "Rrn", "NMID", "Transaction ID",
                       "Whitelabel Transaction ID", "Status", "Amount", "Downline Fee Amount",
                       "Total Amount", "Memo", "Payment Method"],
                      ["2026-07-03", "", "", "", "", "m", "r", "", "u", "D1",
                       "Success", "1", "0", "1", "", "qris"]])
        try:
            keys = [d["parser_key"] for d in detect_source(path, "DP QH MUL.xlsx")]
        finally:
            os.remove(path)
        self.assertIn("qhoki", keys)
        self.assertNotIn("cor_panel_qris", keys)

    def test_cor_panel_qris_dan_qhoki_tidak_tabrakan(self):
        # Header asli COR Panel QRIS (Task 8 brief): punya "bonus", TANPA "nmid"/
        # "whitelabel transaction id" -> tidak boleh ikut kena deteksi qhoki.
        path = _xlsx([["#", "Approved Date", "Requested Date", "Username",
                       "Transaction ID", "Amount", "Bonus", "Status"],
                      ["1", "a", "a", "u", "t", "1", "", "success"]])
        try:
            keys = [d["parser_key"] for d in detect_source(path, "DP_QRIS_PANEL.xlsx")]
        finally:
            os.remove(path)
        self.assertIn("cor_panel_qris", keys)
        self.assertNotIn("qhoki", keys)


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
