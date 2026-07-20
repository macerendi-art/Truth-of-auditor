"""Paket H — WD dengan biaya transfer MENEMPEL di mutasi (fee-glued).

Kasus nyata LBS 19/07/2026: panel WD 400.000 a.n. "UMAR MANAP NASUTION",
mutasi BCA mendebit 406.500 satu baris ("TRF UMAR MANAP NASUTIO… SWITCHING DB")
— 400.000 + 6.500 biaya antarbank. Pass 2 lama bertoleransi max(2500, amt//100)
= 4.000 untuk nominal 400rb → kandidat tak pernah terlihat → no_money palsu.

Aturan anchor TIDAK dilonggarkan: identitas tetap gerbang (persis=100 → cocok,
fuzzy ≥ threshold → perlu_tinjau, nama beda → tetap no_money).
"""
from datetime import datetime
from decimal import Decimal

from django.test import TestCase

from reconciliation.engine import run_batch
from reconciliation.models import MatchResult, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class FeeGluedWDTests(TestCase):
    def setUp(self):
        ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1})
        self.toko = Toko.objects.get(key="lbs")
        self.panel_st = SourceType.objects.get_or_create(
            key="panel", defaults={"name": "Panel"})[0]
        self.bank_st = SourceType.objects.get_or_create(
            key="bank", defaults={"name": "Bank"})[0]
        self.up_p = Upload.objects.create(source_type=self.panel_st, toko=self.toko)
        self.up_b = Upload.objects.create(source_type=self.bank_st, toko=self.toko)

    def _panel_wd(self, amount, name, rh):
        return Transaction.objects.create(
            upload=self.up_p, source_type=self.panel_st, toko=self.toko,
            jenis="wd", amount=Decimal(amount),
            money_delta=Decimal(-amount), credit_delta=Decimal(amount),
            counterparty=name, occurred_at=datetime(2026, 7, 19, 20, 31),
            row_hash=rh,
        )

    def _bank_wd(self, amount, name, rh):
        return Transaction.objects.create(
            upload=self.up_b, source_type=self.bank_st, toko=self.toko,
            jenis="wd", money_delta=Decimal(-amount),
            counterparty=name, occurred_at=datetime(2026, 7, 19, 23, 0),
            row_hash=rh,
        )

    def _hasil(self, panel_row):
        run_batch(self.toko)
        return MatchResult.objects.get(left=panel_row)

    def test_fee_6500_identitas_persis_cocok(self):
        p = self._panel_wd(400000, "UMAR MANAP NASUTION", "p1")
        self._bank_wd(406500, "UMAR MANAP NASUTION", "b1")
        r = self._hasil(p)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.reason_code, "amount_fee")

    def test_fee_6500_nama_terpotong_persis_cocok(self):
        # Nama terpotong PDF BCA ("NASUTIO") = identik by-design (_name_score
        # prefix → 100, lihat docstring-nya) → tetap COCOK.
        p = self._panel_wd(400000, "UMAR MANAP NASUTION", "p1")
        self._bank_wd(406500, "UMAR MANAP NASUTIO", "b1")
        r = self._hasil(p)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.reason_code, "amount_fee")

    def test_fee_6500_nama_typo_tinjau(self):
        # Keterangan mutasi riil menulis "MANAF" (typo/potongan beda huruf) →
        # skor ~94 (fuzzy, bukan identik) → wajib mata manusia: perlu_tinjau.
        p = self._panel_wd(400000, "UMAR MANAP NASUTION", "p1")
        self._bank_wd(406500, "UMAR MANAF NASUTIO", "b1")
        r = self._hasil(p)
        self.assertEqual(r.bucket, MatchResult.Bucket.TINJAU)
        self.assertEqual(r.reason_code, "amount_fee")

    def test_fee_6500_nama_beda_tetap_no_money(self):
        p = self._panel_wd(400000, "UMAR MANAP NASUTION", "p1")
        self._bank_wd(406500, "BUDI SANTOSO", "b1")
        r = self._hasil(p)
        self.assertEqual(r.bucket, MatchResult.Bucket.TIDAK)
        self.assertEqual(r.reason_code, "no_money")

    def test_selisih_di_luar_toleransi_no_money(self):
        # 7.500 bukan konstanta biaya dikenal (> 6.500 dan > 1% nominal).
        p = self._panel_wd(400000, "UMAR MANAP NASUTION", "p1")
        self._bank_wd(407500, "UMAR MANAP NASUTION", "b1")
        r = self._hasil(p)
        self.assertEqual(r.bucket, MatchResult.Bucket.TIDAK)
        self.assertEqual(r.reason_code, "no_money")
