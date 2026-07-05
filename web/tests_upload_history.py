"""Riwayat upload di-cap 20 baris — file lama TAK hilang, cuma tak tampil.

User panik "file lama hilang" setelah upload batch besar mendorong baris lama
keluar layar. Header wajib jujur soal cap + sedia tombol tampilkan semua.
"""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload

User = get_user_model()


class RiwayatUploadCapTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.st = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]

    def _mk(self, n):
        for _ in range(n):
            Upload.objects.create(source_type=self.st, toko=self.lbs)

    def test_di_bawah_cap_tanpa_keterangan(self):
        self._mk(3)
        r = self.client.get(reverse("upload"))
        self.assertNotContains(r, "Tampilkan semua")
        self.assertEqual(len(r.context["uploads"]), 3)

    def test_di_atas_cap_header_jujur_dan_ada_tombol_semua(self):
        self._mk(25)
        r = self.client.get(reverse("upload"))
        self.assertEqual(len(r.context["uploads"]), 20)
        self.assertContains(r, "20 terbaru dari 25")
        self.assertContains(r, "Tampilkan semua")

    def test_param_semua_tampilkan_seluruhnya(self):
        self._mk(25)
        r = self.client.get(reverse("upload") + "?semua=1")
        self.assertEqual(len(r.context["uploads"]), 25)
        self.assertNotContains(r, "Tampilkan semua")
