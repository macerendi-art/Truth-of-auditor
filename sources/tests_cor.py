import os, tempfile
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from openpyxl import Workbook
# Tes sisi parser boleh memanggil helper engine (arah import sources -> recon
# hanya di tes); larangan layering yg berlaku adalah reconciliation !-> web.
from reconciliation.engine import _expected_owner, _route_ok
from sources.models import SourceType, Toko, Upload
from sources.parsers.base import extract_ticket, parse_bank_triplet, row_hash
from sources.parsers.bracket import BracketParser
from sources.parsers.cor import CORPanelBankParser
from sources.parsers.cor import CORPanelManualDepositParser
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


class CORPanelManualDepositTests(SimpleTestCase):
    """Format ke-2 panel COR: manual deposit / DP ELITE (kolom Date tunggal)."""

    HEADER = ["#", "Date", "Username", "From Bank", "Destination Bank",
              "Amount", "Status", "By"]

    def test_dp_elite_chip_tanggal_dan_selalu_depo(self):
        path = _xlsx([
            self.HEADER,
            ["1", "24 Aug 2026 23:59:54", "raditya2015",
             "MANDIRI - 1140020947027 - HASNIDAR",
             "QRIS - 5615607894 - QRISELITE", "35000", "approved", "win25sub1400"],
        ])
        try:
            # flow=wd sengaja: parser manual deposit tetap depo.
            rows = CORPanelManualDepositParser().parse(path, flow="wd")
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["jenis"], "depo")
        self.assertEqual(r["username"], "raditya2015")
        self.assertEqual(r["amount"], Decimal("35000"))
        self.assertEqual(r["money_delta"], Decimal("35000"))
        self.assertEqual(r["credit_delta"], Decimal("-35000"))
        self.assertEqual(r["bank_title"], "QRISELITE")
        self.assertEqual(r["player_bank"], "MANDIRI")
        self.assertEqual(r["posted_date"], date(2026, 8, 24))
        self.assertEqual(r["occurred_at"], datetime(2026, 8, 24, 23, 59, 54))
        self.assertEqual(r["raw"]["Bank Title"], "QRIS|QRISELITE|5615607894")
        self.assertEqual(r["raw"]["Sumber"], "cor_panel_manual_dp")
        self.assertEqual(r["raw"]["Destination Bank"],
                         "QRIS - 5615607894 - QRISELITE")
        t = SimpleNamespace(raw=r["raw"])
        self.assertEqual(_expected_owner(t), "QRISELITE")
        self.assertEqual(kelas_metode("depo", r["bank_title"]), "QRIS")

    def test_cor_panel_bank_date_tunggal_jadi_dateless(self):
        """Salah pilih cor_panel_bank pada file Date-only → tanggal NULL.

        Itulah cacat yang ditolak guard bertanggal di upload; pakai
        cor_panel_manual_dp.
        """
        path = _xlsx([
            self.HEADER,
            ["1", "24 Aug 2026 23:59:54", "raditya2015",
             "MANDIRI - 1 - A", "QRIS - 5615607894 - QRISELITE",
             "35000", "approved", "op"],
        ])
        try:
            bank = CORPanelBankParser().parse(path, flow="dp")
            manual = CORPanelManualDepositParser().parse(path, flow="dp")
        finally:
            os.remove(path)
        self.assertEqual(len(bank), 1)
        self.assertIsNone(bank[0]["posted_date"])
        self.assertIsNone(bank[0]["occurred_at"])
        self.assertEqual(len(manual), 1)
        self.assertEqual(manual[0]["posted_date"], date(2026, 8, 24))
        self.assertEqual(manual[0]["bank_title"], "QRISELITE")

    def test_registrasi_parses(self):
        self.assertIs(
            services.PARSERS.get("cor_panel_manual_dp"),
            CORPanelManualDepositParser,
        )


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

    # Ekspor rail QRIS tak punya kolom bank tujuan sama sekali (DP) atau cuma
    # bank PEMAIN (WD) -> bank_title dulu kosong: sel tabel/ekspor "—", chip
    # filter bank kosong, dan kartu "Metode Pembayaran" dashboard salah
    # menggolongkannya "Lainnya". Railnya memang QRIS -> label disintesis
    # berbentuk triplet panel "KODE|NAMA|NOREK" dgn NAMA & NOREK kosong.
    def test_dp_bank_title_qris_disintesis(self):
        path = _xlsx([
            self.HEADER,
            ["1", "01 Jul 2026 23:59:56", "01 Jul 2026 23:59:19", "zidanhoki11",
             "03f747e8-ac9c-48e0-a", "85000", "", "success"],
        ])
        try:
            rows = CORPanelQRISParser().parse(path, flow="dp")
        finally:
            os.remove(path)
        r = rows[0]
        self.assertEqual(r["bank_title"], "QRIS")      # kolom = segmen pertama
        self.assertEqual(r["raw"]["Bank Title"], "QRIS||")

    def test_wd_bank_title_qris_tak_mengganggu_player_bank(self):
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
        r = rows[0]
        self.assertEqual(r["bank_title"], "QRIS")      # kolom = segmen pertama
        self.assertEqual(r["raw"]["Bank Title"], "QRIS||")
        # Bank PEMAIN (dari Destination Bank) tetap seperti sebelumnya.
        self.assertEqual(r["player_bank"], "DANA")
        self.assertEqual(r["raw"]["Player Bank"],
                         "DANA|MHD ACHIR FADLI PASARIBU|081261612552")

    def test_label_qris_inert_di_engine(self):
        """Label sintetis TIDAK boleh dibaca engine sebagai nama pemilik rekening.

        `_expected_owner` mengambil segmen TENGAH "Bank Title" (dan jatuh ke
        seluruh string bila tak ada "|"). Label telanjang "QRIS" akan jadi
        `expected="QRIS"` sehingga `_route_ok` — yang dulu selalu None untuk
        baris ini — mulai dievaluasi dan menyalakan kunci sort sekunder pada
        SELURUH populasi COR QRIS. Segmen tengah kosong menjaganya inert.
        """
        path = _xlsx([
            self.HEADER,
            ["1", "01 Jul 2026 23:59:56", "01 Jul 2026 23:59:19", "zidanhoki11",
             "03f747e8-ac9c-48e0-a", "85000", "", "success"],
        ])
        try:
            rows = CORPanelQRISParser().parse(path, flow="dp")
        finally:
            os.remove(path)
        t = SimpleNamespace(raw=rows[0]["raw"])
        self.assertEqual(_expected_owner(t), "")
        self.assertIsNone(_route_ok(_expected_owner(t), "QRIS COR 01 JULI", "gateway"))

    def test_row_hash_tak_ikut_bank_title(self):
        # Penjaga dedup: hash HANYA dari [txid, username, amount]. Kalau label
        # bank ikut dihitung, seluruh file COR QRIS lama akan ter-ingest ulang
        # sebagai baris baru.
        path = _xlsx([
            self.HEADER,
            ["1", "01 Jul 2026 23:59:56", "01 Jul 2026 23:59:19", "zidanhoki11",
             "03f747e8-ac9c-48e0-a", "85000", "", "success"],
        ])
        try:
            rows = CORPanelQRISParser().parse(path, flow="dp")
        finally:
            os.remove(path)
        self.assertEqual(
            rows[0]["row_hash"],
            row_hash("cor_panel_qris",
                     ["03f747e8-ac9c-48e0-a", "zidanhoki11", Decimal("85000")]))


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

    def test_bentuk_dp_menang_meski_flow_wd(self):
        path = _xlsx([
            self.HEADER,
            ["QRIS-7-Beta-TMG3", "85000", "83980", "03f747e8-ac9c-48e0-a",
             "01-Jul-2026 23:59:56", "1pysbjp67783", "-", "-", "Channel 7",
             "03f747e8-ac9c-48e0-a"],
        ])
        try:
            rows = CORQRISGatewayParser().parse(path, flow="wd")
        finally:
            os.remove(path)
        self.assertEqual(rows[0]["jenis"], "depo")
        self.assertEqual(rows[0]["money_delta"], Decimal("85000"))


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


