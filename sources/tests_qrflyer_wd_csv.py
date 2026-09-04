"""QR FLYER bentuk kelima — WD CSV (Request Date + Client Ref / Transaction ID).

Sampel klien: ``QRIS FLYER WD 03-09-2026.csv``. Sebelumnya detect CSV Flyer
member = [] (aturan qrflyer hanya di cabang XLSX), dan parser hanya
``read_xlsx_rows`` — commit gagal / jenis tak terdeteksi.
"""
import csv
import os
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase

from sources.detect import detect_source
from sources.flow import detect_flow
from sources.parsers.gateways import QRFlyerParser

SAMPLE = Path(
    "/Users/macads/.hermes/profiles/scope-key/cache/documents/"
    "doc_af833d62b252_QRIS FLYER WD 03-09-2026.csv"
)

HEADER = [
    "Request Date", "Client Ref / Transaction ID", "Bank Account",
    "Account Name", "Username", "Amount", "Settlement Amount",
    "Charge To Player", "Charge To Merchant", "Charge Fee", "Status",
    "Error Message", "Processed Date",
]


def _csv(rows, nama="QRIS FLYER WD 03-09-2026.csv"):
    fd, path = tempfile.mkstemp(suffix=".csv", prefix="flyer_wd_")
    os.close(fd)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        for r in rows:
            w.writerow(r)
    return path


def _baris(
    ticket_blob="260903MP11930000095A||W3323863",
    user="Mayra556",
    amount="Rp52.000",
    settle_amt="Rp54.500",
    fee="Rp2.500",
    status="Success",
    req="2026-09-03 21:51:47",
    proc="2026-09-03 21:51:51",
    name="DINA AULIA",
):
    return [
        req, ticket_blob, "535||Seabank||9019", name, user,
        amount, settle_amt, "Rp0", fee, fee, status, "-", proc,
    ]


class FlyerBentukKelimaWdCsvTests(SimpleTestCase):
    def test_detect_header_csv_qrflyer(self):
        path = _csv([HEADER, _baris()])
        try:
            hit = detect_source(path, "laporan-vendor.csv")  # nama tanpa flyer
        finally:
            os.remove(path)
        self.assertEqual(hit[0]["parser_key"], "qrflyer")
        self.assertGreaterEqual(hit[0]["confidence"], 0.9)

    def test_detect_filename_csv_qrflyer(self):
        path = _csv([["a", "b"], ["1", "2"]])
        try:
            hit = detect_source(path, "QRIS FLYER WD 03-09-2026.csv")
        finally:
            os.remove(path)
        keys = [h["parser_key"] for h in hit]
        self.assertIn("qrflyer", keys)

    def test_flow_filename_wd(self):
        self.assertEqual(detect_flow("QRIS FLYER WD 03-09-2026.csv"), "wd")

    def test_parse_tiket_pipe_dan_nominal_rp(self):
        path = _csv([HEADER, _baris()])
        try:
            r = QRFlyerParser().parse(path, flow="wd")[0]
        finally:
            os.remove(path)
        self.assertEqual(r["ticket_no"], "W3323863")
        self.assertEqual(r["reference"], "260903MP11930000095A")
        self.assertEqual(r["username"], "Mayra556")
        self.assertEqual(r["jenis"], "wd")
        self.assertEqual(r["amount"], Decimal("52000"))
        self.assertEqual(r["money_delta"], Decimal("-52000"))
        self.assertEqual(r["fee"], Decimal("2500"))
        self.assertEqual(str(r["posted_date"]), "2026-09-03")
        self.assertEqual(r["occurred_at"].strftime("%Y-%m-%d %H:%M"), "2026-09-03 21:51")
        self.assertEqual(r["counterparty"], "DINA AULIA")
        self.assertIn("QRFLYER", r["description"])

    def test_parse_tiket_spasi(self):
        path = _csv([HEADER, _baris(ticket_blob="260903MP1193 0000083A W3323760")])
        try:
            r = QRFlyerParser().parse(path, flow="wd")[0]
        finally:
            os.remove(path)
        self.assertEqual(r["ticket_no"], "W3323760")
        self.assertTrue(r["reference"])
        self.assertNotIn("W3323760", r["reference"])

    def test_status_bukan_success_dilewati(self):
        path = _csv([
            HEADER,
            _baris(status="Failed", ticket_blob="260903MP||W1111111"),
            _baris(status="Success", ticket_blob="260903MP||W2222222"),
        ])
        try:
            rows = QRFlyerParser().parse(path, flow="wd")
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticket_no"], "W2222222")

    def test_tanpa_flow_tiket_W_jadi_wd(self):
        path = _csv([HEADER, _baris()])
        try:
            r = QRFlyerParser().parse(path, flow="")[0]
        finally:
            os.remove(path)
        self.assertEqual(r["jenis"], "wd")
        self.assertEqual(r["money_delta"], Decimal("-52000"))

    def test_format_lama_xlsx_tidak_regresi(self):
        """Bentuk snake_case XLSX tetap 1 baris + hash stabil."""
        from openpyxl import Workbook

        fd, path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        wb = Workbook()
        ws = wb.active
        ws.append([
            "created_date", "client_reference", "transaction_id", "username",
            "status", "trans_date_time", "bot_success_time", "total_amount",
        ])
        ws.append([
            "2026-08-06 00:06:46", "A260806119200001624", "D769946", "maxwin255",
            "1", "2026-08-06 00:07:08", "2026-08-06 00:07:12", "100000.00",
        ])
        wb.save(path)
        try:
            r = QRFlyerParser().parse(path, flow="dp")[0]
        finally:
            os.remove(path)
        self.assertEqual(r["ticket_no"], "D769946")
        self.assertEqual(r["amount"], Decimal("100000.00"))
        self.assertEqual(r["jenis"], "depo")


class FlyerBentukKelimaSampleNyataTests(SimpleTestCase):
    """Kalibrasi pada berkas klien asli bila masih ada di cache."""

    def test_sample_89_baris_bila_ada(self):
        if not SAMPLE.is_file():
            self.skipTest("sample cache tidak ada")
        # salin ke tmp supaya parser tidak bergantung path cache
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        shutil.copy(SAMPLE, path)
        try:
            hit = detect_source(path, "QRIS FLYER WD 03-09-2026.csv")
            self.assertEqual(hit[0]["parser_key"], "qrflyer")
            rows = QRFlyerParser().parse(path, flow="wd")
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 89)
        self.assertTrue(all(r["jenis"] == "wd" for r in rows))
        self.assertTrue(all(r["ticket_no"].startswith("W") for r in rows))
        self.assertEqual(rows[0]["amount"], Decimal("52000"))
        self.assertEqual(rows[0]["ticket_no"], "W3323863")
        # total nominal kasar (sanity, bukan hard contract keuangannya)
        total = sum(r["amount"] for r in rows)
        self.assertGreater(total, Decimal("1000000"))
