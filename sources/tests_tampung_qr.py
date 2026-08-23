"""Parser mutasi TAMPUNG QR Flyer / QRIS Elite (payout → rekening CM)."""
import csv
import os
import tempfile
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from sources import services
from sources.detect import detect_source
from sources.models import Toko
from sources.parsers.gateways import QRFlyerTampungParser, QRISEliteTampungParser
from transactions.models import Transaction

# Cuplikan header+baris dari sampel MUL 22-08 (bukan folder samples/ yang gitignored).
FLYER_CSV = """\
Request Timestamp,Client Ref,Bank Identifier,Bank,Beneficiary Account,Beneficiary Name,Payout Status,Payout Amount,Transaction Fee,Settlement Timestamp
2026-08-22 20:46:01,A2608221204000002597,002,BRI,119101022152500,KIKISUASANTO,Success,IDR 30.000.000,IDR 2.500,2026-08-22 20:46:02.765
2026-08-22 15:36:36,A2608221204000001483,014,BCA,5315090854,UBAY NUDIN,Success,IDR 25.000.000,IDR 2.500,2026-08-22 15:36:39.016
2026-08-22 10:00:00,A260822FAIL,002,BRI,119101022152500,KIKISUASANTO,Failed,IDR 1.000.000,IDR 2.500,2026-08-22 10:00:01
"""

ELITE_CSV = """\
DISBURSEMENT HISTORY,,,,,,,,
ID,DATE_DISBURSEMENT,BANK_CODE,BANK_NO,ACCOUNT_NAME,AMOUNT,REF_ID,VENDOR_ID,VENDOR_STATUS
8969742,2026-08-22,1,1191010221*****,KIKISUASANTO,24996500,WEB-1055-11570716,03-202608222200620166631441,success
8969743,2026-08-22,1,1191010221*****,KIKISUASANTO,1000,WEB-FAIL,x,failed
"""


def _write(text, name="t.csv"):
    fd, path = tempfile.mkstemp(suffix=".csv", prefix=name)
    os.close(fd)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return path


class QRFlyerTampungParserTests(SimpleTestCase):
    def test_parse_fixture(self):
        path = _write(FLYER_CSV, "flyer_tampung_")
        try:
            rows = QRFlyerTampungParser().parse(path)
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 2)  # Failed dibuang
        r0 = rows[0]
        self.assertEqual(r0["jenis"], "wd")
        self.assertEqual(r0["source_type"], "gateway")
        self.assertEqual(r0["reference"], "")
        self.assertTrue(r0["description"].startswith("QRFLYER TAMPUNG"))
        self.assertEqual(r0["money_delta"], Decimal("-30000000"))
        self.assertEqual(r0["amount"], Decimal("30000000"))
        self.assertEqual(r0["fee"], Decimal("2500"))
        self.assertEqual(r0["counterparty"], "KIKISUASANTO")
        self.assertIn("119101022152500", r0["description"])
        self.assertEqual(r0["posted_date"], date(2026, 8, 22))

    def test_detect_fixture(self):
        path = _write(FLYER_CSV, "flyer_tampung_")
        try:
            hit = detect_source(path, "MUTASI TAMPUNG QR FLYER MUL 22-08.csv")
        finally:
            os.remove(path)
        self.assertTrue(hit)
        self.assertEqual(hit[0]["parser_key"], "qrflyer_tampung")
        self.assertGreaterEqual(hit[0]["confidence"], 0.95)

    def test_registry(self):
        self.assertIs(services.PARSERS.get("qrflyer_tampung"), QRFlyerTampungParser)


class QRISEliteTampungParserTests(SimpleTestCase):
    def test_parse_fixture(self):
        path = _write(ELITE_CSV, "elite_tampung_")
        try:
            rows = QRISEliteTampungParser().parse(path)
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)  # failed dibuang
        r0 = rows[0]
        self.assertEqual(r0["jenis"], "wd")
        self.assertEqual(r0["amount"], Decimal("24996500"))
        self.assertEqual(r0["money_delta"], Decimal("-24996500"))
        self.assertEqual(r0["counterparty"], "KIKISUASANTO")
        self.assertTrue(r0["description"].startswith("QRISELITE TAMPUNG"))
        self.assertIn("1191010221", r0["description"])
        self.assertEqual(r0["posted_date"], date(2026, 8, 22))
        self.assertEqual(r0["reference"], "")

    def test_detect_fixture(self):
        path = _write(ELITE_CSV, "elite_tampung_")
        try:
            hit = detect_source(path, "MUTASI TAMPUNG QR ELITE MUL 22-08.csv")
        finally:
            os.remove(path)
        self.assertTrue(hit)
        self.assertEqual(hit[0]["parser_key"], "qris_elite_tampung")
        self.assertGreaterEqual(hit[0]["confidence"], 0.95)
        self.assertNotEqual(hit[0]["parser_key"], "qris_elite")

    def test_registry(self):
        self.assertIs(services.PARSERS.get("qris_elite_tampung"), QRISEliteTampungParser)


class TampungIngestSesamaCmTests(TestCase):
    """Ingest Flyer tampung → baris gateway WD dengan nama/norek CM."""

    def test_ingest_flyer_tampung_counterparty_cm(self):
        toko = Toko.objects.get(key="mul")
        path = _write(FLYER_CSV, "flyer_ing_")
        try:
            _, dibuat, _ = services.ingest(
                "qrflyer_tampung", path, toko=toko, flow="wd",
            )
        finally:
            os.remove(path)
        self.assertEqual(dibuat, 2)
        qs = Transaction.objects.filter(toko=toko, source_type__key="gateway")
        self.assertEqual(qs.count(), 2)
        self.assertTrue(qs.filter(jenis="wd", counterparty="KIKISUASANTO").exists())
        t = qs.filter(counterparty="KIKISUASANTO").first()
        self.assertIn("119101022152500", t.description)


class SesamaCmIdentityMaskedNorekTests(SimpleTestCase):
    def test_prefiks_norek_elite_tampung(self):
        from reconciliation.engine import _sesama_cm_identity

        class FR:
            raw = {
                "No. Rek Bank Member": "BRI 119101022152500",
                "Bank": "BANK BRI | KIKI SUASANTO | TAMPUNG",
            }

        class Money:
            counterparty = "KIKISUASANTO"
            description = "QRISELITE TAMPUNG 1191010221 KIKISUASANTO WEB-1"

        sc, reason = _sesama_cm_identity(FR(), Money())
        self.assertEqual(sc, 100.0)
        self.assertEqual(reason, "amount+rek")
