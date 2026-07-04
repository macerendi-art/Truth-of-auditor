"""Test Task 3: bersihkan nama (alfabet+spasi) sebelum fuzzy matching Panel<->Bank."""
from datetime import datetime
from decimal import Decimal

from django.test import TestCase

from reconciliation.engine import run_match
from reconciliation.models import MatchResult, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from sources.parsers.base import clean_name
from transactions.models import Transaction


class CleanNameUnitTests(TestCase):
    """Unit test murni untuk helper clean_name (tanpa DB)."""

    def test_angka_dan_simbol_diganti_spasi(self):
        self.assertEqual(clean_name("John123 Smith!"), "John Smith")

    def test_angka_menempel_tanpa_spasi_tetap_dipisah(self):
        # "John123Smith" -> tidak boleh menyatu jadi "JohnSmith"
        self.assertEqual(clean_name("John123Smith"), "John Smith")

    def test_simbol_ganda_dan_spasi_pinggir_dirapikan(self):
        self.assertEqual(clean_name("  BUDI--SANTOSO  99"), "BUDI SANTOSO")

    def test_none_jadi_string_kosong(self):
        self.assertEqual(clean_name(None), "")

    def test_string_kosong_tetap_kosong(self):
        self.assertEqual(clean_name(""), "")

    def test_nama_bersih_idempotent(self):
        self.assertEqual(clean_name("BUDI SANTOSO"), "BUDI SANTOSO")


class MoneyMatcherNameCleanEngineTests(TestCase):
    """End-to-end lewat run_match: nama kotor di salah satu/kedua sisi tetap cocok
    selama nama bersihnya identik (relasi panel_bank, threshold default 85)."""

    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.lbs = Toko.objects.get(key="lbs")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)
        self.batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)

    def test_nama_kotor_di_panel_tetap_cocok_setelah_dibersihkan(self):
        """RED di kode lama: fuzzy atas nama kotor "John123 Smith!" vs "JOHN SMITH"
        turun di bawah threshold 85 -> bucket perlu_tinjau, bukan cocok."""
        Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=self.lbs, jenis="depo",
            amount=Decimal("50000"), money_delta=Decimal("50000"),
            occurred_at=datetime(2026, 6, 27, 10, 0),
            username="", counterparty="John123 Smith!",
            row_hash="nc1",
        )
        Transaction.objects.create(
            upload=self.up, source_type=self.bank, toko=self.lbs, jenis="lainnya",
            amount=Decimal("50000"), money_delta=Decimal("50000"),
            occurred_at=datetime(2026, 6, 27, 10, 15),
            username="", counterparty="JOHN SMITH",
            row_hash="nc2",
        )
        run = run_match("panel_bank", self.tol, user=None, toko=self.lbs, batch=self.batch)
        result = MatchResult.objects.get(run=run)
        self.assertEqual(
            result.bucket, MatchResult.Bucket.COCOK,
            f"score={result.score} (RED kode lama: fuzzy atas nama kotor jatuh di bawah threshold)",
        )
        self.assertGreaterEqual(result.score, 85)

    def test_regresi_nama_bersih_identik_tetap_cocok(self):
        """Regresi: nama bersih identik dua sisi (tanpa kotoran) tetap cocok skor 100."""
        Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=self.lbs, jenis="depo",
            amount=Decimal("60000"), money_delta=Decimal("60000"),
            occurred_at=datetime(2026, 6, 27, 9, 0),
            username="", counterparty="BUDI SANTOSO",
            row_hash="nc3",
        )
        Transaction.objects.create(
            upload=self.up, source_type=self.bank, toko=self.lbs, jenis="lainnya",
            amount=Decimal("60000"), money_delta=Decimal("60000"),
            occurred_at=datetime(2026, 6, 27, 9, 10),
            username="", counterparty="BUDI SANTOSO",
            row_hash="nc4",
        )
        run = run_match("panel_bank", self.tol, user=None, toko=self.lbs, batch=self.batch)
        result = MatchResult.objects.get(run=run)
        self.assertEqual(result.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(result.score, 100)

    def test_nama_terpotong_bca_tetap_cocok(self):
        """Task 4: BCA memotong nama ~18 char ("M. YULIANSAR SIREG") — harus tetap
        cocok dengan nama lengkap Panel ("M. YULIANSAR SIREGAR"), skor >= 85."""
        Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=self.lbs, jenis="depo",
            amount=Decimal("100000"), money_delta=Decimal("100000"),
            occurred_at=datetime(2026, 6, 27, 11, 0),
            username="", counterparty="M. YULIANSAR SIREGAR",
            row_hash="nc7",
        )
        Transaction.objects.create(
            upload=self.up, source_type=self.bank, toko=self.lbs, jenis="lainnya",
            amount=Decimal("100000"), money_delta=Decimal("100000"),
            occurred_at=datetime(2026, 6, 27, 11, 5),
            username="", counterparty="M. YULIANSAR SIREG",
            row_hash="nc8",
        )
        run = run_match("panel_bank", self.tol, user=None, toko=self.lbs, batch=self.batch)
        result = MatchResult.objects.get(run=run)
        self.assertEqual(result.bucket, MatchResult.Bucket.COCOK)
        self.assertGreaterEqual(result.score, 85)

    def test_regresi_username_exact_match_tetap_skor_100(self):
        """Regresi: username sama persis dua sisi (dua-duanya berisi) tetap skor 100 cocok,
        clean_name tidak boleh menyentuh jalur username."""
        Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=self.lbs, jenis="depo",
            amount=Decimal("70000"), money_delta=Decimal("70000"),
            occurred_at=datetime(2026, 6, 27, 8, 0),
            username="sama_persis", counterparty="",
            row_hash="nc5",
        )
        Transaction.objects.create(
            upload=self.up, source_type=self.bank, toko=self.lbs, jenis="lainnya",
            amount=Decimal("70000"), money_delta=Decimal("70000"),
            occurred_at=datetime(2026, 6, 27, 8, 5),
            username="sama_persis", counterparty="",
            row_hash="nc6",
        )
        run = run_match("panel_bank", self.tol, user=None, toko=self.lbs, batch=self.batch)
        result = MatchResult.objects.get(run=run)
        self.assertEqual(result.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(result.score, 100)
