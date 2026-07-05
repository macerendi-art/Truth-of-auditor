"""TASK 5 UI — checkbox sertakan (5b), tampilan gross/matched + warning (5c)."""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.engine import run_batch
from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class _LoggedIn(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.lbs = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bracket = SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _tx(self, st, jenis, amount, money, ticket, rh, **kw):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.lbs, jenis=jenis,
            amount=Decimal(amount), money_delta=Decimal(money), ticket_no=ticket,
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash=rh, **kw,
        )


class ReconcileCheckboxTests(_LoggedIn):
    def test_present_source_checkbox_checked(self):
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p1")
        self._tx(self.bank, "depo", "50000", "50000", "", "k1")
        r = self.client.get(reverse("reconcile"))
        html = r.content.decode()
        self.assertIn('name="inc_panel_dp"', html)
        self.assertIn('name="inc_bank"', html)
        # Bracket kosong → checkbox TETAP enabled+checked (badge yang bilang kosong).
        # Disabled = tak ikut POST; kalau user ganti tanggal di form, sumber hilang
        # diam-diam dari batch (bug batch-16 K25). Engine yang melewati relasi
        # bila sumber benar-benar kosong pada tanggal yang disubmit.
        self.assertRegex(html, r'name="inc_bracket"[^>]*checked')
        self.assertNotRegex(html, r'name="inc_bracket"[^>]*disabled')

    def test_post_with_unchecked_bank_not_consumed(self):
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p1")
        self._tx(self.bank, "depo", "50000", "50000", "", "k1")
        # Kirim hanya panel_dp dicentang (bank tidak).
        self.client.post(reverse("reconcile"), {
            "tolerance": "Default", "inc_panel_dp": "on",
        })
        bank_tx = Transaction.objects.get(row_hash="k1")
        self.assertIsNone(bank_tx.consumed_by_batch)
        panel_tx = Transaction.objects.get(row_hash="p1")
        self.assertIsNotNone(panel_tx.consumed_by_batch)

    def test_post_all_checked_consumes_all(self):
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p1", username="budi")
        self._tx(self.bank, "depo", "50000", "50000", "", "k1", username="budi")
        self.client.post(reverse("reconcile"), {
            "tolerance": "Default",
            "inc_panel_dp": "on", "inc_panel_wd": "on",
            "inc_bracket": "on", "inc_bank": "on", "inc_gateway": "on",
        })
        self.assertEqual(Transaction.objects.filter(consumed_by_batch__isnull=False).count(), 2)


class BatchDetailDisplayTests(_LoggedIn):
    def test_shows_gross_and_matched(self):
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p1", username="budi")
        self._tx(self.bank, "depo", "50000", "50000", "", "k1", username="budi")
        self._tx(self.bank, "depo", "70000", "70000", "", "k2", username="nomatch")
        batch = run_batch(self.lbs, self.tol)
        r = self.client.get(reverse("batch_detail", args=[batch.pk]))
        html = r.content.decode()
        self.assertIn("Uang real (matched)", html)
        self.assertIn("Uang real (gross)", html)

    def test_warning_banner_renders(self):
        for i in range(12):
            self._tx(self.panel, "depo", "10000", "10000", f"D{i}", f"pl{i}")
        self._tx(self.bracket, "depo", "10000", "10000", "D0", "bx0")
        batch = run_batch(self.lbs, self.tol)
        self.assertTrue(batch.summary["warnings"])
        r = self.client.get(reverse("batch_detail", args=[batch.pk]))
        self.assertContains(r, "Panel↔Bracket")

    def test_old_batch_without_new_keys_still_renders(self):
        # Batch lama: summary hanya punya 'money'/'selisih' (tanpa gross/matched).
        batch = ReconBatch.objects.create(
            toko=self.lbs, tolerance=self.tol,
            summary={
                "dp": {"panel": 50000, "money": 50000, "selisih": 0},
                "wd": {"panel": 0, "money": 0, "selisih": 0},
                "buckets": {"cocok": 0, "perlu_tinjau": 0, "tidak_cocok": 0},
                "skipped": [],
            },
        )
        r = self.client.get(reverse("batch_detail", args=[batch.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Uang real (matched)")


class RiwayatColumnTests(_LoggedIn):
    def test_dp_wd_headers_right_aligned(self):
        r = self.client.get(reverse("reconcile"))
        html = r.content.decode()
        self.assertIn('<th class="num">DP selisih</th>', html)
        self.assertIn('<th class="num">WD selisih</th>', html)
