import os, tempfile
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from openpyxl import Workbook
from sources.models import SourceType, Toko, Upload
from sources.parsers.base import parse_bank_triplet
from sources.parsers.cor import CORPanelBankParser
from sources.parsers.cor import CORPanelQRISParser
from sources.parsers.cor import CORQRISGatewayParser
from sources.parsers.cor import resolve_oth_bank
from sources import services
from transactions.models import Transaction
from web.channels import kelas_metode

class BankTripletTests(SimpleTestCase):
    def test_triplet_bank(self):
        self.assertEqual(parse_bank_triplet("BCA - 2941413058 - BAGAS ARMANDO"),
                         ("BCA", "2941413058", "BAGAS ARMANDO"))

    def test_triplet_ewallet_dengan_slash_di_nama(self):
        self.assertEqual(
            parse_bank_triplet("OTH - 4840394374 - IGNATIUS IVAN / WITHDRAW BCA"),
            ("OTH", "4840394374", "IGNATIUS IVAN / WITHDRAW BCA"))

    def test_triplet_tanpa_spasi(self):
        # Rail QRIS/UNOPAY menulis "KODE-NOREK-NAMA" rapat (tanpa spasi kelilingi
        # '-'), berbeda dari rail bank yang pakai " - ". Harus tetap terpecah 3.
        self.assertEqual(
            parse_bank_triplet("DANA-081261612552-MHD ACHIR FADLI PASARIBU"),
            ("DANA", "081261612552", "MHD ACHIR FADLI PASARIBU"))
        # nama boleh memuat '-' internal -> hanya 2 pemisah pertama yang dipecah
        self.assertEqual(
            parse_bank_triplet("BCA-8295463623-RYAN-GRIFFITH"),
            ("BCA", "8295463623", "RYAN-GRIFFITH"))

    def test_triplet_berspasi_dgn_hyphen_internal(self):
        # Rail bank (" - "): kode/norek ber-'-' internal HARUS utuh — pemisah
        # berspasi diutamakan supaya tak ada regresi vs perilaku lama.
        self.assertEqual(parse_bank_triplet("LAIN-LAIN - 000 - NAMA"),
                         ("LAIN-LAIN", "000", "NAMA"))
        self.assertEqual(parse_bank_triplet("DANA - 0812-6161 - NAMA"),
                         ("DANA", "0812-6161", "NAMA"))

    def test_triplet_kosong(self):
        self.assertEqual(parse_bank_triplet(""), ("", "", ""))
        self.assertEqual(parse_bank_triplet(None), ("", "", ""))


def _xlsx(rows):
    wb = Workbook(); ws = wb.active
    for r in rows:
        ws.append(r)
    fd, path = tempfile.mkstemp(suffix=".xlsx"); os.close(fd)
    wb.save(path)
    return path


