from datetime import datetime
from decimal import Decimal

from django.test import SimpleTestCase

from sources.parsers.base import extract_ref, extract_ticket, parse_decimal, parse_dt


class ParseDecimalTests(SimpleTestCase):
    def test_intl(self):
        self.assertEqual(parse_decimal("1,000,000.00"), Decimal("1000000.00"))

    def test_id_format(self):
        self.assertEqual(parse_decimal("90.000,00", "id"), Decimal("90000.00"))

    def test_id_negative(self):
        self.assertEqual(parse_decimal("-347.000,00", "id"), Decimal("-347000.00"))

    def test_debit_suffix_negative(self):
        self.assertEqual(parse_decimal("400000.00DB"), Decimal("-400000.00"))

    def test_credit_suffix_positive(self):
        self.assertEqual(parse_decimal("400000.00 CR"), Decimal("400000.00"))

    def test_numeric_passthrough(self):
        self.assertEqual(parse_decimal(20000.0), Decimal("20000.0"))

    def test_bri_zero(self):
        self.assertEqual(parse_decimal(".00"), Decimal("0"))

    def test_rp_prefix(self):
        self.assertEqual(parse_decimal("Rp 57,000.00"), Decimal("57000.00"))

    def test_empty(self):
        self.assertEqual(parse_decimal(""), Decimal("0"))


class ExtractTests(SimpleTestCase):
    def test_ticket_deposit(self):
        self.assertEqual(
            extract_ticket("Direct Deposit - D1757153 F260627206100206205"), "D1757153"
        )

    def test_ticket_withdraw(self):
        self.assertEqual(extract_ticket("Direct Withdraw - W1757092"), "W1757092")

    def test_reference_longform(self):
        self.assertEqual(
            extract_ref("Direct Deposit - D1757153 F260627206100206205"),
            "F260627206100206205",
        )

    def test_long_ref_not_mistaken_as_ticket(self):
        self.assertEqual(extract_ticket("F260627206100206205 saja"), "")


class ParseDtTests(SimpleTestCase):
    def test_iso(self):
        self.assertEqual(parse_dt("2026-06-27 23:59:33"), datetime(2026, 6, 27, 23, 59, 33))

    def test_dayfirst(self):
        self.assertEqual(parse_dt("28/06/2026", dayfirst=True).date(), datetime(2026, 6, 28).date())

    def test_us_ampm(self):
        self.assertEqual(parse_dt("6/27/2026 12:00:36 AM"), datetime(2026, 6, 27, 0, 0, 36))

    def test_invalid_returns_none(self):
        self.assertIsNone(parse_dt(""))
        self.assertIsNone(parse_dt("Saldo Awal"))
