"""Jejak audit berkas asli: `Upload.file` benar-benar diisi dan bisa diambil lagi.

`Upload.file` (FileField) ada sejak commit pertama tapi TIDAK PERNAH diisi kode
apa pun — `_persist_rows` tak pernah membawa `file=`, dan alur unggah web
menghapus berkas staging di blok `finally` pada request yang sama. Jadi
pertanyaan audit "berkas mana yang melahirkan baris ini?" tak pernah bisa
dijawab dari aplikasi.

Modul ini mengunci penyambungannya, termasuk sisi yang mudah rusak diam-diam:
penyimpanan berkas BUKAN operasi transaksional, sedangkan `_persist_rows`
berjalan di dalam `atomic()` yang bisa di-rollback (dan `ingest` sengaja
mengulang sekali saat `IntegrityError`). Tanpa pembersihan eksplisit, setiap
rollback meninggalkan berkas yatim di disk.
"""
import shutil
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from sources import services
from sources.models import SourceType, Toko, Upload

ISI = b"tanggal,nominal\n2026-07-12,50000\n"


def _row(rh, jam=1):
    return {
        "occurred_at": datetime(2026, 7, 12, jam, 0), "posted_date": None, "jenis": "depo",
        "amount": Decimal("50000"), "credit_delta": Decimal("-50000"),
        "money_delta": Decimal("50000"), "fee": Decimal("0"), "bonus": Decimal("0"),
        "balance_after": None, "ticket_no": f"D{jam}", "username": "budi",
        "reference": "", "counterparty": "", "description": "", "raw": {},
        "row_hash": f"berkas-{rh}",
    }


def _parser(*hashes):
    class _P:
        source_key = "bank"

        def parse(self, path, flow=""):
            return [_row(h, i + 1) for i, h in enumerate(hashes)]

    return _P


class _Basis(TestCase):
    """Setiap tes menulis ke MEDIA_ROOT sementara — repo tidak ikut kotor."""

    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="toa-media-")
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.enterContext(override_settings(MEDIA_ROOT=self.media))
        self.sumber = Path(tempfile.mkdtemp(prefix="toa-src-")) / "MUTASI BRI 12-07.csv"
        self.addCleanup(shutil.rmtree, self.sumber.parent, ignore_errors=True)
        self.sumber.write_bytes(ISI)
        self.toko = Toko.objects.get(key="lbs")
        SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})
        self.user = User.objects.create_user("pengunggah", password="X-Kuat#88", role="admin")

    def _unggah(self, hashes=("a",), nama="MUTASI BRI 12-07.csv", simpan=True,
                path=None, password=""):
        with patch.dict(services.PARSERS, {"_berkas": _parser(*hashes)}, clear=False):
            return services.ingest(
                "_berkas", str(path or self.sumber), toko=self.toko,
                user=self.user, original_name=nama, simpan_berkas=simpan,
                password=password,
            )

    def _berkas_tersimpan(self):
        return sorted(p for p in Path(self.media).rglob("*") if p.is_file())


class PenyimpananBerkasTests(_Basis):
    def test_berkas_asli_tersimpan_dan_isinya_utuh(self):
        """Inti fitur: berkas benar-benar ada di disk dan bisa dibaca ulang."""
        up, _, _ = self._unggah()

        self.assertTrue(up.file, "Upload.file harus terisi saat simpan_berkas=True")
        self.assertTrue(up.file.name.startswith("uploads/"), up.file.name)
        # Diambil kembali lewat ORM (bukan lewat path yang dirakit tes) —
        # inilah yang akan dipakai view unduh.
        up.refresh_from_db()
        with up.file.open("rb") as fh:
            self.assertEqual(fh.read(), ISI)
        self.assertEqual(Path(self.media, up.file.name).read_bytes(), ISI)

    def test_default_tidak_menyimpan_apa_pun(self):
        """Opt-in: pemanggil yang tak meminta (tes, harness kalibrasi) tak terpengaruh."""
        up, _, _ = self._unggah(simpan=False)

        self.assertFalse(up.file)
        self.assertEqual(self._berkas_tersimpan(), [])

    def test_default_kwarg_memang_mati(self):
        """Tanpa menyebut kwarg sama sekali — pemanggil lama tak berubah perilaku."""
        with patch.dict(services.PARSERS, {"_berkas": _parser("a")}, clear=False):
            up, _, _ = services.ingest("_berkas", str(self.sumber), toko=self.toko)
        self.assertFalse(up.file)
        self.assertEqual(self._berkas_tersimpan(), [])

    def test_original_name_tidak_ikut_disanitasi_storage(self):
        """`original_name` adalah KUNCI pencocokan tiban — penyimpanan berkas
        tak boleh menyentuhnya walau storage mengganti spasi jadi garis bawah."""
        up, _, _ = self._unggah(nama="MUTASI BRI 12-07.csv")

        self.assertEqual(up.original_name, "MUTASI BRI 12-07.csv")
        self.assertNotIn(" ", Path(up.file.name).name)  # storage menyanitasi namanya

    def test_dua_unggahan_nama_sama_tidak_saling_menimpa(self):
        up_a, _, _ = self._unggah(("a",))
        up_b, _, _ = self._unggah(("b",))

        self.assertNotEqual(up_a.file.name, up_b.file.name)
        self.assertEqual(len(self._berkas_tersimpan()), 2)

    def test_berkas_terenkripsi_yang_disimpan_adalah_ASLI_bukan_hasil_dekripsi(self):
        """Mandiri e-statement: yang berhak jadi bukti audit adalah berkas
        SEPERTI DITERIMA. Menyimpan hasil dekripsi akan membuang perlindungan
        yang dipasang klien — dan password-nya tidak ikut disimpan."""
        terenkripsi = self.sumber.parent / "MANDIRI_TERKUNCI.xlsx"
        terenkripsi.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"rahasia")
        polos = self.sumber.parent / "hasil-dekripsi.xlsx"
        polos.write_bytes(b"PK\x03\x04ISI-TERBUKA")

        with patch.object(services, "_decrypt_to_temp", return_value=str(polos)):
            up, _, _ = self._unggah(path=terenkripsi, nama="MANDIRI_TERKUNCI.xlsx",
                                    password="rahasia123")

        with up.file.open("rb") as fh:
            tersimpan = fh.read()
        self.assertEqual(tersimpan, terenkripsi.read_bytes())
        self.assertNotIn(b"ISI-TERBUKA", tersimpan)