class CORPanelBankTests(SimpleTestCase):
    HEADER = ["#", "Approved Date", "Requested Date", "Username", "From Bank",
              "Destination Bank", "Amount", "Status", "By"]

    def test_dp_rupiah_dan_bank_fields(self):
        path = _xlsx([
            self.HEADER,
            ["1", "01 Jul 2026 23:52:18", "01 Jul 2026 23:50:06", "febri72",
             "DANA - 081270670097 - FEBRIA MEGASARI",
             "BCA - 2941413058 - BAGAS ARMANDO", "200000", "approved", "gacor25sub59"],
        ])
        try:
            rows = CORPanelBankParser().parse(path, flow="dp")
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["jenis"], "depo")
        self.assertEqual(str(r["amount"]), "200000")        # RUPIAH, tanpa x1000
        self.assertEqual(str(r["money_delta"]), "200000")
        self.assertEqual(str(r["credit_delta"]), "-200000")
        self.assertEqual(r["counterparty"], "FEBRIA MEGASARI")   # pemain = From Bank
        self.assertEqual(r["player_bank"], "DANA")
        self.assertEqual(r["bank_title"], "BCA")                 # operator = Destination
        self.assertEqual(r["ticket_no"], "")
        self.assertIn("081270670097", r["raw"]["Player Bank"])   # utk phone-match

    def test_wd_membalik_sisi_dan_tanda(self):
        path = _xlsx([
            self.HEADER,
            ["1", "01 Jul 2026 23:57:08", "01 Jul 2026 23:56:43", "zhaa1234",
             "OTH - 4840394374 - IGNATIUS IVAN / WITHDRAW BCA",
             "DANA - 082112822248 - RUSMAN", "350000", "approved", "gacor25sub40"],
        ])
        try:
            rows = CORPanelBankParser().parse(path, flow="wd")
        finally:
            os.remove(path)
        r = rows[0]
        self.assertEqual(r["jenis"], "wd")
        self.assertEqual(str(r["money_delta"]), "-350000")
        self.assertEqual(str(r["credit_delta"]), "350000")
        self.assertEqual(r["counterparty"], "RUSMAN")            # pemain = Destination (WD)
        self.assertEqual(r["player_bank"], "DANA")

    def test_skip_non_approved(self):
        path = _xlsx([self.HEADER,
            ["1", "01 Jul 2026 00:00:00", "01 Jul 2026 00:00:00", "x",
             "BCA - 1 - A", "BCA - 2 - B", "1000", "pending", "op"]])
        try:
            self.assertEqual(CORPanelBankParser().parse(path, flow="dp"), [])
        finally:
            os.remove(path)

    def test_wd_oth_terurai_ke_bank_asli(self):
        # Akun WD situs sendiri (Vigor/TM Gaming) berlabel "OTH" -> bank asli
        # tersimpan di ekor nama ("... / WITHDRAW BCA"). Tanpa urai ini, chip
        # filter Bank Title run-detail menumpuk 1212/1277 baris jadi 1 "OTH".
        path = _xlsx([
            self.HEADER,
            ["1", "01 Jul 2026 23:57:08", "01 Jul 2026 23:56:43", "zhaa1234",
             "OTH - 4840394374 - IGNATIUS IVAN / WITHDRAW BCA",
             "DANA - 082112822248 - RUSMAN", "350000", "approved", "gacor25sub40"],
        ])
        try:
            rows = CORPanelBankParser().parse(path, flow="wd")
        finally:
            os.remove(path)
        r = rows[0]
        self.assertEqual(r["bank_title"], "BCA")
        self.assertEqual(r["raw"]["From Bank"],
                          "OTH - 4840394374 - IGNATIUS IVAN / WITHDRAW BCA")  # raw asli utuh
        self.assertEqual(r["raw"]["Bank Title"],
                          "BCA|IGNATIUS IVAN / WITHDRAW BCA|4840394374")

    def test_dp_oth_varian_deposit_terurai(self):
        path = _xlsx([
            self.HEADER,
            ["1", "01 Jul 2026 23:52:18", "01 Jul 2026 23:50:06", "febri72",
             "DANA - 081270670097 - FEBRIA MEGASARI",
             "OTH - 1966367781 - SUPRIYADI / DEPOSIT BNI",
             "200000", "approved", "gacor25sub59"],
        ])
        try:
            rows = CORPanelBankParser().parse(path, flow="dp")
        finally:
            os.remove(path)
        r = rows[0]
        self.assertEqual(r["bank_title"], "BNI")
        self.assertEqual(r["raw"]["Destination Bank"],
                          "OTH - 1966367781 - SUPRIYADI / DEPOSIT BNI")

    def test_oth_tanpa_pola_bank_tetap_oth(self):
        path = _xlsx([
            self.HEADER,
            ["1", "01 Jul 2026 23:57:08", "01 Jul 2026 23:56:43", "zhaa1234",
             "OTH - 4840394374 - NAMA TANPA POLA",
             "DANA - 082112822248 - RUSMAN", "350000", "approved", "gacor25sub40"],
        ])
        try:
            rows = CORPanelBankParser().parse(path, flow="wd")
        finally:
            os.remove(path)
        self.assertEqual(rows[0]["bank_title"], "OTH")

    def test_non_oth_tak_tersentuh(self):
        # test_dp_rupiah_dan_bank_fields sudah menutupi jalur non-OTH biasa;
        # ini menegaskan kode non-OTH lain (mis. "DANA") juga tak diutak-atik.
        path = _xlsx([
            self.HEADER,
            ["1", "01 Jul 2026 23:57:08", "01 Jul 2026 23:56:43", "zhaa1234",
             "DANA - 4840394374 - IGNATIUS IVAN / WITHDRAW BCA",
             "DANA - 082112822248 - RUSMAN", "350000", "approved", "gacor25sub40"],
        ])
        try:
            rows = CORPanelBankParser().parse(path, flow="wd")
        finally:
            os.remove(path)
        self.assertEqual(rows[0]["bank_title"], "DANA")


