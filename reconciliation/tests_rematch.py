"""Re-match batch: pasangkan mutasi uang susulan (ekor malam T+1, BNI bulanan) ke
baris tidak_cocok panel di batch LAMA, tanpa menghapus batch. Uang dikonsumsi ke
batch lama, summary/selisih dihitung ulang. Lihat docs/superpowers/specs/rematch-batch.md.

Gaya tes mengikuti tests_batch.py (Toko 'lbs' seeded, ToleranceProfile 'Default',
factory helper). Semua transaksi kandidat dibuat AKTIF (belum dikonsumsi) kecuali
disebutkan lain.
"""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.engine import rematch_batch, run_batch
from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class _Base(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol, _ = ToleranceProfile.objects.get_or_create(name="Default")
        self.tol.date_window_days = 1
        self.tol.fuzzy_threshold = 85
        self.tol.save()
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.gw = SourceType.objects.get_or_create(key="gateway", defaults={"name": "Gateway"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _tx(self, st, jenis, money, rh, day=25, status=None, **kw):
        raw = dict(kw.pop("raw", {}))
        if status is not None:
            raw["Payment Status"] = status
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.lbs, jenis=jenis,
            amount=Decimal(abs(int(money))), money_delta=Decimal(money),
            occurred_at=datetime(2026, 6, day, 21, 0), row_hash=rh, raw=raw, **kw,
        )

    def _batch_25(self, noise=True):
        # Batch harian lahir dengan SEBAGIAN uang sudah masuk (mis. BNI bulanan belum,
        # tapi bank lain sudah) → relasi PANEL_BANK JALAN & meninggalkan ekor
        # tidak_cocok. Baris noise ini uang tak-berpasangan (nominal & id beda dari
        # target) supaya PANEL_BANK tidak di-skip. Tak jadi MatchResult (bank unmatched
        # tak di-emit) & tak mempengaruhi matched/selisih target.
        if noise:
            self._tx(self.bank, "depo", "13000", "noise_money", day=25, username="zzz_noise")
        return run_batch(self.lbs, self.tol, date_from=date(2026, 6, 25), date_to=date(2026, 6, 25))

    def _pb(self, batch):
        return batch.runs.get(relation=MatchRun.Relation.PANEL_BANK)


class StragglerBankDPTests(_Base):
    def test_straggler_bank_dp_pairs_on_rematch(self):
        # Panel-25 malam DP tidak_cocok di batch [25,25] (belum ada bank). Lalu bank
        # dated-25 malam datang (AKTIF, nama+nominal cocok) → re-match → COCOK,
        # right terpasang, dikonsumsi ke batch ini, summary matched + selisih 0.
        self._tx(self.panel, "depo", "50000", "p25", day=25, username="budi")
        batch = self._batch_25()
        res = self._pb(batch).results.get(left__isnull=False)
        self.assertEqual(res.bucket, "tidak_cocok")

        bank = self._tx(self.bank, "depo", "50000", "k_straggler", day=25, username="budi")
        stats = rematch_batch(batch)

        res.refresh_from_db()
        self.assertEqual(res.bucket, "cocok")
        self.assertEqual(res.right_id, bank.id)
        self.assertIn("re-match", res.reason_detail)
        bank.refresh_from_db()
        self.assertEqual(bank.consumed_by_batch_id, batch.id)

        batch.refresh_from_db()
        self.assertEqual(batch.summary["dp"]["money_matched"], 50000.0)
        self.assertEqual(batch.summary["dp"]["selisih"], 0.0)
        self.assertEqual(stats["terpasang"], 1)
        self.assertEqual(stats["cocok"], 1)


class StragglerGatewayTicketTests(_Base):
    def test_straggler_gateway_by_txid(self):
        # Panel D123 no_money di batch (belum ada gateway). Lalu gateway PAID
        # ticket D123 datang → re-match → COCOK reason gateway_ticket, dikonsumsi.
        self._tx(self.panel, "depo", "50000", "p1", day=25, ticket_no="D123", username="a")
        batch = self._batch_25()
        res = self._pb(batch).results.get(left__isnull=False)
        self.assertEqual(res.bucket, "tidak_cocok")
        self.assertEqual(res.reason_code, "no_money")

        gw = self._tx(self.gw, "depo", "50000", "g1", day=25, ticket_no="D123", status="PAID", username="a")
        rematch_batch(batch)

        res.refresh_from_db()
        self.assertEqual(res.bucket, "cocok")
        self.assertEqual(res.reason_code, "gateway_ticket")
        self.assertEqual(res.right_id, gw.id)
        gw.refresh_from_db()
        self.assertEqual(gw.consumed_by_batch_id, batch.id)


class IdempotentTests(_Base):
    def test_second_rematch_noop(self):
        self._tx(self.panel, "depo", "50000", "p25", day=25, username="budi")
        batch = self._batch_25()
        self._tx(self.bank, "depo", "50000", "k_straggler", day=25, username="budi")
        first = rematch_batch(batch)
        self.assertEqual(first["terpasang"], 1)

        before = {
            r.id: (r.bucket, r.right_id, r.reason_detail)
            for r in MatchResult.objects.filter(run__batch=batch)
        }
        second = rematch_batch(batch)
        self.assertEqual(second["terpasang"], 0)
        after = {
            r.id: (r.bucket, r.right_id, r.reason_detail)
            for r in MatchResult.objects.filter(run__batch=batch)
        }
        self.assertEqual(before, after)


class NoStealTests(_Base):
    def test_money_consumed_by_other_batch_not_used(self):
        # Bank straggler yang SUDAH dikonsumsi batch LAIN tidak boleh dicuri.
        self._tx(self.panel, "depo", "50000", "p25", day=25, username="budi")
        batch = self._batch_25()
        res = self._pb(batch).results.get(left__isnull=False)

        other = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        bank = self._tx(self.bank, "depo", "50000", "k_owned", day=25, username="budi")
        bank.consumed_by_batch = other
        bank.save(update_fields=["consumed_by_batch"])

        stats = rematch_batch(batch)
        self.assertEqual(stats["terpasang"], 0)
        res.refresh_from_db()
        self.assertEqual(res.bucket, "tidak_cocok")
        bank.refresh_from_db()
        self.assertEqual(bank.consumed_by_batch_id, other.id)


class OrphanSkippedTests(_Base):
    def test_gateway_no_panel_untouched_no_new_results(self):
        # Orphan gateway_no_panel (left=None) tak boleh disentuh; re-match tak
        # membuat MatchResult baru (jumlah result konstan).
        self._tx(self.panel, "depo", "50000", "p1", day=25, ticket_no="D1", username="a")
        self._tx(self.gw, "depo", "50000", "g1", day=25, ticket_no="D1", status="PAID", username="a")
        # gateway settle tanpa panel → orphan
        self._tx(self.gw, "depo", "77000", "g_orphan", day=25, ticket_no="D2", status="PAID", username="z")
        batch = self._batch_25()
        pb = self._pb(batch)

        orphan = pb.results.get(right__row_hash="g_orphan")
        self.assertIsNone(orphan.left_id)
        self.assertEqual(orphan.reason_code, "gateway_no_panel")

        n_before = MatchResult.objects.filter(run__batch=batch).count()
        rematch_batch(batch)
        n_after = MatchResult.objects.filter(run__batch=batch).count()
        self.assertEqual(n_before, n_after)

        orphan.refresh_from_db()
        self.assertEqual(orphan.reason_code, "gateway_no_panel")
        self.assertIsNone(orphan.left_id)


class AmbiguousOnRematchTests(_Base):
    def test_two_distinct_identity_flips_to_review_no_consume(self):
        # Dua bank aktif nominal sama IDENTITAS BEDA → target flip TINJAU
        # ambiguous_multi, right None, tak ada yang dikonsumsi.
        self._tx(self.panel, "depo", "50000", "p25", day=25, counterparty="BUDI SANTOSO")
        batch = self._batch_25()
        res = self._pb(batch).results.get(left__isnull=False)
        self.assertEqual(res.bucket, "tidak_cocok")

        b1 = self._tx(self.bank, "depo", "50000", "kb1", day=25, counterparty="BUDI SANTOSO", username="acc1")
        b2 = self._tx(self.bank, "depo", "50000", "kb2", day=25, counterparty="BUDI SANTOSO", username="acc2")
        stats = rematch_batch(batch)

        res.refresh_from_db()
        self.assertEqual(res.bucket, "perlu_tinjau")
        self.assertEqual(res.reason_code, "ambiguous_multi")
        self.assertIsNone(res.right_id)
        b1.refresh_from_db()
        b2.refresh_from_db()
        self.assertIsNone(b1.consumed_by_batch_id)
        self.assertIsNone(b2.consumed_by_batch_id)
        # ambiguous_multi flip TIDAK→TINJAU tapi TANPA right → tak dihitung "terpasang"
        # (tak ada uang menempel); stats terpasang/cocok/perlu_tinjau tetap 0.
        self.assertEqual(stats["terpasang"], 0)
        self.assertEqual(stats["cocok"], 0)
        self.assertEqual(stats["perlu_tinjau"], 0)


class WeakNameOnRematchTests(_Base):
    def test_weak_name_gets_right_and_consumed(self):
        # Kandidat nominal+tanggal cocok tapi nama lemah → TINJAU weak_name dgn
        # right terpasang + dikonsumsi (mirror matcher normal).
        self._tx(self.panel, "depo", "50000", "p25", day=25, counterparty="BUDI SANTOSO")
        batch = self._batch_25()
        res = self._pb(batch).results.get(left__isnull=False)

        bank = self._tx(self.bank, "depo", "50000", "kb", day=25, counterparty="XYZ RANDOM")
        stats = rematch_batch(batch)

        res.refresh_from_db()
        self.assertEqual(res.bucket, "perlu_tinjau")
        self.assertEqual(res.reason_code, "weak_name")
        self.assertEqual(res.right_id, bank.id)
        bank.refresh_from_db()
        self.assertEqual(bank.consumed_by_batch_id, batch.id)
        self.assertEqual(stats["perlu_tinjau"], 1)
        self.assertEqual(stats["terpasang"], 1)


class AggregateRegressionTests(_Base):
    def test_panel_gross_unchanged_after_rematch(self):
        # Setelah re-match, angka gross panel batch tetap mencerminkan baris yang
        # dikonsumsi batch sendiri (fix _aggregate_batch batch-param) — bukan 0.
        self._tx(self.panel, "depo", "50000", "p25", day=25, username="budi")
        batch = self._batch_25()
        panel_before = batch.summary["dp"]["panel"]
        self.assertEqual(panel_before, 50000.0)

        self._tx(self.bank, "depo", "50000", "k_straggler", day=25, username="budi")
        rematch_batch(batch)
        batch.refresh_from_db()
        self.assertEqual(batch.summary["dp"]["panel"], panel_before)
        self.assertEqual(batch.summary["dp"]["money_matched"], 50000.0)


class IncludeRespectedTests(_Base):
    def test_gateway_excluded_by_include_not_paired(self):
        # Batch run dengan include gateway=False; gateway straggler tak boleh
        # dipasangkan re-match (pool menghormati include batch).
        include = {"panel_dp": True, "panel_wd": True, "bracket": True, "bank": True, "gateway": False}
        self._tx(self.panel, "depo", "50000", "p1", day=25, ticket_no="D123", username="a")
        # bank ADA supaya panel_bank tetap jalan
        self._tx(self.bank, "depo", "70000", "k_other", day=25, username="nomatch")
        batch = run_batch(
            self.lbs, self.tol, date_from=date(2026, 6, 25), date_to=date(2026, 6, 25), include=include
        )
        res = self._pb(batch).results.get(left__isnull=False)
        self.assertEqual(res.bucket, "tidak_cocok")

        gw = self._tx(self.gw, "depo", "50000", "g1", day=25, ticket_no="D123", status="PAID", username="a")
        stats = rematch_batch(batch)
        self.assertEqual(stats["terpasang"], 0)
        res.refresh_from_db()
        self.assertEqual(res.bucket, "tidak_cocok")
        gw.refresh_from_db()
        self.assertIsNone(gw.consumed_by_batch_id)


class RematchViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("sup", "s@s.co", "pw12345", role="supervisor")
        self.client.login(username="sup", password="pw12345")
        self.tol, _ = ToleranceProfile.objects.get_or_create(name="Default", defaults={"date_window_days": 1})
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _tx(self, st, toko, jenis, money, rh, day=25, **kw):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=toko, jenis=jenis,
            amount=Decimal(abs(int(money))), money_delta=Decimal(money),
            occurred_at=datetime(2026, 6, day, 21, 0), row_hash=rh, **kw,
        )

    def test_post_redirects_with_message(self):
        self._tx(self.panel, self.lbs, "depo", "50000", "p25", username="budi")
        # noise money → PANEL_BANK jalan & tinggalkan ekor tidak_cocok.
        self._tx(self.bank, self.lbs, "depo", "13000", "noise", username="zzz")
        batch = run_batch(self.lbs, self.tol, date_from=date(2026, 6, 25), date_to=date(2026, 6, 25))
        self._tx(self.bank, self.lbs, "depo", "50000", "k_straggler", username="budi")

        r = self.client.post(reverse("rematch_batch", args=[batch.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("batch_detail", args=[batch.pk]))
        msgs = [m.message for m in r.wsgi_request._messages]
        self.assertTrue(any("Re-match" in m for m in msgs))

    def test_get_not_allowed(self):
        self._tx(self.panel, self.lbs, "depo", "50000", "p25", username="budi")
        batch = run_batch(self.lbs, self.tol, date_from=date(2026, 6, 25), date_to=date(2026, 6, 25))
        r = self.client.get(reverse("rematch_batch", args=[batch.pk]))
        self.assertEqual(r.status_code, 405)

    def test_other_toko_batch_404_for_restricted_auditor(self):
        User = get_user_model()
        aud = User.objects.create_user("aud", "a@a.co", "pw12345", role="auditor")
        aud.allowed_tokos.set([self.lbs])  # hanya lbs, bukan slo
        self._tx(self.panel, self.slo, "depo", "50000", "p_slo", username="budi")
        batch = run_batch(self.slo, self.tol, date_from=date(2026, 6, 25), date_to=date(2026, 6, 25))

        self.client.logout()
        self.client.login(username="aud", password="pw12345")
        r = self.client.post(reverse("rematch_batch", args=[batch.pk]))
        self.assertEqual(r.status_code, 404)


class RematchHintTests(_Base):
    """Banner saran di flash upload: setelah upload sumber uang, batch lama dengan
    baris tidak_cocok yang window-nya overlap ditandai untuk Re-match."""

    def test_hint_mentions_overlapping_batch_with_tidak_cocok(self):
        from web.views import _rematch_hint

        self._tx(self.panel, "depo", "50000", "p25", day=25, username="budi")
        batch = self._batch_25()  # ada ekor tidak_cocok

        # Upload uang baru dgn transaksi tgl 25 (bank straggler) → overlap window batch.
        money_up = Upload.objects.create(source_type=self.bank, toko=self.lbs)
        Transaction.objects.create(
            upload=money_up, source_type=self.bank, toko=self.lbs, jenis="depo",
            amount=Decimal("50000"), money_delta=Decimal("50000"),
            occurred_at=datetime(2026, 6, 25, 21, 0), row_hash="k_new",
        )
        hint = _rematch_hint(self.lbs, [money_up])
        self.assertIn("Re-match", hint)
        self.assertIn("Batch", hint)

    def test_no_hint_when_batch_has_no_tidak_cocok(self):
        from web.views import _rematch_hint

        # Batch tanpa tidak_cocok (panel cocok penuh) → tak ada saran.
        self._tx(self.panel, "depo", "50000", "p25", day=25, username="budi")
        self._tx(self.bank, "depo", "50000", "k25", day=25, username="budi")
        self._batch_25(noise=False)

        money_up = Upload.objects.create(source_type=self.bank, toko=self.lbs)
        Transaction.objects.create(
            upload=money_up, source_type=self.bank, toko=self.lbs, jenis="depo",
            amount=Decimal("99000"), money_delta=Decimal("99000"),
            occurred_at=datetime(2026, 6, 25, 21, 0), row_hash="k_new",
        )
        self.assertEqual(_rematch_hint(self.lbs, [money_up]), "")

    def test_no_hint_for_empty_money_uploads(self):
        from web.views import _rematch_hint

        self.assertEqual(_rematch_hint(self.lbs, []), "")
