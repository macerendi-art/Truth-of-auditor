import csv
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from openpyxl import Workbook

from sources import services
from sources.detect import detect_source
from sources.models import Toko
from sources.parsers.gateways import QRISEliteParser


ELITE_HEADER = [
    "ID", "RECORD DATE", "RECORD VALUE", "RECORD FEE", "MERCHANT",
    "MEMBER", "APPROVE", "PAYMENT", "SETTLEMENT", "PARTNER ID",
    "VENDOR ID", "STATUS", "TICKET", "PG",
]


def _baris_elite(**beda):
    nilai = {
        "ID": "elite-sintetis-1",
        "RECORD DATE": "2026-08-13T16:24:21+07:00+007",
        "RECORD VALUE": "300001.00",
        "RECORD FEE": "3600.00",
        "MERCHANT": "MERCHANT CONTOH",
        "MEMBER": "pemain_sintetis",
        "APPROVE": "2026-08-13T23:24:46+07:00+007",
        "PAYMENT": "QRIS",
        "SETTLEMENT": "SETTLED",
        "PARTNER ID": "partner-sintetis",
        "VENDOR ID": "vendor-sintetis",
        "STATUS": "SUCCESS",
        "TICKET": "D1234567",
        "PG": "ELITE",
    }
    nilai.update(beda)
    return [nilai.get(k, "") for k in ELITE_HEADER]


def _csv_elite(baris=None, header=None):
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["MUTASI QRIS TRANSACTION"])
        writer.writerow(header or ELITE_HEADER)
        writer.writerows(baris or [])
    return path


def _csv_biasa(rows):
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    return path


def _xlsx(rows):
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


class QRISEliteParserTests(SimpleTestCase):
    def _parse(self, baris, header=None, flow="dp"):
        path = _csv_elite(baris, header=header)
        try:
            return QRISEliteParser().parse(path, flow=flow)
        finally:
            os.remove(path)

    def test_field_kanonik_nominal_dan_waktu_wib(self):
        r = self._parse([_baris_elite()])[0]

        self.assertEqual(r["source_type"], "gateway")
        self.assertEqual(r["jenis"], "depo")
        self.assertEqual(r["ticket_no"], "D1234567")
        self.assertEqual(r["username"], "pemain_sintetis")
        self.assertEqual(r["amount"], Decimal("300001.00"))
        self.assertEqual(r["money_delta"], Decimal("300001.00"))
        self.assertEqual(r["fee"], Decimal("3600.00"))
        self.assertEqual(r["occurred_at"], datetime(2026, 8, 13, 16, 24, 21))
        self.assertEqual(r["posted_date"], date(2026, 8, 13))
        self.assertEqual(r["raw"]["APPROVE"], "2026-08-13T23:24:46+07:00+007")
        self.assertEqual(r["raw"]["ID"], "elite-sintetis-1")
        self.assertEqual(r["raw"]["PARTNER ID"], "partner-sintetis")
        self.assertEqual(r["raw"]["VENDOR ID"], "vendor-sintetis")

    def test_flow_wd_tidak_membalik_bentuk_deposit(self):
        r = self._parse([_baris_elite()], flow="wd")[0]

        self.assertEqual(r["jenis"], "depo")
        self.assertGreater(r["money_delta"], 0)

    def test_hash_nominal_dikanonikalkan(self):
        a = self._parse([_baris_elite(**{"RECORD VALUE": "300001.0"})])[0]
        b = self._parse([_baris_elite(**{"RECORD VALUE": "300001.00"})])[0]

        self.assertEqual(a["row_hash"], b["row_hash"])

    def test_status_hanya_success(self):
        rows = self._parse([
            _baris_elite(**{"TICKET": "D1234567", "STATUS": "SUCCESS"}),
            _baris_elite(**{"TICKET": "D1234568", "STATUS": "PENDING"}),
        ])

        self.assertEqual([r["ticket_no"] for r in rows], ["D1234567"])

    def test_semua_status_asing_melempar_dengan_status_ditemukan(self):
        with self.assertRaises(ValueError) as ctx:
            self._parse([
                _baris_elite(**{"TICKET": "D1234567", "STATUS": "PAID"}),
                _baris_elite(**{"TICKET": "D1234568", "STATUS": "PENDING"}),
            ])

        pesan = str(ctx.exception)
        self.assertIn("PAID", pesan)
        self.assertIn("PENDING", pesan)
        self.assertIn("SUCCESS", pesan)

    def test_berkas_tanpa_baris_transaksi_sah_kosong(self):
        self.assertEqual(self._parse([]), [])

    def test_header_wajib_melempar_dan_menyebut_header_yang_ada(self):
        for hilang in ("TICKET", "RECORD VALUE", "RECORD DATE"):
            with self.subTest(hilang=hilang):
                header = [h for h in ELITE_HEADER if h != hilang]
                baris = [["x"] * len(header)]
                with self.assertRaises(ValueError) as ctx:
                    self._parse(baris, header=header)
                pesan = str(ctx.exception)
                self.assertIn(hilang, pesan)
                self.assertIn("Header berkas", pesan)
                self.assertIn("MEMBER", pesan)

    def test_tanggal_transaksi_rusak_melempar_bukan_hilang_senyap(self):
        with self.assertRaises(ValueError) as ctx:
            self._parse([_baris_elite(**{"RECORD DATE": "tanggal-rusak"})])

        self.assertIn("RECORD DATE", str(ctx.exception))
        self.assertIn("D1234567", str(ctx.exception))


