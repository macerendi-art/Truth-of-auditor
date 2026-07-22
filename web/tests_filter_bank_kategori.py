"""K3 — filter bank pada kategori 'Tidak Cocok' DAN 'Tidak Ada di Panel'
(run_detail Panel↔Mutasi Bank).

Tab 'Tidak Cocok' (ada sisi panel) memakai filter bank pemain / bank title dari
sisi kiri (kredit) — regresi dijaga di bawah. Tab 'Tidak Ada di Panel' (orphan
uang, left=None) tidak punya sisi panel, jadi filter 'bank title' beralih ke
SISI UANG: label bank/sumber diturunkan dari upload mutasi (BRI/BCA/Mandiri/...).
"""
from decimal import Decimal

from sources.models import Upload
from web.tests_run_detail_filters import _Base


class NoPanelFilterUangTests(_Base):
    def setUp(self):
        super().setUp()
        self.up_bri = Upload.objects.create(
            source_type=self.bank, toko=self.lbs, provider="BRI"
        )
        self.up_bca = Upload.objects.create(
            source_type=self.bank, toko=self.lbs, provider="BCA"
        )
        # 2 orphan dari BRI (50rb) + 1 orphan dari BCA (70rb) — semua left=None.
        for i in range(2):
            r = self._tx(self.bank, f"obri{i}", upload=self.up_bri,
                         amount=Decimal("50000"))
            self._res("tidak_cocok", None, r, "no_panel")
        r = self._tx(self.bank, "obca0", upload=self.up_bca, amount=Decimal("70000"))
        self._res("tidak_cocok", None, r, "no_panel")

    def test_no_panel_filter_uang_menyaring(self):
        rows = list(self._get(bucket="tidak_ada_panel", btitle="BRI").context["page"])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.right.upload_id == self.up_bri.id for r in rows))

    def test_no_panel_chip_uang_terhitung(self):
        c = self._get(bucket="tidak_ada_panel").context
        codes = {b["code"]: b["n"] for b in c["btitles"]}
        self.assertEqual(codes.get("BRI"), 2)
        self.assertEqual(codes.get("BCA"), 1)
        # bank pemain N/A untuk orphan → fold tidak dirender.
        self.assertFalse(c["banks"])

    def test_no_panel_total_ikut_filter_uang(self):
        t = self._get(bucket="tidak_ada_panel", btitle="BRI").context["totals"]
        self.assertEqual(t["n"], 2)
        self.assertEqual(t["saldo"], Decimal("100000"))

    def test_no_panel_opsi_filter_muncul_di_html(self):
        html = self._get(bucket="tidak_ada_panel").content.decode()
        self.assertIn("BRI", html)
        self.assertIn("BCA", html)


class TidakCocokFilterRegressionTests(_Base):
    """Regresi: tab 'Tidak Cocok' (ada kredit) tetap memakai filter sisi panel."""

    def setUp(self):
        super().setUp()
        for i, (pb, bt) in enumerate([("DANA", "BNI"), ("DANA", "BNI"), ("OVO", "BCA")]):
            left = self._tx(self.panel, f"nc{i}", amount=Decimal("30000"),
                            player_bank=pb, bank_title=bt, ticket_no=f"D{i}")
            self._res("tidak_cocok", left, None, "no_money")

    def test_tidak_cocok_bank_title_menyaring(self):
        c = self._get(bucket="tidak_cocok", btitle="BNI").context
        rows = list(c["page"])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.left.bank_title == "BNI" for r in rows))
        # chip panel tetap tampil.
        self.assertTrue(c["btitles"])
        self.assertTrue(c["banks"])

    def test_tidak_cocok_bank_pemain_tetap(self):
        rows = list(self._get(bucket="tidak_cocok", bank="DANA").context["page"])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.left.player_bank == "DANA" for r in rows))

    def test_tidak_cocok_opsi_filter_muncul_di_html(self):
        html = self._get(bucket="tidak_cocok").content.decode()
        self.assertIn("bank pemain", html)
        self.assertIn("bank title", html)
