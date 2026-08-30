"""WD QRIS ELITE — bentuk BERBEDA dari DP, bukan varian.

Kalibrasi nyata K25 29-08-2026: 4 baris, TICKET_ID `W…` cocok 4/4 dengan
Ticket Number panel WD. STATUS di sampel: `success` dan `failed verification`.
"""
import csv
import tempfile
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase

from sources.detect import detect_source
from sources.services import PARSERS

HEADER = [
    "ID", "DATE_TRANSACTION", "DATE_TRANSACTION_PANEL", "TICKET_ID",
    "MEMBER_NAME", "ACCOUNT_NO", "ACCOUNT_NAME", "BANK_TYPE", "STATUS",
    "NOMINAL", "VENDOR_ID", "INFO", "BALANCE_REVERT",
]


def tulis(rows, header=HEADER, judul="WITHDRAWAL TRANSACTION"):
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="",
                                    encoding="utf-8-sig")
    w = csv.writer(f)
    w.writerow([judul] + [""] * (len(header) - 1))
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    f.close()
    return f.name


def baris(ticket="W2334126", status="success", nominal="8000000",
          panel_dt="2026-08-29T07:36:50.657", revert="0", ident="4786867"):
    return [ident, "2026-08-29", panel_dt, ticket, "pemainuji",
            "0422010368*****", "NAMA UJI", "BRI", status, nominal,
            "03-2026", "", revert]


class ParserWDTests(SimpleTestCase):
    def _parse(self, rows, **kw):
        return PARSERS["qris_elite_wd"]().parse(tulis(rows, **kw))

    def test_baris_sukses_jadi_uang_keluar(self):
        (r,) = self._parse([baris()])
        self.assertEqual(r["jenis"], "wd")
        self.assertEqual(r["ticket_no"], "W2334126")
        self.assertEqual(r["amount"], Decimal("8000000"))
        self.assertEqual(r["money_delta"], Decimal("-8000000"))
        self.assertEqual(r["credit_delta"], Decimal("0"))
        self.assertEqual(r["counterparty"], "NAMA UJI")
        self.assertEqual(r["username"], "pemainuji")

    def test_waktu_dari_kolom_panel_bukan_tanggal_saja(self):
        (r,) = self._parse([baris()])
        # DATE_TRANSACTION cuma '2026-08-29'; yang dipakai stempel ber-jam
        self.assertEqual(r["occurred_at"].hour, 7)
        self.assertEqual(r["occurred_at"].minute, 36)

    def test_failed_verification_tidak_jadi_uang(self):
        rows = self._parse([baris(), baris(ticket="W2", status="failed verification")])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticket_no"], "W2334126")

    def test_semua_ditolak_melempar_dan_menyebut_status(self):
        with self.assertRaises(ValueError) as cm:
            self._parse([baris(status="failed verification")])
        pesan = str(cm.exception)
        self.assertIn("FAILED VERIFICATION", pesan)
        self.assertIn("ditolak", pesan)

    def test_status_asing_melempar_dan_minta_dilaporkan(self):
        with self.assertRaises(ValueError) as cm:
            self._parse([baris(status="entah apa")])
        self.assertIn("Laporkan", str(cm.exception))

    def test_kolom_wajib_hilang_melempar(self):
        h = [x for x in HEADER if x != "TICKET_ID"]
        with self.assertRaises(ValueError) as cm:
            self._parse([[c for c, n in zip(baris(), HEADER) if n != "TICKET_ID"]],
                        header=h)
        self.assertIn("TICKET_ID", str(cm.exception))

    def test_balance_revert_tersimpan_utuh_di_raw(self):
        # Maknanya saat tidak-nol BELUM terbukti — tidak dipakai menyaring.
        (r,) = self._parse([baris(revert="500")])
        self.assertEqual(r["raw"]["BALANCE_REVERT"], "500")
        self.assertEqual(r["money_delta"], Decimal("-8000000"))

    def test_row_hash_stabil_dan_unik(self):
        rows = self._parse([baris(), baris(ticket="W9", ident="9", nominal="5000")])
        self.assertEqual(len({r["row_hash"] for r in rows}), 2)
        (ulang,) = self._parse([baris()])
        self.assertEqual(ulang["row_hash"], rows[0]["row_hash"])

    def test_nominal_desimal_beda_gaya_hash_sama(self):
        (a,) = self._parse([baris(nominal="8000000")])
        (b,) = self._parse([baris(nominal="8000000.00")])
        self.assertEqual(a["row_hash"], b["row_hash"])


class DeteksiWDTests(SimpleTestCase):
    def test_terdeteksi(self):
        p = tulis([baris()])
        hasil = detect_source(p, "29-08-2026 K25 WD QRIS ELITE.csv")
        self.assertEqual(hasil[0]["parser_key"], "qris_elite_wd")
        self.assertGreaterEqual(hasil[0]["confidence"], 0.95)

    def test_tidak_menabrak_elite_dp(self):
        # header DP tidak boleh memicu aturan WD
        dp_header = ["ID", "RECORD DATE", "RECORD VALUE", "RECORD FEE",
                     "MERCHANT", "MEMBER", "APPROVE", "PAYMENT", "SETTLEMENT",
                     "PARTNER ID", "VENDOR ID", "STATUS", "TICKET", "PG"]
        p = tulis([["1", "2026-08-29T00:00:54+07:00+007", "50000", "425", "M",
                    "u", "2026-08-29 07:03:27", "", "", "", "9", "SUCCESS",
                    "D1", ""]], header=dp_header, judul="MUTASI QRIS TRANSACTION")
        keys = [h["parser_key"] for h in detect_source(p, "DP QRIS ELITE.csv")]
        self.assertIn("qris_elite", keys)
        self.assertNotIn("qris_elite_wd", keys)
