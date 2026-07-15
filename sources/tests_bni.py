import os
from decimal import Decimal
from django.test import SimpleTestCase
from sources.parsers.bni_pdf import extract_bni_name, is_bni_fee, parse_bni_lines


class ExtractBNINameTests(SimpleTestCase):
    def test_transfer_ke_nama_tunggal(self):
        self.assertEqual(extract_bni_name("TRANSFER KE FAJAR"), "FAJAR")

    def test_transfer_ke_dengan_gelar(self):
        self.assertEqual(extract_bni_name("TRANSFER KE Bpk KELPIN BORNEO"), "KELPIN BORNEO")

    def test_transfer_ke_simon(self):
        self.assertEqual(extract_bni_name("TRANSFER KE Bpk SIMON ROSON"), "SIMON ROSON")

    def test_echannel_tanpa_nama_kosong(self):
        # baris echannel: hanya nomor & kode -> tanpa nama
        s = ("TRF/PAY/TOP-UP ECHANNEL KARTU 0000000000000000 BIZID "
             "20260713BNINIDJA010 O0217812687 901113275828")
        self.assertEqual(extract_bni_name(s), "")

    def test_gopay_hanya_nomor_kosong(self):
        self.assertEqual(extract_bni_name("TRANSFER KE GOPAY) NO :050525"), "")

    def test_linkaja_hanya_hp_kosong(self):
        self.assertEqual(extract_bni_name("TRANSFER KE aba8513014490053 LINKAJA 083177257639"), "")

    def test_dana_nama_tersamar_dipertahankan(self):
        # nama e-wallet tersamar (huruf, tanpa angka) boleh lolos apa adanya
        s = "TRANSFER KE ESPAY DEBIT INDONESIA KOE 8810085849792965 Dana-DNID FICXX"
        self.assertEqual(extract_bni_name(s), "FICXX")

    def test_kosong_tetap_kosong(self):
        self.assertEqual(extract_bni_name(""), "")


# Baris nyata (disederhanakan) dari 13_07_2026_WD_BNI_MARULLOH.pdf.
SAMPLE_LINES = [
    "HISTORI TRANSAKSI",                 # header -> diabaikan (sebelum transaksi)
    "Rekening: TAPLUS DIGITAL",
    "Tanggal Uraian Transaksi Tipe Nominal Saldo Akhir",
    "2026-07-13 TRANSFER KE Bpk KELPIN BORNEO Db. 800.000,00 2.065.363,00",
    "2026-07-13 BY TRX BIFAST lDb. 2.500,00 3.622.863,00",   # fee + huruf nyasar 'l'
    "g",                                                     # watermark 1-karakter
    "2026-07-13 TRF/PAY/TOP-UP Db. 900.000,00 3.882.363,00",  # echannel (main line)
    "ECHANNEL KARTU",                                        # lanjutan
    "0000000000000000 BIZID",                                # lanjutan
    "20260713BNINIDJA010",                                   # lanjutan
    "O0217812687 901113275828",                              # lanjutan: no rek tujuan
    "2026-07-13 TRF/PAY/TOP-UP ECHANNEL KARTU 0000000000000000 BIZID 20260713 Cr. 2.000.000,00 4.431.363,00",
    "Printed on 13/7/2026 6:27:15 Waktu",                    # footer -> diabaikan
    "Page 1 of 3",
]


class ParseBNILinesTests(SimpleTestCase):
    def setUp(self):
        self.rows = parse_bni_lines(SAMPLE_LINES)

    def test_jumlah_baris_transaksi(self):
        # 4 transaksi (KELPIN, fee, echannel 900k, Cr topup); watermark & footer diabaikan
        self.assertEqual(len(self.rows), 4)

    def test_arah_db_negatif_cr_positif(self):
        by_amt = {r["amount"]: r for r in self.rows}
        self.assertEqual(by_amt[Decimal("800000")]["money_delta"], Decimal("-800000"))
        self.assertEqual(by_amt[Decimal("2000000")]["money_delta"], Decimal("2000000"))

    def test_jenis_wd_depo_admin(self):
        by_amt = {r["amount"]: r["jenis"] for r in self.rows}
        self.assertEqual(by_amt[Decimal("800000")], "wd")
        self.assertEqual(by_amt[Decimal("2500")], "admin")     # BY TRX BIFAST
        self.assertEqual(by_amt[Decimal("2000000")], "depo")   # Cr topup

    def test_fee_terdeteksi(self):
        self.assertTrue(is_bni_fee("BY TRX BIFAST"))
        self.assertTrue(is_bni_fee("TRANSFER KE BIAYA ADMIN (GOPAY) NO :000724750525"))
        self.assertFalse(is_bni_fee("TRANSFER KE Bpk KELPIN BORNEO"))

    def test_saldo_dan_nominal_format_id(self):
        r = next(r for r in self.rows if r["amount"] == Decimal("800000"))
        self.assertEqual(r["balance_after"], Decimal("2065363"))
        self.assertEqual(r["credit_delta"], Decimal("0"))
        self.assertEqual(r["source_type"], "bank")

    def test_nomor_rekening_tujuan_terpelihara_di_raw(self):
        # anchor identitas: 901113275828 harus ada di raw echannel 900k
        r = next(r for r in self.rows if r["amount"] == Decimal("900000"))
        joined = " ".join(str(v) for v in r["raw"].values())
        self.assertIn("901113275828", joined)

    def test_counterparty_nama_transfer_bank(self):
        r = next(r for r in self.rows if r["amount"] == Decimal("800000"))
        self.assertEqual(r["counterparty"], "KELPIN BORNEO")

    def test_counterparty_echannel_kosong(self):
        r = next(r for r in self.rows if r["amount"] == Decimal("900000"))
        self.assertEqual(r["counterparty"], "")

    def test_tanggal_tanpa_jam(self):
        r = self.rows[0]
        self.assertEqual(r["occurred_at"].year, 2026)
        self.assertEqual(r["occurred_at"].hour, 0)

    def test_row_hash_stabil_dan_unik(self):
        hashes = [r["row_hash"] for r in self.rows]
        self.assertEqual(len(hashes), len(set(hashes)))
        # deterministik: parse ulang -> hash sama
        again = [r["row_hash"] for r in parse_bni_lines(SAMPLE_LINES)]
        self.assertEqual(hashes, again)


class BNIPDFParserSampleTests(SimpleTestCase):
    SAMPLE = "samples/bni/13_07_2026_WD_BNI_MARULLOH.pdf"

    def test_parse_file_nyata(self):
        if not os.path.exists(self.SAMPLE):
            self.skipTest("file kanonik BNI WD PDF tidak tersedia")
        from sources.parsers.bni_pdf import BNIPDFParser
        rows = BNIPDFParser().parse(self.SAMPLE)
        # semua baris bersumber bank & punya money_delta != 0
        self.assertTrue(rows)
        self.assertTrue(all(r["source_type"] == "bank" for r in rows))
        # nomor rekening tujuan wahyudi (SEABANK) harus muncul di salah satu raw
        joined_all = " ".join(
            str(v) for r in rows for v in r["raw"].values()
        )
        self.assertIn("901113275828", joined_all)


class ParsersRegistryTests(SimpleTestCase):
    def test_bni_pdf_terdaftar(self):
        from sources.services import PARSERS
        from sources.parsers.bni_pdf import BNIPDFParser
        self.assertIs(PARSERS["bni_pdf"], BNIPDFParser)
