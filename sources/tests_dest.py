"""Test T1: nomor tujuan (HP e-wallet / norek) sebagai kunci kuat WD.

Ekstraksi dest_account per format bank + Panel, dan normalisasi bersama.
Regex/normalisasi mengikuti hasil validasi di data nyata (BCA/BRI/MANDIRI/Panel).
"""
import csv
import tempfile

from django.test import SimpleTestCase

from sources.parsers.banks import (
    BCACSVParser,
    BRIParser,
    MandiriParser,
    extract_bca_dest,
    extract_bri_dest,
    extract_mandiri_dest,
    is_mandiri_fee,
)
from sources.parsers.base import normalize_dest
from sources.parsers.panel import extract_panel_dest


class NormalizeDestTests(SimpleTestCase):
    """digits-only -> buang '62' -> lstrip('0') -> valid jika >=9 digit."""

    def test_hp_leading_zero_dibuang(self):
        # Panel simpan '0812...' -> ternormalisasi tanpa 0 depan.
        self.assertEqual(normalize_dest("081917710481"), "81917710481")

    def test_hp_tanpa_leading_zero_sama(self):
        # Bank CSV buang '0' depan ('81917710481') -> sama dgn panel ternormalisasi.
        self.assertEqual(normalize_dest("81917710481"), "81917710481")

    def test_kode_negara_62_dibuang(self):
        self.assertEqual(normalize_dest("6282279003062"), "82279003062")

    def test_semua_bentuk_hp_konvergen(self):
        # 0812.. == 812.. == 62812.. setelah normalisasi (kasus wajib #c).
        a = normalize_dest("081234567890")
        b = normalize_dest("81234567890")
        c = normalize_dest("6281234567890")
        self.assertEqual(a, b)
        self.assertEqual(b, c)
        self.assertEqual(a, "81234567890")

    def test_norek_dipertahankan(self):
        self.assertEqual(normalize_dest("1540017669015"), "1540017669015")

    def test_terlalu_pendek_kosong(self):
        # <9 digit -> bukan kunci valid (1 baris panel nyata terlalu pendek).
        self.assertEqual(normalize_dest("12345678"), "")

    def test_non_digit_dibersihkan(self):
        self.assertEqual(normalize_dest(" 0838-2215-3879 "), "83822153879")

    def test_kosong_none(self):
        self.assertEqual(normalize_dest(""), "")
        self.assertEqual(normalize_dest(None), "")


class ExtractBCADestTests(SimpleTestCase):
    """BCA e-wallet topup: HP tujuan setelah pola '- - <hp>' (PDF) / di ekor (CSV)."""

    def test_pdf_dana_pola_dash_dash_hp(self):
        # HENDI PDF: '.../DANA - - 083113323945 TRSF' -> HP setelah '- - '.
        self.assertEqual(
            extract_bca_dest("2606/FTFVA/WS9501139010/DANA - - 083113323945 TRSF E-BANKING DB"),
            "83113323945",
        )

    def test_gopay_topup_pola_dash_dash_hp(self):
        self.assertEqual(
            extract_bca_dest("2606/FTFVA/WS9501170001/GOPAY TOPUP - - 085795753516"),
            "85795753516",
        )

    def test_csv_nijun_hp_di_ekor_tanpa_nol(self):
        # NIJUN CSV: HP di ekor tanpa '0' depan ('.../DANA  -  -  81917710481').
        self.assertEqual(
            extract_bca_dest(
                "TRSF E-BANKING DB 2606/FTFVA/WS9501139010/DANA        -                 -                 81917710481"
            ),
            "81917710481",
        )

    def test_transfer_ke_nama_tanpa_nomor_kosong(self):
        # Transfer bank-ke-bank hanya NAMA, tak ada nomor tujuan -> '' (jangan karang).
        self.assertEqual(extract_bca_dest("TRANSFER KE 535 ROZALI MyBCA BI-FAST DB"), "")
        self.assertEqual(
            extract_bca_dest("TRSF E-BANKING CR 2606/FTSCY/WS95031 3000000.00MARIO KARO-KARO"),
            "",
        )

    def test_kosong(self):
        self.assertEqual(extract_bca_dest(""), "")
        self.assertEqual(extract_bca_dest(None), "")


