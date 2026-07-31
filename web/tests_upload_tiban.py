"""Jalur WEB fitur "ketiban" — nama file asli dari form + penandanya di halaman.

Deteksi tiban (`sources/services._tandai_tiban`) memakai nama file sebagai
gerbang. Handler commit memanggil `ingest` dengan path STAGING, dan bila nama
staging bentrok storage Django membubuhkan sufiks acak ("X.xlsx" ->
"X_1pZwg1n.xlsx") — tanpa meneruskan nama asli dari form, gerbang itu praktis
tak pernah lolos. Yang diuji di sini jalur webnya; deteksinya sendiri ada di
`sources/tests_tiban.py`.
"""
import re
import shutil
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from sources import services
from sources.models import SourceType, Toko, Upload


def _row(rh, jam):
    return {
        "occurred_at": datetime(2026, 7, 12, jam, 0), "posted_date": None, "jenis": "depo",
        "amount": Decimal("50000"), "credit_delta": Decimal("-50000"),
        "money_delta": Decimal("50000"), "fee": Decimal("0"), "bonus": Decimal("0"),
        "balance_after": None, "ticket_no": f"D{jam}", "username": "budi",
        "reference": "", "counterparty": "PENGIRIM", "description": "", "raw": {},
        "row_hash": f"webtiban-{rh}",
    }


