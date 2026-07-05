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

    def test_t1_ambiguous_distinct_identity_review(self):
        # Ambigu SEJATI: 2 kandidat nominal+tanggal seri di skor tertinggi TAPI
        # IDENTITAS BERBEDA (nama sama, akun beda) — tak bisa dipastikan mana
        # pasangannya → perlu ditinjau, tak satupun dikonsumsi (auditor pilih).
        self._tx(self.panel, "depo", "50000", "p26", 26, counterparty="BUDI SANTOSO")
        b1 = self._tx(self.bank, "depo", "50000", "k27a", 27, counterparty="BUDI SANTOSO", username="acc1")
        b2 = self._tx(self.bank, "depo", "50000", "k27b", 27, counterparty="BUDI SANTOSO", username="acc2")
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

    def test_t1_repeat_same_user_pairs_not_review(self):
        # BUG asli (QRIS): 1 player deposit nominal bulat berkali-kali dalam window.
        # N baris Panel + N baris bank dgn username SAMA BUKAN ambigu — identitas
        # pasti & uang identik, jadi PASANGKAN greedy 1-1 (COCOK), jangan banjir
        # perlu-ditinjau. Sebelumnya semua ke-flag ambiguous_multi (skor 100).
        self._tx(self.panel, "depo", "50000", "p26a", 26, username="nono1989")
        self._tx(self.panel, "depo", "50000", "p26b", 26, username="nono1989")
        b1 = self._tx(self.bank, "depo", "50000", "k27a", 27, username="nono1989")
        b2 = self._tx(self.bank, "depo", "50000", "k27b", 27, username="nono1989")
        batch = self._day26()
        pb = batch.runs.get(relation=MatchRun.Relation.PANEL_BANK)
        self.assertEqual(pb.summary["cocok"], 2)
        self.assertEqual(pb.summary["perlu_tinjau"], 0)
        b1.refresh_from_db()
        b2.refresh_from_db()
        self.assertEqual(b1.consumed_by_batch_id, batch.id)
        self.assertEqual(b2.consumed_by_batch_id, batch.id)
        self.assertEqual(batch.summary["dp"]["money_matched"], 100000.0)

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
        self._tx(self.bank, "depo", "50000", "k27", 27, counterparty="BUDI S")
        batch = self._day26()
        pb = batch.runs.get(relation=MatchRun.Relation.PANEL_BANK)
        res = pb.results.get()
        self.assertEqual(res.reason_code, "weak_name")
        self.assertEqual(pb.summary["perlu_tinjau"], 1)