class ResolveOthBankTests(SimpleTestCase):
    """Unit test `resolve_oth_bank` — dipakai parser & command backfill."""

    def test_wd_bca(self):
        self.assertEqual(
            resolve_oth_bank("OTH", "IGNATIUS IVAN / WITHDRAW BCA"), "BCA")

    def test_wd_bni(self):
        self.assertEqual(
            resolve_oth_bank("OTH", "SUPRIYADI / WITHDRAW BNI"), "BNI")

    def test_wd_bri(self):
        self.assertEqual(
            resolve_oth_bank("OTH", "SUPARDI / WITHDRAW BRI"), "BRI")

    def test_wd_bca_supardi(self):
        self.assertEqual(
            resolve_oth_bank("OTH", "SUPARDI / WITHDRAW BCA"), "BCA")

    def test_deposit_varian(self):
        self.assertEqual(
            resolve_oth_bank("OTH", "BUDI / DEPOSIT MANDIRI"), "MANDIRI")

    def test_non_oth_kembali_apa_adanya(self):
        self.assertEqual(resolve_oth_bank("BCA", "APA SAJA / WITHDRAW BNI"), "BCA")
        self.assertEqual(resolve_oth_bank("DANA", ""), "DANA")

    def test_oth_tanpa_pola_tetap_oth(self):
        self.assertEqual(resolve_oth_bank("OTH", "NAMA POLOS"), "OTH")
        self.assertEqual(resolve_oth_bank("OTH", ""), "OTH")
        self.assertEqual(resolve_oth_bank("OTH", None), "OTH")

    def test_kode_kosong_atau_none(self):
        self.assertEqual(resolve_oth_bank("", "APA SAJA"), "")
        self.assertEqual(resolve_oth_bank(None, "APA SAJA"), None)


class KelasMetodeOthPinTests(SimpleTestCase):
    """Pin: "OTH" mentah sudah jatuh ke bucket "Bank" (fallback tanpa QR/NXPAY),
    sama seperti kode bank asli hasil urai — jadi fix ini tak mengubah bucket
    kartu dashboard "Metode Pembayaran", cuma memecah isi bucket Bank lebih rinci."""

    def test_oth_dan_bca_sama_sama_bucket_bank(self):
        self.assertEqual(kelas_metode("wd", "BCA"), "Bank")
        self.assertEqual(kelas_metode("wd", "OTH"), "Bank")
        self.assertEqual(kelas_metode("wd", "BCA"), kelas_metode("wd", "OTH"))


