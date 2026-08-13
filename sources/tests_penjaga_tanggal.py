"""Gerbang lintas-parser: unggahan yang seluruh barisnya tak bertanggal DITOLAK.

Latar belakangnya kegagalan senyap QR Flyer bentuk keempat (LTN 12-08-2026).
Penjaga header di `QRFlyerParser` menutup lubang itu untuk parser Flyer saja;
gerbang ini menutup KELASNYA untuk semua parser, karena bentuk kegagalannya tak
ada hubungannya dengan vendor mana pun: kolom waktu berganti nama, parser tak
mengenalinya, lalu menghasilkan baris bertiket dan bernominal benar yang tak
akan pernah dicocokkan maupun tampil di laporan — sementara unggahannya
dilaporkan BERHASIL.

Yang dijaga di sini justru batas-batasnya: gerbang harus menyala hanya pada
kepastian (semua baris tanpa waktu apa pun) dan tetap diam pada berkas yang
sah — kalau tidak, ia akan menghalangi pekerjaan harian tanpa alasan.
"""
from datetime import date, datetime
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from sources import services
from sources.models import Toko
from transactions.models import Transaction


def _baris(rh="h1", posted=None, occurred=None):
    return {
        "occurred_at": occurred, "posted_date": posted, "jenis": "depo",
        "amount": Decimal("50000"), "credit_delta": Decimal("0"),
        "money_delta": Decimal("50000"), "fee": Decimal("0"),
        "bonus": Decimal("0"), "balance_after": None, "ticket_no": "D1",
        "username": "u1", "reference": "", "counterparty": "",
        "description": "", "raw": {}, "row_hash": rh,
    }


class PeriksaHasilBertanggalTest(SimpleTestCase):
    """Predikatnya murni — bisa diuji tanpa database sama sekali."""

    def test_semua_baris_tanpa_waktu_MELEMPAR(self):
        with self.assertRaises(ValueError) as ctx:
            services.periksa_hasil_bertanggal(
                [_baris("a"), _baris("b"), _baris("c")], "qrflyer")

        pesan = str(ctx.exception)
        self.assertIn("3 baris", pesan)          # sebut berapa yang hilang
        self.assertIn("qrflyer", pesan)          # sebut parser yang gagal
        self.assertIn("kolom tanggal", pesan)    # sebut dugaan sebabnya

    def test_pesan_MELARANG_unggah_ulang(self):
        """Refleks pertama operator adalah mengunggah ulang. Hasilnya akan sama
        persis, jadi pesannya harus menghentikan itu, bukan cuma mengeluh."""
        with self.assertRaises(ValueError) as ctx:
            services.periksa_hasil_bertanggal([_baris()], "zpay")

        self.assertIn("jangan diunggah ulang", str(ctx.exception).lower())

    def test_berkas_TANPA_baris_tetap_sah(self):
        """Nol baris punya penjaganya sendiri di tiap parser (mis. ZPay). Di
        sini nol baris bukan bukti apa-apa — jangan diklaim rusak."""
        services.periksa_hasil_bertanggal([], "qrflyer")   # tak melempar

    def test_posted_date_saja_sudah_cukup(self):
        services.periksa_hasil_bertanggal(
            [_baris(posted=date(2026, 8, 12))], "qrflyer")

    def test_occurred_at_saja_sudah_cukup(self):
        """Mesin pencocokan menyaring `occurred_at__date`, jadi baris ini nyata
        bisa dipakai walau `posted_date`-nya kosong."""
        services.periksa_hasil_bertanggal(
            [_baris(occurred=datetime(2026, 8, 12, 13, 30))], "qrflyer")

    def test_SEBAGIAN_tak_bertanggal_TIDAK_melempar(self):
        """Batas yang disengaja. Baris tak bertanggal yang bercampur baris
        bertanggal bisa saja footer/pending yang wajar — memblokirnya akan
        menahan berkas yang sebetulnya baik. Gerbang ini hanya untuk kepastian."""
        services.periksa_hasil_bertanggal(
            [_baris("a"), _baris("b", posted=date(2026, 8, 12))], "qrflyer")


class _ParserTanpaTanggal:
    source_key = "gateway"

    def parse(self, path, flow=""):
        return [_baris("tanpa-tgl-1"), _baris("tanpa-tgl-2")]


class GerbangIngestTest(TestCase):
    """Gerbangnya harus berdiri SEBELUM apa pun ditulis — kalau tidak, ia cuma
    mengeluh setelah barisnya sudah telanjur masuk."""

    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        services.PARSERS["_fake_tanpa_tanggal"] = _ParserTanpaTanggal
        self.addCleanup(services.PARSERS.pop, "_fake_tanpa_tanggal", None)

    def test_ingest_ditolak_dan_TAK_ADA_yang_tertulis(self):
        sebelum = Transaction.objects.count()

        with self.assertRaises(ValueError):
            services.ingest("_fake_tanpa_tanggal", "/tmp/x.xlsx", toko=self.toko)

        self.assertEqual(Transaction.objects.count(), sebelum)
        self.assertFalse(
            Transaction.objects.filter(row_hash__startswith="tanpa-tgl").exists())