class GatewayTicketMatchTests(TestCase):
    """QR gateway punya TXN ID immutable (ticket_no `D…`) yang == panel.ticket_no.
    Match QR via kunci eksak (bukan fuzzy) — kebal T+1, kebal deposit berulang.
    Bank tetap fuzzy (tak punya ticket). Waterfall: gateway dulu, sisanya ke bank."""

    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(name="Default")[0]
        self.tol.date_window_days = 1
        self.tol.fuzzy_threshold = 85
        self.tol.save()
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.gw = SourceType.objects.get_or_create(key="gateway", defaults={"name": "Gateway"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _tx(self, st, jenis, money, rh, day=27, status=None, **kw):
        raw = dict(kw.pop("raw", {}))
        if status is not None:
            raw["Payment Status"] = status
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.lbs, jenis=jenis,
            amount=Decimal(abs(int(money))), money_delta=Decimal(money),
            occurred_at=datetime(2026, 6, day, 21, 0), row_hash=rh, raw=raw, **kw,
        )

    def _run(self):
        return run_batch(self.lbs, self.tol)  # from=to=None → seluruh rentang

    def _pb(self, batch):
        return batch.runs.get(relation=MatchRun.Relation.PANEL_BANK)

    def test_gateway_ticket_exact_match(self):
        # Ticket sama → COCOK walau username beda (kunci eksak kalahkan fuzzy).
        self._tx(self.panel, "depo", "50000", "p1", ticket_no="D1758731", username="playerA")
        self._tx(self.gw, "depo", "50000", "g1", ticket_no="D1758731", status="PAID", username="beda")
        b = self._run()
        r = self._pb(b).results.get(left__isnull=False)
        self.assertEqual(r.bucket, "cocok")
        self.assertEqual(r.reason_code, "gateway_ticket")
        self.assertEqual(b.summary["dp"]["money_matched"], 50000.0)

    def test_gateway_reference_fallback(self):
        # Ticket tak ketemu, Client Reference ketemu → COCOK gateway_reference.
        self._tx(self.panel, "depo", "50000", "p1", ticket_no="D999", reference="D2606001")
        self._tx(self.gw, "depo", "50000", "g1", ticket_no="UUID-abc", reference="D2606001", status="PAID")
        r = self._pb(self._run()).results.get(left__isnull=False)
        self.assertEqual(r.reason_code, "gateway_reference")
        self.assertEqual(r.bucket, "cocok")

    def test_repeat_same_user_all_matched_by_ticket(self):
        # BUG asli QRIS: 1 player deposit nominal bulat berkali. Dgn ticket unik → semua
        # COCOK, NOL ambigu (ticket bedakan tiap deposit walau username+nominal sama).
        for i in range(3):
            self._tx(self.panel, "depo", "20000", f"p{i}", ticket_no=f"D100{i}", username="nono")
            self._tx(self.gw, "depo", "20000", f"g{i}", ticket_no=f"D100{i}", status="PAID", username="nono")
        pb = self._pb(self._run())
        self.assertEqual(pb.summary["cocok"], 3)
        self.assertEqual(pb.summary["perlu_tinjau"], 0)

    def test_gateway_unpaid_becomes_discrepancy(self):
        # Ticket ADA tapi QR UNPAID → uang tak masuk → tidak_cocok gateway_unpaid, tak dihitung.
        self._tx(self.panel, "depo", "50000", "p1", ticket_no="D1", username="a")
        self._tx(self.gw, "depo", "50000", "g1", ticket_no="D1", status="UNPAID", username="a")
        b = self._run()
        r = self._pb(b).results.get(left__isnull=False)
        self.assertEqual(r.bucket, "tidak_cocok")
        self.assertEqual(r.reason_code, "gateway_unpaid")
        self.assertEqual(b.summary["dp"]["money_matched"], 0.0)

    def test_unpaid_panel_does_not_fall_to_bank(self):
        # Panel yang ticketnya cuma ada sbg UNPAID → JANGAN nyasar match ke bank sewarna.
        self._tx(self.panel, "depo", "50000", "p1", ticket_no="D1", username="a", counterparty="BUDI")
        self._tx(self.gw, "depo", "50000", "g1", ticket_no="D1", status="UNPAID", username="a")
        self._tx(self.bank, "depo", "50000", "kb", counterparty="BUDI")
        b = self._run()
        pb = self._pb(b)
        self.assertEqual(pb.results.get(left__isnull=False).reason_code, "gateway_unpaid")
        self.assertFalse(pb.results.filter(left__row_hash="p1", right__isnull=False).exists())
        self.assertEqual(b.summary["dp"]["money_matched"], 0.0)

    def test_gateway_amount_mismatch_terminal(self):
        # Ticket cocok tapi NOMINAL beda → gateway_amount_mismatch, TERMINAL (tak jatuh ke bank).
        self._tx(self.panel, "depo", "50000", "p1", ticket_no="D1", username="a", counterparty="BUDI")
        self._tx(self.gw, "depo", "40000", "g1", ticket_no="D1", status="PAID", username="a")
        self._tx(self.bank, "depo", "50000", "kb", counterparty="BUDI")
        pb = self._pb(self._run())
        r = pb.results.get(left__isnull=False)
        self.assertEqual(r.reason_code, "gateway_amount_mismatch")
        self.assertEqual(r.bucket, "perlu_tinjau")
        self.assertFalse(pb.results.filter(right__row_hash="kb", bucket="cocok").exists())

    def test_bank_fuzzy_when_no_gateway_ticket(self):
        # Panel tanpa padanan gateway → pass 2 bank fuzzy tetap jalan.
        self._tx(self.panel, "depo", "50000", "p1", ticket_no="Dxxx", username="budi")
        self._tx(self.bank, "depo", "50000", "kb", username="budi")
        r = self._pb(self._run()).results.get(left__isnull=False)
        self.assertEqual(r.bucket, "cocok")
        self.assertEqual(r.reason_code, "amount+date+name")

    def test_gateway_ticket_no_double_count_with_bank(self):
        # Panel match gateway by ticket; bank sewarna JANGAN ikut dihitung (no double count).
        self._tx(self.panel, "depo", "50000", "p1", ticket_no="D1", username="budi")
        self._tx(self.gw, "depo", "50000", "g1", ticket_no="D1", status="PAID", username="budi")
        self._tx(self.bank, "depo", "50000", "kb", username="budi")
        b = self._run()
        pb = self._pb(b)
        self.assertEqual(b.summary["dp"]["money_matched"], 50000.0)  # sekali, bukan 100000
        self.assertFalse(pb.results.filter(right__row_hash="kb", bucket="cocok").exists())

    def test_unmatched_settled_gateway_flagged(self):
        # Uang QR settle (PAID) tanpa deposit Panel → tidak_cocok gateway_no_panel.
        self._tx(self.panel, "depo", "50000", "p1", ticket_no="D1", username="a")
        self._tx(self.gw, "depo", "50000", "g1", ticket_no="D1", status="PAID", username="a")
        self._tx(self.gw, "depo", "77000", "g2", ticket_no="D2", status="PAID", username="b")
        pb = self._pb(self._run())
        r = pb.results.get(right__row_hash="g2")
        self.assertIsNone(r.left_id)
        self.assertEqual(r.bucket, "tidak_cocok")
        self.assertEqual(r.reason_code, "gateway_no_panel")

    def test_unmatched_unpaid_gateway_not_flagged(self):
        # Orphan UNPAID gateway BUKAN discrepancy uang (uang tak pernah masuk) → tak di-emit.
        self._tx(self.panel, "depo", "50000", "p1", ticket_no="D1", username="a")
        self._tx(self.gw, "depo", "50000", "g1", ticket_no="D1", status="PAID", username="a")
        self._tx(self.gw, "depo", "99000", "g2", ticket_no="UUIDX", status="UNPAID", username="z")
        pb = self._pb(self._run())
        self.assertFalse(pb.results.filter(right__row_hash="g2").exists())

    def test_money_gross_excludes_unpaid(self):
        # money_gross hanya uang yang settle — UNPAID tak menggelembungkan gross.
        self._tx(self.panel, "depo", "50000", "p1", ticket_no="D1", username="a")
        self._tx(self.gw, "depo", "50000", "g1", ticket_no="D1", status="PAID", username="a")
        self._tx(self.gw, "depo", "88000", "g2", ticket_no="UUIDY", status="UNPAID", username="z")
        b = self._run()
        self.assertEqual(b.summary["dp"]["money_gross"], 50000.0)


class WdDestKeyTests(TestCase):
    """WD dicocokkan via NOMOR TUJUAN (HP e-wallet / norek) sebagai kunci kuat —
    analog TXN ID gateway. Nama boleh kosong/lemah: kalau dest cocok -> COCOK
    (reason bank_dest). Dest beda -> tetap weak_name. Nomor sama utk 2 player = tetap
    dua-duanya COCOK (identitas pasti, bukan ambigu)."""

    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol, _ = ToleranceProfile.objects.get_or_create(name="Default")
        self.tol.date_window_days = 1
        self.tol.fuzzy_threshold = 85
        self.tol.save()
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _tx(self, st, jenis, money, rh, day=27, **kw):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.lbs, jenis=jenis,
            amount=Decimal(abs(int(money))), money_delta=Decimal(money),
            occurred_at=datetime(2026, 6, day, 21, 0), row_hash=rh, **kw,
        )

    def _pb(self, batch):
        return batch.runs.get(relation=MatchRun.Relation.PANEL_BANK)

    def _run(self):
        return run_batch(self.lbs, self.tol)

    def test_wd_dest_match_no_name_cocok(self):
        # (a) Panel WD + bank WD dest sama, NAMA KOSONG kedua sisi -> COCOK bank_dest.
        self._tx(self.panel, "wd", "-50000", "p1", dest_account="81917710481", counterparty="", username="")
        self._tx(self.bank, "wd", "-50000", "kb", dest_account="81917710481", counterparty="", username="")
        pb = self._pb(self._run())
        r = pb.results.get(left__isnull=False)
        self.assertEqual(r.bucket, "cocok")
        self.assertEqual(r.reason_code, "bank_dest")
        self.assertEqual(r.score, 100)

    def test_wd_dest_beda_tetap_weak_name(self):
        # (b) dest beda + nama tak cocok -> tetap weak_name (tak diselamatkan dest).
        self._tx(self.panel, "wd", "-50000", "p1", dest_account="81917710481", counterparty="BUDI SANTOSO")
        self._tx(self.bank, "wd", "-50000", "kb", dest_account="99900011122", counterparty="BUDI S")
        pb = self._pb(self._run())
        r = pb.results.get(left__isnull=False)
        self.assertEqual(r.bucket, "perlu_tinjau")
        self.assertEqual(r.reason_code, "weak_name")

    def test_wd_dest_match_menang_atas_nama(self):
        # (c-var) dest ternormalisasi cocok walau panel simpan '0' depan & bank buang.
        self._tx(self.panel, "wd", "-50000", "p1", dest_account="81917710481", counterparty="A")
        self._tx(self.bank, "wd", "-50000", "kb", dest_account="81917710481", counterparty="Z")
        pb = self._pb(self._run())
        r = pb.results.get(left__isnull=False)
        self.assertEqual(r.bucket, "cocok")
        self.assertEqual(r.reason_code, "bank_dest")

    def test_wd_dua_player_dest_sama_dua_cocok(self):
        # (f) dua Panel WD player beda, nominal sama, dua bank dest SAMA nomor ->
        # dua-duanya COCOK bank_dest (nomor sama = identitas sama, BUKAN ambigu).
        self._tx(self.panel, "wd", "-50000", "p1", dest_account="81917710481", counterparty="", username="ariii25")
        self._tx(self.panel, "wd", "-50000", "p2", dest_account="81917710481", counterparty="", username="jarottt25")
        self._tx(self.bank, "wd", "-50000", "kb1", dest_account="81917710481", counterparty="")
        self._tx(self.bank, "wd", "-50000", "kb2", dest_account="81917710481", counterparty="")
        pb = self._pb(self._run())
        self.assertEqual(pb.summary["cocok"], 2)
        self.assertEqual(pb.summary["perlu_tinjau"], 0)
        for r in pb.results.filter(left__isnull=False):
            self.assertEqual(r.reason_code, "bank_dest")

    def test_dp_name_match_still_amount_date_name(self):
        # Tanpa dest (atau dest tak dipakai): DP nama cocok tetap reason lama.
        self._tx(self.panel, "depo", "50000", "p1", username="budi")
        self._tx(self.bank, "depo", "50000", "kb", username="budi")
        pb = self._pb(self._run())
        r = pb.results.get(left__isnull=False)
        self.assertEqual(r.bucket, "cocok")
        self.assertEqual(r.reason_code, "amount+date+name")

    def test_wd_dest_only_one_side_falls_back_to_name(self):
        # Panel punya dest, bank tak punya dest (transfer nama saja) tapi NAMA cocok
        # -> tetap COCOK lewat jalur nama (reason amount+date+name), bukan bank_dest.
        self._tx(self.panel, "wd", "-50000", "p1", dest_account="81917710481", counterparty="BUDI SANTOSO")
        self._tx(self.bank, "wd", "-50000", "kb", dest_account="", counterparty="BUDI SANTOSO")
        pb = self._pb(self._run())
        r = pb.results.get(left__isnull=False)
        self.assertEqual(r.bucket, "cocok")
        self.assertEqual(r.reason_code, "amount+date+name")


