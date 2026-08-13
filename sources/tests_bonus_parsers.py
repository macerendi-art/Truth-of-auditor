"""Parser bonus: panel Credit Balance & bracket Credit/Non-Credit Bonus."""
import os
import tempfile

from django.test import SimpleTestCase
from openpyxl import Workbook


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    wb.save(path)
    return path


# --- Panel Credit Balance (bonus) ---------------------------------------

PANEL_HEADER = ["No.", "Brand", "Date & Time", "Description", "Remarks",
                "Payment Type", "Payment Details", "Amt.", "Current Credit Balance"]

PANEL_ROWS = [
    [1, "M77", "15-Jul-2026 00:00:09.927", "Deposit M77Aaa", "",
     "Bank Transfer", "", 500, 10000],
    [2, "M77", "15-Jul-2026 00:05:00.000", "Withdraw M77Bbb", "",
     "Bank Transfer", "", -200, 9800],
    [3, "M77", "15-Jul-2026 00:00:00.000", "Opening Balance", "",
     "", "", 0, 10000],
    [4, "M77", "15-Jul-2026 01:00:00.000",
     "Offset M77ccc Lucky Draw Agent: ...", "", "", "", 50, 10050],
    [5, "M77", "15-Jul-2026 01:00:05.000",
     "Lucky Draw Agent: Gold Ticket - Event X M77Ccc", "", "", "", -50, 10000],
    [6, "M77", "15-Jul-2026 02:00:00.000",
     "Redemption Coupon: CREDIT 15.000 - x:1 M77Ddd", "", "", "", -15, 9985],
    [7, "M77", "15-Jul-2026 03:00:00.000",
     "Promotion Claim: BONUS NEW MEMBER 30% SLOT - [D123] - M77Eee", "",
     "", "", -15, 9970],
    [8, "M77", "15-Jul-2026 04:00:00.000", "Adjustment: M77Fff", "K-BCR3",
     "", "", -5, 9965],
]


class PanelBonusParserTests(SimpleTestCase):
    def _parse(self):
        from sources.parsers.bonus import PanelBonusParser
        path = _xlsx([["Credit Balance Report"], PANEL_HEADER] + PANEL_ROWS)
        try:
            return PanelBonusParser().parse(path)
        finally:
            os.remove(path)

    def test_hanya_baris_bonus_yang_diambil(self):
        rows = self._parse()
        self.assertEqual(len(rows), 4)

    def test_field_umum_setiap_baris(self):
        for r in self._parse():
            self.assertEqual(r["jenis"], "bonus")
            self.assertEqual(str(r["money_delta"]), "0")
            self.assertEqual(r["ticket_no"], "")
            self.assertLess(r["credit_delta"], 0)
            self.assertIsNotNone(r["posted_date"])
            self.assertEqual(r["posted_date"].day, 15)

    def test_lucky_draw(self):
        r = next(r for r in self._parse() if r["raw"]["Kategori"] == "Lucky Draw")
        self.assertEqual(r["username"], "Ccc")
        self.assertEqual(str(r["amount"]), "50000")
        self.assertEqual(str(r["credit_delta"]), "-50000")

    def test_redemption_coupon(self):
        r = next(r for r in self._parse()
                 if r["raw"]["Kategori"] == "Redemption Coupon")
        self.assertEqual(r["username"], "Ddd")
        self.assertEqual(str(r["amount"]), "15000")

    def test_promotion_claim(self):
        r = next(r for r in self._parse()
                 if r["raw"]["Kategori"] == "Promotion Claim")
        self.assertEqual(r["username"], "Eee")
        self.assertEqual(str(r["amount"]), "15000")

    def test_adjustment(self):
        r = next(r for r in self._parse() if r["raw"]["Kategori"] == "Adjustment")
        self.assertEqual(r["username"], "Fff")
        self.assertEqual(str(r["amount"]), "5000")

    def test_offset_deposit_withdraw_opening_dilewati(self):
        kategoris = {r["raw"]["Kategori"] for r in self._parse()}
        self.assertEqual(
            kategoris, {"Lucky Draw", "Redemption Coupon", "Promotion Claim", "Adjustment"})

    def test_row_hash_stabil(self):
        a = self._parse()
        b = self._parse()
        self.assertEqual([r["row_hash"] for r in a], [r["row_hash"] for r in b])


