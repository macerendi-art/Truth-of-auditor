"""Unduh berkas asli sebuah unggahan — sisi "bisa diambil kembali" dari jejak audit.

Menyimpan berkas tanpa jalan mengambilnya lagi sama saja tidak menyimpannya:
`MEDIA_URL` hanya dilayani saat DEBUG (`truth_auditor/urls.py`), jadi di produksi
tidak ada URL media sama sekali — dan kalaupun ada, URL media tak mengenal siapa
pun, sementara ekspor mutasi bank memuat nama pemain, nomor rekening, dan nominal.
Karena itu satu-satunya jalur adalah view ber-scope `tokos_for` yang diuji di sini.
"""
import shutil
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from django.urls import reverse

from sources import services
from sources.models import SourceType, Toko, Upload

ISI = b"TGL_TRAN,MUTASI_KREDIT\n27/06/2026,50000\n"

_ROW = {
    "occurred_at": datetime(2026, 6, 27, 10, 0), "posted_date": None, "jenis": "depo",
    "amount": Decimal("50000"), "credit_delta": Decimal("-50000"), "money_delta": Decimal("50000"),
    "fee": Decimal("0"), "bonus": Decimal("0"), "balance_after": None, "ticket_no": "D1",
    "username": "budi", "reference": "", "counterparty": "", "description": "", "raw": {},
    "row_hash": "unduh-row-1",
}


class _DummyBracket:
    source_key = "bracket"

    def parse(self, path, flow=""):
        return [dict(_ROW)]


class _Basis(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="toa-media-")
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.enterContext(override_settings(MEDIA_ROOT=self.media))
        User = get_user_model()
        self.u = User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"})[0]
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})


class JalurCommitMenyimpanTests(_Basis):
    """Pin jalur produksi: unggah lewat web WAJIB menyimpan berkas aslinya.

    `simpan_berkas` sengaja opt-in di `services.ingest`, jadi pemanggil ini
    adalah tempat fitur bisa mati diam-diam tanpa satu tes pun memerah."""

    def _commit(self, nama="MUTASI BRI 27-06.csv", isi=ISI):
        staged = default_storage.save(f"staging/{nama}", ContentFile(isi))
        with patch.dict(services.PARSERS, {"dummy": _DummyBracket}, clear=False):
            r = self.client.post(reverse("upload"), {
                "action": "commit", "staged": [staged], "orig_name": [nama],
                "parser_key": ["dummy"], "flow": [""], "provider": "Nexus",
            })
        return r, staged

    def test_commit_menyimpan_berkas_asli(self):
        r, staged = self._commit()

        self.assertEqual(r.status_code, 302)
        up = Upload.objects.latest("id")
        self.assertTrue(up.file, "unggahan web harus menyimpan berkas aslinya")
        with up.file.open("rb") as fh:
            self.assertEqual(fh.read(), ISI)
        # Alur staging LAMA tidak berubah: yang disimpan salinannya.
        self.assertFalse(default_storage.exists(staged))

    def test_berkas_staging_tetap_dihapus(self):
        """Regresi terarah: penyimpanan permanen tidak boleh membuat volume
        staging jadi menumpuk (sapuan `_sweep_staging` mengandalkan ini)."""
        _, staged = self._commit()
        self.assertEqual(
            [p.name for p in Path(self.media, "staging").glob("*")], [])
        self.assertFalse(default_storage.exists(staged))


class UnduhBerkasTests(_Basis):
    def _upload_berisi(self, toko=None, nama="MUTASI BRI 27-06.csv"):
        up = Upload.objects.create(
            source_type=self.bracket, toko=toko or self.lbs,
            original_name=nama, uploaded_by=self.u,
        )
        up.file.save(nama, ContentFile(ISI), save=True)
        return up

    def test_unduh_mengembalikan_byte_yang_sama(self):
        up = self._upload_berisi()

        r = self.client.get(reverse("unduh_upload", args=[up.pk]))

        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), ISI)

    def test_nama_unduhan_memakai_original_name_bukan_nama_storage(self):
        """Storage menyanitasi spasi jadi garis bawah; yang dilihat auditor
        harus tetap nama file seperti yang ia unggah."""
        up = self._upload_berisi()

        r = self.client.get(reverse("unduh_upload", args=[up.pk]))

        self.assertIn("attachment", r["Content-Disposition"])
        self.assertIn("MUTASI BRI 27-06.csv", r["Content-Disposition"])

    def test_toko_lain_tidak_bisa_mengunduh(self):
        """Auditor ber-scope: `tokos_for` adalah gerbangnya, sama seperti hapus."""
        User = get_user_model()
        lain = User.objects.create_user("aud2", "b@b.co", "pw12345", role="auditor")
        lain.allowed_tokos.set([self.slo])
        up = self._upload_berisi(toko=self.lbs)

        self.client.logout()
        self.client.login(username="aud2", password="pw12345")
        r = self.client.get(reverse("unduh_upload", args=[up.pk]))

        self.assertEqual(r.status_code, 404)

    def test_baris_lama_tanpa_berkas_404_bukan_500(self):
        """SELURUH baris Upload dari sebelum fitur ini ada berada di sini."""
        up = Upload.objects.create(
            source_type=self.bracket, toko=self.lbs,
            original_name="lama.xlsx", uploaded_by=self.u,
        )
        self.assertFalse(up.file)

        r = self.client.get(reverse("unduh_upload", args=[up.pk]))

        self.assertEqual(r.status_code, 404)

    def test_berkas_lenyap_dari_disk_404_bukan_500(self):
        """Baris menunjuk berkas yang hilang (deploy sebelum volume terpasang)."""
        up = self._upload_berisi()
        Path(self.media, up.file.name).unlink()

        r = self.client.get(reverse("unduh_upload", args=[up.pk]))

        self.assertEqual(r.status_code, 404)

    def test_anonim_diarahkan_ke_login(self):
        up = self._upload_berisi()
        self.client.logout()

        r = self.client.get(reverse("unduh_upload", args=[up.pk]))

        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])

    def test_tautan_unduh_muncul_di_riwayat_hanya_bila_berkas_ada(self):
        ada = self._upload_berisi(nama="ADA.csv")
        kosong = Upload.objects.create(
            source_type=self.bracket, toko=self.lbs,
            original_name="KOSONG.csv", uploaded_by=self.u,
        )

        r = self.client.get(reverse("upload"))

        self.assertContains(r, reverse("unduh_upload", args=[ada.pk]))
        self.assertNotContains(r, reverse("unduh_upload", args=[kosong.pk]))
