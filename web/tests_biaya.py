"""Rincian Biaya admin: agregasi web.biaya + view /biaya-admin/."""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.biaya import rincian_biaya

TGL = date(2026, 7, 17)


class _BiayaData(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.bank = SourceType.objects.get_or_create(
            key="bank", defaults={"name": "Bank"})[0]
        self.up_bri = Upload.objects.create(
            source_type=self.bank, toko=self.toko,
            original_name="17_07_2026_WD_BRI_NASRUL.csv", owner_name="NASRUL")
        self._n = 0

    def tx(self, up, desc, amount, jenis="wd", tanggal=TGL):
        self._n += 1
        return Transaction.objects.create(
            upload=up, source_type=self.bank, toko=self.toko, jenis=jenis,
            amount=Decimal(amount), money_delta=-Decimal(amount),
            posted_date=tanggal, occurred_at=datetime(2026, 7, 17, 10, 0),
            description=desc, row_hash=f"by{self._n}")


class AgregasiBiayaTests(_BiayaData):
    def test_bertanda_admin_dan_legacy_rule_ikut(self):
        self.tx(self.up_bri, "BFST123 NBMB:X", "2500", jenis="admin")   # bertanda
        self.tx(self.up_bri, "ATMSTRPRM 0888", "6500", jenis="wd")     # legacy tanpa tanda
        self.tx(self.up_bri, "BRIVA30135082 NBMB", "1000", jenis="wd") # legacy
        self.tx(self.up_bri, "NBMB ANDI TO BUDI ESB", "500000", jenis="wd")  # transfer nyata
        data = rincian_biaya(self.toko, dari=TGL, sampai=TGL)
        self.assertEqual(data["ringkas"]["n"], 3)
        self.assertEqual(data["ringkas"]["total"], Decimal("10000"))
        kanal = data["ringkas"]["kanal"]
        self.assertEqual(kanal["BI Fast"]["total"], Decimal("2500"))
        self.assertEqual(kanal["Transfer online"]["total"], Decimal("6500"))
        self.assertEqual(kanal["E-wallet"]["total"], Decimal("1000"))

    def test_rentang_tanggal(self):
        self.tx(self.up_bri, "BFST1", "2500", jenis="admin", tanggal=date(2026, 7, 1))
        self.tx(self.up_bri, "BFST2", "2500", jenis="admin", tanggal=TGL)
        data = rincian_biaya(self.toko, dari=date(2026, 7, 10), sampai=TGL)
        self.assertEqual(data["ringkas"]["n"], 1)

    def test_baris_per_tanggal_sumber(self):
        self.tx(self.up_bri, "BFST1", "2500", jenis="admin")
        self.tx(self.up_bri, "BFST2", "2500", jenis="admin")
        data = rincian_biaya(self.toko, dari=TGL, sampai=TGL)
        (baris,) = data["rows"]
        self.assertEqual(baris["tanggal"], TGL)
        self.assertIn("BRI", baris["sumber"])
        self.assertEqual(baris["n"], 2)
        self.assertEqual(baris["total"], Decimal("5000"))


class BiayaViewTests(_BiayaData):
    def setUp(self):
        super().setUp()
        u = get_user_model().objects.create_user(
            username="aud_b", password="rahasia123", role="auditor")
        u.allowed_tokos.add(self.toko)
        self.client.force_login(u)
        s = self.client.session
        s["active_toko_id"] = self.toko.id
        s.save()

    def test_halaman_render(self):
        self.tx(self.up_bri, "BFST1", "2500", jenis="admin")
        r = self.client.get(reverse("rincian_biaya"),
                            {"dari": "2026-07-01", "sampai": "2026-07-31"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Rincian Biaya")
        self.assertContains(r, "2.500")

    def test_kosong_empty_state(self):
        r = self.client.get(reverse("rincian_biaya"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Belum ada")
