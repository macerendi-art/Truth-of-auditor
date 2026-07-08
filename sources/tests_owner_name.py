"""Nama pemilik rekening (owner_name): ekstraksi header file + fallback nama file.

Permintaan UAT: baris "Tidak Ada di Panel" harus menampilkan rekening bank
milik end user ("BCA a/n HENDI"), bukan hanya brand banknya.
"""
import os
import tempfile

from django.test import SimpleTestCase, TestCase
from openpyxl import Workbook

from sources.models import SourceType, Toko
from sources.parsers.banks import BCACSVParser, BRIParser, MandiriParser
from sources.parsers.bca_pdf import BCAPDFParser, extract_pdf_owner
from sources.services import ingest
from transactions.models import Transaction, owner_from_filename


def _csv(path_suffix, text):
    fd, path = tempfile.mkstemp(suffix=path_suffix)
    with os.fdopen(fd, "w", newline="") as f:
        f.write(text)
    return path


BCA_CSV_WITH_PREAMBLE = (
    "No. Rekening,=,'0202405914\n"
    "Nama,=,NIJUN\n"
    "Mata Uang,=,IDR\n"
    "\n"
    "Tanggal,Keterangan,Cabang,Jumlah,,Saldo\n"
    "'27/06/2026,TRSF E-BANKING CR 2606/FTSCY/WS95031 100000.00BUDI SANTOSO,'0000,100000.00,CR,4964637.00\n"
)

BCA_CSV_NO_PREAMBLE = (
    "Tanggal,Keterangan,Cabang,Jumlah,,Saldo\n"
    "'27/06/2026,TRSF E-BANKING CR 2606/FTSCY/WS95031 100000.00BUDI SANTOSO,'0000,100000.00,CR,4964637.00\n"
)

BRI_CSV = (
    '"ID","NOREK","TGL_TRAN","TGL_EFEKTIF","JAM_TRAN","SEQ","DESK_TRAN",'
    '"SALDO_AWAL_MUTASI","MUTASI_DEBET","MUTASI_KREDIT","SALDO_AKHIR_MUTASI","GLSIGN"\n'
    '"1","384801026030509","2026-06-27 00:04:26","2026-06-27 00:04:26","426","4074000",'
    '"NBMB MARIO KARO TO PANCA SENTANA ESB:NBMB:0001500F:151727003767",'
    '"4116652.00",".00","20000000.00","24116652.00","Cr"\n'
)


def _mandiri_xlsx(with_header=True):
    wb = Workbook()
    ws = wb.active
    if with_header:
        ws.append(["e-Statement"])
        ws.append(["Nama/Name", ":", "SITI NURUL WIRDAH", "Periode/Period", ":", "01 Jun 2026"])
        ws.append(["Nomor Rekening/Account Number", ":", "1550015493524"])
    ws.append(["No", "Tanggal", "Keterangan", "Dana Masuk (IDR)", "Dana Keluar (IDR)", "Saldo (IDR)"])
    ws.append([1, "27 Jun 2026", "Transfer ke BANK MANDIRI BUDI", "", "100.000,00", "2.004.500,00"])
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    wb.save(path)
    return path


class OwnerFromFilenameTests(SimpleTestCase):
    """Fallback: token nama pemilik setelah token brand di nama file upload."""

    def test_bri_dengan_nama_pemilik(self):
        self.assertEqual(
            owner_from_filename("27_JUNI_2026_WD_BRI_PANCA_SENTANA.csv"), "PANCA SENTANA"
        )

    def test_bca_pdf_nama_tunggal(self):
        self.assertEqual(owner_from_filename("27_JUNI_2026_WD_BCA_HENDI.pdf"), "HENDI")

    def test_gateway_tanpa_nama_pemilik(self):
        # OKE25 = kode toko (mengandung digit), bukan nama orang.
        self.assertEqual(owner_from_filename("MUTASI DP QR FLYER OKE25 27-06.xlsx"), "")

    def test_tanpa_token_brand(self):
        self.assertEqual(owner_from_filename("HISTORI DP PANEL OKE25 27-06.xlsx"), "")

    def test_kosong(self):
        self.assertEqual(owner_from_filename(""), "")


