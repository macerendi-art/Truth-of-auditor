"""Dekripsi xlsx terenkripsi yang GAGAL (password salah / file rusak) tidak boleh
meninggalkan file temp, dan error-nya harus berpesan jelas bahasa Indonesia."""
import os
import tempfile

from django.test import SimpleTestCase

from sources.services import _decrypt_to_temp

# Header OLE2 valid + isi sampah → msoffcrypto gagal parse/verifikasi.
_FAKE_OLE2 = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1" + b"\x00" * 4096


class DecryptTempCleanupTests(SimpleTestCase):
    def _make_fake(self, d):
        src = os.path.join(d, "fake.xlsx")
        with open(src, "wb") as f:
            f.write(_FAKE_OLE2)
        return src

    def test_gagal_dekripsi_tidak_meninggalkan_temp(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._make_fake(d)
            old = tempfile.tempdir
            tempfile.tempdir = d  # arahkan NamedTemporaryFile ke dir terpantau
            try:
                with self.assertRaises(ValueError):
                    _decrypt_to_temp(src, "password-salah")
            finally:
                tempfile.tempdir = old
            leftovers = sorted(n for n in os.listdir(d) if n != "fake.xlsx")
            self.assertEqual(leftovers, [])

    def test_file_hilang_bukan_error_password(self):
        # File staged hilang/tak terbaca = OSError apa adanya — bukan pesan
        # "password salah" yang menyesatkan; temp tetap dibersihkan.
        with tempfile.TemporaryDirectory() as d:
            old = tempfile.tempdir
            tempfile.tempdir = d
            try:
                with self.assertRaises(OSError):
                    _decrypt_to_temp(os.path.join(d, "tidak-ada.xlsx"), "pw")
            finally:
                tempfile.tempdir = old
            self.assertEqual(os.listdir(d), [])

    def test_pesan_error_bahasa_indonesia(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._make_fake(d)
            with self.assertRaises(ValueError) as cm:
                _decrypt_to_temp(src, "password-salah")
            self.assertIn("assword", str(cm.exception))  # "Password salah ..."
