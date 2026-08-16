from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class PerbaikiArahQRISUnoTests(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="w25")
        self.toko_lain = Toko.objects.exclude(key="w25").first()
        self.gateway = SourceType.objects.get(key="gateway")
        self.upload = Upload.objects.create(
            toko=self.toko,
            source_type=self.gateway,
            original_name="contoh-sintetis.xlsx",
        )
        self.urutan = 0

    def _rusak(self, **beda):
        self.urutan += 1
        bidang = {
            "toko": self.toko,
            "source_type": self.gateway,
            "upload": self.upload,
            "posted_date": date(2026, 8, 13),
            "jenis": "wd",
            "amount": Decimal("85000"),
            "credit_delta": Decimal("0"),
            "money_delta": Decimal("-85000"),
            "fee": Decimal("0"),
            "bonus": Decimal("0"),
            "reference": f"pesanan-sintetis-{self.urutan}",
            "raw": {
                "BranchName": "QRIS-7-CONTOH",
                "GrandTotal": "85000",
                "BranchNominal": "83980",
            },
            "row_hash": f"arah-uno-{self.urutan}",
        }
        bidang.update(beda)
        return Transaction.objects.create(**bidang)

    def _jalankan(self, *args):
        keluar = StringIO()
        call_command("perbaiki_arah_qris_uno", *args, stdout=keluar)
        return keluar.getvalue()

    def test_default_dry_run_tidak_menulis(self):
        tx = self._rusak()

        keluaran = self._jalankan()

        tx.refresh_from_db()
        self.assertEqual(tx.jenis, "wd")
        self.assertEqual(tx.money_delta, Decimal("-85000"))
        self.assertIn("dry-run", keluaran)
        self.assertIn("siap=1", keluaran)

    def test_flag_dry_run_diterima_secara_eksplisit(self):
        tx = self._rusak()

        keluaran = self._jalankan("--dry-run")

        tx.refresh_from_db()
        self.assertEqual(tx.jenis, "wd")
        self.assertIn("dry-run", keluaran)

    def test_terapkan_memulihkan_nilai_dari_raw(self):
        tx = self._rusak()
        raw_asli = dict(tx.raw)
        hash_asli = tx.row_hash

        keluaran = self._jalankan("--terapkan")

        tx.refresh_from_db()
        self.assertEqual(tx.jenis, "depo")
        self.assertEqual(tx.amount, Decimal("85000"))
        self.assertEqual(tx.money_delta, Decimal("85000"))
        self.assertEqual(tx.fee, Decimal("1020"))
        self.assertEqual(tx.raw, raw_asli)
        self.assertEqual(tx.row_hash, hash_asli)
        self.assertIn("diubah=1", keluaran)

    def test_sebaran_dilaporkan_per_toko_dan_tanggal(self):
        self._rusak(posted_date=date(2026, 7, 14))
        self._rusak(posted_date=date(2026, 8, 13))
        upload_lain = Upload.objects.create(
            toko=self.toko_lain,
            source_type=self.gateway,
            original_name="contoh-lain.xlsx",
        )
        self._rusak(
            toko=self.toko_lain,
            upload=upload_lain,
            posted_date=date(2026, 8, 13),
        )

        keluaran = self._jalankan()

        self.assertIn("toko=w25 tanggal=2026-07-14 n=1", keluaran)
        self.assertIn("toko=w25 tanggal=2026-08-13 n=1", keluaran)
        self.assertIn(
            f"toko={self.toko_lain.key} tanggal=2026-08-13 n=1",
            keluaran,
        )

    def test_raw_tidak_sah_dilewati_dan_disebut(self):
        tx = self._rusak(raw={"BranchName": "QRIS", "GrandTotal": "bukan angka"})

        keluaran = self._jalankan("--terapkan")

        tx.refresh_from_db()
        self.assertEqual(tx.jenis, "wd")
        self.assertIn("dilewati raw tidak lengkap atau nominal tidak sah=1", keluaran)

    def test_nominal_raw_yang_tak_cocok_dilewati(self):
        tx = self._rusak(
            raw={
                "BranchName": "QRIS",
                "GrandTotal": "90000",
                "BranchNominal": "88000",
            }
        )

        keluaran = self._jalankan("--terapkan")

        tx.refresh_from_db()
        self.assertEqual(tx.jenis, "wd")
        self.assertIn("dilewati isi raw tak cocok baris=1", keluaran)

    def test_baris_di_luar_gerbang_struktural_tidak_disentuh(self):
        tanpa_branch = self._rusak(raw={"GrandTotal": "85000", "BranchNominal": "83980"})
        sudah_depo = self._rusak(jenis="depo", money_delta=Decimal("85000"))

        keluaran = self._jalankan("--terapkan")

        tanpa_branch.refresh_from_db()
        sudah_depo.refresh_from_db()
        self.assertEqual(tanpa_branch.jenis, "wd")
        self.assertEqual(sudah_depo.jenis, "depo")
        self.assertIn("diperiksa=0", keluaran)

    def test_baris_terkunci_batch_menghentikan_seluruh_perubahan(self):
        bebas = self._rusak()
        terkunci = self._rusak()
        batch = ReconBatch.objects.create(
            toko=self.toko,
            tolerance=ToleranceProfile.objects.get(name="Default"),
            recon_date=date(2026, 8, 13),
        )
        terkunci.consumed_by_batch = batch
        terkunci.save(update_fields=["consumed_by_batch"])

        keluaran = self._jalankan("--terapkan")

        bebas.refresh_from_db()
        terkunci.refresh_from_db()
        self.assertEqual(bebas.jenis, "wd")
        self.assertEqual(terkunci.jenis, "wd")
        self.assertIn("terkunci batch=1", keluaran)
        self.assertIn("DIHENTIKAN", keluaran)

    def test_idempoten_setelah_diterapkan(self):
        self._rusak()
        self._jalankan("--terapkan")

        keluaran = self._jalankan("--terapkan")

        self.assertIn("diperiksa=0", keluaran)
        self.assertIn("diubah=0", keluaran)
