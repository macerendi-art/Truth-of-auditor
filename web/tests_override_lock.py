"""Bug: review manual (manual_override) tak mengunci baris → run tanggal berikutnya
memperlakukan baris itu sebagai SUSULAN dan menulis hasil tidak_cocok duplikat yang
menimpa override (klien: "yang sudah dicek manual jadi cocok, balik lagi begitu
tanggal berikutnya dimasukkan"). Fix: konsumsi baris ke batch asal saat di-override.
"""
from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from reconciliation.engine import run_batch
from reconciliation.models import MatchResult, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class OverrideLockTests(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1})[0]
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.toko)
        self.user = User.objects.create_user(
            username="rev", password="x", role="admin", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)

    def _panel_wd(self, ticket, rh, dt):
        return Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=self.toko, jenis="wd",
            amount=Decimal("50000"), money_delta=Decimal("-50000"), credit_delta=Decimal("50000"),
            ticket_no=ticket, username="budi", counterparty="BUDI SANTOSO", occurred_at=dt, row_hash=rh)

    def _bank_lain(self, rh):
        # Uang lain (identitas & nominal beda) supaya sumber bank "ada" tapi tak match.
        return Transaction.objects.create(
            upload=self.up, source_type=self.bank, toko=self.toko, jenis="wd",
            amount=Decimal("70000"), money_delta=Decimal("-70000"),
            counterparty="SITI AMINAH", occurred_at=datetime(2026, 6, 27, 22, 0), row_hash=rh)

    def _no_money_result(self, batch, p):
        return MatchResult.objects.get(
            run__batch=batch, left=p, run__relation="panel_bank")

    def _override(self, result, action="mark_matched"):
        return self.client.post(reverse("review", args=[result.pk]), {"action": action})

    def test_override_mengunci_baris(self):
        p = self._panel_wd("W1", "p1", datetime(2026, 6, 27, 23, 0))
        self._bank_lain("k1")
        batch = run_batch(self.toko, self.tol, recon_date=date(2026, 6, 27))
        r = self._no_money_result(batch, p)
        self.assertEqual(r.reason_code, "no_money")
        p.refresh_from_db()
        self.assertIsNone(p.consumed_by_batch)  # sebelum override: menunggu settlement
        resp = self._override(r)
        self.assertIn(resp.status_code, (200, 302))
        r.refresh_from_db()
        p.refresh_from_db()
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(p.consumed_by_batch, batch)  # FIX: terkunci ke batch asal

    def test_tak_ada_duplikat_hari_berikutnya(self):
        # INTI reproduksi: override hari D, lalu run D+1 → tak boleh muncul hasil
        # susulan duplikat, dan override harus TETAP cocok.
        p = self._panel_wd("W1", "p1", datetime(2026, 6, 27, 23, 0))
        self._bank_lain("k1")
        batch = run_batch(self.toko, self.tol, recon_date=date(2026, 6, 27))
        r = self._no_money_result(batch, p)
        self._override(r)
        run_batch(self.toko, self.tol, recon_date=date(2026, 6, 28))
        results = MatchResult.objects.filter(left=p, run__relation="panel_bank")
        self.assertEqual(results.count(), 1, "hasil susulan duplikat muncul (bug belum tertutup)")
        self.assertEqual(results.first().bucket, MatchResult.Bucket.COCOK,
                         "override ter-revert oleh susulan")

    def test_non_override_tetap_carry(self):
        # GUARD: baris no_money yang TIDAK di-review manual TIDAK ikut terkunci —
        # tetap aktif menunggu settlement (fix hanya mengunci yang di-override).
        p = self._panel_wd("W2", "p2", datetime(2026, 6, 27, 23, 0))
        self._bank_lain("k2")
        batch = run_batch(self.toko, self.tol, recon_date=date(2026, 6, 27))
        r = self._no_money_result(batch, p)
        self.assertEqual(r.reason_code, "no_money")
        p.refresh_from_db()
        self.assertIsNone(p.consumed_by_batch)  # tak dikunci: belum di-review
