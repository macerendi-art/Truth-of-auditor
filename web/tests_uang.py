"""Halaman Uang Tanpa Pasangan (/batch/<pk>/uang/) + kartu di batch detail."""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.engine import run_batch
from reconciliation.models import ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

D = Decimal


class BatchUangTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        up_p = Upload.objects.create(source_type=panel, toko=self.toko,
                                     original_name="HISTORI PANEL.xlsx")
        up_b = Upload.objects.create(source_type=bank, toko=self.toko,
                                     original_name="27_WD_BCA_HENDI.csv")
        n = iter(range(100))
        def tx(st, up, jenis, md, dt, **kw):
            return Transaction.objects.create(
                upload=up, source_type=st, toko=self.toko, jenis=jenis,
                amount=D(str(abs(md))), money_delta=D(str(md)), occurred_at=dt,
                row_hash=f"u{next(n)}", **kw,
            )
        tx(panel, up_p, "depo", 10000, datetime(2026, 6, 27, 8),
           ticket_no="D1", counterparty="PAS OK")
        tx(bank, up_b, "depo", 10000, datetime(2026, 6, 27, 9), counterparty="PAS OK")
        self.d_row = tx(bank, up_b, "wd", -14000, datetime(2026, 6, 27, 9),
                        counterparty="TANPA PENJELASAN")
        self.a_row = tx(bank, up_b, "depo", 11000, datetime(2026, 6, 20, 9),
                        counterparty="HISTORI LAMA")
        self.batch = run_batch(self.toko, self.tol, recon_date=date(2026, 6, 27))

    def test_kartu_muncul_di_batch_detail(self):
        r = self.client.get(reverse("batch_detail", args=[self.batch.pk]))
        self.assertContains(r, "Uang tanpa pasangan")
        self.assertContains(r, reverse("batch_uang", args=[self.batch.pk]))

    def test_halaman_daftar_dan_filter(self):
        r = self.client.get(reverse("batch_uang", args=[self.batch.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "TANPA PENJELASAN")
        self.assertContains(r, "HISTORI LAMA")
        r = self.client.get(reverse("batch_uang", args=[self.batch.pk]) + "?k=d")
        self.assertContains(r, "TANPA PENJELASAN")
        self.assertNotContains(r, "HISTORI LAMA")

    def test_export_excel(self):
        r = self.client.get(reverse("batch_uang", args=[self.batch.pk]) + "?export=1")
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r["Content-Type"])

    def test_rbac_auditor_toko_lain_ditolak(self):
        User = get_user_model()
        u = User.objects.create_user("audlain", "b@b.co", "pw12345", role="auditor")
        other = Toko.objects.exclude(pk=self.toko.pk).first()
        u.allowed_tokos.add(other)
        self.client.login(username="audlain", password="pw12345")
        r = self.client.get(reverse("batch_uang", args=[self.batch.pk]))
        self.assertEqual(r.status_code, 404)
