"""Alat pangkas berkas unggahan — sengaja TIDAK BERSENJATA.

Retensi yang berlaku (keputusan pemilik 2026-09-05) adalah **simpan selamanya**.
Tes di sini mengunci dua hal yang membuat alat ini aman disimpan di repo: ia
menolak jalan tanpa `--hari` eksplisit, dan tanpa `--terapkan` ia tidak menyentuh
apa pun. Plus yang paling penting: memangkas berkas TIDAK boleh menyentuh baris
Upload, transaksinya, tautan dedup, maupun penanda ketiban.
"""
import shutil
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

ISI = b"isi berkas ekspor\n"


class PangkasBerkasTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="toa-media-")
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.enterContext(override_settings(MEDIA_ROOT=self.media))
        self.toko = Toko.objects.get(key="lbs")
        self.st = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]

    def _upload(self, umur_hari, nama="MUTASI.csv", toko=None):
        up = Upload.objects.create(
            source_type=self.st, toko=toko or self.toko, original_name=nama)
        up.file.save(nama, ContentFile(ISI), save=True)
        Upload.objects.filter(pk=up.pk).update(
            created_at=timezone.now() - timedelta(days=umur_hari))
        up.refresh_from_db()
        return up

    def _jalan(self, *args):
        out = StringIO()
        call_command("pangkas_berkas_unggahan", *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_tanpa_hari_menolak_jalan(self):
        with self.assertRaises(CommandError) as cm:
            self._jalan()
        self.assertIn("--hari", str(cm.exception))

    def test_hari_nol_ditolak(self):
        with self.assertRaises(CommandError):
            self._jalan("--hari", "0")

    def test_dry_run_tidak_menghapus_apa_pun(self):
        up = self._upload(400)

        keluaran = self._jalan("--hari", "365")

        self.assertIn("dry-run", keluaran)
        up.refresh_from_db()
        self.assertTrue(up.file)
        self.assertTrue(Path(self.media, up.file.name).exists())

    def test_terapkan_menghapus_berkas_tapi_bukan_barisnya(self):
        up = self._upload(400)
        Transaction.objects.create(
            upload=up, source_type=self.st, toko=self.toko,
            occurred_at=datetime(2025, 7, 1, 9, 0), posted_date=None, jenis="depo",
            amount=Decimal("1000"), credit_delta=Decimal("-1000"),
            money_delta=Decimal("1000"), row_hash="pangkas-1",
        )
        path = Path(self.media, up.file.name)

        self._jalan("--hari", "365", "--terapkan")

        self.assertFalse(path.exists())
        up.refresh_from_db()
        self.assertFalse(up.file)
        # Metadata rekonsiliasi utuh — itu seluruh syarat keamanan alat ini.
        self.assertEqual(Upload.objects.filter(pk=up.pk).count(), 1)
        self.assertEqual(up.transactions.count(), 1)
        self.assertEqual(up.original_name, "MUTASI.csv")

    def test_yang_lebih_muda_dari_ambang_tidak_disentuh(self):
        muda = self._upload(10)
        tua = self._upload(400)

        self._jalan("--hari", "365", "--terapkan")

        muda.refresh_from_db()
        tua.refresh_from_db()
        self.assertTrue(muda.file)
        self.assertFalse(tua.file)

    def test_saringan_toko_dihormati(self):
        lbs = self._upload(400)
        slo = self._upload(400, toko=Toko.objects.get(key="slo"))

        self._jalan("--hari", "365", "--terapkan", "--toko", "slo")

        lbs.refresh_from_db()
        slo.refresh_from_db()
        self.assertTrue(lbs.file)
        self.assertFalse(slo.file)

    def test_penanda_ketiban_tidak_ikut_hilang(self):
        lama = self._upload(400, nama="A.csv")
        baru = self._upload(400, nama="A.csv")
        lama.superseded_by = baru
        lama.save(update_fields=["superseded_by"])

        self._jalan("--hari", "365", "--terapkan")

        lama.refresh_from_db()
        self.assertEqual(lama.superseded_by_id, baru.pk)

    def test_berkas_yang_sudah_lenyap_tetap_membersihkan_kolomnya(self):
        """Baris menunjuk berkas yang hilang (deploy sebelum volume terpasang).
        Perintah tidak boleh melempar, dan kolomnya HARUS dibersihkan — kalau
        tidak, view unduh terus menjanjikan berkas yang tak ada."""
        up = self._upload(400)
        Path(self.media, up.file.name).unlink()

        keluaran = self._jalan("--hari", "365", "--terapkan")

        up.refresh_from_db()
        self.assertFalse(up.file)
        self.assertIn("1 berkas", keluaran)
        self.assertEqual(Upload.objects.filter(pk=up.pk).count(), 1)

    def test_baris_tanpa_berkas_tidak_terhitung(self):
        Upload.objects.create(source_type=self.st, toko=self.toko, original_name="kosong.csv")

        keluaran = self._jalan("--hari", "1")

        self.assertIn("0 berkas", keluaran)