class ExtractBRIDestTests(SimpleTestCase):
    """BRI: BFST<nomor> (transfer keluar e-wallet) & BRIVA<va> (virtual account)."""

    def test_bfst_transfer_keluar(self):
        self.assertEqual(
            extract_bri_dest("BFST2037645783 NBMB:0001500F:151731713566"),
            "2037645783",
        )

    def test_briva_virtual_account(self):
        self.assertEqual(
            extract_bri_dest("BRIVA 12345678901234 PANCA"),
            "12345678901234",
        )

    def test_nbmb_internal_tanpa_nomor_kosong(self):
        # Baris internal 'NBMB ... TO <NAMA> ESB:...': ekor angka = referensi ESB,
        # BUKAN norek tujuan -> '' (by design, bukan bug).
        self.assertEqual(
            extract_bri_dest("NBMB PANCA SENTANA TO ZAENUL BASYAR ESB:NBMB:0001500F:151731713566"),
            "",
        )

    def test_kosong(self):
        self.assertEqual(extract_bri_dest(""), "")


class ExtractMandiriDestTests(SimpleTestCase):
    """Mandiri e-statement: norek/HP tujuan = run digit >=9 di EKOR Keterangan.
    'Transfer ke BANK MANDIRI TRIYONO 1680000099422' -> norek penerima;
    'Pembayaran GoPay Customer 085822815507' -> HP e-wallet (DANA/GoPay match
    via NOMOR — nama sering kosong); baris 'Biaya ...' bukan tujuan."""

    def test_transfer_ke_norek_di_ekor(self):
        self.assertEqual(
            extract_mandiri_dest("Transfer ke BANK MANDIRI TRIYONO 1680000099422"),
            "1680000099422",
        )

    def test_pembayaran_ewallet_hp_ternormalisasi(self):
        self.assertEqual(
            extract_mandiri_dest("Pembayaran GoPay Customer 085822815507"),
            "85822815507",
        )

    def test_biaya_tanpa_dest(self):
        self.assertEqual(extract_mandiri_dest("Biaya transfer BI Fast"), "")
        self.assertEqual(extract_mandiri_dest("Biaya transaksi bank 123456789012"), "")

    def test_tanpa_nomor_kosong(self):
        self.assertEqual(extract_mandiri_dest("Transfer BI Fast"), "")
        self.assertEqual(extract_mandiri_dest(""), "")
        self.assertEqual(extract_mandiri_dest(None), "")


class MandiriFeeTests(SimpleTestCase):
    def test_baris_biaya(self):
        self.assertTrue(is_mandiri_fee("Biaya transfer BI Fast"))
        self.assertTrue(is_mandiri_fee("Biaya transaksi bank"))
        self.assertFalse(is_mandiri_fee("Transfer ke BANK MANDIRI TRIYONO 168000"))
        self.assertFalse(is_mandiri_fee(""))


class MandiriParserDestFeeTests(SimpleTestCase):
    """Parser Mandiri mengisi dest_account + menandai baris 'Biaya ...' jenis=admin
    (analog fee BCA — biaya bukan WD nyata, jangan menggelembungkan total uang)."""

    def _parse(self, rows):
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["No", "Tanggal", "Keterangan",
                   "Dana Masuk (IDR)", "Dana Keluar (IDR)", "Saldo (IDR)"])
        for r in rows:
            ws.append(r)
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = f.name
        wb.save(path)
        return MandiriParser().parse(path)

    def test_dest_terisi_dan_fee_admin(self):
        rows = self._parse([
            ["1", "27 Jun 2026", "Transfer ke BANK MANDIRI TRIYONO 1680000099422",
             0, 50000.00, 1791693.00],
            ["2", "27 Jun 2026", "Biaya transfer BI Fast", 0, 2500.00, 1789193.00],
            ["3", "27 Jun 2026", "Pembayaran GoPay Customer 085822815507",
             0, 50000.00, 1738693.00],
        ])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["dest_account"], "1680000099422")
        self.assertEqual(rows[0]["jenis"], "wd")
        self.assertEqual(rows[1]["jenis"], "admin")
        self.assertEqual(rows[1]["dest_account"], "")
        self.assertEqual(rows[2]["dest_account"], "85822815507")


