"""Regresi: dedup harus di-scope per toko (bukan lintas toko).

Bug: `existing` di `services.ingest()` dibangun dari SEMUA toko, sedangkan
`row_hash` per baris tidak menyertakan toko. Akibatnya baris Toko B yang
kebetulan punya `row_hash` sama dengan baris tersimpan milik Toko A dianggap
duplikat dan diam-diam dibuang -> isolasi data per-toko rusak.
"""
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from sources import services
from sources.models import SourceType, Toko
from transactions.models import Transaction

# Dua baris kanonik dengan row_hash TIDAK menyertakan toko (persis seperti
# yang dihasilkan parser nyata, mis. panel: row_hash("panel", [ticket, user, amount])).
_ROWS = [
    {
        "occurred_at": datetime(2026, 6, 27, 10, 0), "posted_date": None, "jenis": "depo",
        "amount": Decimal("50000"), "credit_delta": Decimal("-50000"),
        "money_delta": Decimal("50000"), "fee": Decimal("0"), "bonus": Decimal("0"),
        "balance_after": None, "ticket_no": "D1757153", "username": "budi",
        "reference": "", "counterparty": "", "description": "", "raw": {},
        "row_hash": "shared-hash-row-1",
    },
    {
        "occurred_at": datetime(2026, 6, 27, 11, 0), "posted_date": None, "jenis": "wd",
        "amount": Decimal("100000"), "credit_delta": Decimal("100000"),
        "money_delta": Decimal("-100000"), "fee": Decimal("0"), "bonus": Decimal("0"),
        "balance_after": None, "ticket_no": "W1757092", "username": "siti",
        "reference": "", "counterparty": "", "description": "", "raw": {},
        "row_hash": "shared-hash-row-2",
    },
]


class _SharedParser:
    """Parser dummy: selalu kembalikan baris identik (row_hash sama untuk file/konten sama)."""

    source_key = "bracket"

    def parse(self, path, flow=""):
        return [dict(r) for r in _ROWS]


class CrossTokoDedupTests(TestCase):
    def setUp(self):
        self.toko_a = Toko.objects.get(key="lbs")
        self.toko_b = Toko.objects.get(key="slo")
        SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})

    def test_cross_toko_not_suppressed(self):
        """Toko B harus tetap dapat transaksinya walau row_hash sama dgn Toko A."""
        with patch.dict(services.PARSERS, {"shared": _SharedParser}, clear=False):
            _, created_a, _ = services.ingest("shared", "/nofile", toko=self.toko_a)
            _, created_b, _ = services.ingest("shared", "/nofile", toko=self.toko_b)

        self.assertEqual(created_a, len(_ROWS))
        # Inti bug: Toko B TIDAK boleh disuppress jadi 0.
        self.assertEqual(created_b, len(_ROWS))
        self.assertEqual(Transaction.objects.filter(toko=self.toko_a).count(), len(_ROWS))
        self.assertEqual(Transaction.objects.filter(toko=self.toko_b).count(), len(_ROWS))

    def test_same_toko_idempotent(self):
        """Re-ingest data yang SAMA untuk toko yang SAMA tidak menggandakan."""
        with patch.dict(services.PARSERS, {"shared": _SharedParser}, clear=False):
            _, created_first, _ = services.ingest("shared", "/nofile", toko=self.toko_a)
            _, created_second, dup_second = services.ingest("shared", "/nofile", toko=self.toko_a)

        self.assertEqual(created_first, len(_ROWS))
        self.assertEqual(created_second, 0)
        self.assertEqual(dup_second, len(_ROWS))
        self.assertEqual(Transaction.objects.filter(toko=self.toko_a).count(), len(_ROWS))