class BackfillOthBankCommandTests(TestCase):
    """Command idempoten: baris `panel` lama dengan bank_title=="OTH" diurai
    ulang dari segmen tengah raw["Bank Title"] (nama), tanpa menyentuh raw."""

    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.toko_lain = Toko.objects.get(key="slo")
        self.st_panel = SourceType.objects.get(key="panel")
        self.up = Upload.objects.create(
            source_type=self.st_panel, toko=self.toko, original_name="lama.xlsx")

    def _buat_baris_oth(self, toko=None, upload=None, acct="4840394374",
                         nama="IGNATIUS IVAN / WITHDRAW BCA", row_hash="backfill-oth-1"):
        return Transaction.objects.create(
            upload=upload or self.up, source_type=self.st_panel, toko=toko or self.toko,
            jenis="wd", amount=Decimal("350000"), credit_delta=Decimal("350000"),
            money_delta=Decimal("-350000"), ticket_no="", username="zhaa1234",
            reference="", counterparty="RUSMAN", player_bank="DANA", bank_title="OTH",
            raw={
                "From Bank": f"OTH - {acct} - {nama}",
                "Bank Title": f"OTH|{nama}|{acct}",
            },
            row_hash=row_hash,
        )

    def test_backfill_mengurai_oth_jadi_bank_asli(self):
        tx = self._buat_baris_oth()
        out = StringIO()
        call_command("backfill_oth_bank", stdout=out)
        tx.refresh_from_db()
        self.assertEqual(tx.bank_title, "BCA")
        self.assertEqual(tx.raw["From Bank"],
                          "OTH - 4840394374 - IGNATIUS IVAN / WITHDRAW BCA")  # raw tak berubah
        laporan = out.getvalue()
        self.assertIn("diperiksa=1", laporan)
        self.assertIn("diubah=1", laporan)
        self.assertIn("dilewati=0", laporan)

    def test_backfill_idempoten_jalan_dua_kali(self):
        self._buat_baris_oth()
        call_command("backfill_oth_bank")
        out2 = StringIO()
        call_command("backfill_oth_bank", stdout=out2)
        self.assertIn("diubah=0", out2.getvalue())

    def test_backfill_dry_run_tidak_menulis(self):
        tx = self._buat_baris_oth()
        out = StringIO()
        call_command("backfill_oth_bank", "--dry-run", stdout=out)
        tx.refresh_from_db()
        self.assertEqual(tx.bank_title, "OTH")  # tak ditulis
        self.assertIn("diubah=1", out.getvalue())  # tapi tetap dihitung/dilaporkan

    def test_backfill_tanpa_pola_bank_dilewati(self):
        tx = self._buat_baris_oth(nama="TANPA POLA BANK")
        out = StringIO()
        call_command("backfill_oth_bank", stdout=out)
        tx.refresh_from_db()
        self.assertEqual(tx.bank_title, "OTH")
        self.assertIn("dilewati=1", out.getvalue())

    def test_backfill_filter_toko(self):
        up_lain = Upload.objects.create(
            source_type=self.st_panel, toko=self.toko_lain, original_name="lain.xlsx")
        tx_lbs = self._buat_baris_oth(row_hash="backfill-oth-lbs")
        tx_lain = self._buat_baris_oth(
            toko=self.toko_lain, upload=up_lain, row_hash="backfill-oth-lain")
        call_command("backfill_oth_bank", "--toko", "lbs")
        tx_lbs.refresh_from_db()
        tx_lain.refresh_from_db()
        self.assertEqual(tx_lbs.bank_title, "BCA")
        self.assertEqual(tx_lain.bank_title, "OTH")  # toko lain tak tersentuh


