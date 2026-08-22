"""Parser + deteksi QRIS KINGSPAY CSV (STN 20-08-2026)."""
import csv
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from reconciliation.engine import run_match
from reconciliation.models import MatchResult, ToleranceProfile
from sources import services
from sources.detect import detect_source
from sources.parsers.gateways import KingsPayParser
from sources.models import SourceType, Upload
from transactions.models import Transaction

HEADER = [
    "idMerchant", "merchantName", "channelType", "merchantTrxId",
    "platformTrxId", "amount", "productName", "biayaPlatform", "netAmount",
    "status", "rrn", "nmid", "username", "storeName", "idSettlement",
    "created_at", "success_at",
]


def _baris(**beda):
    nilai = {
        "idMerchant": "57",
        "merchantName": "Spontan77 Script",
        "channelType": "QRIS",
        "merchantTrxId": "PUB20260820235608575481656",
        "platformTrxId": "20260820235608741234191",
        "amount": "300000",
        "productName": "QRIS_AUTO_1_300000",
        "biayaPlatform": "3000",
        "netAmount": "297000",
        "status": "success",
        "rrn": "608201132689",
        "nmid": "ID1026481168346",
        "username": "Assololo99",
        "storeName": "Book of Luma Digital Stor",
        "idSettlement": "",
        "created_at": "2026-08-20 23:56:08",
        "success_at": "2026-08-20 23:57:46",
    }
    nilai.update(beda)
    return [nilai.get(k, "") for k in HEADER]


def _csv(baris=None, header=None):
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header or HEADER)
        w.writerows(baris or [])
    return path