class StringDateTests(TestCase):
    """Regresi: web POST /reconcile/ mengirim tanggal sebagai STRING 'YYYY-MM-DD'
    (bukan objek date) — _widen_dto pernah crash 'str + timedelta'. run_batch &
    run_match wajib menerima keduanya."""

    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol, _ = ToleranceProfile.objects.get_or_create(name="Default")
        self.tol.date_window_days = 1
        self.tol.save()
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        up = Upload.objects.create(source_type=self.panel, toko=self.lbs)
        for st, jenis, money, rh, day in [
            (self.panel, "depo", "50000", "p26", 26),
            (self.bank, "depo", "50000", "k27", 27),  # T+1: butuh _widen_dto jalan
        ]:
            Transaction.objects.create(
                upload=up, source_type=st, toko=self.lbs, jenis=jenis,
                amount=Decimal("50000"), money_delta=Decimal(money),
                occurred_at=datetime(2026, 6, day, 21, 0), row_hash=rh, username="budi",
            )

    def test_run_batch_terima_tanggal_string(self):
        batch = run_batch(self.lbs, self.tol, date_from="2026-06-26", date_to="2026-06-26")
        pb = batch.runs.get(relation=MatchRun.Relation.PANEL_BANK)
        self.assertEqual(pb.summary["cocok"], 1)
        # window tersimpan sebagai date beneran di batch
        self.assertEqual(batch.date_from, date(2026, 6, 26))

    def test_run_batch_tanggal_string_tak_valid_error_jelas(self):
        with self.assertRaises(ValueError):
            run_batch(self.lbs, self.tol, date_from="26/06/2026", date_to="26/06/2026")


