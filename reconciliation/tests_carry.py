"""Rekonsiliasi harian: carry-over "menunggu settlement" + late settlement.

Baris kredit tidak_cocok/no_money yang masih dalam window TIDAK dikonsumsi
saat run tanggal N, supaya bisa match dengan mutasi yang baru muncul di file
tanggal N+1. Match terlambat meng-update hasil di batch ASALnya.
"""
from datetime import date, datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from reconciliation import engine
from reconciliation.engine import NO_MONEY_DETAIL, revert_late_settlements, run_batch
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

    def _tx(self, st, jenis, amount, money, ticket, rh, dt=datetime(2026, 6, 27, 10, 0), **kw):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.lbs, jenis=jenis,
            amount=Decimal(amount), money_delta=Decimal(money), ticket_no=ticket,
            occurred_at=dt, row_hash=rh, **kw,
        )


class CarryOverTests(_Base):
    def test_no_money_dalam_window_tidak_dikonsumsi(self):
        # Panel malam 27 belum ada uangnya; bank lain nominal beda → no_money.
        p = self._tx(self.panel, "depo", "50000", "50000", "D1", "p1",
                     username="budi", dt=datetime(2026, 6, 27, 21, 0))
        b = self._tx(self.bank, "depo", "70000", "70000", "", "k1", username="siti")
        batch = run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 27))
        p.refresh_from_db()
        b.refresh_from_db()
        self.assertIsNone(p.consumed_by_batch)  # menunggu settlement
        self.assertEqual(b.consumed_by_batch, batch)  # uang tetap dikonsumsi
        r = MatchResult.objects.get(run__batch=batch, left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.TIDAK)
        self.assertEqual(r.reason_code, "no_money")

    def test_luar_window_dikonsumsi_normal(self):
        # Baris tanggal 26 pada run 27 (window 1) sudah tak mungkin settle.
        p = self._tx(self.panel, "depo", "50000", "50000", "D1", "p1",
                     username="budi", dt=datetime(2026, 6, 26, 21, 0))
        self._tx(self.bank, "depo", "70000", "70000", "", "k1", username="siti")
        batch = run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 27))
        p.refresh_from_db()
        self.assertEqual(p.consumed_by_batch, batch)

    def test_ketat_window0_tanpa_carry(self):
        ketat = ToleranceProfile.objects.get_or_create(
            name="Ketat", defaults={"date_window_days": 0}
        )[0]
        p = self._tx(self.panel, "depo", "50000", "50000", "D1", "p1",
                     username="budi", dt=datetime(2026, 6, 27, 21, 0))
        self._tx(self.bank, "depo", "70000", "70000", "", "k1", username="siti")
        batch = run_batch(self.lbs, ketat, recon_date=date(2026, 6, 27))
        p.refresh_from_db()
        self.assertEqual(p.consumed_by_batch, batch)

    def test_tanpa_recon_date_konsumsi_legacy(self):
        # Path legacy (recon_date=None): no_money dalam window pun dikonsumsi.
        p = self._tx(self.panel, "depo", "50000", "50000", "D1", "p1",
                     username="budi", dt=datetime(2026, 6, 27, 21, 0))
        self._tx(self.bank, "depo", "70000", "70000", "", "k1", username="siti")
        batch = run_batch(self.lbs, self.tol)
        p.refresh_from_db()
        self.assertEqual(p.consumed_by_batch, batch)


