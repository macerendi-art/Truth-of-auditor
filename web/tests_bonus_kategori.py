"""Fitur I2 /bonus/: kategori detail + filter kategori + nilai ringkasan.

Kategori tampilan sisi panel = detail program yang diekstrak dari Description
("Promotion Claim: BONUS X - [D...] - user" -> "BONUS X"), fallback ke kategori
kanonik lama; sisi bracket tetap memakai kategorinya sendiri (kolom Category
sudah detail). Filter kategori dieksekusi PASCA-pairing (display-only) supaya
hasil cocok tidak berubah oleh filter.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.urls import reverse

from web.bonus import kategori_detail, rekonsiliasi_bonus
from web.tests_bonus import TGL, _BonusData

DESC_PROMO = "Promotion Claim: BONUS ROLLINGAN SLOT 0.5% DAILY - [D6463335] - BMSuser"


class KategoriDetailTests(SimpleTestCase):
    """Ekstraksi detail dari Description panel_bonus (contoh data nyata)."""

    def test_promotion_claim_diekstrak(self):
        self.assertEqual(kategori_detail("Promotion Claim", DESC_PROMO),
                         "BONUS ROLLINGAN SLOT 0.5% DAILY")

    def test_spasi_ganda_data_nyata_m77(self):
        # Dataset M77 punya dua spasi setelah " - " terakhir.
        self.assertEqual(
            kategori_detail("Promotion Claim",
                            "Promotion Claim: BONUS BOLA 10% - [D6232827] -  M77Gemusniko97"),
            "BONUS BOLA 10%")

    def test_redemption_fallback_kategori_lama(self):
        # Tak ada segmen " - [" -> jatuh ke kategori kanonik.
        self.assertEqual(
            kategori_detail("Redemption Coupon",
                            "Redemption Coupon: CREDIT 15.000 - x:1 M77mulyakan"),
            "Redemption Coupon")

    def test_adjustment_username_tidak_bocor(self):
        self.assertEqual(kategori_detail("Adjustment", "Adjustment: M77ubay789"),
                         "Adjustment")

    def test_lucky_draw_fallback(self):
        self.assertEqual(
            kategori_detail("Lucky Draw",
                            "Lucky Draw Agent: Gold Ticket - Event GASCOR Mingguan "
                            "Juli Periode 3 (7th Reward) M77Pratama121"),
            "Lucky Draw")

    def test_desc_kosong_atau_none(self):
        self.assertEqual(kategori_detail("Promotion Claim", ""), "Promotion Claim")
        self.assertEqual(kategori_detail("Promotion Claim", None), "Promotion Claim")
        self.assertEqual(kategori_detail("", None), "Bonus")


class _DataKategori(_BonusData):
    """P1+B1 berpasangan (kunci username+nominal+tanggal); P2 panel_only;
    B2 bracket_only. Kategori sengaja beda-beda per baris."""

    def isi(self):
        self.panel_row("BMSuser", "50000", kategori="Promotion Claim",
                       desc=DESC_PROMO)
        self.bracket_row("bmsuser", "50000", kategori="Lucky Draw",
                         desc="Player: bmsuser")
        self.panel_row("Cici", "20000", kategori="Redemption Coupon",
                       desc="Redemption Coupon: CREDIT 20.000 - x:1 M77Cici")
        self.bracket_row("Dodi", "15000", kategori="BONUS LOYALTY MURAH (BL1)",
                         desc="Player: Dodi")


class KategoriDetailAgregasiTests(_DataKategori):
    def test_baris_membawa_kategori_detail(self):
        self.isi()
        data = rekonsiliasi_bonus(self.toko, dari=TGL, sampai=TGL)
        self.assertEqual(data["cocok"][0]["panel"]["kategori_detail"],
                         "BONUS ROLLINGAN SLOT 0.5% DAILY")
        # Sisi bracket TIDAK diekstrak dari description — pakai kategorinya.
        self.assertEqual(data["cocok"][0]["bracket"]["kategori_detail"],
                         "Lucky Draw")
        self.assertEqual(data["panel_only"][0]["kategori_detail"],
                         "Redemption Coupon")
        self.assertEqual(data["bracket_only"][0]["kategori_detail"],
                         "BONUS LOYALTY MURAH (BL1)")

    def test_ringkas_kategori_pakai_detail_plus_nilai(self):
        self.isi()
        data = rekonsiliasi_bonus(self.toko, dari=TGL, sampai=TGL)
        kat = data["ringkas"]["kategori"]
        promo = kat["BONUS ROLLINGAN SLOT 0.5% DAILY"]
        self.assertEqual(promo["cocok"], 1)
        self.assertEqual(promo["cocok_total"], Decimal("50000"))
        self.assertEqual(promo["panel_only"], 0)
        self.assertEqual(promo["panel_only_total"], Decimal("0"))
        red = kat["Redemption Coupon"]
        self.assertEqual(red["panel_only"], 1)
        self.assertEqual(red["panel_only_total"], Decimal("20000"))
        bl1 = kat["BONUS LOYALTY MURAH (BL1)"]
        self.assertEqual(bl1["bracket_only"], 1)
        self.assertEqual(bl1["bracket_only_total"], Decimal("15000"))

    def test_kategori_opsi_urut_abjad(self):
        self.isi()
        data = rekonsiliasi_bonus(self.toko, dari=TGL, sampai=TGL)
        self.assertEqual(data["kategori_opsi"],
                         ["BONUS LOYALTY MURAH (BL1)",
                          "BONUS ROLLINGAN SLOT 0.5% DAILY",
                          "Redemption Coupon"])

    def test_filter_kategori_memfilter_list_dan_ringkas(self):
        self.isi()
        data = rekonsiliasi_bonus(self.toko, dari=TGL, sampai=TGL,
                                  kategori="Redemption Coupon")
        self.assertEqual(len(data["cocok"]), 0)
        self.assertEqual(len(data["panel_only"]), 1)
        self.assertEqual(len(data["bracket_only"]), 0)
        self.assertEqual(data["ringkas"]["cocok"]["n"], 0)
        self.assertEqual(data["ringkas"]["panel_only"]["n"], 1)
        self.assertEqual(data["ringkas"]["panel_only"]["total"], Decimal("20000"))
        self.assertEqual(list(data["ringkas"]["kategori"].keys()),
                         ["Redemption Coupon"])
        # Opsi dropdown tetap lengkap walau sedang difilter.
        self.assertEqual(len(data["kategori_opsi"]), 3)

    def test_filter_tidak_mengubah_pairing(self):
        """Filter pasca-pairing: bracket yang sudah terkonsumsi pasangan tidak
        bocor ke bracket_only meski difilter dengan kategorinya sendiri."""
        self.isi()
        data = rekonsiliasi_bonus(self.toko, dari=TGL, sampai=TGL,
                                  kategori="Lucky Draw")
        self.assertEqual(len(data["cocok"]), 0)
        self.assertEqual(len(data["panel_only"]), 0)
        self.assertEqual(len(data["bracket_only"]), 0)


class BonusKategoriViewTests(_DataKategori):
    def setUp(self):
        super().setUp()
        u = get_user_model().objects.create_user(
            username="aud_kat", password="rahasia123", role="auditor")
        u.allowed_tokos.add(self.toko)
        self.client.force_login(u)
        s = self.client.session
        s["active_toko_id"] = self.toko.id
        s.save()

    def test_dropdown_dan_link_tab_membawa_kategori(self):
        self.isi()
        r = self.client.get(reverse("bonus_recon"),
                            {"dari": "2026-07-01", "sampai": "2026-07-31",
                             "kategori": "BONUS ROLLINGAN SLOT 0.5% DAILY"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Semua kategori")
        # Opsi dropdown tetap lengkap walau sedang difilter.
        self.assertContains(r, "BONUS LOYALTY MURAH (BL1)")
        # Link tab membawa kategori ter-urlencode (spasi %20, persen %25).
        self.assertContains(r, "kategori=BONUS%20ROLLINGAN%20SLOT%200.5%25%20DAILY")

    def test_filter_memfilter_tabel_dan_kartu(self):
        self.isi()
        r = self.client.get(reverse("bonus_recon"),
                            {"dari": "2026-07-01", "sampai": "2026-07-31",
                             "tab": "panel", "kategori": "Redemption Coupon"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Cici")
        self.assertNotContains(r, "BMSuser")

    def test_badge_dan_ringkasan_pakai_detail(self):
        self.isi()
        r = self.client.get(reverse("bonus_recon"),
                            {"dari": "2026-07-01", "sampai": "2026-07-31",
                             "tab": "cocok"})
        self.assertContains(
            r, '<span class="badge src">BONUS ROLLINGAN SLOT 0.5% DAILY</span>',
            html=True)
        self.assertContains(r, "Nilai (Rp)")
        self.assertContains(r, "TOTAL")
