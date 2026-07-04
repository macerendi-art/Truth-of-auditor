"""Test Task 4: isolasi nama dari teks struktural bank SEBELUM normalisasi fuzzy.

Urutan wajib: (1) isolasi nama per-sumber (buang prefiks bank, kode transaksi,
nomor rekening, nominal menempel), (2) baru normalisasi via clean_name di engine.
"""
import csv
import tempfile

from django.test import SimpleTestCase

from sources.parsers.banks import BRIParser, extract_bca_name, extract_mandiri_name
from sources.parsers.bca_pdf import _clean_name


class ExtractMandiriNameTests(SimpleTestCase):
    """Isolasi nama dari Keterangan Mandiri e-statement."""

    def test_transfer_dari_bank_mandiri(self):
        # Kasus wajib #1
        self.assertEqual(
            extract_mandiri_name("Transfer dari BANK MANDIRI DAUS DJUMENA SOBANDI 1150011530112"),
            "DAUS DJUMENA SOBANDI",
        )

    def test_transfer_ke_bank_mandiri(self):
        self.assertEqual(
            extract_mandiri_name("Transfer ke BANK MANDIRI MARIO KAROKARO 1550014852167"),
            "MARIO KAROKARO",
        )

    def test_transfer_dari_bank_lain(self):
        self.assertEqual(
            extract_mandiri_name("Transfer dari Bank lain SEABANK INDONESIA AYUB EKA WIJAYADI 901111839605"),
            "AYUB EKA WIJAYADI",
        )

    def test_transfer_bi_fast_dari(self):
        self.assertEqual(
            extract_mandiri_name("Transfer BI Fast Dari BCA HENDI 7126201591 -"),
            "HENDI",
        )

    def test_transfer_bi_fast_ke_bank_bni(self):
        self.assertEqual(
            extract_mandiri_name("Transfer BI Fast Ke BANK BNI FAHRIAH 2037645783"),
            "FAHRIAH",
        )

    def test_bank_lain_nama_menempel_prefiks_dana(self):
        self.assertEqual(
            extract_mandiri_name("Transfer dari Bank lain  DANA-ERWIN SYARIEF H 1500011085839109464"),
            "ERWIN SYARIEF H",
        )

    def test_bi_fast_dana_dengan_referensi_panjang(self):
        self.assertEqual(
            extract_mandiri_name(
                "Transfer BI Fast Dari  EKO PUJISRIYANTO 6282330356369 DANA20260624DANAIDJ1010O9960662288EKOPUJ"
            ),
            "EKO PUJISRIYANTO",
        )

    def test_antar_mandiri_gopay_ambil_nama_korporat(self):
        self.assertEqual(
            extract_mandiri_name(
                "Transfer antar Mandiri DARI DOMPET ANAK BANGSA GoPay Bank Transfer "
                "ID2617839690368CY3 Transfer Fee 9037149070610314"
            ),
            "DOMPET ANAK BANGSA",
        )

    def test_baris_biaya_tanpa_nama_kosong(self):
        self.assertEqual(extract_mandiri_name("Biaya administrasi kartu debit"), "")
        self.assertEqual(extract_mandiri_name("Biaya transfer BI Fast"), "")

    def test_pembayaran_gopay_hanya_nomor_hp_kosong(self):
        self.assertEqual(extract_mandiri_name("Pembayaran GoPay Customer 085822815507"), "")

    def test_kosong_tetap_kosong(self):
        self.assertEqual(extract_mandiri_name(""), "")
        self.assertEqual(extract_mandiri_name(None), "")


