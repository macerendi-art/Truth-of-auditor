from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase

from reconciliation.engine import check_completeness, run_batch
from reconciliation.models import MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class ReconBatchModelTests(TestCase):
    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(name="Default", defaults={"date_window_days": 1})[0]
        self.lbs = Toko.objects.get(key="lbs")

    def test_batch_links_runs(self):
        batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        run = MatchRun.objects.create(relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=batch)
        self.assertEqual(list(batch.runs.all()), [run])
        self.assertEqual(str(batch), f"Batch #{batch.pk}")


class CompletenessTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _tx(self, st, jenis, money, rh):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.lbs, jenis=jenis,
            amount=Decimal("50000"), money_delta=Decimal(money),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash=rh,
        )

    def test_minimum_met_with_panel_and_bank(self):
        self._tx(self.panel, "depo", "50000", "c1")
        self._tx(self.bank, "depo", "50000", "c2")
        comp = check_completeness(self.lbs)
        self.assertTrue(comp["panel_dp"])
        self.assertTrue(comp["bank"])
        self.assertFalse(comp["bracket"])
        self.assertTrue(comp["minimum_met"])

    def test_minimum_not_met_panel_only(self):
        self._tx(self.panel, "depo", "50000", "c3")
        comp = check_completeness(self.lbs)
        self.assertFalse(comp["minimum_met"])


class TokoScopeTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.up = Upload.objects.create(source_type=self.panel)

    def test_completeness_isolated_per_toko(self):
        Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=self.lbs, jenis="depo",
            amount=Decimal("1"), money_delta=Decimal("1"),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash="lbs-only",
        )
        self.assertTrue(check_completeness(self.lbs)["panel_dp"])
        self.assertFalse(check_completeness(self.slo)["panel_dp"])


class RunBatchTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(name="Default", defaults={"date_window_days": 1})[0]
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

    def test_runs_both_relations_when_data_present(self):
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p1", username="budi")
        self._tx(self.bracket, "depo", "50000", "50000", "D1", "b1", username="budi")
        self._tx(self.bank, "depo", "50000", "50000", "", "k1", username="budi")
        batch = run_batch(self.lbs, self.tol)
        self.assertEqual(batch.runs.count(), 2)
        self.assertEqual(batch.summary["skipped"], [])
        self.assertEqual(batch.summary["dp"]["panel"], 50000.0)

    def test_skips_panel_bracket_when_no_bracket(self):
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p2", username="budi")
        self._tx(self.bank, "depo", "50000", "50000", "", "k2", username="budi")
        batch = run_batch(self.lbs, self.tol)
        self.assertEqual(batch.runs.count(), 1)
        self.assertIn("panel_bracket", batch.summary["skipped"])

    def test_summary_shape_matched_and_gross(self):
        # DP cocok (uang berpasangan) + DP uang bank tanpa padanan (gross saja).
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p10", username="budi")
        self._tx(self.bank, "depo", "50000", "50000", "", "k10", username="budi")
        self._tx(self.bank, "depo", "70000", "70000", "", "k11", username="nomatch")  # gross-only
        batch = run_batch(self.lbs, self.tol)
        dp = batch.summary["dp"]
        # Kunci baru hadir + backward-compat 'money'/'selisih'.
        for key in ("panel", "money_gross", "money_matched", "money", "selisih"):
            self.assertIn(key, dp)
        self.assertEqual(dp["money"], dp["money_matched"])
        self.assertEqual(dp["panel"], 50000.0)
        self.assertEqual(dp["money_matched"], 50000.0)  # hanya yang berpasangan
        self.assertEqual(dp["money_gross"], 120000.0)  # 50k + 70k
        self.assertEqual(dp["selisih"], dp["panel"] - dp["money_matched"])
        self.assertIn("warnings", batch.summary)
        self.assertEqual(batch.summary["warnings"], [])

    def test_wd_matched_selisih_and_dp_wd_not_swapped(self):
        # WD: panel keluar 30k, bank keluar 30k berpasangan -> selisih WD kecil.
        self._tx(self.panel, "wd", "30000", "-30000", "W1", "pw1", username="andi")
        self._tx(self.bank, "wd", "30000", "-30000", "", "kw1", username="andi")
        batch = run_batch(self.lbs, self.tol)
        wd = batch.summary["wd"]
        self.assertEqual(wd["panel"], 30000.0)
        self.assertEqual(wd["money_matched"], 30000.0)
        self.assertEqual(wd["selisih"], 0.0)
        # DP kosong -> tidak tercampur ke WD (arah tidak tertukar).
        self.assertEqual(batch.summary["dp"]["money_matched"], 0.0)

    def test_bca_fee_admin_excluded_from_wd_money(self):
        # Baris fee 'admin' tidak dihitung sebagai uang WD gross/matched.
        self._tx(self.panel, "wd", "30000", "-30000", "W2", "pw2", username="andi")
        self._tx(self.bank, "wd", "30000", "-30000", "", "kw2", username="andi")
        self._tx(self.bank, "admin", "2500", "-2500", "", "fee1", counterparty="andi")
        batch = run_batch(self.lbs, self.tol)
        wd = batch.summary["wd"]
        self.assertEqual(wd["money_gross"], 30000.0)  # 2.500 fee TIDAK masuk
        self.assertEqual(wd["money_matched"], 30000.0)

    def test_bracket_warning_fires_on_low_overlap(self):
        # Panel penuh (banyak tiket), bracket menyusut jadi 1 -> overlap << 0.10.
        for i in range(12):
            self._tx(self.panel, "depo", "10000", "10000", f"D{i}", f"pl{i}")
        self._tx(self.bracket, "depo", "10000", "10000", "D0", "bx0")  # cocok 1
        batch = run_batch(self.lbs, self.tol)
        self.assertTrue(batch.summary["warnings"])
        self.assertIn("Panel↔Bracket", batch.summary["warnings"][0])

    def test_bracket_warning_silent_when_healthy(self):
        for i in range(5):
            self._tx(self.panel, "depo", "10000", "10000", f"H{i}", f"hp{i}")
            self._tx(self.bracket, "depo", "10000", "10000", f"H{i}", f"hb{i}")
        batch = run_batch(self.lbs, self.tol)
        self.assertEqual(batch.summary["warnings"], [])