# --- Bracket Credit/Non-Credit Bonus -------------------------------------

BRACKET_HEADER_TANPA_CATEGORY = ["Transaction ID", "Date", "Description",
                                  "Nominal", "Deleted", "Created By"]
BRACKET_HEADER_LENGKAP = ["Transaction ID", "Date", "Category", "Description",
                           "Nominal", "Deleted", "Created By"]


class BracketBonusParserNonCreditTests(SimpleTestCase):
    """Varian TANPA kolom Category — kode di Description (K-BLD = Lucky Draw)."""

    def _parse(self, rows):
        from sources.parsers.bonus import BracketBonusParser
        path = _xlsx([BRACKET_HEADER_TANPA_CATEGORY] + rows)
        try:
            return BracketBonusParser().parse(path)
        finally:
            os.remove(path)

    def test_deleted_dilewati(self):
        rows = self._parse([
            ["TID1", "15-Jul-2026 05:00:00", "K-BLD\nPlayer: skip", 1000,
             "Yes", "adminx"],
        ])
        self.assertEqual(rows, [])

    def test_kode_bld_lucky_draw(self):
        rows = self._parse([
            ["TID2", "15-Jul-2026 05:05:00", "K-BLD\nPlayer: Ggg", 30000,
             "No", "adminx"],
        ])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["raw"]["Kategori"], "Lucky Draw")
        self.assertEqual(r["username"], "Ggg")
        self.assertEqual(str(r["amount"]), "30000")
        self.assertEqual(str(r["credit_delta"]), "-30000")
        self.assertEqual(r["jenis"], "bonus")
        self.assertEqual(str(r["money_delta"]), "0")


class BracketBonusParserCreditTests(SimpleTestCase):
    """Varian LENGKAP dengan kolom Category — kategori dipakai verbatim."""

    def _parse(self, rows):
        from sources.parsers.bonus import BracketBonusParser
        path = _xlsx([BRACKET_HEADER_LENGKAP] + rows)
        try:
            return BracketBonusParser().parse(path)
        finally:
            os.remove(path)

    def test_category_verbatim_dan_nominal_tanpa_x1000(self):
        rows = self._parse([
            ["TID3", "15-Jul-2026 06:00:00", "BONUS LOYALTY MURAH (BL1)",
             "Some header text\nPlayer: hhh", 25000, "No", "adminx"],
        ])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["raw"]["Kategori"], "BONUS LOYALTY MURAH (BL1)")
        self.assertEqual(r["username"], "hhh")
        self.assertEqual(str(r["amount"]), "25000")
        self.assertEqual(str(r["credit_delta"]), "-25000")


# --- Panel bonus COR / Vigor-TM Gaming (cor_panel_bonus) -----------------

COR_HEADER = ["#", "Date", "Username", "Event Type", "Event Name",
              "Amount", "Description"]

COR_ROWS = [
    ["1", "04 Aug 2026 00:00:13", "bodatt", "Bonus Cashback",
     "BONUS ROLLINGAN SLOT HARIAN 0.5%", "85,770",
     "Free Bet: BONUS ROLLINGAN SLOT HARIAN 0.5% (85,770)"],
    ["2", "04 Aug 2026 00:05:32", "bulbul26", "Daily Spin Bonus",
     "Daily Login", "25", "Free Bet: Daily Login (25)"],
    # Event Name kosong -> kategori jatuh ke Event Type.
    ["3", "04 Aug 2026 01:00:00", "w25master", "Manual Freebet", "",
     "10,000", "Free Bet: Manual Freebet (10,000)"],
    # Event Name & Event Type kosong -> kategori jatuh ke "Bonus".
    ["4", "04 Aug 2026 02:00:00", "zeta9", "", "", "40,351.5",
     "Free Bet: (40,351.5)"],
]

