"""UI rekonsiliasi harian: preview auto-split per tanggal, skip tanggal ber-batch,
seksi settlement, dan revert late settlement saat batch penyelesai dihapus."""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.engine import run_batch
from reconciliation.models import MatchResult, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class _LoggedIn(TestCase):
    role = "supervisor"

    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role=self.role)
        self.client.login(username="aud", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.lbs = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _tx(self, st, jenis, amount, money, ticket, rh, dt=datetime(2026, 6, 27, 10, 0), **kw):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.lbs, jenis=jenis,
            amount=Decimal(amount), money_delta=Decimal(money), ticket_no=ticket,
            occurred_at=dt, row_hash=rh, **kw,
        )

    def _flow_27_28(self):
        """Run 27 dengan carry, lalu run 28 yang men-settle-nya."""
        p = self._tx(self.panel, "depo", "50000", "50000", "D1", "p1",
                     username="budi", dt=datetime(2026, 6, 27, 21, 0))
        self._tx(self.bank, "depo", "70000", "70000", "", "k1", username="siti")
        b27 = run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 27))
        self._tx(self.bank, "depo", "50000", "50000", "", "k2",
                 username="budi", dt=datetime(2026, 6, 28, 1, 0))
        b28 = run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 28))
        return p, b27, b28


class ReconDateFormTests(_LoggedIn):
    def test_form_preview_tanggal_dan_kolom_tanggal(self):
        # Auto-split: date picker manual dihapus, diganti preview tanggal panel.
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p1", username="budi")
        self._tx(self.bank, "depo", "50000", "50000", "", "k1", username="budi")
        run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 27))
        r = self.client.get(reverse("reconcile"))
        html = r.content.decode()
        self.assertNotIn('name="recon_date"', html)  # tak ada lagi field manual
        self.assertIn("Tanggal yang akan diproses", html)  # preview auto-split
        self.assertIn("<th>Tanggal</th>", html)

    def test_post_tanpa_recon_date_auto_split(self):
        # Tanpa recon_date manual: tanggal dideteksi dari data (27 Jun) → 1 batch.
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p1", username="budi")
        self._tx(self.bank, "depo", "50000", "50000", "", "k1", username="budi")
        self.client.post(reverse("reconcile"), {
            "tolerance": "Default", "inc_panel_dp": "on", "inc_bank": "on",
        })
        self.assertEqual(
            ReconBatch.objects.filter(toko=self.lbs, recon_date=date(2026, 6, 27)).count(), 1
        )

    def test_tanggal_sudah_ada_batch_dilewati(self):
        # Run pertama bikin batch 27. Lalu panel-27 susulan aktif + data 28:
        # auto-run melewati 27 (dilaporkan), hanya bikin batch 28, tak menggandakan 27.
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p1", username="budi")
        self._tx(self.bank, "depo", "50000", "50000", "", "k1", username="budi")
        self.client.post(reverse("reconcile"), {
            "tolerance": "Default", "inc_panel_dp": "on", "inc_bank": "on",
        })
        self.assertEqual(
            ReconBatch.objects.filter(toko=self.lbs, recon_date=date(2026, 6, 27)).count(), 1
        )
        self._tx(self.panel, "depo", "80000", "80000", "D9", "p9", username="rian")
        self._tx(self.panel, "depo", "60000", "60000", "D2", "p2",
                 username="andi", dt=datetime(2026, 6, 28, 9, 0))
        self._tx(self.bank, "depo", "60000", "60000", "", "k2",
                 username="andi", dt=datetime(2026, 6, 28, 10, 0))
        r = self.client.post(reverse("reconcile"), {
            "tolerance": "Default", "inc_panel_dp": "on", "inc_bank": "on",
        }, follow=True)
        self.assertContains(r, "dilewati")
        self.assertEqual(
            ReconBatch.objects.filter(toko=self.lbs, recon_date=date(2026, 6, 27)).count(), 1
        )
        self.assertEqual(
            ReconBatch.objects.filter(toko=self.lbs, recon_date=date(2026, 6, 28)).count(), 1
        )

    def test_pending_settlement_info_muncul(self):
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p1",
                 username="budi", dt=datetime(2026, 6, 27, 21, 0))
        self._tx(self.bank, "depo", "70000", "70000", "", "k1", username="siti")
        run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 27))
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, "menunggu settlement")


class SettlementDisplayTests(_LoggedIn):
    def test_batch_penyelesai_menampilkan_settlement_tertunda(self):
        p, b27, b28 = self._flow_27_28()
        r = self.client.get(reverse("batch_detail", args=[b28.pk]))
        self.assertContains(r, "Settlement tertunda")
        self.assertContains(r, "50,000")  # intcomma, konsisten dgn tampilan lain

    def test_batch_asal_menampilkan_catatan_di_settle(self):
        p, b27, b28 = self._flow_27_28()
        r = self.client.get(reverse("batch_detail", args=[b27.pk]))
        self.assertContains(r, "di-settle terlambat")

    def test_batch_menampilkan_catatan_susulan(self):
        # Batch 27 rapi, lalu baris bertanggal 27 muncul susulan di run 28.
        self._tx(self.panel, "depo", "50000", "50000", "D1", "p1", username="budi")
        self._tx(self.bank, "depo", "50000", "50000", "", "k1", username="budi")
        run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 27))
        self._tx(self.bank, "depo", "90000", "90000", "", "k3",
                 username="rudi", dt=datetime(2026, 6, 27, 23, 30))
        b28 = run_batch(self.lbs, self.tol, recon_date=date(2026, 6, 28))
        r = self.client.get(reverse("batch_detail", args=[b28.pk]))
        self.assertContains(r, "susulan")

    def test_batch_detail_menampilkan_tanggal(self):
        p, b27, b28 = self._flow_27_28()
        r = self.client.get(reverse("batch_detail", args=[b27.pk]))
        self.assertContains(r, "Tanggal 27/06/2026")


class DeleteRevertTests(_LoggedIn):
    role = "admin"

    def test_hapus_batch_penyelesai_revert_flip(self):
        p, b27, b28 = self._flow_27_28()
        r = self.client.post(reverse("delete_batch", args=[b28.pk]), follow=True)
        self.assertFalse(ReconBatch.objects.filter(pk=b28.pk).exists())
        self.assertContains(r, "dikembalikan")
        res = MatchResult.objects.get(run__batch=b27, left=p)
        self.assertEqual(res.bucket, MatchResult.Bucket.TIDAK)
        self.assertEqual(res.reason_code, "no_money")
        p.refresh_from_db()
        self.assertIsNone(p.consumed_by_batch)  # menunggu settlement lagi