class GatewayOrphanWindowTests(TestCase):
    """Orphan `gateway_no_panel` HANYA untuk uang QR dalam window batch [from,to].

    Pool sisi uang dilebarkan T+n supaya settlement telat tetap bisa BERPASANGAN —
    tapi uang QR bertanggal D+1 yang belum punya deposit Panel itu milik batch
    BESOK, bukan orphan hari ini. Bug asli (staging K25): batch-27 mengecap 6.679
    baris gateway-28 sebagai gateway_no_panel lalu MENGONSUMSINYA (spillover tanpa
    guard left) → batch-28 kehilangan uangnya → no_money massal + selisih ratusan juta.
    """

    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(name="Default")[0]
        self.tol.date_window_days = 3
        self.tol.save()
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.gw = SourceType.objects.get_or_create(key="gateway", defaults={"name": "Gateway"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _tx(self, st, money, rh, day, **kw):
        raw = dict(kw.pop("raw", {}))
        if st is self.gw:
            raw.setdefault("Payment Status", "PAID")
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.lbs, jenis="depo",
            amount=Decimal(abs(int(money))), money_delta=Decimal(money),
            occurred_at=datetime(2026, 6, day, 21, 0), row_hash=rh, raw=raw, **kw,
        )

    def test_gateway_besok_bukan_orphan_dan_tak_dikonsumsi(self):
        # Hari 27: 1 panel + gateway pasangannya. Hari 28: gateway TANPA panel (panelnya
        # baru diupload besok). Batch-27 tak boleh mengecap/mengonsumsi uang 28.
        self._tx(self.panel, "50000", "p27", 27, ticket_no="D1", username="a")
        self._tx(self.gw, "50000", "g27", 27, ticket_no="D1", username="a")
        g28 = self._tx(self.gw, "70000", "g28", 28, ticket_no="D2", username="b")

        b27 = run_batch(self.lbs, self.tol, date_from=date(2026, 6, 27), date_to=date(2026, 6, 27))
        pb = b27.runs.get(relation=MatchRun.Relation.PANEL_BANK)
        self.assertFalse(pb.results.filter(reason_code="gateway_no_panel").exists())
        g28.refresh_from_db()
        self.assertIsNone(g28.consumed_by_batch)

        # Besok: panel-28 datang → uang g28 masih aktif, match sempurna, selisih 0.
        self._tx(self.panel, "70000", "p28", 28, ticket_no="D2", username="b")
        b28 = run_batch(self.lbs, self.tol, date_from=date(2026, 6, 28), date_to=date(2026, 6, 28))
        pb28 = b28.runs.get(relation=MatchRun.Relation.PANEL_BANK)
        self.assertEqual(pb28.summary["cocok"], 1)
        self.assertEqual(b28.summary["dp"]["selisih"], 0.0)
        g28.refresh_from_db()
        self.assertEqual(g28.consumed_by_batch_id, b28.pk)

    def test_orphan_dalam_window_tetap_dilaporkan(self):
        # Sinyal audit asli TIDAK hilang: uang QR settle DALAM window tanpa panel
        # tetap gateway_no_panel dan dikonsumsi batch (in-window consume).
        self._tx(self.panel, "50000", "p27", 27, ticket_no="D1", username="a")
        self._tx(self.gw, "50000", "g27", 27, ticket_no="D1", username="a")
        orphan = self._tx(self.gw, "99000", "gx", 27, ticket_no="D9", username="x")
        b27 = run_batch(self.lbs, self.tol, date_from=date(2026, 6, 27), date_to=date(2026, 6, 27))
        pb = b27.runs.get(relation=MatchRun.Relation.PANEL_BANK)
        r = pb.results.get(reason_code="gateway_no_panel")
        self.assertEqual(r.right_id, orphan.id)
        orphan.refresh_from_db()
        self.assertEqual(orphan.consumed_by_batch_id, b27.pk)

    def test_tanpa_window_perilaku_lama(self):
        # from=to=None (CLI penuh) → tak ada clamp; orphan tetap dilaporkan.
        self._tx(self.gw, "99000", "gx", 27, ticket_no="D9", username="x")
        b = run_batch(self.lbs, self.tol)
        pb = b.runs.get(relation=MatchRun.Relation.PANEL_BANK)
        self.assertTrue(pb.results.filter(reason_code="gateway_no_panel").exists())


class WeakFloorTests(TestCase):
    """Floor bukti nama (_WEAK_FLOOR=55): nominal+tanggal sama TANPA bukti identitas
    BUKAN pasangan. Bukti staging K25: 337 dari 552 tinjau berskor <40 (243 di
    antaranya 0-9) — dipasangkan cuma karena nominal+window, dan uang bank ikut
    terkunci ke pasangan sampah. Di bawah floor → no_money, uang TETAP BEBAS."""

    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(name="Default")[0]
        self.tol.date_window_days = 1
        self.tol.fuzzy_threshold = 85
        self.tol.save()
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _tx(self, st, money, rh, day=27, **kw):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.lbs, jenis="depo",
            amount=Decimal(abs(int(money))), money_delta=Decimal(money),
            occurred_at=datetime(2026, 6, day, 21, 0), row_hash=rh, **kw,
        )

    def _pb(self):
        b = run_batch(self.lbs, self.tol, date_from=date(2026, 6, 27), date_to=date(2026, 6, 27))
        return b.runs.get(relation=MatchRun.Relation.PANEL_BANK)

    def test_skor_nol_jadi_no_money(self):
        # Nama beda total (skor ~40 token noise) → JANGAN dipasangkan.
        self._tx(self.panel, "50000", "p1", counterparty="BUDI SANTOSO")
        self._tx(self.bank, "50000", "k1", counterparty="XYZ RANDOM")
        r = self._pb().results.get(left__isnull=False)
        self.assertEqual(r.bucket, "tidak_cocok")
        self.assertEqual(r.reason_code, "no_money")
        self.assertIsNone(r.right)
        self.assertIn("bukti identitas", r.reason_detail)

    def test_kandidat_t1_di_bawah_floor_tak_dicuri(self):
        # Bank T+1 (di luar window) bukti nol → tak dipasangkan DAN tak ikut
        # spillover — tetap bebas untuk batch pemilik tanggalnya. (Baris DALAM
        # window tetap dikonsumsi _consume_scope — itu desain kepemilikan window,
        # bukan pairing.)
        self._tx(self.panel, "50000", "p1", counterparty="BUDI SANTOSO")
        bank = self._tx(self.bank, "50000", "k1", day=28, counterparty="XYZ RANDOM")
        r = self._pb().results.get(left__isnull=False)
        self.assertEqual(r.reason_code, "no_money")
        bank.refresh_from_db()
        self.assertIsNone(bank.consumed_by_batch)

    def test_skor_menengah_tetap_weak_name(self):
        # Nama terpotong khas bank (skor ~80: 55<=s<85) → tetap tinjau weak_name.
        self._tx(self.panel, "50000", "p1", counterparty="BUDI SANTOSO")
        self._tx(self.bank, "50000", "k1", counterparty="BUDI S")
        r = self._pb().results.get(left__isnull=False)
        self.assertEqual(r.bucket, "perlu_tinjau")
        self.assertEqual(r.reason_code, "weak_name")