# 85.770 + 25 + 10.000 + 40.351,5
COR_TOTAL = "136146.5"
COR_FOOTER = [
    ["", "", "", "", "Page Total", "136,146.5"],
    ["", "", "", "", "Grand Total", "136,146.5"],
]


class CORPanelBonusParserTests(SimpleTestCase):
    """Bentuk kedua bonus panel: keluarga COR (Vigor/TM Gaming), rupiah penuh."""

    def _parse(self, rows=None, header=None):
        from sources.parsers.bonus import CORPanelBonusParser
        isi = COR_ROWS + COR_FOOTER if rows is None else rows
        path = _xlsx([COR_HEADER if header is None else header] + isi)
        try:
            return CORPanelBonusParser().parse(path)
        finally:
            os.remove(path)

    # --- penjaga header ---
    def test_header_wajib_hilang_melempar(self):
        header = ["#", "Date", "Username", "Event Type", "Event Name",
                  "Nominal", "Description"]  # 'Amount' diganti nama vendor
        with self.assertRaises(ValueError) as cm:
            self._parse(rows=COR_ROWS + COR_FOOTER, header=header)
        pesan = str(cm.exception)
        self.assertIn("Amount", pesan)      # kolom yang hilang disebut
        self.assertIn("Nominal", pesan)     # header yang ADA disebut

    def test_header_kosong_melempar_tanpa_crash(self):
        with self.assertRaises(ValueError) as cm:
            self._parse(rows=[], header=[])
        self.assertIn("Date", str(cm.exception))

    # --- baris kaki ---
    def test_baris_kaki_dilewati(self):
        rows = self._parse()
        self.assertEqual(len(rows), 4)
        self.assertNotIn("", [r["username"] for r in rows])

    def test_label_kaki_asing_dilewati(self):
        rows = self._parse(rows=COR_ROWS + [
            ["", "", "", "", "Subtotal", "999"],
            ["", "", "", "", "Grand Total", "136,146.5"],
        ])
        self.assertEqual(len(rows), 4)

    # --- nominal & tanggal ---
    def test_nominal_rupiah_penuh_tanpa_x1000(self):
        """Jebakan `SCALE = Decimal(1000)` yang duduk di modul yang sama."""
        r = self._parse()[0]
        self.assertEqual(str(r["amount"]), "85770")
        self.assertEqual(str(r["bonus"]), "85770")

    def test_desimal_intl_bukan_id(self):
        r = self._parse()[3]
        self.assertEqual(str(r["amount"]), "40351.5")  # mode 'id' -> 40.3515

    def test_tanggal_dd_mmm_yyyy(self):
        r = self._parse()[0]
        self.assertEqual(str(r["posted_date"]), "2026-08-04")
        self.assertEqual(r["occurred_at"].hour, 0)
        self.assertEqual(r["occurred_at"].second, 13)

    # --- kategori ---
    def test_kategori_dari_event_name_dan_fallback_berjenjang(self):
        rows = self._parse()
        self.assertEqual(rows[0]["raw"]["Kategori"],
                         "BONUS ROLLINGAN SLOT HARIAN 0.5%")
        self.assertEqual(rows[1]["raw"]["Kategori"], "Daily Login")
        self.assertEqual(rows[2]["raw"]["Kategori"], "Manual Freebet")
        self.assertEqual(rows[3]["raw"]["Kategori"], "Bonus")

    # --- penanda ---
    def test_penanda_sumber_ditulis(self):
        from sources.parsers.bonus import MARKER_AGREGAT
        for r in self._parse():
            self.assertEqual(r["raw"]["Sumber"], MARKER_AGREGAT)
        self.assertEqual(MARKER_AGREGAT, "cor_panel_bonus")

    def test_penanda_tak_bisa_ditimpa_kolom_vendor(self):
        header = COR_HEADER + ["Sumber", "Kategori"]
        rows = self._parse(rows=[COR_ROWS[0] + ["PALSU", "PALSU"]],
                           header=header)
        self.assertEqual(rows[0]["raw"]["Sumber"], "cor_panel_bonus")
        self.assertEqual(rows[0]["raw"]["Kategori"],
                         "BONUS ROLLINGAN SLOT HARIAN 0.5%")

    # --- tanda & field kanonik ---
    def test_credit_delta_negatif_money_delta_nol(self):
        for r in self._parse():
            self.assertEqual(r["source_type"], "panel_bonus")
            self.assertEqual(r["jenis"], "bonus")
            self.assertLess(r["credit_delta"], 0)
            self.assertEqual(str(r["money_delta"]), "0")
            self.assertEqual(str(r["fee"]), "0")
            self.assertEqual(r["ticket_no"], "")
            self.assertEqual(r["amount"], r["bonus"])
            self.assertEqual(r["credit_delta"], -r["amount"])

    def test_username_verbatim(self):
        """Prefix brand TIDAK dikupas — 'w25master' pemain sah di toko W25."""
        self.assertEqual([r["username"] for r in self._parse()],
                         ["bodatt", "bulbul26", "w25master", "zeta9"])

    def test_description_verbatim(self):
        self.assertEqual(self._parse()[1]["description"],
                         "Free Bet: Daily Login (25)")

    # --- tie-out ---
    def test_tie_out_beda_melempar(self):
        with self.assertRaises(ValueError) as cm:
            self._parse(rows=COR_ROWS + [["", "", "", "", "Grand Total",
                                          "136,000"]])
        pesan = str(cm.exception)
        self.assertIn("136146.5", pesan)     # jumlah baris data
        self.assertIn("136000", pesan)       # angka yang dicetak berkas
        self.assertIn("pengembang", pesan.lower())
        self.assertIn("jangan", pesan.lower())  # jangan unggah ulang

    def test_tie_out_beda_presisi_tetap_lolos(self):
        rows = self._parse(rows=COR_ROWS + [["", "", "", "", "Grand Total",
                                             "136,146.500"]])
        self.assertEqual(len(rows), 4)

    def test_tanpa_footer_tidak_melempar(self):
        self.assertEqual(len(self._parse(rows=COR_ROWS)), 4)

    def test_page_total_menang_atas_grand_total(self):
        """Ekspor multi-halaman: Grand Total mencakup halaman yang TIDAK ada
        di berkas, jadi Σ Page Total yang dipakai."""
        rows = self._parse(rows=COR_ROWS + [
            ["", "", "", "", "Page Total", "85,795"],       # baris 1+2
            ["", "", "", "", "Page Total", "50,351.5"],     # baris 3+4
            ["", "", "", "", "Grand Total", "9,999,999"],   # halaman lain
        ])
        self.assertEqual(len(rows), 4)

    # --- baris ber-username tanpa tanggal: MELEMPAR, tidak terbit diam-diam ---
    def test_baris_ber_username_tanggal_gagal_melempar(self):
        with self.assertRaises(ValueError) as cm:
            self._parse(rows=COR_ROWS + [
                ["5", "n/a", "pemainx", "Manual Freebet", "Manual Freebet",
                 "1,000", "Free Bet: Manual Freebet (1,000)"],
            ])
        pesan = str(cm.exception)
        self.assertIn("pemainx", pesan)
        self.assertIn("n/a", pesan)

    # --- row_hash ---
    def test_row_hash_stabil(self):
        self.assertEqual([r["row_hash"] for r in self._parse()],
                         [r["row_hash"] for r in self._parse()])

    def test_row_hash_unik_dalam_satu_berkas(self):
        hashes = [r["row_hash"] for r in self._parse()]
        self.assertEqual(len(set(hashes)), len(hashes))

    def test_row_hash_stabil_lintas_tipe_sel(self):
        """Kalau vendor memperbaiki stylesheet-nya, openpyxl berhasil dan sel
        tiba BERTIPE (datetime/angka) alih-alih str. Hash di-hitung dari nilai
        hasil parse, jadi hari yang sama tetap satu hash — bukan duplikat massal
        (KNOWN DEFECT QRFlyer)."""
        from datetime import datetime
        bertipe = [
            [1, datetime(2026, 8, 4, 0, 0, 13), "bodatt", "Bonus Cashback",
             "BONUS ROLLINGAN SLOT HARIAN 0.5%", 85770,
             "Free Bet: BONUS ROLLINGAN SLOT HARIAN 0.5% (85,770)"],
            [2, datetime(2026, 8, 4, 0, 5, 32), "bulbul26", "Daily Spin Bonus",
             "Daily Login", 25, "Free Bet: Daily Login (25)"],
            [3, datetime(2026, 8, 4, 1, 0, 0), "w25master", "Manual Freebet",
             "", 10000, "Free Bet: Manual Freebet (10,000)"],
            [4, datetime(2026, 8, 4, 2, 0, 0), "zeta9", "", "", 40351.5,
             "Free Bet: (40,351.5)"],
            ["", "", "", "", "Grand Total", 136146.5],
        ]
        self.assertEqual([r["row_hash"] for r in self._parse(rows=bertipe)],
                         [r["row_hash"] for r in self._parse()])

    def test_row_hash_stabil_lintas_format_desimal(self):
        """Gaya penulisan desimal vendor tak boleh mengubah hash.

        '85,770' / '85,770.00' / 85770 adalah transaksi yang SAMA. Tanpa
        kanonikalisasi, `str(Decimal)` mempertahankan nol di belakang sehingga
        ekspor ulang bergaya lain lolos sebagai baris BARU dan harinya
        terhitung dua kali — cacat yang sudah menduplikasi 1.366 baris BSW di
        jalur QRIS Flyer, dan di sana tak bisa lagi diperbaiki.
        """
        gaya_dua_desimal = [
            [1, "04 Aug 2026 00:00:13", "bodatt", "Bonus Cashback",
             "BONUS ROLLINGAN SLOT HARIAN 0.5%", "85,770.00",
             "Free Bet: BONUS ROLLINGAN SLOT HARIAN 0.5% (85,770)"],
            [2, "04 Aug 2026 00:05:32", "bulbul26", "Daily Spin Bonus",
             "Daily Login", "25.00", "Free Bet: Daily Login (25)"],
            [3, "04 Aug 2026 01:00:00", "w25master", "Manual Freebet",
             "", "10,000.00", "Free Bet: Manual Freebet (10,000)"],
            [4, "04 Aug 2026 02:00:00", "zeta9", "", "", "40,351.50",
             "Free Bet: (40,351.5)"],
            ["", "", "", "", "Grand Total", "136,146.50"],
        ]

        self.assertEqual(
            [r["row_hash"] for r in self._parse(rows=gaya_dua_desimal)],
            [r["row_hash"] for r in self._parse()])

    def test_desimal_signifikan_tidak_dibulatkan_di_hash(self):
        """Kanonikalisasi hanya membuang nol di belakang. Dua baris yang beda
        di desimal ketiga (nyata: '128,472.575') tetap dua hash berbeda."""
        def satu(nominal):
            return self._parse(rows=[
                [1, "04 Aug 2026 00:00:13", "bodatt", "Bonus Cashback",
                 "BONUS ROLLINGAN SLOT HARIAN 0.5%", nominal, "x"],
            ])[0]["row_hash"]

        self.assertNotEqual(satu("128,472.575"), satu("128,472.57"))

    def test_nomor_urut_tidak_ikut_hash(self):
        """`#` = penghitung relatif-halaman; ekspor ulang menomori ulang."""
        digeser = [["90" + r[0]] + r[1:] for r in COR_ROWS] + COR_FOOTER
        self.assertEqual([r["row_hash"] for r in self._parse(rows=digeser)],
                         [r["row_hash"] for r in self._parse()])

    # --- registrasi ---
    def test_terdaftar_di_parsers(self):
        from sources.parsers.bonus import CORPanelBonusParser
        from sources.services import PARSERS
        self.assertIs(PARSERS.get("cor_panel_bonus"), CORPanelBonusParser)
        self.assertEqual(CORPanelBonusParser.source_key, "panel_bonus")