class T1SettlementTests(TestCase):
    """Bank settle T+1: Panel malam tgl 26, mutasi bank baru masuk statement tgl 27.
    Reconcile HARIAN (from=to=26) harus tetap lihat & cocokkan bank-27, atribusi ke 26,
    dan konsumsi bank-27 supaya tak double-match. Kandidat ganda → perlu ditinjau."""

    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol, _ = ToleranceProfile.objects.get_or_create(name="Default")
        self.tol.date_window_days = 1
        self.tol.fuzzy_threshold = 85
        self.tol.save()
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _tx(self, st, jenis, money, rh, day, **kw):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.lbs, jenis=jenis,
            amount=Decimal(abs(int(money))), money_delta=Decimal(money),
            occurred_at=datetime(2026, 6, day, 21, 0), row_hash=rh, **kw,
        )

    def _day26(self):
        return run_batch(self.lbs, self.tol, date_from=date(2026, 6, 26), date_to=date(2026, 6, 26))

    def test_t1_single_day_reconcile_runs_panel_bank(self):
        # Panel-26 ada, bank baru muncul di mutasi tgl 27; reconcile harian tgl 26
        # tetap harus MENJALANKAN relasi panel_bank (bukan skip karena bank "tak ada").
        self._tx(self.panel, "depo", "50000", "p26", 26, username="budi")
        self._tx(self.bank, "depo", "50000", "k27", 27, username="budi")
        batch = self._day26()
        self.assertNotIn("panel_bank", batch.summary["skipped"])

    def test_t1_selisih_zero_and_bank_consumed(self):
        self._tx(self.panel, "depo", "50000", "p26", 26, username="budi")
        bank = self._tx(self.bank, "depo", "50000", "k27", 27, username="budi")
        batch = self._day26()
        pb = batch.runs.get(relation=MatchRun.Relation.PANEL_BANK)
        self.assertEqual(pb.summary["cocok"], 1)
        self.assertEqual(batch.summary["dp"]["money_matched"], 50000.0)
        self.assertEqual(batch.summary["dp"]["selisih"], 0.0)
        bank.refresh_from_db()
        self.assertEqual(bank.consumed_by_batch_id, batch.id)

    def test_t1_ambiguous_two_candidates_review(self):
        self._tx(self.panel, "depo", "50000", "p26", 26, username="budi")
        b1 = self._tx(self.bank, "depo", "50000", "k27a", 27, username="budi")
        b2 = self._tx(self.bank, "depo", "50000", "k27b", 27, username="budi")
        batch = self._day26()
        pb = batch.runs.get(relation=MatchRun.Relation.PANEL_BANK)
        self.assertEqual(pb.summary["cocok"], 0)
        self.assertEqual(pb.summary["perlu_tinjau"], 1)
        res = pb.results.get()
        self.assertEqual(res.reason_code, "ambiguous_multi")
        self.assertIsNone(res.right_id)
        b1.refresh_from_db()
        b2.refresh_from_db()
        self.assertIsNone(b1.consumed_by_batch_id)
        self.assertIsNone(b2.consumed_by_batch_id)
        self.assertEqual(batch.summary["dp"]["money_matched"], 0.0)

    def test_t1_single_best_candidate_matches(self):
        # Dua bank beda nama: hanya satu cocok nama → bukan ambigu, tetap COCOK.
        self._tx(self.panel, "depo", "50000", "p26", 26, username="budi")
        self._tx(self.bank, "depo", "50000", "k27a", 27, username="budi")
        self._tx(self.bank, "depo", "50000", "k27b", 27, username="siti")
        batch = self._day26()
        pb = batch.runs.get(relation=MatchRun.Relation.PANEL_BANK)
        self.assertEqual(pb.summary["cocok"], 1)
        self.assertEqual(pb.summary["perlu_tinjau"], 0)

    def test_t1_weak_name_still_review(self):
        # Satu kandidat, nama lemah, tanpa username → tetap weak_name (bukan ambiguous_multi).
        self._tx(self.panel, "depo", "50000", "p26", 26, counterparty="BUDI SANTOSO")
        self._tx(self.bank, "depo", "50000", "k27", 27, counterparty="XYZ RANDOM")
        batch = self._day26()
        pb = batch.runs.get(relation=MatchRun.Relation.PANEL_BANK)
        res = pb.results.get()
        self.assertEqual(res.reason_code, "weak_name")
        self.assertEqual(pb.summary["perlu_tinjau"], 1)
