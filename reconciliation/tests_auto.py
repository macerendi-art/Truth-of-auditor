"""Rekonsiliasi otomatis per tanggal (auto-split): satu batch per tanggal-panel.

Panel jadi jangkar. Loop MENAIK memakai carry-over bawaan (run_batch date_from=None,
date_to=D). Pre-flight verify_panel_anchor memblokir uang/bracket tanpa panel penutup.
"""
from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase

from reconciliation.engine import (
    _panel_dates,
    run_batch,
    run_batches_auto,
    verify_panel_anchor,
)
from reconciliation.models import MatchResult, ReconBatch, ToleranceProfile
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

    def _tx(self, st, jenis, amount, money, ticket, rh, dt, **kw):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.lbs, jenis=jenis,
            amount=Decimal(amount), money_delta=Decimal(money), ticket_no=ticket,
            occurred_at=dt, row_hash=rh, **kw,
        )

    def _hari(self, st, jenis, amount, money, ticket, rh, hari, jam=10, **kw):
        return self._tx(st, jenis, amount, money, ticket, rh,
                        datetime(2026, 6, hari, jam, 0), **kw)


class AutoSplitTests(_Base):
    def test_tiga_tanggal_jadi_tiga_batch(self):
        # Tiap tanggal punya panel + uang sehari (cocok). 3 tanggal → 3 batch.
        self._hari(self.panel, "depo", "50000", "50000", "D1", "p1", 27, username="budi")
        self._hari(self.bank, "depo", "50000", "50000", "", "k1", 27, username="budi")
        self._hari(self.panel, "depo", "60000", "60000", "D2", "p2", 28, username="andi")
        self._hari(self.bank, "depo", "60000", "60000", "", "k2", 28, username="andi")
        self._hari(self.panel, "depo", "70000", "70000", "D3", "p3", 29, username="cici")
        self._hari(self.bank, "depo", "70000", "70000", "", "k3", 29, username="cici")

        res = run_batches_auto(self.lbs, self.tol)
        self.assertTrue(res["ok"])
        self.assertEqual([b.recon_date for b in res["batches"]],
                         [date(2026, 6, 27), date(2026, 6, 28), date(2026, 6, 29)])
        self.assertEqual(ReconBatch.objects.filter(recon_date__isnull=False).count(), 3)
        for b in res["batches"]:
            self.assertEqual(b.summary["buckets"]["cocok"], 1)

    def test_satu_tanggal_tetap_satu_batch(self):
        self._hari(self.panel, "depo", "50000", "50000", "D1", "p1", 27, username="budi")
        self._hari(self.bank, "depo", "50000", "50000", "", "k1", 27, username="budi")
        res = run_batches_auto(self.lbs, self.tol)
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["batches"]), 1)
        self.assertEqual(res["batches"][0].recon_date, date(2026, 6, 27))

    def test_carry_over_lintas_hari_dalam_auto_run(self):
        # Panel 27 (50k budi) uangnya baru datang 28; day-27 punya bank 70k (siti)
        # supaya PANEL_BANK jalan → panel27 no_money → carried. Panel 28 murni.
        p27 = self._hari(self.panel, "depo", "50000", "50000", "D1", "p1", 27, jam=21, username="budi")
        self._hari(self.bank, "depo", "70000", "70000", "", "k1", 27, username="siti")
        self._hari(self.panel, "depo", "60000", "60000", "D2", "p2", 28, jam=9, username="andi")
        self._hari(self.bank, "depo", "60000", "60000", "", "k2", 28, username="andi")
        uang = self._hari(self.bank, "depo", "50000", "50000", "", "k3", 28, jam=1, username="budi")

        res = run_batches_auto(self.lbs, self.tol)
        self.assertTrue(res["ok"])
        b27, b28 = res["batches"]
        self.assertEqual(b27.recon_date, date(2026, 6, 27))
        self.assertEqual(b28.recon_date, date(2026, 6, 28))
        # Settle terlambat: hasil panel27 ter-flip jadi COCOK di batch ASALnya (b27).
        r = MatchResult.objects.get(run__batch=b27, left=p27)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.reason_code, "late_settlement")
        self.assertEqual(r.resolved_by_batch, b28)
        self.assertEqual(r.right, uang)
        p27.refresh_from_db()
        self.assertEqual(p27.consumed_by_batch, b27)  # pulang ke batch asal
        # Batch 28 murni tanggal 28 — nilai carried tidak ikut gross.
        self.assertEqual(b28.summary["dp"]["panel"], 60000.0)
        self.assertEqual(b28.summary["late_settlement"]["dp"], {"count": 1, "amount": 50000.0})

    def test_tanggal_sudah_ada_batch_dilewati(self):
        # Batch 27 sudah ada (dari run manual). Lalu ada panel-27 SUSULAN aktif +
        # data tanggal 28. Auto-run melewati 27 (dilaporkan), hanya bikin batch 28.
        self._hari(self.panel, "depo", "50000", "50000", "D1", "p1", 27, username="budi")
        self._hari(self.bank, "depo", "50000", "50000", "", "k1", 27, username="budi")
        b27 = run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 27))
        # Panel 27 susulan (aktif) + tanggal 28.
        self._hari(self.panel, "depo", "80000", "80000", "D9", "p9", 27, username="rian")
        self._hari(self.panel, "depo", "60000", "60000", "D2", "p2", 28, username="andi")
        self._hari(self.bank, "depo", "60000", "60000", "", "k2", 28, username="andi")

        res = run_batches_auto(self.lbs, self.tol)
        self.assertTrue(res["ok"])
        self.assertEqual([b.recon_date for b in res["batches"]], [date(2026, 6, 28)])
        self.assertEqual([s["date"] for s in res["skipped_existing"]], [date(2026, 6, 27)])
        self.assertEqual(res["skipped_existing"][0]["batch_id"], b27.id)
        self.assertEqual(res["errors"], [])