class AliasHistoryTests(TestCase):
    """Kamus alias dari SEJARAH: pasangan COCOK lama (kunci kuat) mengajari matcher
    'player X memang memakai rekening atas nama Y / nomor Z'. Deposit rekening
    pinjaman yang BERULANG naik jadi match kuat (95, alias_history) — cara
    memaksimalkan match yang benar tanpa melonggarkan fuzzy."""

    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(name="Default")[0]
        self.tol.date_window_days = 1
        self.tol.fuzzy_threshold = 85
        self.tol.save()
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)
        self._n = 0

    def _tx(self, st, money, rh, day, **kw):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.lbs, jenis="depo",
            amount=Decimal(abs(int(money))), money_delta=Decimal(money),
            occurred_at=datetime(2026, 6, day, 21, 0), row_hash=rh, **kw,
        )

    def _run_day(self, day):
        b = run_batch(self.lbs, self.tol, date_from=date(2026, 6, day), date_to=date(2026, 6, day))
        return b, b.runs.get(relation=MatchRun.Relation.PANEL_BANK)

    def _seed_history(self):
        # Hari 26: budi77 match kuat ke rekening 'SITI AMINAH' (username exact di bank).
        self._tx(self.panel, "50000", "hp", 26, username="budi77", counterparty="SITI AMINAH")
        self._tx(self.bank, "50000", "hk", 26, username="budi77", counterparty="SITI AMINAH")
        _, pb = self._run_day(26)
        self.assertEqual(pb.summary["cocok"], 1)  # sejarah terbentuk

    def test_alias_naikkan_match_berulang(self):
        self._seed_history()
        # Hari 27: budi77 deposit lagi via rekening SITI AMINAH — nominal beda,
        # username bank kosong, nama panel != nama rekening → tanpa alias = sampah.
        self._tx(self.panel, "75000", "p2", 27, username="budi77", counterparty="BUDI SANTOSO")
        self._tx(self.bank, "75000", "k2", 27, counterparty="SITI AMINAH")
        _, pb = self._run_day(27)
        r = pb.results.get(left__isnull=False)
        self.assertEqual(r.bucket, "cocok")
        self.assertEqual(r.reason_code, "alias_history")
        self.assertGreaterEqual(r.score, 95)

    def test_alias_tak_bocor_ke_user_lain(self):
        self._seed_history()
        # Player LAIN pakai rekening yang sama → alias budi77 tak boleh menular.
        self._tx(self.panel, "75000", "p2", 27, username="tono99", counterparty="TONO S")
        self._tx(self.bank, "75000", "k2", 27, counterparty="SITI AMINAH")
        _, pb = self._run_day(27)
        r = pb.results.get(left__isnull=False)
        self.assertNotEqual(r.reason_code, "alias_history")
        self.assertNotEqual(r.bucket, "cocok")

    def test_alias_hilang_saat_batch_sejarah_dihapus(self):
        self._seed_history()
        ReconBatch.objects.filter(toko=self.lbs).delete()  # bukti dihapus
        self._tx(self.panel, "75000", "p2", 27, username="budi77", counterparty="BUDI SANTOSO")
        self._tx(self.bank, "75000", "k2", 27, counterparty="SITI AMINAH")
        _, pb = self._run_day(27)
        r = pb.results.get(left__isnull=False)
        self.assertNotEqual(r.reason_code, "alias_history")