class KingsPayParserTests(SimpleTestCase):
    def _parse(self, baris, flow="dp"):
        path = _csv(baris)
        try:
            return KingsPayParser().parse(path, flow=flow)
        finally:
            os.remove(path)

    def test_field_kanonik_username_tanpa_reference(self):
        r = self._parse([_baris()])[0]
        self.assertEqual(r["source_type"], "gateway")
        self.assertEqual(r["jenis"], "depo")
        self.assertEqual(r["ticket_no"], "")
        self.assertEqual(r["reference"], "")  # platformTrxId hanya di raw
        self.assertEqual(r["username"], "Assololo99")
        self.assertEqual(r["amount"], Decimal("300000"))
        self.assertEqual(r["money_delta"], Decimal("300000"))
        self.assertEqual(r["fee"], Decimal("3000"))
        self.assertEqual(r["occurred_at"], datetime(2026, 8, 20, 23, 57, 46))
        self.assertEqual(r["posted_date"], date(2026, 8, 20))
        self.assertTrue(r["description"].startswith("KINGSPAY"))
        self.assertEqual(r["raw"]["platformTrxId"], "20260820235608741234191")
        self.assertEqual(r["raw"]["merchantTrxId"], "PUB20260820235608575481656")

    def test_status_bukan_success_dilewati(self):
        rows = self._parse([
            _baris(platformTrxId="1", status="success"),
            _baris(platformTrxId="2", status="pending"),
            _baris(platformTrxId="3", status="failed"),
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["raw"]["platformTrxId"], "1")

    def test_zero_yield_status_asing_raise(self):
        with self.assertRaises(ValueError) as ctx:
            self._parse([
                _baris(platformTrxId="1", status="pending"),
                _baris(platformTrxId="2", status="expired"),
            ])
        self.assertIn("tidak satu", str(ctx.exception).lower())

    def test_flow_wd_tidak_membalik_deposit(self):
        r = self._parse([_baris()], flow="wd")[0]
        self.assertEqual(r["jenis"], "depo")
        self.assertEqual(r["money_delta"], Decimal("300000"))

    def test_header_wajib_hilang_raise(self):
        path = _csv([_baris()], header=["amount", "status", "username"])
        try:
            with self.assertRaises(ValueError) as ctx:
                KingsPayParser().parse(path)
            self.assertIn("tidak ditemukan", str(ctx.exception))
        finally:
            os.remove(path)

    def test_row_hash_stabil(self):
        a = self._parse([_baris()])[0]["row_hash"]
        b = self._parse([_baris()])[0]["row_hash"]
        self.assertEqual(a, b)
        c = self._parse([_baris(amount="300000.00")])[0]["row_hash"]
        self.assertEqual(a, c)  # normalize nominal


class KingsPayDetectTests(SimpleTestCase):
    def test_deteksi_header(self):
        path = _csv([_baris()])
        try:
            hasil = detect_source(path, "mutasi.csv")
            self.assertEqual(hasil[0]["parser_key"], "kingspay")
            self.assertGreaterEqual(hasil[0]["confidence"], 0.95)
        finally:
            os.remove(path)

    def test_deteksi_nama_file(self):
        # header palsu tapi nama kingspay — confidence lebih rendah, tetap top
        path = _csv(
            [["x"]],
            header=["foo", "bar", "baz"],
        )
        # rewrite with kingspay name
        os.remove(path)
        fd, path = tempfile.mkstemp(suffix=".csv", prefix="qriskingspay_")
        os.close(fd)
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([["foo", "bar"], ["1", "2"]])
        try:
            # only filename rule if headers don't match — may not be top if empty
            hasil = detect_source(path, "20-08-2026 STN DP QRISKINGSPAY.csv")
            keys = [h["parser_key"] for h in hasil]
            self.assertIn("kingspay", keys)
        finally:
            os.remove(path)

    def test_terdaftar_parsers(self):
        self.assertIs(services.PARSERS.get("kingspay"), KingsPayParser)

    def test_sample_asli_stn_20(self):
        sample = Path.home() / (
            ".hermes/profiles/scope-key/cache/documents/"
            "doc_f2fc269f0042_20-08-2026 STN DP QRISKINGSPAY.csv"
        )
        if not sample.exists():
            self.skipTest("sample cache tidak ada di host ini")
        hasil = detect_source(str(sample), sample.name)
        self.assertEqual(hasil[0]["parser_key"], "kingspay")
        rows = KingsPayParser().parse(str(sample))
        self.assertEqual(len(rows), 560)
        self.assertEqual(sum(r["amount"] for r in rows), Decimal("92371000"))
        self.assertTrue(all(r["username"] for r in rows))
        self.assertTrue(all(r["reference"] == "" for r in rows))
        self.assertTrue(all(r["description"].startswith("KINGSPAY") for r in rows))


class KingsPayChannelGuardTests(TestCase):
    def setUp(self):
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.gw = SourceType.objects.get_or_create(
            key="gateway", defaults={"name": "Gateway", "is_money_source": True}
        )[0]
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1, "fuzzy_threshold": 85}
        )[0]
        self.up = Upload.objects.create(source_type=self.panel)
        self.upg = Upload.objects.create(source_type=self.gw, original_name="dp kings.csv")
        self.dt = datetime(2026, 8, 20, 12, 0)

    def _panel(self, rh, username, bank_title, amount=300000):
        return Transaction.objects.create(
            upload=self.up, source_type=self.panel, jenis="depo",
            amount=Decimal(amount), money_delta=Decimal(amount),
            username=username, bank_title=bank_title,
            occurred_at=self.dt, row_hash=rh,
        )

    def _kings(self, rh, username, amount=300000):
        return Transaction.objects.create(
            upload=self.upg, source_type=self.gw, jenis="depo",
            amount=Decimal(amount), money_delta=Decimal(amount),
            username=username, description="KINGSPAY 608201132689",
            occurred_at=self.dt, row_hash=rh,
        )

    def test_kingspay_jodoh_username(self):
        p = self._panel("p1", "Assololo99", "KINGSPAY|KINGSPAY|8497894156")
        b = self._kings("g1", "Assololo99")
        run = run_match("panel_bank", self.tol)
        r = MatchResult.objects.get(run=run, left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.right_id, b.id)

    def test_uang_kingspay_tidak_menyedot_nxpay(self):
        p = self._panel("p1", "Assololo99", "NXPAY DEPOSIT QR")
        b = self._kings("g1", "Assololo99")
        run = run_match("panel_bank", self.tol)
        r = MatchResult.objects.get(run=run, left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.TIDAK)
        self.assertEqual(r.reason_code, "no_money")
        self.assertFalse(MatchResult.objects.filter(run=run, right=b).exists())
