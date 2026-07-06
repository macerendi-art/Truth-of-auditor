"""Ekstraksi kode bank (player_bank / bank_title) dari raw per sumber + wiring parser."""
import os
import tempfile

from django.test import SimpleTestCase
from openpyxl import Workbook

from sources.parsers.base import bank_code, derive_bank_fields
from sources.parsers.bracket import BracketParser
from sources.parsers.panel import PanelParser


class BankCodeTests(SimpleTestCase):
    def test_pipe_ambil_segmen_pertama_uppercase(self):
        self.assertEqual(bank_code("dana|Mhd Ilyas |0822", "|"), "DANA")

    def test_spasi_ambil_token_pertama(self):
        self.assertEqual(bank_code("BCA 7126201591", " "), "BCA")

    def test_kode_berstrip_utuh(self):
        self.assertEqual(bank_code("LAIN-LAIN 000", " "), "LAIN-LAIN")

    def test_kosong_dan_none(self):
        self.assertEqual(bank_code("", "|"), "")
        self.assertEqual(bank_code(None, "|"), "")


class DeriveBankFieldsTests(SimpleTestCase):
    def test_panel_player_bank_dan_bank_title(self):
        pb, bt = derive_bank_fields("panel", {
            "Player Bank": "DANA|Mhd Ilyas |0822", "Bank Title": "QRIS|QRISFLYER|156",
        })
        self.assertEqual((pb, bt), ("DANA", "QRIS"))

    def test_bracket_norek_member_dan_bank(self):
        pb, bt = derive_bank_fields("bracket", {
            "No. Rek Bank Member": "BCA 7126201591", "Bank": "BANK BCA | DEPOSIT / WITHDRAW",
        })
        self.assertEqual((pb, bt), ("BCA", "BANK BCA"))

    def test_sumber_lain_kosong(self):
        self.assertEqual(derive_bank_fields("bank", {"x": "y"}), ("", ""))

    def test_key_hilang_aman(self):
        self.assertEqual(derive_bank_fields("panel", {}), ("", ""))


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    wb.save(path)
    return path


class ParserWiringTests(SimpleTestCase):
    """Parser panel/bracket mengisi player_bank + bank_title di baris keluaran."""

    def test_panel_isi_player_bank_dan_bank_title(self):
        path = _xlsx([
            ["HISTORI DP/WD PANEL"],  # baris 1 = judul
            ["Ticket Number", "Deposit Amount", "Requested Date", "User Name",
             "Full Name", "Player Bank", "Bank Title"],  # baris 2 = header
            ["D0012345", "50", "2026-06-27 10:00:00", "budi", "BUDI",
             "DANA|Budi P|08", "QRIS|QRISFLYER|1"],
        ])
        try:
            rows = PanelParser().parse(path)
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["player_bank"], "DANA")
        self.assertEqual(rows[0]["bank_title"], "QRIS")

    def test_bracket_isi_player_bank_dari_norek_member(self):
        path = _xlsx([
            ["Tanggal", "Kategori", "Total", "Credit Awal", "Credit Akhir",
             "Description", "Transaction Date", "No. Rek Bank Member", "Bank",
             "Username", "Member"],  # baris 1 = header
            ["2026-06-27", "Deposit", "100000", "0", "100000", "dep",
             "2026-06-27 10:00:00", "BCA 712620", "BANK BCA | DEPOSIT", "user1", "MEMBER"],
        ])
        try:
            rows = BracketParser().parse(path)
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["player_bank"], "BCA")
        self.assertEqual(rows[0]["bank_title"], "BANK BCA")
