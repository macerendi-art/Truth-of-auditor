from django.test import SimpleTestCase
from sources.parsers.bni_pdf import extract_bni_name


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
