"""Guard urutan reconcile (F4).

Menjalankan tanggal N sebelum N-1 direkonsiliasi = batch N bisa mengonsumsi uang
milik panel N-1 (window sisi uang melebar) → cocok palsu PERMANEN (re-match tak
pernah mencuri balik). Halaman reconcile membawa tanggal saran di atribut
`data-saran`; JS menyalakan modal konfirmasi bila tanggal dipilih melompati saran.
"""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


class OrderGuardTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get(name="Default")
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def test_form_membawa_data_saran(self):
        ReconBatch.objects.create(
            toko=self.lbs, tolerance=self.tol,
            date_from=date(2026, 6, 27), date_to=date(2026, 6, 27), summary={},
        )
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, 'data-saran="2026-06-28"')

    def test_data_saran_tetap_ada_saat_tanggal_eksplisit(self):
        # User buka ?date_from=2026-06-30 (loncat) — guard butuh saran utk deteksi gap.
        ReconBatch.objects.create(
            toko=self.lbs, tolerance=self.tol,
            date_from=date(2026, 6, 27), date_to=date(2026, 6, 27), summary={},
        )
        r = self.client.get(reverse("reconcile") + "?date_from=2026-06-30&date_to=2026-06-30")
        self.assertContains(r, 'data-saran="2026-06-28"')

    def test_tanpa_data_tanpa_saran(self):
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, 'data-saran=""')

    def test_script_guard_urutan_terpasang(self):
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, "belum direkonsiliasi")  # teks modal gap
        self.assertContains(r, "salah-atribusi")


class SaranFallbackPanelTests(TestCase):
    """Tanpa batch, saran = tanggal PANEL aktif tertua — bukan tanggal transaksi
    apa pun. Statement bank diekspor sebulan penuh (mulai tgl 1), kalau ikut
    dihitung saran selalu keseret ke awal bulan padahal data panel mulai belakangan.
    """

    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self._n = 0

    def _tx(self, key, when):
        self._n += 1
        st = SourceType.objects.get_or_create(key=key, defaults={"name": key.title()})[0]
        up = Upload.objects.create(source_type=st, toko=self.lbs)
        return Transaction.objects.create(
            upload=up, source_type=st, toko=self.lbs, jenis="dp",
            amount=Decimal("50000"), money_delta=Decimal("50000"),
            occurred_at=when, row_hash=f"sf{self._n}",
        )

    def test_saran_pakai_panel_tertua_bukan_bank(self):
        self._tx("bank", datetime(2026, 6, 1, 10, 0))    # statement full-month
        self._tx("panel", datetime(2026, 6, 27, 10, 0))  # data panel mulai 27
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, 'data-saran="2026-06-27"')

    def test_hanya_bank_fallback_ke_tanggal_bank(self):
        self._tx("bank", datetime(2026, 6, 1, 10, 0))
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, 'data-saran="2026-06-01"')