class VerifyAnchorTests(_Base):
    def test_uang_yatim_memblokir_tanpa_bikin_batch(self):
        # Panel hanya 27; uang 30 tak tertutup panel (window 1) → tolak, 0 batch.
        self._hari(self.panel, "depo", "50000", "50000", "D1", "p1", 27, username="budi")
        self._hari(self.bank, "depo", "50000", "50000", "", "k1", 30, username="budi")
        res = run_batches_auto(self.lbs, self.tol)
        self.assertFalse(res["ok"])
        self.assertEqual([(v["date"], v["source"]) for v in res["violations"]],
                         [(date(2026, 6, 30), "uang")])
        self.assertEqual(ReconBatch.objects.filter(recon_date__isnull=False).count(), 0)

    def test_uang_dalam_window_lolos(self):
        # Panel 27, uang 28 (window 1: 27<=28<=28) → tertutup, lolos.
        self._hari(self.panel, "depo", "50000", "50000", "D1", "p1", 27, username="budi")
        self._hari(self.bank, "depo", "50000", "50000", "", "k1", 28, username="budi")
        self.assertEqual(verify_panel_anchor(self.lbs, None, None, None, 1), [])
        # Uang 29 di luar window (27+1=28<29) → pelanggaran.
        self._hari(self.bank, "depo", "90000", "90000", "", "k2", 29, username="siti")
        v = verify_panel_anchor(self.lbs, None, None, None, 1)
        self.assertEqual([(x["date"], x["source"]) for x in v], [(date(2026, 6, 29), "uang")])

    def test_admin_fee_tanpa_panel_tidak_memblokir(self):
        # Baris admin (fee) di tanggal tanpa panel tidak memicu pelanggaran.
        self._hari(self.panel, "depo", "50000", "50000", "D1", "p1", 27, username="budi")
        self._hari(self.bank, "depo", "50000", "50000", "", "k1", 27, username="budi")
        self._hari(self.bank, "admin", "6500", "-6500", "", "k9", 30)
        self.assertEqual(verify_panel_anchor(self.lbs, None, None, None, 1), [])

    def test_bracket_yatim_memblokir(self):
        # Bracket tanggal 30, panel hanya 27 (|30-27|=3 > window 1) → pelanggaran.
        self._hari(self.panel, "depo", "50000", "50000", "D1", "p1", 27, username="budi")
        self._hari(self.bank, "depo", "50000", "50000", "", "k1", 27, username="budi")
        self._hari(self.bracket, "depo", "40000", "40000", "D5", "b5", 30, username="tono")
        res = run_batches_auto(self.lbs, self.tol)
        self.assertFalse(res["ok"])
        self.assertIn("bracket", [v["source"] for v in res["violations"]])

    def test_panel_dates_menaik_dan_aktif(self):
        self._hari(self.panel, "depo", "60000", "60000", "D2", "p2", 29, username="andi")
        self._hari(self.panel, "depo", "50000", "50000", "D1", "p1", 27, username="budi")
        self.assertEqual(_panel_dates(self.lbs), [date(2026, 6, 27), date(2026, 6, 29)])
