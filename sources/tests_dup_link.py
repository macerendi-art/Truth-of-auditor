"""Pemetaan baris duplikat -> upload barunya (`Upload.duplicate_transactions`).

File ekspor bank sering rolling/tumpang-tindih: baris yang sama muncul di
beberapa file. Dedup row_hash menyimpan baris HANYA di upload pertama; tanpa
pemetaan ini, "isi file" upload berikutnya tidak bisa direkonstruksi lagi —
filter per-file di Mutasi Bank tampak "kepotong" (kasus nyata LBS 10/07 &
12/07: file 13 baris tampil 1 baris).
"""
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from sources import services
from sources.models import SourceType, Toko
from transactions.models import Transaction


def _row(hash_suffix, ticket="D1", jam=10):
    return {
        "occurred_at": datetime(2026, 7, 12, jam, 0), "posted_date": None, "jenis": "depo",
        "amount": Decimal("50000"), "credit_delta": Decimal("-50000"),
        "money_delta": Decimal("50000"), "fee": Decimal("0"), "bonus": Decimal("0"),
        "balance_after": None, "ticket_no": ticket, "username": "budi",
        "reference": "", "counterparty": "", "description": "", "raw": {},
        "row_hash": f"dup-link-{hash_suffix}",
    }


class _ParserAB:
    """File #1: baris a+b."""

    source_key = "bank"

    def parse(self, path, flow=""):
        return [_row("a", "D1", 1), _row("b", "D2", 2)]


class _ParserBC:
    """File #2 (rolling): b lagi + c baru."""

    source_key = "bank"

    def parse(self, path, flow=""):
        return [_row("b", "D2", 2), _row("c", "D3", 3)]


class _ParserRepeat:
    """Satu file memuat baris kembar identik (repeat DALAM file)."""

    source_key = "bank"

    def parse(self, path, flow=""):
        return [_row("x", "D9", 4), _row("x", "D9", 4)]


class DupLinkIngestTests(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.toko_lain = Toko.objects.get(key="slo")
        SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})

    def test_duplikat_dilink_ke_upload_baru(self):
        """Baris yang di-skip dedup harus ter-link ke upload barunya."""
        with patch.dict(services.PARSERS, {"ab": _ParserAB, "bc": _ParserBC}, clear=False):
            up1, _, _ = services.ingest("ab", "/nofile-1.csv", toko=self.toko)
            up2, created2, dup2 = services.ingest("bc", "/nofile-2.csv", toko=self.toko)

        self.assertEqual((created2, dup2), (1, 1))
        tx_b = Transaction.objects.get(row_hash="dup-link-b")
        self.assertEqual(tx_b.upload_id, up1.id)  # data tetap di upload pertama
        self.assertEqual(list(up2.duplicate_transactions.all()), [tx_b])
        self.assertEqual(up1.duplicate_transactions.count(), 0)

    def test_repeat_dalam_satu_file_tidak_dilink(self):
        """Baris kembar DALAM file yang sama bukan 'tercatat di file terdahulu'."""
        with patch.dict(services.PARSERS, {"rep": _ParserRepeat}, clear=False):
            up, created, dup = services.ingest("rep", "/nofile.csv", toko=self.toko)
        self.assertEqual((created, dup), (1, 1))
        self.assertEqual(up.duplicate_transactions.count(), 0)

    def test_lintas_toko_tidak_dilink(self):
        """Dedup di-scope per toko — toko lain dapat baris sendiri, tanpa link."""
        with patch.dict(services.PARSERS, {"ab": _ParserAB}, clear=False):
            services.ingest("ab", "/nofile-1.csv", toko=self.toko)
            up_b, created_b, dup_b = services.ingest("ab", "/nofile-1.csv", toko=self.toko_lain)
        self.assertEqual((created_b, dup_b), (2, 0))
        self.assertEqual(up_b.duplicate_transactions.count(), 0)

    def test_hapus_upload_asal_membersihkan_link(self):
        """Hapus upload pertama (data ikut terhapus) -> link di upload kedua ikut bersih."""
        with patch.dict(services.PARSERS, {"ab": _ParserAB, "bc": _ParserBC}, clear=False):
            up1, _, _ = services.ingest("ab", "/nofile-1.csv", toko=self.toko)
            up2, _, _ = services.ingest("bc", "/nofile-2.csv", toko=self.toko)
        up1.delete()
        self.assertEqual(up2.duplicate_transactions.count(), 0)
