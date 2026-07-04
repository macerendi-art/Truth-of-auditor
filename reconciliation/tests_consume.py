"""TASK 5 — konsumsi dataset saat sukses (5a) + toggle sertakan sumber (5b)."""
from datetime import datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from reconciliation import engine
from reconciliation.engine import check_completeness, run_batch
from reconciliation.models import MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class _Base(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bracket = SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.gateway = SourceType.objects.get_or_create(key="gateway", defaults={"name": "Gateway"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _tx(self, st, jenis, amount, money, ticket, rh, **kw):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.lbs, jenis=jenis,
            amount=Decimal(amount), money_delta=Decimal(money), ticket_no=ticket,
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash=rh, **kw,
        )


class ConsumeOnSuccessTests(_Base):
    def _simple_data(self):
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p1", username="budi")
        self._tx(self.bank, "depo", "50000", "50000", "", "k1", username="budi")

    def test_success_consumes_and_completeness_empties(self):
        self._simple_data()
        self.assertTrue(check_completeness(self.lbs)["minimum_met"])
        batch = run_batch(self.lbs, self.tol)
        # Semua transaksi dalam lingkup terkunci ke batch ini.
        self.assertEqual(
            Transaction.objects.filter(consumed_by_batch=batch).count(), 2
        )
        comp = check_completeness(self.lbs)
        self.assertFalse(comp["panel_dp"])
        self.assertFalse(comp["bank"])
        self.assertFalse(comp["minimum_met"])

    def test_second_run_without_upload_does_nothing_meaningful(self):
        self._simple_data()
        run_batch(self.lbs, self.tol)
        batch2 = run_batch(self.lbs, self.tol)
        # Tidak ada transaksi aktif → tidak ada relasi dijalankan.
        self.assertEqual(batch2.runs.count(), 0)
        self.assertIn("panel_bracket", batch2.summary["skipped"])
        self.assertIn("panel_bank", batch2.summary["skipped"])

    def test_consumed_excluded_from_matching(self):
        # Batch 1 mengonsumsi. Upload baru → hanya baris baru yang dicocokkan.
        self._simple_data()
        run_batch(self.lbs, self.tol)
        self._tx(self.panel, "depo", "70000", "70000", "D2", "p2", username="siti")
        self._tx(self.bank, "depo", "70000", "70000", "", "k2", username="siti")
        batch2 = run_batch(self.lbs, self.tol)
        self.assertEqual(batch2.summary["dp"]["panel"], 70000.0)  # bukan 120k
        self.assertEqual(batch2.summary["dp"]["money_matched"], 70000.0)

    def test_failure_does_not_consume(self):
        self._simple_data()
        with mock.patch.object(
            engine, "_aggregate_batch", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                run_batch(self.lbs, self.tol)
        # Gagal → tidak ada yang dikonsumsi, kelengkapan tetap utuh.
        self.assertEqual(Transaction.objects.filter(consumed_by_batch__isnull=False).count(), 0)
        self.assertTrue(check_completeness(self.lbs)["minimum_met"])

    def test_delete_batch_frees_transactions(self):
        self._simple_data()
        batch = run_batch(self.lbs, self.tol)
        self.assertFalse(check_completeness(self.lbs)["minimum_met"])
        ReconBatch.objects.filter(pk=batch.pk).delete()
        # SET_NULL → transaksi bebas lagi (utuh), kelengkapan pulih.
        self.assertEqual(Transaction.objects.filter(consumed_by_batch__isnull=False).count(), 0)
        self.assertTrue(check_completeness(self.lbs)["minimum_met"])


class IncludeToggleTests(_Base):
    def test_default_all_included_matches_current(self):
        # include=None (default) identik dengan perilaku hari ini.
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p1", username="budi")
        self._tx(self.bracket, "depo", "50000", "50000", "D1", "b1", username="budi")
        self._tx(self.bank, "depo", "50000", "50000", "", "k1", username="budi")
        batch = run_batch(self.lbs, self.tol)
        self.assertEqual(batch.runs.count(), 2)
        self.assertEqual(batch.summary["skipped"], [])

    def test_unchecked_source_not_matched_and_not_consumed(self):
        # Bank hadir tapi TIDAK dicentang → tidak dicocokkan & tidak dikonsumsi.
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p1", username="budi")
        self._tx(self.bank, "depo", "50000", "50000", "", "k1", username="budi")
        include = {"panel_dp": True, "panel_wd": True, "bracket": False,
                   "bank": False, "gateway": False}
        batch = run_batch(self.lbs, self.tol, include=include)
        # Tak ada sumber uang dicentang → PANEL_BANK dilewati.
        self.assertIn("panel_bank", batch.summary["skipped"])
        # Bank tidak dikonsumsi → masih ada di kelengkapan.
        bank_tx = Transaction.objects.get(row_hash="k1")
        self.assertIsNone(bank_tx.consumed_by_batch)
        self.assertTrue(check_completeness(self.lbs)["bank"])
        # Panel dicentang & dikonsumsi.
        panel_tx = Transaction.objects.get(row_hash="p1")
        self.assertEqual(panel_tx.consumed_by_batch, batch)

    def test_gateway_only_excludes_bank_from_money(self):
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p1", username="budi")
        self._tx(self.panel, "depo", "60000", "60000", "D2", "p2", username="andi")
        self._tx(self.bank, "depo", "50000", "50000", "", "k1", username="budi")
        self._tx(self.gateway, "depo", "60000", "60000", "", "g1", username="andi")
        include = {"panel_dp": True, "panel_wd": True, "bracket": False,
                   "bank": False, "gateway": True}
        batch = run_batch(self.lbs, self.tol, include=include)
        # Hanya gateway ikut → gross uang = 60k (bukan 110k).
        self.assertEqual(batch.summary["dp"]["money_gross"], 60000.0)
        # Bank tidak dikonsumsi (tidak dicentang).
        self.assertIsNone(Transaction.objects.get(row_hash="k1").consumed_by_batch)
        self.assertEqual(Transaction.objects.get(row_hash="g1").consumed_by_batch, batch)

    def test_panel_wd_unchecked_excluded(self):
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p1", username="budi")
        self._tx(self.panel, "wd", "30000", "-30000", "W1", "pw1", username="andi")
        self._tx(self.bank, "depo", "50000", "50000", "", "k1", username="budi")
        include = {"panel_dp": True, "panel_wd": False, "bracket": False,
                   "bank": True, "gateway": False}
        batch = run_batch(self.lbs, self.tol, include=include)
        # WD panel tidak dicentang → tidak masuk total & tidak dikonsumsi.
        self.assertEqual(batch.summary["wd"]["panel"], 0.0)
        self.assertIsNone(Transaction.objects.get(row_hash="pw1").consumed_by_batch)