class ParserMetaTests(SimpleTestCase):
    """parser.meta['owner_name'] terisi dari header file (bila ada)."""

    def test_bca_csv_preamble_nama(self):
        path = _csv(".csv", BCA_CSV_WITH_PREAMBLE)
        try:
            p = BCACSVParser()
            rows = p.parse(path)
        finally:
            os.remove(path)
        self.assertEqual(p.meta.get("owner_name"), "NIJUN")
        self.assertEqual(len(rows), 1)  # parse tetap jalan normal

    def test_bca_csv_tanpa_preamble_meta_kosong(self):
        path = _csv(".csv", BCA_CSV_NO_PREAMBLE)
        try:
            p = BCACSVParser()
            rows = p.parse(path)
        finally:
            os.remove(path)
        self.assertEqual(p.meta.get("owner_name", ""), "")
        self.assertEqual(len(rows), 1)

    def test_bri_meta_kosong(self):
        path = _csv(".csv", BRI_CSV)
        try:
            p = BRIParser()
            rows = p.parse(path)
        finally:
            os.remove(path)
        self.assertEqual(p.meta.get("owner_name", ""), "")
        self.assertEqual(len(rows), 1)

    def test_mandiri_header_nama(self):
        path = _mandiri_xlsx(with_header=True)
        try:
            p = MandiriParser()
            rows = p.parse(path)
        finally:
            os.remove(path)
        self.assertEqual(p.meta.get("owner_name"), "SITI NURUL WIRDAH")
        self.assertEqual(len(rows), 1)

    def test_mandiri_tanpa_header_meta_kosong(self):
        path = _mandiri_xlsx(with_header=False)
        try:
            p = MandiriParser()
            rows = p.parse(path)
        finally:
            os.remove(path)
        self.assertEqual(p.meta.get("owner_name", ""), "")
        self.assertEqual(len(rows), 1)

    def test_pdf_owner_dari_lines(self):
        # Ekstraksi PDF diuji lewat helper murni (tanpa membangun file PDF).
        lines = ["MUTASI REKENING", "NO. REKENING : 712-6201-591", "NAMA : HENDI", "HALAMAN : 1/35"]
        self.assertEqual(extract_pdf_owner(lines), "HENDI")
        self.assertEqual(extract_pdf_owner(["MUTASI REKENING", "PERIODE : X"]), "")

    def test_pdf_sample_nyata(self):
        path = "samples/SAMPLING TO RND (TOKO= OKE25)/27-06/WD/27_JUNI_2026_WD_BCA_HENDI.pdf"
        if not os.path.exists(path):
            self.skipTest("file kanonik BCA WD PDF tidak tersedia")
        p = BCAPDFParser()
        p.parse(path)
        self.assertEqual(p.meta.get("owner_name"), "HENDI")


class IngestOwnerNameTests(TestCase):
    """ingest() menyimpan owner_name ke Upload (header dulu, fallback nama file)."""

    def setUp(self):
        self.toko = Toko.objects.filter(is_active=True).first()

    def test_bca_csv_owner_dari_header(self):
        path = _csv(".csv", BCA_CSV_WITH_PREAMBLE)
        try:
            up, created, dup = ingest("bca_csv", path, toko=self.toko)
        finally:
            os.remove(path)
        self.assertEqual(up.owner_name, "NIJUN")
        self.assertEqual(created, 1)

    def test_bri_fallback_nama_file(self):
        # Simpan dengan nama file bermakna agar fallback terpakai.
        d = tempfile.mkdtemp()
        path = os.path.join(d, "27_JUNI_2026_WD_BRI_PANCA_SENTANA.csv")
        with open(path, "w", newline="") as f:
            f.write(BRI_CSV)
        try:
            up, created, dup = ingest("bri", path, toko=self.toko)
        finally:
            os.remove(path)
        self.assertEqual(up.owner_name, "PANCA SENTANA")
        self.assertEqual(created, 1)

    def test_reingest_tetap_dedup(self):
        """KRITIS: penambahan meta TIDAK boleh mengubah row_hash — re-import 100% dedup."""
        path = _csv(".csv", BCA_CSV_WITH_PREAMBLE)
        try:
            _, created1, dup1 = ingest("bca_csv", path, toko=self.toko)
            _, created2, dup2 = ingest("bca_csv", path, toko=self.toko)
        finally:
            os.remove(path)
        self.assertEqual((created1, dup1), (1, 0))
        self.assertEqual((created2, dup2), (0, 1))


class SourceLabelFullTests(TestCase):
    """Transaction.source_label_full = 'BCA a/n NIJUN' utk sumber uang ber-owner."""

    def setUp(self):
        self.toko = Toko.objects.filter(is_active=True).first()

    def _tx_from_ingest(self, text, fname="27_JUNI_2026_WD_BCA_NIJUN.CSV"):
        d = tempfile.mkdtemp()
        path = os.path.join(d, fname)
        with open(path, "w", newline="") as f:
            f.write(text)
        try:
            up, _, _ = ingest("bca_csv", path, toko=self.toko)
        finally:
            os.remove(path)
        return Transaction.objects.filter(upload=up).first()

    def test_dengan_owner(self):
        tx = self._tx_from_ingest(BCA_CSV_WITH_PREAMBLE)
        self.assertEqual(tx.source_label_full, "BCA a/n NIJUN")

    def test_fallback_nama_file_saat_header_absen(self):
        tx = self._tx_from_ingest(BCA_CSV_NO_PREAMBLE)
        self.assertEqual(tx.source_label_full, "BCA a/n NIJUN")  # dari nama file

    def test_tanpa_owner_sama_dengan_source_label(self):
        tx = self._tx_from_ingest(BCA_CSV_NO_PREAMBLE, fname="data.csv")
        self.assertEqual(tx.upload.owner_name, "")
        self.assertEqual(tx.source_label_full, tx.source_label)
