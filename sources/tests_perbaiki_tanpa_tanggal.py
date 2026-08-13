"""Pemulihan baris gateway tak bertanggal dari `raw`.

Yang diuji bukan cuma "tanggalnya terisi", tapi tiga hal yang kalau salah
justru menimbulkan kerusakan baru: hash barunya harus SAMA dengan hash yang
akan dihasilkan unggahan ulang berkas yang sama (kalau tidak, hari itu
terhitung dua kali), baris sampah bentuk ketiga TIDAK boleh ikut tersentuh,
dan bentrok hash harus dilewati alih-alih menimpa bukti.
"""
import os
import tempfile
from datetime import datetime
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from openpyxl import Workbook

from sources.models import SourceType, Toko, Upload
from sources.parsers.gateways import QRFlyerParser
from transactions.models import Transaction

RAW_KEEMPAT = {
    "date": "2026-08-12 13:30:59.0",
    "Client Reff": "D260812119700084141",
    "transaction_id": "D2506425",
    "rrn": "1r8yujw12322",
    "username": "Pablo007",
    "total_amount": "50000.00",
    "charges": "600.00",
    "net_amount": "49400.00",
    "rate_merchant": "1.2",
}


class PerbaikiTanpaTanggalTest(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.st = SourceType.objects.get(key="gateway")
        self.upload = Upload.objects.create(
            toko=self.toko, source_type=self.st, original_name="flyer.xlsx")

    def _rusak(self, **beda):
        """Baris seperti yang ditulis parser LAMA: isi benar, tanggal hilang."""
        bidang = {
            "toko": self.toko, "source_type": self.st, "upload": self.upload,
            "occurred_at": None, "posted_date": None, "jenis": "depo",
            "amount": Decimal("50000.00"), "credit_delta": Decimal("0"),
            "money_delta": Decimal("50000.00"), "fee": Decimal("0"),
            "bonus": Decimal("0"), "ticket_no": "D2506425", "username": "Pablo007",
            "reference": "", "raw": dict(RAW_KEEMPAT), "row_hash": "hash-lama",
        }
        bidang.update(beda)
        return Transaction.objects.create(**bidang)

    def _jalankan(self, **opts):
        keluar = StringIO()
        call_command("perbaiki_gateway_tanpa_tanggal", stdout=keluar, **opts)
        return keluar.getvalue()

    def test_tanggal_referensi_dan_fee_pulih_dari_raw(self):
        tx = self._rusak()

        self._jalankan()

        tx.refresh_from_db()
        self.assertEqual(str(tx.occurred_at), "2026-08-12 13:30:59")
        self.assertEqual(str(tx.posted_date), "2026-08-12")
        self.assertEqual(tx.reference, "D260812119700084141")
        self.assertEqual(str(tx.fee), "600.00")

    def test_hash_baru_SAMA_dengan_hasil_parse_berkasnya(self):
        """Inti pemulihan ini. Kalau hash-nya meleset, unggahan ulang berkas
        yang sama lolos sebagai baris BARU dan hari itu terhitung dua kali."""
        tx = self._rusak()
        wb = Workbook()
        ws = wb.active
        ws.append(list(RAW_KEEMPAT.keys()))
        ws.append(list(RAW_KEEMPAT.values()))
        fd, path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        wb.save(path)
        try:
            dari_berkas = QRFlyerParser().parse(path, flow="dp")[0]
        finally:
            os.remove(path)

        self._jalankan()

        tx.refresh_from_db()
        self.assertEqual(tx.row_hash, dari_berkas["row_hash"])

    def test_baris_sampah_bentuk_ketiga_TIDAK_disentuh(self):
        """6.118 baris tiket-kosong/Rp0 juga tak bertanggal. Membuangnya
        keputusan pemilik data; command ini tak boleh menyentuhnya."""
        sampah = self._rusak(ticket_no="", amount=Decimal("0"),
                             money_delta=Decimal("0"), raw={"Client Reference": "x"},
                             row_hash="hash-sampah")

        self._jalankan()

        sampah.refresh_from_db()
        self.assertIsNone(sampah.posted_date)
        self.assertEqual(sampah.row_hash, "hash-sampah")

    def test_baris_yang_isinya_tak_cocok_dilewati_dan_DISEBUT(self):
        """Kalau tiket di raw tak sama dengan yang tersimpan, barisnya bukan
        yang kita kira — jangan ditulis, dan jangan diam."""
        tx = self._rusak(ticket_no="D9999999", row_hash="hash-asing")

        keluaran = self._jalankan()

        tx.refresh_from_db()
        self.assertIsNone(tx.posted_date)
        self.assertIn("isi raw tak cocok baris=1", keluaran)

    def test_bentrok_dengan_salinan_benar_dilewati(self):
        """Kalau berkasnya sudah pernah diunggah ulang setelah parser diperbaiki,
        salinan benarnya sudah ada. Menimpanya melanggar constraint."""
        benar = QRFlyerParser._petakan(list(RAW_KEEMPAT.keys()))
        self.assertTrue(benar["ticket"])          # pagar: peta memang terisi
        tx = self._rusak()
        self._jalankan()                          # baris pertama pulih
        tx.refresh_from_db()
        kembar = self._rusak(row_hash="hash-lama-2")

        keluaran = self._jalankan()

        kembar.refresh_from_db()
        self.assertIsNone(kembar.posted_date)
        self.assertEqual(kembar.row_hash, "hash-lama-2")
        self.assertIn("salinan benar sudah ada=1", keluaran)

    def test_dua_baris_rusak_identik_tak_saling_menabrak(self):
        """Keduanya lolos cek DB (belum ada yang benar), lalu akan menabrak satu
        sama lain di bulk_update kalau potongan tak diperiksa terhadap dirinya."""
        self._rusak()
        self._rusak(row_hash="hash-lama-2")

        keluaran = self._jalankan()

        self.assertEqual(
            Transaction.objects.filter(posted_date__isnull=False).count(), 1)
        self.assertIn("salinan benar sudah ada=1", keluaran)

    def test_dry_run_tidak_menulis(self):
        tx = self._rusak()

        keluaran = self._jalankan(dry_run=True)

        tx.refresh_from_db()
        self.assertIsNone(tx.posted_date)
        self.assertIn("diubah=1", keluaran)
        self.assertIn("dry-run", keluaran)

    def test_idempoten(self):
        tx = self._rusak()

        self._jalankan()
        keluaran = self._jalankan()

        tx.refresh_from_db()
        self.assertEqual(str(tx.posted_date), "2026-08-12")
        self.assertIn("diperiksa=0 diubah=0", keluaran)

    def test_baris_bertanggal_tak_ikut_tersapu(self):
        tx = self._rusak(occurred_at=datetime(2026, 8, 12, 9, 0),
                         posted_date=datetime(2026, 8, 12, 9, 0).date(),
                         row_hash="hash-sehat")

        self._jalankan()

        tx.refresh_from_db()
        self.assertEqual(tx.row_hash, "hash-sehat")
        self.assertEqual(str(tx.occurred_at), "2026-08-12 09:00:00")

    def test_saring_toko(self):
        lain = Toko.objects.exclude(key="lbs").first()
        tx = self._rusak()

        self._jalankan(toko=lain.key)

        tx.refresh_from_db()
        self.assertIsNone(tx.posted_date)