class ExtractBCANameTests(SimpleTestCase):
    """Isolasi nama dari keterangan BCA (CSV & PDF memakai helper yang sama)."""

    def test_nominal_menempel_ke_nama(self):
        # Kasus wajib #2 (teks gabungan baris PDF: middle + lanjutan)
        self.assertEqual(
            extract_bca_name("2706/FTSCY/WS95271 100000.00M. YULIANSAR SIREG TRSF E-BANKING CR"),
            "M. YULIANSAR SIREG",
        )

    def test_clean_name_pdf_membungkus_helper(self):
        self.assertEqual(
            _clean_name("2706/FTSCY/WS95271 100000.00M. YULIANSAR SIREG", ["TRSF E-BANKING CR"]),
            "M. YULIANSAR SIREG",
        )

    def test_trfdn_espay_menempel(self):
        self.assertEqual(
            extract_bca_name("2706/FTSCY/WS95051 60000.002026062707446276 TRFDN-DWI NUR HABIESPAY DEBIT INDONE"),
            "DWI NUR HABI",
        )

    def test_trfdn_espay_spasi(self):
        self.assertEqual(
            extract_bca_name("TRFDN-WARSIM ESPAY DEBIT INDONE"),
            "WARSIM",
        )

    def test_bi_fast_transfer_ke_mybca(self):
        self.assertEqual(
            extract_bca_name("TRANSFER KE 535 ROZALI MyBCA BI-FAST DB"),
            "ROZALI",
        )

    def test_bi_fast_mybca_menempel(self):
        self.assertEqual(
            extract_bca_name("TRANSFER KE 535 MUHAMMAD SAILILLAHMyBCA BI-FAST DB"),
            "MUHAMMAD SAILILLAH",
        )

    def test_bi_fast_transfer_dr(self):
        self.assertEqual(
            extract_bca_name("TRANSFER DR 013 DARMAWAN BI-FAST CR"),
            "DARMAWAN",
        )

    def test_csv_bi_fast_dengan_tanggal(self):
        self.assertEqual(
            extract_bca_name("BI-FAST CR TANGGAL :26/06    TRANSFER   DR 008 MARIO KAROKARO"),
            "MARIO KAROKARO",
        )

    def test_csv_bi_fast_ke_kbi(self):
        self.assertEqual(
            extract_bca_name("BI-FAST DB TRANSFER   KE 009 FAHRIAH           KBI"),
            "FAHRIAH",
        )

    def test_csv_nominal_menempel(self):
        self.assertEqual(
            extract_bca_name("TRSF E-BANKING CR 2606/FTSCY/WS95031        3000000.00MARIO KARO-KARO"),
            "MARIO KARO-KARO",
        )

    def test_csv_ewallet_hanya_nomor_hp_kosong(self):
        # Baris DANA/GOPAY: tanpa nama orang -> counterparty kosong, jangan dikarang.
        self.assertEqual(
            extract_bca_name(
                "TRSF E-BANKING DB 2606/FTFVA/WS9501139010/DANA        -                 -                 82279003062"
            ),
            "",
        )
        self.assertEqual(
            extract_bca_name(
                "TRSF E-BANKING DB 2606/FTFVA/WS9501170001/GOPAY TOPUP -                 -                 085767555197"
            ),
            "",
        )

    def test_referensi_numerik_bukan_nama(self):
        self.assertEqual(extract_bca_name("2706/FTSCY/WS95051 60000.002026062707446276"), "")

    def test_switching_brilink(self):
        self.assertEqual(
            extract_bca_name("TRF 531629653305 SURYANI SUKRI, S.K002 Web BRILink SWITCHING CR"),
            "SURYANI SUKRI",
        )

    def test_kosong_tetap_kosong(self):
        self.assertEqual(extract_bca_name(""), "")
        self.assertEqual(extract_bca_name(None), "")


class BRIParserNameTests(SimpleTestCase):
    """BRI: logika NBMB dipertahankan (DP=pengirim, WD=penerima); non-NBMB kosong."""

    HEADER = [
        "ID", "NOREK", "TGL_TRAN", "TGL_EFEKTIF", "JAM_TRAN", "SEQ", "DESK_TRAN",
        "SALDO_AWAL_MUTASI", "MUTASI_DEBET", "MUTASI_KREDIT", "SALDO_AKHIR_MUTASI",
        "GLSIGN", "TRUSER", "KODE_TRAN", "KODE_TRAN_TELLER", "TRREMK", "TLBDS1", "TLBDS2",
        "REMARK_CUSTOM",
    ]

    def _parse_one(self, desc, debet=".00", kredit="100000.00"):
        row = ["1", "181201005938507", "2026-06-27 10:00:00", "2026-06-27 10:00:00", "1000",
               "4110000", desc, "0.00", debet, kredit, "100000.00", "Cr", "x", "2", "8506",
               "", "", "", ""]
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
            w = csv.writer(f)
            w.writerow(self.HEADER)
            w.writerow(row)
            path = f.name
        rows = BRIParser().parse(path)
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_nbmb_dp_ambil_pengirim(self):
        # Kasus wajib #3: uang masuk (DP) -> nama pengirim
        r = self._parse_one("NBMB IRAMAYA YUATI TO MARGANI ESB:NBMB:0001500F:151783035958")
        self.assertEqual(r["counterparty"], "IRAMAYA YUATI")

    def test_nbmb_wd_ambil_penerima(self):
        r = self._parse_one(
            "NBMB PANCA SENTANA TO ZAENUL BASYAR ESB:NBMB:0001500F:151731713566",
            debet="100000.00", kredit=".00",
        )
        self.assertEqual(r["counterparty"], "ZAENUL BASYAR")

    def test_atmstrprm_tanpa_nama_kosong(self):
        r = self._parse_one("ATMSTRPRM 08888 000528944 6044603718 ESB:NBMB:0005T00F:151728528944")
        self.assertEqual(r["counterparty"], "")
