"""Rekonsiliasi Bonus panel<->bracket: agregasi web.bonus + view /bonus/."""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.bonus import rekonsiliasi_bonus

TGL = date(2026, 7, 17)


class _BonusData(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.panel = SourceType.objects.get(key="panel_bonus")
        self.bracket = SourceType.objects.get(key="bracket_bonus")
        self.up_panel = Upload.objects.create(
            source_type=self.panel, toko=self.toko,
            original_name="17_07_2026_BONUS_PANEL.xlsx")
        self.up_bracket = Upload.objects.create(
            source_type=self.bracket, toko=self.toko,
            original_name="17_07_2026_BONUS_BRACKET.xlsx")
        self._n = 0

    def buat(self, up, st, username, amount, kategori="Lucky Draw",
             tanggal=TGL, desc=None):
        self._n += 1
        return Transaction.objects.create(
            upload=up, source_type=st, toko=self.toko, jenis="bonus",
            amount=Decimal(amount), money_delta=Decimal("0"), ticket_no="",
            username=username, posted_date=tanggal,
            occurred_at=datetime(tanggal.year, tanggal.month, tanggal.day, 10, 0),
            description=desc or f"{kategori} {username}",
            raw={"Kategori": kategori}, row_hash=f"bn{self._n}")

    def panel_row(self, username, amount, **kw):
        return self.buat(self.up_panel, self.panel, username, amount, **kw)

    def bracket_row(self, username, amount, **kw):
        return self.buat(self.up_bracket, self.bracket, username, amount, **kw)


class AgregasiBonusTests(_BonusData):
    def test_pasangan_beda_kapital_cocok(self):
        self.panel_row("BudiSlot", "50000")
        self.bracket_row("budislot", "50000")
        data = rekonsiliasi_bonus(self.toko, dari=TGL, sampai=TGL)
        self.assertEqual(len(data["cocok"]), 1)
        self.assertEqual(len(data["panel_only"]), 0)
        self.assertEqual(len(data["bracket_only"]), 0)
        pasangan = data["cocok"][0]
        self.assertEqual(pasangan["panel"]["username"], "BudiSlot")
        self.assertEqual(pasangan["bracket"]["username"], "budislot")

    def test_panel_tanpa_pasangan_masuk_panel_only(self):
        self.panel_row("Sendy", "20000")
        data = rekonsiliasi_bonus(self.toko, dari=TGL, sampai=TGL)
        self.assertEqual(len(data["cocok"]), 0)
        self.assertEqual(len(data["panel_only"]), 1)
        self.assertEqual(data["panel_only"][0]["username"], "Sendy")

    def test_bracket_tanpa_pasangan_masuk_bracket_only(self):
        self.bracket_row("Andi", "15000")
        data = rekonsiliasi_bonus(self.toko, dari=TGL, sampai=TGL)
        self.assertEqual(len(data["cocok"]), 0)
        self.assertEqual(len(data["bracket_only"]), 1)
        self.assertEqual(data["bracket_only"][0]["username"], "Andi")

    def test_greedy_1_ke_1_dua_panel_satu_bracket(self):
        self.panel_row("Doni", "10000")
        self.panel_row("Doni", "10000")
        self.bracket_row("doni", "10000")
        data = rekonsiliasi_bonus(self.toko, dari=TGL, sampai=TGL)
        self.assertEqual(len(data["cocok"]), 1)
        self.assertEqual(len(data["panel_only"]), 1)
        self.assertEqual(len(data["bracket_only"]), 0)

    def test_rentang_tanggal_memfilter(self):
        self.panel_row("Rina", "30000", tanggal=date(2026, 7, 1))
        self.bracket_row("rina", "30000", tanggal=date(2026, 7, 1))
        self.panel_row("Rina", "30000", tanggal=TGL)
        self.bracket_row("rina", "30000", tanggal=TGL)
        data = rekonsiliasi_bonus(self.toko, dari=date(2026, 7, 10), sampai=TGL)
        self.assertEqual(len(data["cocok"]), 1)

    def test_ringkas_per_kategori(self):
        self.panel_row("A", "10000", kategori="Lucky Draw")
        self.bracket_row("a", "10000", kategori="Lucky Draw")
        self.panel_row("B", "20000", kategori="Redemption Coupon")
        self.bracket_row("c", "5000", kategori="Adjustment")
        data = rekonsiliasi_bonus(self.toko, dari=TGL, sampai=TGL)
        kat = data["ringkas"]["kategori"]
        self.assertEqual(kat["Lucky Draw"]["cocok"], 1)
        self.assertEqual(kat["Redemption Coupon"]["panel_only"], 1)
        self.assertEqual(kat["Adjustment"]["bracket_only"], 1)
        self.assertEqual(data["ringkas"]["cocok"]["n"], 1)
        self.assertEqual(data["ringkas"]["panel_only"]["n"], 1)
        self.assertEqual(data["ringkas"]["bracket_only"]["n"], 1)


class BonusViewTests(_BonusData):
    def setUp(self):
        super().setUp()
        u = get_user_model().objects.create_user(
            username="aud_bn", password="rahasia123", role="auditor")
        u.allowed_tokos.add(self.toko)
        self.client.force_login(u)
        s = self.client.session
        s["active_toko_id"] = self.toko.id
        s.save()

    def test_halaman_render(self):
        self.panel_row("Cici", "40000")
        self.bracket_row("cici", "40000")
        r = self.client.get(reverse("bonus_recon"),
                            {"dari": "2026-07-01", "sampai": "2026-07-31"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Rekonsiliasi Bonus")

    def test_kosong_empty_state(self):
        r = self.client.get(reverse("bonus_recon"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Belum ada")

    def test_menu_link_muncul(self):
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, reverse("bonus_recon"))