class CORPanelQRISTests(SimpleTestCase):
    HEADER = ["#", "Approved Date", "Requested Date", "Username",
              "Transaction ID", "Amount", "Bonus", "Status"]

    def test_dp_reference_uuid(self):
        path = _xlsx([
            self.HEADER,
            ["1", "01 Jul 2026 23:59:56", "01 Jul 2026 23:59:19", "zidanhoki11",
             "03f747e8-ac9c-48e0-a", "85000", "", "success"],
        ])
        try:
            rows = CORPanelQRISParser().parse(path, flow="dp")
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["jenis"], "depo")
        self.assertEqual(str(r["amount"]), "85000")
        self.assertEqual(r["reference"], "03f747e8-ac9c-48e0-a")   # kunci exact
        self.assertEqual(r["ticket_no"], "")
        self.assertEqual(r["username"], "zidanhoki11")

    def test_skip_tanpa_txid(self):
        path = _xlsx([self.HEADER,
            ["1", "x", "x", "user", "", "1000", "", "success"]])
        try:
            self.assertEqual(CORPanelQRISParser().parse(path, flow="dp"), [])
        finally:
            os.remove(path)

    # WD QRIS/UNOPAY: Destination Bank rapat "KODE-NOREK-NAMA" (tanpa spasi).
    # Regresi prod 11-07-2026: player_bank memuat string 42+ karakter penuh ->
    # varchar(40) overflow di Postgres. Harus jadi kode bank pendek + nama pemain.
    WD_HEADER = ["#", "Approved Date", "Requested Date", "Username",
                 "Transaction ID", "Destination Bank", "Amount", "Status", "By"]

    def test_wd_destination_bank_rapat(self):
        path = _xlsx([
            self.WD_HEADER,
            ["1", "11 Jul 2026 23:03:05", "11 Jul 2026 23:02:56", "batako87",
             "1d4c8093-f8b0-482a-af1f-dc452ef7ed6a",
             "DANA-081261612552-MHD ACHIR FADLI PASARIBU", "800000", "success",
             "gacor25sub42"],
        ])
        try:
            rows = CORPanelQRISParser().parse(path, flow="wd")
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["jenis"], "wd")
        self.assertEqual(r["player_bank"], "DANA")
        self.assertLessEqual(len(r["player_bank"]), 40)   # tak boleh overflow
        self.assertEqual(r["counterparty"], "MHD ACHIR FADLI PASARIBU")
        self.assertEqual(r["reference"], "1d4c8093-f8b0-482a-af1f-dc452ef7ed6a")


class CORQRISGatewayTests(SimpleTestCase):
    HEADER = ["BranchName", "GrandTotal", "BranchNominal", "OrderId",
              "TransactionTime", "RRN", "IssuerName", "CustomerName",
              "Channel", "Order Id Merchant"]

    def test_gateway_reference_gross_fee(self):
        path = _xlsx([
            self.HEADER,
            ["QRIS-7-Beta-TMG3", "85000", "83980", "03f747e8-ac9c-48e0-a",
             "01-Jul-2026 23:59:56", "1pysbjp67783", "-", "-", "Channel 7",
             "03f747e8-ac9c-48e0-a"],
        ])
        try:
            rows = CORQRISGatewayParser().parse(path, flow="dp")
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["source_type"], "gateway")
        self.assertEqual(r["jenis"], "depo")
        self.assertEqual(str(r["amount"]), "85000")          # gross
        self.assertEqual(str(r["money_delta"]), "85000")
        self.assertEqual(str(r["fee"]), "1020")              # 85000 - 83980
        self.assertEqual(r["reference"], "03f747e8-ac9c-48e0-a")
        self.assertEqual(r["ticket_no"], "")


class IngestBankFieldsTests(TestCase):
    def test_ingest_panel_mengisi_player_bank(self):
        path = _xlsx([
            CORPanelBankTests.HEADER,
            ["1", "01 Jul 2026 23:52:18", "01 Jul 2026 23:50:06", "febri72",
             "DANA - 081270670097 - FEBRIA MEGASARI",
             "BCA - 2941413058 - BAGAS ARMANDO", "200000", "approved", "gacor25sub59"],
        ])
        try:
            services.ingest("cor_panel_bank", path, flow="dp")
        finally:
            os.remove(path)
        t = Transaction.objects.get()
        self.assertEqual(t.player_bank, "DANA")
        self.assertEqual(t.bank_title, "BCA")