class QRISEliteRegistrasiDanDeteksiTests(SimpleTestCase):
    def test_parser_terdaftar(self):
        self.assertIs(services.PARSERS.get("qris_elite"), QRISEliteParser)

    def test_deteksi_dari_header_bukan_ejaan_nama(self):
        path = _csv_elite([_baris_elite()])
        try:
            hasil = detect_source(path, "14_08_2026 W25 DP QRIS ELIT.csv")
        finally:
            os.remove(path)

        self.assertEqual(hasil[0]["parser_key"], "qris_elite")
        self.assertGreaterEqual(hasil[0]["confidence"], 0.95)

    def test_tidak_menabrak_parser_gateway_lain(self):
        kasus = [
            ("zpay", _csv_biasa([
                ["Order ID", "Tiket Number", "Nilai", "Status Settled", "Confirmed Bot At"],
                ["TOKO-pemain-acak", "D1234567", "10000", "Settled", "x"],
            ]), "zpay.csv"),
            ("qhoki", _csv_biasa([
                ["Whitelabel Transaction ID", "NMID", "Amount"],
                ["D1234567", "nmid", "10000"],
            ]), "qhoki.csv"),
            ("nxpay", _xlsx([
                ["judul"],
                ["Ticket Number", "Username", "Amount", "Admin Fee", "Account Title"],
                ["D1234567", "pemain", "10000", "100", "PEMILIK CONTOH"],
            ]), "nxpay.xlsx"),
            ("rpay_xlsx", _xlsx([
                ["Ticket Number", "User Name", "Payment Gateway", "RRN", "Amount (Chip)"],
                ["D1234567", "pemain", "RPAY", "rrn", "10000"],
            ]), "rpay.xlsx"),
            ("rpay_wd_xlsx", _xlsx([
                ["Source of Funds", "Beneficiary", "Disbursed Amount"],
                ["bank", "pemain", "10000"],
            ]), "rpay-wd.xlsx"),
            ("cor_qris_gateway", _xlsx([
                ["BranchName", "OrderId", "GrandTotal", "BranchNominal"],
                ["qris", "id", "10000", "9900"],
            ]), "cor-dp.xlsx"),
            ("cor_qris_wd_gateway", _xlsx([
                ["Order ID (Merchant)", "RecipientName", "AccountNumber"],
                ["id", "pemain", "0812"],
            ]), "cor-wd.xlsx"),
        ]
        flyer = (
            ["TXN ID", "Client Reference", "Transaction Value", "Settlement Time"],
            ["transaction_id", "client_reference", "total_amount", "trans_date_time"],
            ["Transaction Id", "Client Reference", "RRN", "Callback", "Amount"],
            ["transaction_id", "Client Reff", "total_amount", "net_amount", "date"],
        )
        for i, header in enumerate(flyer, start=1):
            kasus.append(("qrflyer", _xlsx([header, ["x"] * len(header)]),
                          f"flyer-{i}.xlsx"))

        try:
            for harapan, path, nama in kasus:
                with self.subTest(parser=harapan, nama=nama):
                    kunci = [r["parser_key"] for r in detect_source(path, nama)]
                    self.assertIn(harapan, kunci)
                    self.assertNotIn("qris_elite", kunci)
        finally:
            for _, path, _ in kasus:
                os.remove(path)


class QRISEliteIdempotensiTests(TestCase):
    def test_ingest_dua_kali_menjadi_duplikat(self):
        path = _csv_elite([_baris_elite()])
        toko = Toko.objects.get(key="lbs")
        try:
            _, dibuat_1, duplikat_1 = services.ingest("qris_elite", path, toko=toko)
            _, dibuat_2, duplikat_2 = services.ingest("qris_elite", path, toko=toko)
        finally:
            os.remove(path)

        self.assertEqual((dibuat_1, duplikat_1), (1, 0))
        self.assertEqual((dibuat_2, duplikat_2), (0, 1))