class LateSettlementTests(_Base):
    def _carry_day27(self):
        """Run tanggal 27: panel malam 27 no_money (carry), bank pengisi dikonsumsi."""
        p = self._tx(self.panel, "depo", "50000", "50000", "D1", "p1",
                     username="budi", dt=datetime(2026, 6, 27, 21, 0))
        self._tx(self.bank, "depo", "70000", "70000", "", "k1", username="siti")
        b27 = run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 27))
        return p, b27

    def test_flip_hasil_di_batch_asal(self):
        p, b27 = self._carry_day27()
        uang = self._tx(self.bank, "depo", "50000", "50000", "", "k2",
                        username="budi", dt=datetime(2026, 6, 28, 1, 0))
        b28 = run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 28))
        r = MatchResult.objects.get(run__batch=b27, left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.right, uang)
        self.assertEqual(r.reason_code, "late_settlement")
        self.assertEqual(r.resolved_by_batch, b28)
        p.refresh_from_db()
        uang.refresh_from_db()
        self.assertEqual(p.consumed_by_batch, b27)  # pulang ke batch asalnya
        self.assertEqual(uang.consumed_by_batch, b28)
        # Baris carried tidak membuat MatchResult baru di batch 28.
        self.assertFalse(MatchResult.objects.filter(run__batch=b28, left=p).exists())

    def test_summary_batch_asal_di_refresh(self):
        p, b27 = self._carry_day27()
        self._tx(self.bank, "depo", "50000", "50000", "", "k2",
                 username="budi", dt=datetime(2026, 6, 28, 1, 0))
        run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 28))
        b27.refresh_from_db()
        self.assertEqual(b27.summary["dp"]["money_matched"], 50000.0)
        self.assertEqual(b27.summary["dp"]["selisih"], 0.0)
        self.assertEqual(b27.summary["buckets"]["cocok"], 1)
        self.assertEqual(b27.summary["buckets"]["tidak_cocok"], 0)

    def test_batch_baru_tanpa_dobel_hitung(self):
        p, b27 = self._carry_day27()
        # Data murni tanggal 28 + uang untuk settle si carried.
        self._tx(self.panel, "depo", "60000", "60000", "D2", "p2",
                 username="andi", dt=datetime(2026, 6, 28, 9, 0))
        self._tx(self.bank, "depo", "60000", "60000", "", "k3",
                 username="andi", dt=datetime(2026, 6, 28, 10, 0))
        self._tx(self.bank, "depo", "50000", "50000", "", "k2",
                 username="budi", dt=datetime(2026, 6, 28, 1, 0))
        b28 = run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 28))
        # Panel batch 28 murni tanggal 28 — nilai carried (50k) tidak ikut.
        self.assertEqual(b28.summary["dp"]["panel"], 60000.0)
        self.assertEqual(b28.summary["dp"]["money_matched"], 60000.0)
        # Settle terlambat tampil terpisah.
        self.assertEqual(b28.summary["late_settlement"]["dp"],
                         {"count": 1, "amount": 50000.0})

    def test_weak_name_late_jadi_perlu_tinjau(self):
        p, b27 = self._carry_day27()
        self._tx(self.bank, "depo", "50000", "50000", "", "k2",
                 username="bodi", dt=datetime(2026, 6, 28, 1, 0))  # nama lemah
        b28 = run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 28))
        r = MatchResult.objects.get(run__batch=b27, left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.TINJAU)
        self.assertEqual(r.reason_code, "late_settlement")
        self.assertEqual(r.resolved_by_batch, b28)

    def test_expiry_diam_diam_ke_batch_asal(self):
        p, b27 = self._carry_day27()
        # Run 28 tanpa uang yang cocok → p (tanggal 27) lewat window, kadaluarsa.
        self._tx(self.bank, "depo", "90000", "90000", "", "k9",
                 username="rudi", dt=datetime(2026, 6, 28, 10, 0))
        b28 = run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 28))
        p.refresh_from_db()
        self.assertEqual(p.consumed_by_batch, b27)  # pulang diam-diam ke asalnya
        r = MatchResult.objects.get(run__batch=b27, left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.TIDAK)  # status tidak berubah
        self.assertEqual(r.reason_code, "no_money")
        self.assertFalse(MatchResult.objects.filter(run__batch=b28, left=p).exists())
        self.assertEqual(b28.summary["late_settlement"]["expired"],
                         [{"tx": p.id, "home": b27.id}])

    def test_longgar_window2_menunggu_lalu_settle(self):
        longgar = ToleranceProfile.objects.get_or_create(
            name="Longgar", defaults={"date_window_days": 2}
        )[0]
        p = self._tx(self.panel, "depo", "50000", "50000", "D1", "p1",
                     username="budi", dt=datetime(2026, 6, 27, 21, 0))
        self._tx(self.bank, "depo", "70000", "70000", "", "k1", username="siti")
        b27 = run_batch(self.lbs, longgar, recon_date=date(2026, 6, 27))
        # Run 28: belum ada uangnya → masih menunggu (window 2).
        self._tx(self.bank, "depo", "90000", "90000", "", "k9",
                 username="rudi", dt=datetime(2026, 6, 28, 10, 0))
        run_batch(self.lbs, longgar, recon_date=date(2026, 6, 28))
        p.refresh_from_db()
        self.assertIsNone(p.consumed_by_batch)
        # Run 29: uangnya muncul (selisih 2 hari, masih dalam window) → settle.
        self._tx(self.bank, "depo", "50000", "50000", "", "k2",
                 username="budi", dt=datetime(2026, 6, 29, 1, 0))
        b29 = run_batch(self.lbs, longgar, recon_date=date(2026, 6, 29))
        r = MatchResult.objects.get(run__batch=b27, left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.resolved_by_batch, b29)
        p.refresh_from_db()
        self.assertEqual(p.consumed_by_batch, b27)

    def test_guard_tanggal_duplikat_ditolak(self):
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p1", username="budi")
        self._tx(self.bank, "depo", "50000", "50000", "", "k1", username="budi")
        run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 27))
        self._tx(self.panel, "depo", "60000", "60000", "D2", "p2", username="andi")
        self._tx(self.bank, "depo", "60000", "60000", "", "k2", username="andi")
        with self.assertRaises(ValueError):
            run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 27))
        self.assertEqual(
            ReconBatch.objects.filter(toko=self.lbs, recon_date=date(2026, 6, 27)).count(), 1
        )

    def test_gagal_rollback_total_tanggal_tidak_terblokir(self):
        p, b27 = self._carry_day27()
        self._tx(self.bank, "depo", "50000", "50000", "", "k2",
                 username="budi", dt=datetime(2026, 6, 28, 1, 0))
        with mock.patch.object(engine, "_aggregate_batch", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 28))
        # Rollback total: batch 28 tidak tersisa (tanggal tidak terblokir),
        # hasil batch asal tidak ter-flip, tidak ada konsumsi baru.
        self.assertFalse(
            ReconBatch.objects.filter(toko=self.lbs, recon_date=date(2026, 6, 28)).exists()
        )
        r = MatchResult.objects.get(run__batch=b27, left=p)
        self.assertEqual(r.reason_code, "no_money")
        p.refresh_from_db()
        self.assertIsNone(p.consumed_by_batch)
        # Run ulang tanggal 28 setelah gagal → sukses settle.
        b28 = run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 28))
        r.refresh_from_db()
        self.assertEqual(r.resolved_by_batch, b28)

    def test_revert_late_settlements_round_trip(self):
        p, b27 = self._carry_day27()
        uang = self._tx(self.bank, "depo", "50000", "50000", "", "k2",
                        username="budi", dt=datetime(2026, 6, 28, 1, 0))
        b28 = run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 28))
        n = revert_late_settlements(b28)
        self.assertEqual(n, 1)
        r = MatchResult.objects.get(run__batch=b27, left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.TIDAK)
        self.assertEqual(r.reason_code, "no_money")
        self.assertEqual(r.reason_detail, NO_MONEY_DETAIL)
        self.assertIsNone(r.right)
        self.assertEqual(r.score, 0)
        self.assertIsNone(r.resolved_by_batch)
        p.refresh_from_db()
        self.assertIsNone(p.consumed_by_batch)  # aktif lagi, kandidat settle berikutnya
        b27.refresh_from_db()
        self.assertEqual(b27.summary["dp"]["money_matched"], 0.0)
        self.assertEqual(b27.summary["dp"]["selisih"], 50000.0)
        # Hapus batch 28 lalu run ulang tanggal 28 → settle lagi (round-trip).
        b28.delete()
        uang.refresh_from_db()
        self.assertIsNone(uang.consumed_by_batch)
        b28b = run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 28))
        r.refresh_from_db()
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.resolved_by_batch, b28b)

    def test_revert_mengaktifkan_baris_kadaluarsa(self):
        p, b27 = self._carry_day27()
        self._tx(self.bank, "depo", "90000", "90000", "", "k9",
                 username="rudi", dt=datetime(2026, 6, 28, 10, 0))
        b28 = run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 28))
        p.refresh_from_db()
        self.assertEqual(p.consumed_by_batch, b27)  # kadaluarsa ke asal
        revert_late_settlements(b28)
        p.refresh_from_db()
        self.assertIsNone(p.consumed_by_batch)  # bisa menunggu settlement lagi

    def test_carried_tidak_ikut_panel_bracket(self):
        p, b27 = self._carry_day27()
        # Tanggal 28 lengkap dengan bracket → PANEL_BRACKET jalan.
        self._tx(self.panel, "depo", "60000", "60000", "D2", "p2",
                 username="andi", dt=datetime(2026, 6, 28, 9, 0))
        self._tx(self.bracket, "depo", "60000", "60000", "D2", "br2",
                 username="andi", dt=datetime(2026, 6, 28, 9, 0))
        self._tx(self.bank, "depo", "60000", "60000", "", "k3",
                 username="andi", dt=datetime(2026, 6, 28, 10, 0))
        b28 = run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 28))
        # Carried p tidak boleh dapat hasil no_bracket di batch 28.
        self.assertFalse(MatchResult.objects.filter(run__batch=b28, left=p).exists())