class DefaultWindowTests(TestCase):
    """Profil Default window 2 hari: WD Sabtu settle Senin (bukti staging 27-29
    Jun — 27=Sabtu, uangnya baru muncul di mutasi Senin 29; window 1 hari buta
    weekend). Konsumsi in-window tetap [from,to] — hanya pool kandidat melebar,
    dan tie-break tanggal menjaga uang hari terdekat yang diambil dulu."""

    def test_default_window_dua_hari(self):
        tol = ToleranceProfile.objects.get(name="Default")
        self.assertEqual(tol.date_window_days, 2)

    def test_wd_sabtu_settle_senin_match(self):
        lbs = Toko.objects.get(key="lbs")
        tol = ToleranceProfile.objects.get(name="Default")
        panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        up = Upload.objects.create(source_type=panel, toko=lbs)

        def tx(st, money, rh, day, **kw):
            return Transaction.objects.create(
                upload=up, source_type=st, toko=lbs, jenis="wd",
                amount=Decimal(abs(int(money))), money_delta=Decimal(money),
                occurred_at=datetime(2026, 6, day, 21, 0), row_hash=rh, **kw,
            )

        tx(panel, "-50000", "p1", 27, counterparty="BUDI SANTOSO")   # Sabtu
        uang = tx(bank, "-50000", "k1", 29, counterparty="BUDI SANTOSO")  # Senin
        b = run_batch(lbs, tol, date_from=date(2026, 6, 27), date_to=date(2026, 6, 27))
        r = b.runs.get(relation=MatchRun.Relation.PANEL_BANK).results.get(left__isnull=False)
        self.assertEqual(r.bucket, "cocok")
        self.assertEqual(r.right_id, uang.id)
        uang.refresh_from_db()
        self.assertEqual(uang.consumed_by_batch_id, b.id)  # spillover ikut terkunci


