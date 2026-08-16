from django.test import SimpleTestCase

from reconciliation.management.commands.validate_brands import _flow
from sources.management.commands.ingest import detect_flow


class DeteksiArahNamaBerkasTests(SimpleTestCase):
    KASUS = (
        ("13_08_2026 W25 WD DP QRIS UNOPAY.xlsx", "dp"),
        ("13_08_2026 W25 WD WD QRIS UNOPAY.xlsx", "wd"),
        ("13-08-2026 BBS DP PANEL.xlsx", "dp"),
        ("13-08-2026 BBS WD NXPAY.xlsx", "wd"),
        ("13_08_2026_BBS_DP_QRIS_ELITE.csv", "dp"),
        ("13_08_2026_BBS_WD_QRIS_RPAY.xlsx", "wd"),
        ("13_08_2026_BBS_PG_BRI_NISA_AYU_NURSEHA.CSV", ""),
        ("Bank Mutation 14 Aug 2026.xlsx", ""),
    )

    def test_token_arah_terakhir_menang(self):
        for nama, harapan in self.KASUS:
            with self.subTest(nama=nama):
                self.assertEqual(detect_flow(nama), harapan)

    def test_validate_brands_memakai_aturan_yang_sama(self):
        for nama, harapan in self.KASUS:
            with self.subTest(nama=nama):
                self.assertEqual(_flow(nama), harapan)

    def test_token_menempel_tidak_lagi_dianggap_arah(self):
        for nama in ("13-08-2026 WDPANEL.xlsx", "13-08-2026 DPNXPAY.xlsx"):
            with self.subTest(nama=nama):
                self.assertEqual(detect_flow(nama), "")
                self.assertEqual(_flow(nama), "")
