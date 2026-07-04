"""F6 — CTA langkah berikutnya di halaman Upload.

Setelah upload, auditor harus langsung diarahkan ke langkah ritual berikutnya:
reconcile tanggal yang disarankan. Tanpa data (belum ada transaksi aktif yang
belum direkonsiliasi), tidak ada saran → CTA tidak boleh muncul.
"""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


class _Base(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})


class NextStepCtaTests(_Base):
    def test_ada_saran_tampilkan_cta(self):
        up = Upload.objects.create(source_type=self.panel, toko=self.lbs)
        Transaction.objects.create(
            upload=up, source_type=self.panel, toko=self.lbs, jenis="depo",
            amount=Decimal("50000"), money_delta=Decimal("-50000"),
            occurred_at=datetime(2026, 6, 28, 10, 0), row_hash="cta1",
            is_duplicate=False, consumed_by_batch=None,
        )
        r = self.client.get(reverse("upload"))
        self.assertContains(r, "Langkah berikutnya")
        self.assertContains(r, "28 Jun 2026")

    def test_tanpa_data_tidak_ada_cta(self):
        r = self.client.get(reverse("upload"))
        self.assertNotContains(r, "Langkah berikutnya")
