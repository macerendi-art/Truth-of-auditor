"""Backfill label QRIS untuk baris panel COR lama.

Fix parser tidak retroaktif: baris yang sudah diingest tetap ber-`bank_title`
kosong. Command mengisi kolom DAN `raw["Bank Title"]` sekali jalan, idempoten.
"""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.channels import kelas_metode

UUID = "03f747e8-ac9c-48e0-a"


class BackfillQrisBankTitleTests(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.toko_lain = Toko.objects.get(key="slo")
        self.st_panel = SourceType.objects.get(key="panel")
        self.up = Upload.objects.create(
            source_type=self.st_panel, toko=self.toko, original_name="qris-lama.xlsx")

    def _baris(self, *, toko=None, upload=None, source_type=None, bank_title="",
               description=f"QRIS {UUID}", row_hash="qris-1"):
        return Transaction.objects.create(
            upload=upload or self.up, source_type=source_type or self.st_panel,
            toko=toko or self.toko, jenis="depo", amount=Decimal("85000"),
            credit_delta=Decimal("-85000"), money_delta=Decimal("85000"),
            ticket_no="", username="zidanhoki11", reference=UUID, counterparty="",
            player_bank="", bank_title=bank_title, description=description,
            raw={"Transaction ID": UUID, "Amount": "85000"}, row_hash=row_hash,
        )

    def test_kolom_dan_raw_terisi_qris(self):
        tx = self._baris()
        out = StringIO()
        call_command("backfill_qris_bank_title", stdout=out)
        tx.refresh_from_db()
        self.assertEqual(tx.bank_title, "QRIS")
        self.assertEqual(tx.raw["Bank Title"], "QRIS")
        self.assertEqual(tx.raw["Transaction ID"], UUID)  # isi raw lama utuh
        laporan = out.getvalue()
        self.assertIn("diperiksa=1", laporan)
        self.assertIn("diubah=1", laporan)

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
        tx_lbs = self._baris(row_hash="qris-lbs")
        tx_lain = self._baris(toko=self.toko_lain, upload=up_lain, row_hash="qris-lain")
        call_command("backfill_qris_bank_title", "--toko", "lbs",
                     stdout=StringIO())
        tx_lbs.refresh_from_db()
        tx_lain.refresh_from_db()
        self.assertEqual(tx_lbs.bank_title, "QRIS")
        self.assertEqual(tx_lain.bank_title, "")  # toko lain tak tersentuh

    def test_bank_title_terisi_tak_ditimpa(self):
        tx = self._baris(bank_title="BCA", row_hash="qris-bca")
        call_command("backfill_qris_bank_title", stdout=StringIO())
        tx.refresh_from_db()
        self.assertEqual(tx.bank_title, "BCA")


class KelasMetodeQrisTests(SimpleTestCase):
    """Bukti kartu "Metode Pembayaran" dashboard ikut terbetulkan: bank_title
    "QRIS" jatuh ke bucket QRIS — dulu kosong, jadi tergolong "Lainnya"."""

    def test_qris_bukan_lagi_lainnya(self):
        self.assertEqual(kelas_metode("depo", "QRIS"), "QRIS")
        self.assertEqual(kelas_metode("wd", "QRIS"), "QRIS")
        self.assertEqual(kelas_metode("depo", ""), "Lainnya")  # keadaan lama