class FRBracketCORTests(SimpleTestCase):
    """Pin-down: file FR (Finance Report) COR/Gacor25 dilayani parser Bracket
    GENERIK apa adanya — tidak perlu parser khusus. Bentuk kolomnya sama persis
    dengan FR Nexus; yang berbeda hanya isinya (Description kosong, jadi tidak
    ada Ticket Number). Tes ini memaku asumsi yang dipakai matcher Panel↔Bracket
    mode username: jenis dari Kategori, nominal bertanda seperti di file,
    ticket_no kosong, dan raw kolom asli utuh."""

    HEADER = ["Tanggal", "Jam", "Asset Bank", "ID", "Description", "Member",
              "Username", "Product", "Expense", "No. Rek Bank Member", "Bank",
              "Total", "Saldo Akhir", "Credit Awal", "Credit Akhir", "Kategori",
              "Status", "OP", "Transaction ID", "Transaction Date",
              "Status Backdated"]

    ROWS = [
        # Deposit backdated: Tanggal (posting FR) 23/07 tapi Transaction Date 22/07.
        ["23/07/2026", "00:00", "Gacor25", "1878", None, "KUSNAMA", "tutupboto",
         "Vigor", None, "UNOPAY 000000003", "QRIS UNOPAY | DEPOSIT / WITHDRAW",
         150000.0, 850159180.0, 128863315.81, 128713315.81, "Deposit", None,
         "gcr25autobracket", "DP38162049", "2026-07-22 23:59:33", "Backdated"],
        ["23/07/2026", "00:02", "Gacor25", "1869", None, "IGNATIUS IVAN",
         "lendhut18", "Vigor", None, "BCA 4840394374",
         "BANK BCA | IGNATIUS IVAN | WITHDRAW", -200000.0, 2840258.79, 500000.0,
         700000.0, "Withdrawal", None, "NICKY", "WD7422265",
         "2026-07-23 00:02:17", None],
        ["23/07/2026", "00:05", "Gacor25", "1869", "BIAYA TRANSFER WD SEABANK ID",
         None, None, None, "Expense", "BRI 714401016406504",
         "BANK BRI | SUPARDI | WITHDRAW", -2500.0, 3394423.0, 0.0, 0.0,
         "BEBAN ADMIN BANK", None, "NICKY", "EX3234134", "2026-07-23 00:05:44",
         None],
    ]

    def _parse(self):
        path = _xlsx([self.HEADER] + self.ROWS)
        try:
            return BracketParser().parse(path)
        finally:
            os.remove(path)

    def test_kategori_dipetakan_ke_jenis(self):
        dp, wd, adm = self._parse()
        self.assertEqual(dp["jenis"], "depo")
        self.assertEqual(wd["jenis"], "wd")
        self.assertEqual(adm["jenis"], "admin")

    def test_nominal_bertanda_seperti_di_file(self):
        dp, wd, adm = self._parse()
        self.assertEqual(dp["money_delta"], Decimal("150000"))    # DP uang masuk
        self.assertEqual(dp["amount"], Decimal("150000"))
        self.assertEqual(wd["money_delta"], Decimal("-200000"))   # WD uang keluar
        self.assertEqual(wd["amount"], Decimal("200000"))
        self.assertEqual(adm["money_delta"], Decimal("-2500"))

    def test_ticket_no_kosong(self):
        # Description FR COR kosong → tak ada ticket. Transaction ID juga BUKAN
        # ticket (dan memang tak pernah dibaca sebagai ticket).
        for row in self._parse():
            self.assertEqual(row["ticket_no"], "")

    def test_transaction_id_bukan_pola_ticket(self):
        # TICKET_RE = [DW]\d{6,9}: 'DP38162049'/'WD7422265' punya HURUF di posisi
        # kedua, jadi tak pernah lolos — bentuk Nexus 'D1234567' tetap lolos.
        self.assertEqual(extract_ticket("DP38162049"), "")
        self.assertEqual(extract_ticket("WD7422265"), "")
        self.assertEqual(extract_ticket("D1234567"), "D1234567")

    def test_username_member_dan_tanggal(self):
        dp, wd, adm = self._parse()
        self.assertEqual(dp["username"], "tutupboto")
        self.assertEqual(dp["counterparty"], "KUSNAMA")
        # Baris backdated: posted_date (kolom Tanggal, dayfirst) ≠ tanggal transaksi.
        self.assertEqual(dp["posted_date"], date(2026, 7, 23))
        self.assertEqual(dp["occurred_at"], datetime(2026, 7, 22, 23, 59, 33))
        self.assertEqual(wd["username"], "lendhut18")
        self.assertEqual(adm["username"], "")   # baris beban tak punya pemain

    def test_raw_kolom_asli_utuh(self):
        dp = self._parse()[0]
        self.assertEqual(dp["raw"]["Bank"], "QRIS UNOPAY | DEPOSIT / WITHDRAW")
        self.assertEqual(dp["raw"]["Kategori"], "Deposit")
        self.assertEqual(dp["raw"]["Jam"], "00:00")
        self.assertEqual(dp["raw"]["Transaction ID"], "DP38162049")
        self.assertEqual(dp["bank_title"], "QRIS UNOPAY")

    def test_row_hash_stabil_antar_parse(self):
        # Idempotensi ingest: file yang sama di-upload dua kali tak boleh
        # menghasilkan hash baru (baris duplikat akan dilewati).
        self.assertEqual([r["row_hash"] for r in self._parse()],
                         [r["row_hash"] for r in self._parse()])
