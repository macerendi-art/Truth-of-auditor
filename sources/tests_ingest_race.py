"""Balapan ingest ganda (double-submit / dua worker): constraint DB menolak baris
kembar → ingest harus RETRY SEKALI (percobaan kedua melihat baris yang sudah
commit sebagai duplikat), bukan menggagalkan upload dengan IntegrityError mentah."""
from datetime import datetime
from decimal import Decimal
from unittest import mock

from django.db import IntegrityError
from django.test import TestCase

from sources import services
from sources.models import Toko
from transactions.models import Transaction


class _FakeParser:
    source_key = "panel"

    def parse(self, path, flow=""):
        def row(rh, amt):
            return {
                "occurred_at": datetime(2026, 6, 27, 10, 0), "posted_date": None,
                "jenis": "depo", "amount": Decimal(amt), "credit_delta": -Decimal(amt),
                "money_delta": Decimal(amt), "fee": Decimal("0"), "bonus": Decimal("0"),
                "balance_after": None, "ticket_no": "", "username": "u1",
                "reference": "", "counterparty": "", "description": "",
                "raw": {}, "row_hash": rh,
            }
        return [row("race-1", "10000"), row("race-2", "20000")]


class IngestRaceRetryTests(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        services.PARSERS["_fake_race"] = _FakeParser
        self.addCleanup(services.PARSERS.pop, "_fake_race", None)

    def test_integrity_error_diulang_sekali_dan_sukses(self):
        real = Transaction.objects.bulk_create
        calls = {"n": 0}

        def flaky(objs, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise IntegrityError("simulasi balapan ingest ganda")
            return real(objs, **kw)

        with mock.patch.object(services.Transaction.objects, "bulk_create", side_effect=flaky):
            up, created, dup = services.ingest("_fake_race", "/tmp/xx.xlsx", toko=self.toko)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(created, 2)
        self.assertEqual(Transaction.objects.filter(row_hash__startswith="race-").count(), 2)

    def test_integrity_error_kedua_tetap_dilempar(self):
        with mock.patch.object(
            services.Transaction.objects, "bulk_create",
            side_effect=IntegrityError("terus-menerus"),
        ):
            with self.assertRaises(IntegrityError):
                services.ingest("_fake_race", "/tmp/xx.xlsx", toko=self.toko)
