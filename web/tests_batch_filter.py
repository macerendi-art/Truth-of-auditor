"""Filter sumber uang (Mutasi Bank) di Riwayat Batch — nomor batch tetap posisi asli.

Pola setup (user + toko + session + login) mengikuti tests_batch_number.py.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import Toko

User = get_user_model()


class BatchFilterSumberTests(TestCase):
    def setUp(self):
        User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.lbs = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def _batch(self, **comp):
        return ReconBatch.objects.create(
            toko=self.lbs, tolerance=self.tol, completeness=comp
        )

    def test_regresi_hapus_dua_tertua_tambah_satu(self):
        """3 batch → hapus 2 tertua → tambah 1 → nomor mulai #1 lagi (bukan pk global)."""
        b1 = self._batch(bank=True)
        b2 = self._batch(bank=True)
        self._batch(bank=True)
        b1.delete()
        b2.delete()
        self._batch(bank=True)
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, ">#1</a>")
        self.assertContains(r, ">#2</a>")
        self.assertNotContains(r, ">#3</a>")

    def test_filter_bank_nomor_tetap_posisi_asli(self):
        """?bank=bank: batch ke-2 (gateway saja) hilang; sisanya tetap #1 & #3, bukan #1 & #2."""
        self._batch(bank=True, gateway=False)
        self._batch(bank=False, gateway=True)  # batch ke-2: bukan bank
        self._batch(bank=True, gateway=False)
        r = self.client.get(reverse("reconcile"), {"bank": "bank"})
        self.assertContains(r, ">#1</a>")
        self.assertContains(r, ">#3</a>")
        self.assertNotContains(r, ">#2</a>")

    def test_filter_gateway_nomor_tetap_posisi_asli(self):
        """?bank=gateway: hanya batch ke-2 yang punya gateway → tampil #2 saja (bukan #1)."""
        self._batch(bank=True, gateway=False)
        self._batch(bank=False, gateway=True)  # hanya batch ke-2 gateway
        self._batch(bank=True, gateway=False)
        r = self.client.get(reverse("reconcile"), {"bank": "gateway"})
        self.assertContains(r, ">#2</a>")
        self.assertNotContains(r, ">#1</a>")
        self.assertNotContains(r, ">#3</a>")

    def test_tanpa_filter_semua_tampil(self):
        self._batch(bank=True, gateway=False)
        self._batch(bank=False, gateway=True)
        self._batch(bank=True, gateway=True)
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, ">#1</a>")
        self.assertContains(r, ">#2</a>")
        self.assertContains(r, ">#3</a>")

    def test_bank_tidak_valid_diperlakukan_semua(self):
        """?bank=xxx bukan nilai valid → diperlakukan seperti tanpa filter, tidak error."""
        self._batch(bank=True, gateway=False)
        self._batch(bank=False, gateway=True)
        r = self.client.get(reverse("reconcile"), {"bank": "xxx"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, ">#1</a>")
        self.assertContains(r, ">#2</a>")

    def test_filter_aktif_hasil_kosong_pesan_khusus(self):
        """Filter aktif tapi tak ada batch cocok → pesan khusus, bukan 'Belum ada batch.'."""
        self._batch(bank=True, gateway=False)
        r = self.client.get(reverse("reconcile"), {"bank": "gateway"})
        self.assertContains(r, "Tidak ada batch dengan sumber ini.")
        self.assertNotContains(r, "Belum ada batch.")
