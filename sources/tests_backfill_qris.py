"""Backfill label QRIS untuk baris panel COR lama.

Fix parser tidak retroaktif: baris yang sudah diingest tetap ber-`bank_title`
kosong. Command mengisi kolom DAN `raw["Bank Title"]` sekali jalan, idempoten.
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from sources.management.commands import backfill_qris_bank_title as backfill_qris
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.channels import kelas_metode

UUID = "03f747e8-ac9c-48e0-a"


class BackfillQrisBankTitleTests(TestCase):
    def setUp(self):
        # g25 = Gacor25/COR, panel TM Gaming — satu-satunya sumber baris QRIS ini.
        self.toko = Toko.objects.get(key="g25")
        self.toko_lain = Toko.objects.get(key="slo")  # Vigor, juga bukan Nexus
        self.st_panel = SourceType.objects.get(key="panel")
        self.up = Upload.objects.create(
            source_type=self.st_panel, toko=self.toko, original_name="qris-lama.xlsx")

    def _baris(self, *, toko=False, upload=None, source_type=None, bank_title="",
               description=f"QRIS {UUID}", row_hash="qris-1", raw=None):
        return Transaction.objects.create(
            upload=upload or self.up, source_type=source_type or self.st_panel,
            toko=self.toko if toko is False else toko, jenis="depo",
            amount=Decimal("85000"),
            credit_delta=Decimal("-85000"), money_delta=Decimal("85000"),
            ticket_no="", username="zidanhoki11", reference=UUID, counterparty="",
            player_bank="", bank_title=bank_title, description=description,
            raw={"Transaction ID": UUID, "Amount": "85000"} if raw is None else raw,
            row_hash=row_hash,
        )

    def test_kolom_dan_raw_terisi_qris(self):
        tx = self._baris()
        out = StringIO()
        call_command("backfill_qris_bank_title", stdout=out)
        tx.refresh_from_db()
        # Kolom = "QRIS" (segmen pertama), raw = triplet dgn nama & norek
        # kosong — sama persis dgn yang ditulis parser, lihat CORPanelQRISParser.
        self.assertEqual(tx.bank_title, "QRIS")
        self.assertEqual(tx.raw["Bank Title"], "QRIS||")
        self.assertEqual(tx.raw["Transaction ID"], UUID)  # isi raw lama utuh
        laporan = out.getvalue()
        self.assertIn("diperiksa=1", laporan)
        self.assertIn("diubah=1", laporan)

    def test_raw_kosong_tetap_terisi(self):
        """Baris ber-`raw` kosong menempuh cabang `tx.raw or {}` — tak boleh KO.

        (`raw` NOT NULL di DB, jadi `{}` adalah satu-satunya nilai falsy yang
        benar-benar bisa muncul; guard `or {}` tetap dipertahankan untuk
        instance yang belum tersimpan.)
        """
        tx = self._baris(row_hash="qris-raw-kosong")
        Transaction.objects.filter(pk=tx.pk).update(raw={})
        call_command("backfill_qris_bank_title", stdout=StringIO())
        tx.refresh_from_db()
        self.assertEqual(tx.raw, {"Bank Title": "QRIS||"})
        self.assertEqual(tx.bank_title, "QRIS")

    def test_potongan_menghabiskan_semua_baris(self):
        """Loop potongan (500/putaran) harus menyapu bersih, bukan 1 potongan."""
        for i in range(7):
            self._baris(row_hash=f"qris-massal-{i}")
        out = StringIO()
        with patch.object(backfill_qris, "UKURAN_POTONGAN", 3):
            call_command("backfill_qris_bank_title", stdout=out)
        self.assertEqual(
            Transaction.objects.filter(bank_title="QRIS").count(), 7)
        self.assertIn("diubah=7", out.getvalue())

    def test_idempoten_jalan_dua_kali(self):
        tx = self._baris()
        call_command("backfill_qris_bank_title", stdout=StringIO())
        out2 = StringIO()
        call_command("backfill_qris_bank_title", stdout=out2)
        tx.refresh_from_db()
        self.assertEqual(tx.bank_title, "QRIS")
        self.assertIn("diubah=0", out2.getvalue())

    def test_dry_run_tidak_menulis(self):
        tx = self._baris()
        out = StringIO()
        call_command("backfill_qris_bank_title", "--dry-run", stdout=out)
        tx.refresh_from_db()
        self.assertEqual(tx.bank_title, "")
        self.assertNotIn("Bank Title", tx.raw)
        self.assertIn("diubah=1", out.getvalue())  # tetap dihitung & dilaporkan

    def test_panel_non_qris_tak_tersentuh(self):
        tx = self._baris(description="BCA BAGAS ARMANDO", row_hash="qris-non")
        call_command("backfill_qris_bank_title", stdout=StringIO())
        tx.refresh_from_db()
        self.assertEqual(tx.bank_title, "")
        self.assertNotIn("Bank Title", tx.raw)

    def test_baris_gateway_qris_tak_tersentuh(self):
        # Parser gateway COR juga menulis description berawalan "QRIS " ("QRIS
        # COR <RRN>", "QRIS WD <merchant>") — yang mengasingkannya HANYA filter
        # source_type panel. Selektor tak boleh melebar ke sisi uang.
        tx = self._baris(source_type=SourceType.objects.get(key="gateway"),
                         description="QRIS COR 1pysbjp67783", row_hash="qris-gw")
        call_command("backfill_qris_bank_title", stdout=StringIO())
        tx.refresh_from_db()
        self.assertEqual(tx.bank_title, "")
        self.assertNotIn("Bank Title", tx.raw)

    def test_filter_toko(self):
        up_lain = Upload.objects.create(
            source_type=self.st_panel, toko=self.toko_lain, original_name="lain.xlsx")
        tx_cor = self._baris(row_hash="qris-cor")
        tx_lain = self._baris(toko=self.toko_lain, upload=up_lain, row_hash="qris-lain")
        call_command("backfill_qris_bank_title", "--toko", "g25",
                     stdout=StringIO())
        tx_cor.refresh_from_db()
        tx_lain.refresh_from_db()
        self.assertEqual(tx_cor.bank_title, "QRIS")
        self.assertEqual(tx_lain.bank_title, "")  # toko lain tak tersentuh

    def test_toko_panel_vigor_ikut_terisi(self):
        """Selektor menyaring per PANEL, bukan per toko: Vigor pun rail QRIS."""
        up_lain = Upload.objects.create(
            source_type=self.st_panel, toko=self.toko_lain, original_name="lain.xlsx")
        tx = self._baris(toko=self.toko_lain, upload=up_lain, row_hash="qris-vigor")
        call_command("backfill_qris_bank_title", stdout=StringIO())
        tx.refresh_from_db()
        self.assertEqual(tx.bank_title, "QRIS")

    def test_bank_title_terisi_tak_ditimpa(self):
        tx = self._baris(bank_title="BCA", row_hash="qris-bca")
        call_command("backfill_qris_bank_title", stdout=StringIO())
        tx.refresh_from_db()
        self.assertEqual(tx.bank_title, "BCA")


class PanelNexusDilindungiTests(TestCase):
    """Selektor `description__startswith="QRIS "` saja TIDAK cukup mengasingkan COR.

    Parser panel Nexus menyalin `description` dari kolom Remarks yang berisi teks
    bebas, jadi baris Nexus ber-Remarks awalan "QRIS " ikut tersapu — dan sapuannya
    MENIMPA `raw["Bank Title"]` yang bisa memuat triplet asli, sehingga nama pemilik
    rekening (dibaca engine `_expected_owner`) dan golongan kartu "Metode Pembayaran"
    ikut berubah tanpa jejak. Pagarnya sekarang struktural: hanya toko ber-panel
    Vigor/TM Gaming yang boleh disentuh.
    """

    def setUp(self):
        self.st_panel = SourceType.objects.get(key="panel")
        self.nexus = Toko.objects.get(key="lbs")
        self.cor = Toko.objects.get(key="g25")
        assert self.nexus.panel == Toko.PANEL_NEXUS
        assert self.cor.panel == Toko.PANEL_TMG

    def _baris(self, toko, row_hash, raw=None):
        up = Upload.objects.create(source_type=self.st_panel, toko=toko)
        return Transaction.objects.create(
            upload=up, source_type=self.st_panel, toko=toko, jenis="wd",
            amount=Decimal("50000"), credit_delta=Decimal("50000"),
            money_delta=Decimal("-50000"), bank_title="",
            description=f"QRIS {UUID}", raw=raw or {}, row_hash=row_hash,
        )

    def test_baris_nexus_tak_tersentuh(self):
        tx = self._baris(self.nexus, "nexus-remarks-qris")
        call_command("backfill_qris_bank_title", stdout=StringIO())
        tx.refresh_from_db()
        self.assertEqual(tx.bank_title, "")
        self.assertNotIn("Bank Title", tx.raw)

    def test_raw_bank_title_nexus_tak_dirusak(self):
        """Kasus paling merusak: kolom kosong tapi raw membawa triplet asli.

        Menimpanya dgn "QRIS||" menghapus nama pemilik untuk selamanya —
        `backfill_bank_fields` kelak menurunkan kolom dari raw yang sudah salah.
        """
        tx = self._baris(self.nexus, "nexus-raw-utuh",
                         raw={"Bank Title": "NEXUSPAY|BUDI SANTOSO|0812"})
        call_command("backfill_qris_bank_title", stdout=StringIO())
        tx.refresh_from_db()
        self.assertEqual(tx.raw["Bank Title"], "NEXUSPAY|BUDI SANTOSO|0812")
        self.assertEqual(kelas_metode("wd", tx.raw["Bank Title"].split("|")[0]),
                         "Nexuspay")  # bukan "QRIS"

    def test_baris_cor_tetap_terisi(self):
        tx = self._baris(self.cor, "cor-qris")
        call_command("backfill_qris_bank_title", stdout=StringIO())
        tx.refresh_from_db()
        self.assertEqual(tx.bank_title, "QRIS")
        self.assertEqual(tx.raw["Bank Title"], "QRIS||")

    def test_dry_run_tak_menghitung_nexus(self):
        self._baris(self.nexus, "nexus-hitung")
        self._baris(self.cor, "cor-hitung")
        out = StringIO()
        call_command("backfill_qris_bank_title", "--dry-run", stdout=out)
        self.assertIn("diubah=1", out.getvalue())

    def test_baris_tanpa_toko_dilewati_dan_dilaporkan(self):
        """Baris tanpa toko (jalur CLI debug) TAK BISA diatribusikan ke panel apa
        pun, jadi command yang MENULIS memilih diam — tapi tidak diam-diam:
        jumlahnya disebut di keluaran supaya operator bisa menindaklanjuti."""
        tx = self._baris(None, "tanpa-toko")
        out = StringIO()
        call_command("backfill_qris_bank_title", stdout=out)
        tx.refresh_from_db()
        self.assertEqual(tx.bank_title, "")
        self.assertNotIn("Bank Title", tx.raw)
        self.assertIn("tanpa toko=1", out.getvalue())

    def test_tanpa_baris_tanpa_toko_keluaran_tetap_ringkas(self):
        self._baris(self.cor, "cor-bersih")
        out = StringIO()
        call_command("backfill_qris_bank_title", stdout=out)
        self.assertNotIn("tanpa toko", out.getvalue())


class KelasMetodeQrisTests(SimpleTestCase):
    """Bukti kartu "Metode Pembayaran" dashboard ikut terbetulkan: bank_title
    "QRIS" jatuh ke bucket QRIS — dulu kosong, jadi tergolong "Lainnya"."""

    def test_qris_bukan_lagi_lainnya(self):
        self.assertEqual(kelas_metode("depo", "QRIS"), "QRIS")
        self.assertEqual(kelas_metode("wd", "QRIS"), "QRIS")
        self.assertEqual(kelas_metode("depo", ""), "Lainnya")  # keadaan lama