class RollbackTidakMeninggalkanYatimTests(_Basis):
    def test_kegagalan_setelah_simpan_membersihkan_berkas(self):
        """`_tandai_tiban` adalah statement TERAKHIR di dalam atomic(); kalau ia
        melempar, DB ter-rollback tapi berkas sudah terlanjur ada di disk."""
        with patch.object(services, "_tandai_tiban", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self._unggah()

        self.assertEqual(Upload.objects.count(), 0)
        self.assertEqual(self._berkas_tersimpan(), [], "berkas yatim tertinggal di disk")

    def test_retry_integrityerror_tidak_menggandakan_berkas(self):
        """`ingest` mengulang `_persist_rows` sekali saat IntegrityError —
        percobaan pertama harus membersihkan berkasnya sendiri."""
        asli = services._tandai_tiban
        panggilan = {"n": 0}

        def _sekali_gagal(*a, **kw):
            panggilan["n"] += 1
            if panggilan["n"] == 1:
                raise IntegrityError("bentrok row_hash")
            return asli(*a, **kw)

        with patch.object(services, "_tandai_tiban", side_effect=_sekali_gagal):
            up, _, _ = self._unggah()

        self.assertEqual(panggilan["n"], 2)
        self.assertEqual(Upload.objects.count(), 1)
        self.assertEqual(len(self._berkas_tersimpan()), 1)
        with up.file.open("rb") as fh:
            self.assertEqual(fh.read(), ISI)


class PerilakuLamaTidakBerubahTests(_Basis):
    """Dedup / tiban / atribusi harus IDENTIK dengan dan tanpa penyimpanan berkas."""

    def test_unggah_ulang_identik_tetap_nol_baris_baru(self):
        _, created_1, dup_1 = self._unggah(("a", "b"))
        _, created_2, dup_2 = self._unggah(("a", "b"))

        self.assertEqual((created_1, dup_1), (2, 0))
        self.assertEqual((created_2, dup_2), (0, 2))

    def test_baris_dedup_tetap_terlink_ke_upload_baru(self):
        self._unggah(("a", "b"))
        up_2, _, _ = self._unggah(("a", "b", "c"))

        self.assertEqual(up_2.duplicate_transactions.count(), 2)

    def test_tiban_tetap_menandai_saat_berkas_disimpan(self):
        up_a, _, _ = self._unggah(("a", "b"))
        up_b, created, _ = self._unggah(("a", "b", "c"))

        self.assertEqual(created, 1)
        up_a.refresh_from_db()
        self.assertEqual(up_a.superseded_by_id, up_b.pk)
        # Berkas file lama TIDAK ikut dihapus — "ketiban" murni metadata.
        self.assertTrue(up_a.file)
        self.assertTrue(Path(self.media, up_a.file.name).exists())

    def test_unggah_ulang_identik_byte_per_byte_tetap_no_op_pada_tiban(self):
        up_a, _, _ = self._unggah(("a", "b"))
        up_b, created, _ = self._unggah(("a", "b"))

        self.assertEqual(created, 0)
        up_a.refresh_from_db()
        self.assertIsNone(up_a.superseded_by_id, "tanpa baris baru, tak boleh menandai")


class PerintahCLITests(_Basis):
    def test_manage_ingest_menyimpan_berkas_secara_default(self):
        """`manage.py ingest` adalah jalur ingest PRODUKSI (membuat Upload +
        Transaction sungguhan), jadi ia ikut menyimpan jejaknya."""
        with patch.dict(services.PARSERS, {"_berkas": _parser("a")}, clear=False):
            call_command("ingest", "_berkas", str(self.sumber))

        up = Upload.objects.get()
        self.assertTrue(up.file)
        with up.file.open("rb") as fh:
            self.assertEqual(fh.read(), ISI)

    def test_manage_ingest_bisa_dimatikan(self):
        with patch.dict(services.PARSERS, {"_berkas": _parser("a")}, clear=False):
            call_command("ingest", "_berkas", str(self.sumber), "--tanpa-berkas")

        self.assertFalse(Upload.objects.get().file)
        self.assertEqual(self._berkas_tersimpan(), [])