class DateProximityTieTests(TestCase):
    """Skor seri → pilih kandidat tanggal TERDEKAT ke panel. Tanpa preferensi ini
    greedy memilih urutan DB: batch hari-H bisa nyomot settlement H+1 padahal uang
    hari-H ada, dan baris repeat player besok kelaparan. Bukti staging K25: 80
    baris no_money padahal kandidat skor 100 ada — semua uangnya sudah dikonsumsi
    batch kemarin."""

    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(name="Default")[0]
        self.tol.date_window_days = 1
        self.tol.fuzzy_threshold = 85
        self.tol.save()
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _tx(self, st, money, rh, day=27, **kw):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.lbs, jenis="depo",
            amount=Decimal(abs(int(money))), money_delta=Decimal(money),
            occurred_at=datetime(2026, 6, day, 21, 0), row_hash=rh, **kw,
        )

    def _run_day(self, day):
        b = run_batch(self.lbs, self.tol, date_from=date(2026, 6, day), date_to=date(2026, 6, day))
        return b, b.runs.get(relation=MatchRun.Relation.PANEL_BANK)

    def test_seri_pilih_tanggal_terdekat(self):
        self._tx(self.panel, "50000", "p1", counterparty="BUDI SANTOSO")
        # Uang H+1 sengaja dibuat DULUAN (id lebih kecil) — tanpa tie-break
        # tanggal, greedy urutan DB memilihnya dan uang hari-H terlantar.
        besok = self._tx(self.bank, "50000", "k28", day=28, counterparty="BUDI SANTOSO")
        hari_h = self._tx(self.bank, "50000", "k27", day=27, counterparty="BUDI SANTOSO")
        _, pb = self._run_day(27)
        r = pb.results.get(left__isnull=False)
        self.assertEqual(r.bucket, "cocok")
        self.assertEqual(r.right_id, hari_h.id)
        besok.refresh_from_db()
        self.assertIsNone(besok.consumed_by_batch)  # uang besok tetap bebas

    def test_repeat_player_dua_hari_dua_batch(self):
        # Orang sama, nominal sama, dua hari berturut — batch 27 tak boleh
        # mencuri uang 28; batch 28 harus tetap dapat pasangannya.
        self._tx(self.panel, "50000", "p27", day=27, counterparty="IRAMAYA YUATI")
        self._tx(self.panel, "50000", "p28", day=28, counterparty="IRAMAYA YUATI")
        uang28 = self._tx(self.bank, "50000", "k28", day=28, counterparty="IRAMAYA YUATI")
        uang27 = self._tx(self.bank, "50000", "k27", day=27, counterparty="IRAMAYA YUATI")
        _, pb27 = self._run_day(27)
        r27 = pb27.results.get(left__isnull=False)
        self.assertEqual(r27.right_id, uang27.id)
        _, pb28 = self._run_day(28)
        r28 = pb28.results.get(left__isnull=False)
        self.assertEqual(r28.bucket, "cocok")
        self.assertEqual(r28.right_id, uang28.id)

    def test_dest_menang_atas_tanggal(self):
        # Kunci kuat (nomor tujuan sama) H+1 mengalahkan nama-100 hari-H:
        # identitas pasti > kedekatan tanggal.
        self._tx(self.panel, "50000", "p1", counterparty="BUDI SANTOSO",
                 dest_account="123456789")
        self._tx(self.bank, "50000", "kh", day=27, counterparty="BUDI SANTOSO")
        besok_dest = self._tx(self.bank, "50000", "kd", day=28,
                              counterparty="BUDI SANTOSO", dest_account="123456789")
        _, pb = self._run_day(27)
        r = pb.results.get(left__isnull=False)
        self.assertEqual(r.bucket, "cocok")
        self.assertEqual(r.reason_code, "bank_dest")
        self.assertEqual(r.right_id, besok_dest.id)
