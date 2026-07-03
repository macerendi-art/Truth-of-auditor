"""Nomor batch tampil = posisi urut per-toko (bukan pk global). Lihat tests_reconcile.py untuk pola."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import Toko

User = get_user_model()


class BatchNumberTests(TestCase):
    def setUp(self):
        User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.lbs = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def test_dua_batch_bernomor_1_dan_2(self):
        ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, ">#1</a>")
        self.assertContains(r, ">#2</a>")

    def test_hapus_semua_lalu_batch_baru_mulai_dari_1_lagi(self):
        b1 = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        b2 = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        b1.delete()
        b2.delete()
        ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, ">#1</a>")
        self.assertNotContains(r, ">#3</a>")  # bukan pk global (batch ke-3 yang pernah dibuat)

    def test_batch_detail_h1_pakai_nomor_urut(self):
        b1 = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        r = self.client.get(reverse("batch_detail", args=[b1.pk]))
        self.assertContains(r, "Batch #1")

    def test_scoping_per_toko_toko_lain_sudah_5_batch(self):
        lain = Toko.objects.exclude(key="lbs").first()
        for _ in range(5):
            ReconBatch.objects.create(toko=lain, tolerance=self.tol)
        ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, ">#1</a>")
