"""UX flow reconcile harian: saran tanggal otomatis + konfirmasi tanggal kosong.

Latar: form reconcile dengan tanggal kosong = rekonsiliasi SEMUA data aktif jadi
satu batch — footgun yang pernah menelan 3 hari sample sekaligus. Perbaikan:
1. GET /rekonsiliasi/ tanpa param tanggal → form di-prefill tanggal yang
   disarankan (hari setelah window batch terakhir; kalau belum ada batch
   berjendela, tanggal transaksi AKTIF tertua).
2. Submit dengan kedua tanggal kosong → dicegat modal konfirmasi (data-confirm
   di-toggle dinamis oleh script di reconcile.html).
"""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.engine import run_batch
from reconciliation.models import ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


class _Base(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get(name="Default")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})


class SaranTanggalTests(_Base):
    def test_prefill_hari_setelah_batch_terakhir(self):
        run_batch(self.lbs, self.tol, date_from=date(2026, 6, 27), date_to=date(2026, 6, 27))
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, 'value="2026-06-28"')

    def test_prefill_tanggal_data_aktif_tertua_tanpa_batch(self):
        up = Upload.objects.create(source_type=self.panel, toko=self.lbs)
        Transaction.objects.create(
            upload=up, source_type=self.panel, toko=self.lbs, jenis="depo",
            amount=Decimal("50000"), money_delta=Decimal("-50000"),
            occurred_at=datetime(2026, 6, 27, 21, 0), row_hash="p27",
        )
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, 'value="2026-06-27"')

    def test_param_eksplisit_menang_atas_saran(self):
        run_batch(self.lbs, self.tol, date_from=date(2026, 6, 27), date_to=date(2026, 6, 27))
        r = self.client.get(reverse("reconcile") + "?date_from=2026-06-01&date_to=2026-06-02")
        self.assertContains(r, 'value="2026-06-01"')
        self.assertContains(r, 'value="2026-06-02"')
        self.assertNotContains(r, 'value="2026-06-28"')

    def test_tanpa_data_tanpa_batch_form_kosong(self):
        r = self.client.get(reverse("reconcile"))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Tanggal disarankan")


class KonfirmasiTanggalKosongTests(_Base):
    def test_script_toggle_konfirmasi_ada(self):
        # Script di reconcile.html men-set data-confirm HANYA saat kedua tanggal
        # kosong; pesan menyebut konsekuensi "SEMUA data aktif".
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, "SEMUA data aktif")
        self.assertContains(r, "jalankan-form")
