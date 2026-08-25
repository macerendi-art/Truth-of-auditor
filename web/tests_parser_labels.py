"""Label jenis parser cor_* → vgr_*/tmg_* di Impor (UI only)."""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from sources.models import Toko
from web.parser_labels import label_parser, parser_options


class LabelParserUnitTests(SimpleTestCase):
    def test_vigor_ganti_cor(self):
        self.assertEqual(
            label_parser("cor_panel_manual_dp", "vigor"),
            "vgr_panel_manual_dp",
        )
        self.assertEqual(label_parser("cor_panel_bank", "vigor"), "vgr_panel_bank")
        self.assertEqual(label_parser("cor_qris_gateway", "vigor"), "vgr_qris_gateway")

    def test_tm_gaming_ganti_cor(self):
        self.assertEqual(
            label_parser("cor_panel_manual_dp", "tm_gaming"),
            "tmg_panel_manual_dp",
        )
        self.assertEqual(label_parser("cor_panel_qris", Toko.PANEL_TMG), "tmg_panel_qris")

    def test_nexus_jadi_nx(self):
        self.assertEqual(label_parser("cor_panel_bank", "nexus"), "nx_panel_bank")
        self.assertEqual(
            label_parser("cor_panel_manual_dp", Toko.PANEL_NEXUS),
            "nx_panel_manual_dp",
        )
        # panel kosong / tak dikenal: tetap cor_
        self.assertEqual(label_parser("cor_panel_bank", ""), "cor_panel_bank")
        self.assertEqual(label_parser("cor_panel_bank", "lain"), "cor_panel_bank")

    def test_bukan_cor_tidak_diubah(self):
        self.assertEqual(label_parser("qris_elite", "tm_gaming"), "qris_elite")
        self.assertEqual(label_parser("bri", "vigor"), "bri")
        # substring di tengah tidak disentuh
        self.assertEqual(label_parser("score_board", "vigor"), "score_board")

    def test_parser_options_key_tetap_cor_label_berganti(self):
        opts = {o["key"]: o["label"] for o in parser_options("tm_gaming")}
        self.assertIn("cor_panel_manual_dp", opts)
        self.assertEqual(opts["cor_panel_manual_dp"], "tmg_panel_manual_dp")
        self.assertEqual(opts["qris_elite"], "qris_elite")


class LabelParserUploadViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.w25 = Toko.objects.filter(key="w25").first()
        if not self.w25:
            self.w25 = Toko.objects.create(
                key="w25x", name="W25X", panel=Toko.PANEL_TMG, is_active=True
            )
        else:
            self.w25.panel = Toko.PANEL_TMG
            self.w25.save(update_fields=["panel"])
        self.client.post(reverse("set_toko"), {"toko_id": self.w25.id})

    def test_dropdown_label_tmg_value_cor(self):
        f = SimpleUploadedFile(
            "entah.csv", b"kolom_a,kolom_b\n1,2\n", content_type="text/csv"
        )
        r = self.client.post(reverse("upload"), {"action": "analyze", "files": [f]})
        html = r.content.decode()
        # value POST tetap key internal
        self.assertIn('value="cor_panel_manual_dp"', html)
        # teks opsi pakai tmg_
        self.assertIn(">tmg_panel_manual_dp<", html)
        self.assertNotIn(">cor_panel_manual_dp<", html)
        # non-cor tidak diubah
        self.assertIn(">qris_elite<", html)

    def test_dropdown_label_nx_untuk_toko_nexus(self):
        lbs = Toko.objects.filter(key="lbs").first()
        if not lbs:
            lbs = Toko.objects.create(
                key="lbsx", name="LBSX", panel=Toko.PANEL_NEXUS, is_active=True
            )
        else:
            lbs.panel = Toko.PANEL_NEXUS
            lbs.save(update_fields=["panel"])
        self.client.post(reverse("set_toko"), {"toko_id": lbs.id})
        f = SimpleUploadedFile(
            "entah.csv", b"kolom_a,kolom_b\n1,2\n", content_type="text/csv"
        )
        r = self.client.post(reverse("upload"), {"action": "analyze", "files": [f]})
        html = r.content.decode()
        self.assertIn('value="cor_panel_bank"', html)
        self.assertIn(">nx_panel_bank<", html)
        self.assertNotIn(">cor_panel_bank<", html)