class ExtractPanelDestTests(SimpleTestCase):
    """Panel: dest dari raw 'Player Bank' segmen ke-3 (split '|'), dinormalisasi sama."""

    def test_dana_hp(self):
        self.assertEqual(
            extract_panel_dest("DANA|fajar Pratama |083822153879"),
            "83822153879",
        )

    def test_bca_norek(self):
        self.assertEqual(
            extract_panel_dest("BCA|HENDI|7126201591"),
            "7126201591",
        )

    def test_segmen_kurang_kosong(self):
        self.assertEqual(extract_panel_dest("DANA|fajar"), "")
        self.assertEqual(extract_panel_dest(""), "")
        self.assertEqual(extract_panel_dest(None), "")


class BCADestParserTests(SimpleTestCase):
    """Parser BCA CSV mengisi dest_account dari deskripsi topup e-wallet."""

    def test_csv_parser_sets_dest_for_ewallet(self):
        rows = [
            ["No. Rekening", "=", "'0202405914"],
            ["Nama", "=", "NIJUN"],
            [],
            ["Tanggal", "Keterangan", "Cabang", "Jumlah", "", "Saldo"],
            [
                "'27/06/2026",
                "TRSF E-BANKING DB 2606/FTFVA/WS9501139010/DANA        -                 -                 81917710481",
                "'0000", "50000.00", "DB", "11770137.00",
            ],
            [
                "'27/06/2026",
                "BI-FAST DB TRANSFER   KE 009 FAHRIAH           KBI",
                "'0000", "2000000.00", "DB", "9770137.00",
            ],
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".CSV", delete=False, newline="") as f:
            csv.writer(f).writerows(rows)
            path = f.name
        parsed = BCACSVParser().parse(path)
        by_amt = {str(p["amount"]): p for p in parsed}
        # E-wallet topup -> dest terisi (HP ternormalisasi).
        self.assertEqual(by_amt["50000.00"]["dest_account"], "81917710481")
        # Transfer bank-ke-bank hanya nama -> dest kosong.
        self.assertEqual(by_amt["2000000.00"]["dest_account"], "")


class BRIDestParserTests(SimpleTestCase):
    """Parser BRI mengisi dest_account dari BFST/BRIVA di deskripsi."""

    HEADER = [
        "ID", "NOREK", "TGL_TRAN", "TGL_EFEKTIF", "JAM_TRAN", "SEQ", "DESK_TRAN",
        "SALDO_AWAL_MUTASI", "MUTASI_DEBET", "MUTASI_KREDIT", "SALDO_AKHIR_MUTASI",
        "GLSIGN", "TRUSER", "KODE_TRAN", "KODE_TRAN_TELLER", "TRREMK", "TLBDS1", "TLBDS2",
        "REMARK_CUSTOM",
    ]

    def _parse_one(self, desc, debet="100000.00", kredit=".00"):
        row = ["1", "181201005938507", "2026-06-27 10:00:00", "2026-06-27 10:00:00", "1000",
               "4110000", desc, "0.00", debet, kredit, "100000.00", "Db", "x", "2", "8506",
               "", "", "", ""]
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
            w = csv.writer(f)
            w.writerow(self.HEADER)
            w.writerow(row)
            path = f.name
        rows = BRIParser().parse(path)
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_bfst_dest_extracted(self):
        r = self._parse_one("BFST2037645783 NBMB:0001500F:151731713566")
        self.assertEqual(r["dest_account"], "2037645783")

    def test_nbmb_internal_no_dest(self):
        r = self._parse_one("NBMB PANCA SENTANA TO ZAENUL BASYAR ESB:NBMB:0001500F:151731713566")
        self.assertEqual(r["dest_account"], "")