def _parser(*hashes):
    """Kelas parser palsu bersumber `bank`: satu baris per hash yang diminta."""

    class _P:
        source_key = "bank"

        def parse(self, path, flow=""):
            return [_row(h, i + 1) for i, h in enumerate(hashes)]

    return _P


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="toa-test-tiban-"))
class _TibanWebBase(TestCase):
    """Media sementara: tes ini menaruh file di `staging/` dan bergantung pada
    ada/tidaknya bentrok nama — sisa file di media dev mengubah hasilnya."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._overridden_settings["MEDIA_ROOT"], ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        get_user_model().objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.lbs = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def _stage(self, nama):
        """Taruh satu file di staging; kembalikan path relatifnya (bisa bersufiks)."""
        return default_storage.save(f"staging/{nama}", ContentFile(b"isi"))

    def _commit(self, staged, hashes, orig_name=None, **kw):
        """POST action=commit untuk satu file staging, parser dipalsukan."""
        data = {"action": "commit", "staged": [staged],
                "parser_key": ["_tiban"], "flow": [""]}
        if orig_name is not None:
            data["orig_name"] = [orig_name]
        with patch.dict(services.PARSERS, {"_tiban": _parser(*hashes)}, clear=False):
            return self.client.post(reverse("upload"), data, **kw)

    def _unggah(self, hashes, nama, **kw):
        """Alur lengkap: stage dgn nama `nama` lalu commit membawa nama aslinya."""
        return self._commit(self._stage(nama), hashes, orig_name=nama, **kw)


class NamaAsliDiteruskanTests(_TibanWebBase):
    def test_nama_asli_bersih_walau_path_staging_bersufiks(self):
        """Staging bentrok -> path bersufiks acak, nama tersimpan tetap bersih."""
        self._stage("MUTASI BRI 27-06.csv")            # penghuni pertama = pemicu bentrok
        staged = self._stage("MUTASI BRI 27-06.csv")
        self.assertNotEqual(staged, "staging/MUTASI BRI 27-06.csv",
                            "prasyarat tes: path staging kedua harus bersufiks")

        self._commit(staged, ["a"], orig_name="MUTASI BRI 27-06.csv")

        self.assertEqual(Upload.objects.latest("id").original_name, "MUTASI BRI 27-06.csv")

    def test_tanpa_orig_name_pakai_basename_staging(self):
        """Back-compat: POST tanpa field itu -> perilaku lama (basename staging)."""
        staged = self._stage("lawas.csv")

        self._commit(staged, ["a"])

        self.assertEqual(Upload.objects.latest("id").original_name, Path(staged).name)

    def test_orig_name_berpath_dibersihkan(self):
        """Nilai dari form tak dipercaya: hanya basename-nya yang dipakai."""
        staged = self._stage("polos.csv")

        self._commit(staged, ["a"], orig_name="../../evil.xlsx")

        self.assertEqual(Upload.objects.latest("id").original_name, "evil.xlsx")

    def test_form_preview_mengirim_nama_asli(self):
        """Markup preview ikut mengirim nama asli — tanpa ini view tak pernah dapat."""
        r = self.client.post(reverse("upload"), {
            "action": "analyze",
            "files": [SimpleUploadedFile("bri.csv", b"TGL_TRAN,MUTASI_DEBET\n")],
        })

        self.assertContains(r, 'name="orig_name"')
        self.assertContains(r, 'value="bri.csv"')     # staged = "staging/bri.csv", beda


class FlashTibanTests(_TibanWebBase):
    def test_flash_menyebut_penggantian(self):
        """Upload ulang sama-nama yang lebih lengkap -> pesan penggantian tampil."""
        self._unggah(["a", "b"], "MUTASI BRI 27-06.csv")
        r = self._unggah(["a", "b", "c"], "MUTASI BRI 27-06.csv", follow=True)

        pesan = " ".join(str(m) for m in r.context["messages"])
        self.assertIn(
            '"MUTASI BRI 27-06.csv" menggantikan "MUTASI BRI 27-06.csv" — '
            "file lama ditandai Ketiban (1 baris baru).", pesan)
        self.assertIn("1 file diproses, 0 gagal.", pesan)   # ringkasan lama tetap ada

    def test_tanpa_tiban_tanpa_flash_penggantian(self):
        """Nama beda -> tak ada yang ketiban, tak ada pesannya (bukan blanket)."""
        self._unggah(["a", "b"], "MUTASI BRI 27-06.csv")
        r = self._unggah(["a", "b", "c"], "MUTASI BCA 27-06.csv", follow=True)

        pesan = " ".join(str(m) for m in r.context["messages"])
        self.assertNotIn("menggantikan", pesan)


class BadgeRiwayatTests(_TibanWebBase):
    def _upload(self, nama):
        return Upload.objects.create(source_type=self.bank, toko=self.lbs,
                                     original_name=nama, status=Upload.PARSED)

    def test_badge_ketiban_dan_nama_pengganti_di_tooltip(self):
        # Nama sengaja DIBEDAKAN (di lapangan sama) supaya jelas tooltip
        # menyebut si PENGGANTI, bukan barisnya sendiri.
        lama = self._upload("MUTASI BRI 27-06.csv")
        baru = self._upload("MUTASI BRI 27-06 UTUH.csv")
        lama.superseded_by = baru
        lama.save(update_fields=["superseded_by"])

        r = self.client.get(reverse("upload"))

        self.assertContains(r, ">Ketiban<")
        self.assertContains(
            r, 'Ketiban — seluruh isinya sudah tercakup file "MUTASI BRI 27-06 UTUH.csv" '
               f'({baru.created_at.strftime("%d/%m %H:%M")})')

    def test_upload_biasa_tanpa_badge(self):
        """Penjaga anti-false-positive: badge jangan muncul di semua baris."""
        self._upload("MUTASI BRI 27-06.csv")

        r = self.client.get(reverse("upload"))

        self.assertContains(r, "MUTASI BRI 27-06.csv")
        self.assertNotContains(r, ">Ketiban<")


class TibanQueryTests(_TibanWebBase):
    """Badge & sufiks membaca FK `superseded_by` per baris — tanpa select_related
    itu satu query TAMBAHAN per baris ketiban (terukur: /upload/ 18→23 query saat
    baris ketiban naik 5→10). Halaman ini sudah pernah jadi 10,8 dtk di prod."""

    def _seed(self, n):
        baru = Upload.objects.create(source_type=self.bank, toko=self.lbs,
                                     original_name="baru.csv", status=Upload.PARSED)
        for i in range(n):
            Upload.objects.create(source_type=self.bank, toko=self.lbs, superseded_by=baru,
                                  original_name=f"lama{i}.csv", status=Upload.PARSED)

    def _n_query(self, url):
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).status_code, 200)
        return len(ctx)

    def test_query_tidak_tumbuh_saat_baris_ketiban_bertambah(self):
        for nama, url in (("upload", reverse("upload")), ("mutasi", reverse("bank_mutations"))):
            with self.subTest(halaman=nama):
                Upload.objects.all().delete()
                self._seed(2)
                self.client.get(url)                      # warm-up cache ContentType dkk.
                sedikit = self._n_query(url)
                self._seed(8)
                self.assertEqual(sedikit, self._n_query(url),
                                 f"query {nama} tumbuh saat baris ketiban bertambah (N+1)")


class DropdownMutasiBankTests(_TibanWebBase):
    def test_sufiks_ketiban_di_dropdown_dan_tetap_bisa_dipilih(self):
        """Entri ketiban = bukti audit — ditandai, tapi tidak disembunyikan."""
        self._unggah(["a", "b"], "MUTASI BRI 27-06.csv")
        self._unggah(["a", "b", "c"], "MUTASI BRI 27-06.csv")
        lama = Upload.objects.order_by("id").first()
        self.assertIsNotNone(lama.superseded_by_id, "prasyarat tes: file lama harus ketiban")

        r = self.client.get(reverse("bank_mutations"))

        html = r.content.decode()
        # dipersempit ke dropdown file — pemilih Toko juga punya <option value=…>
        daftar = re.search(r'<select name="upload">.*?</select>', html, re.S)
        self.assertIsNotNone(daftar, "dropdown file mutasi harus ada")
        opsi = re.search(rf'<option value="{lama.id}"[^>]*>[^<]*</option>', daftar.group(0))
        self.assertIsNotNone(opsi, "entri ketiban harus tetap ada sebagai opsi")
        self.assertIn(" · ketiban", opsi.group(0))
        self.assertNotIn("disabled", opsi.group(0))
        self.assertEqual(html.count(" · ketiban"), 1)   # hanya yang ketiban ditandai
