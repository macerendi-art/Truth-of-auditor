"""Deteksi "tiban": upload ulang sama-nama yang LEBIH LENGKAP menandai file lama.

File tarikan mutasi bank kadang kepotong di BAGIAN BAWAH (baris terbaru hilang).
End user meng-upload ulang versi utuhnya dengan nama file yang sama; tanpa penanda
apa pun, file lama yang usang tetap terdaftar dan bisa terpilih orang.

Buktinya bukan nama file, melainkan superset `row_hash`: SELURUH isi file lama
(baris miliknya + baris dedup yang ter-link padanya) harus tercakup file baru.
Nama file hanya sinyal pendukung.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from core.models import AuditLog
from sources import services
from sources.models import SourceType, Toko, Upload


def _row(rh, jam):
    return {
        "occurred_at": datetime(2026, 7, 12, jam, 0), "posted_date": None, "jenis": "depo",
        "amount": Decimal("50000"), "credit_delta": Decimal("-50000"),
        "money_delta": Decimal("50000"), "fee": Decimal("0"), "bonus": Decimal("0"),
        "balance_after": None, "ticket_no": f"D{jam}", "username": "budi",
        "reference": "", "counterparty": "", "description": "", "raw": {},
        "row_hash": f"tiban-{rh}",
    }


def _parser(*hashes):
    """Kelas parser palsu: satu baris per hash yang diminta."""

    class _P:
        source_key = "bank"

        def parse(self, path, flow=""):
            return [_row(h, i + 1) for i, h in enumerate(hashes)]

    return _P


class TibanTests(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})
        self.user = User.objects.create_user("pengunggah", password="X-Kuat#88", role="admin")

    def _unggah(self, hashes, nama):
        """Ingest satu "file" berisi `hashes`, dgn nama asli `nama`."""
        with patch.dict(services.PARSERS, {"_tiban": _parser(*hashes)}, clear=False):
            return services.ingest(
                "_tiban", "/staging/apa-saja.csv", toko=self.toko,
                user=self.user, original_name=nama,
            )

    def _mundurkan(self, up, selisih):
        """Mundurkan `created_at` lewat UPDATE — `auto_now_add` menimpa save() biasa."""
        Upload.objects.filter(pk=up.pk).update(created_at=timezone.now() - selisih)

    def test_superset_sama_nama_menandai_tiban(self):
        """File baru memuat SELURUH isi file lama + baris tambahan -> lama ketiban."""
        up_a, _, _ = self._unggah(["a", "b"], "MUTASI BRI 27-06.csv")
        up_b, created, _ = self._unggah(["a", "b", "c"], "MUTASI BRI 27-06.csv")

        self.assertEqual(created, 1)
        up_a.refresh_from_db()
        self.assertEqual(up_a.superseded_by_id, up_b.pk)
        self.assertEqual(list(up_b.supersedes.all()), [up_a])

        log = AuditLog.objects.get(aksi="upload_tiban")
        self.assertEqual(log.objek, f"Upload #{up_a.pk}")
        self.assertEqual(log.username, "pengunggah")
        self.assertEqual(
            (log.detail["lama"], log.detail["baru"], log.detail["upload_baru"]),
            ("MUTASI BRI 27-06.csv", "MUTASI BRI 27-06.csv", up_b.pk),
        )

    def test_nama_staging_bersufiks_tetap_cocok(self):
        """Sufiks acak storage Django ("X_1pZwg1n.xlsx") dibuang sebelum dibandingkan."""
        up_a, _, _ = self._unggah(["a", "b"], "MUTASI BRI 27-06_1pZwg1n.csv")
        up_b, _, _ = self._unggah(["a", "b", "c"], "MUTASI BRI 27-06.csv")

        up_a.refresh_from_db()
        self.assertEqual(up_a.superseded_by_id, up_b.pk)

    def test_nama_beda_tidak_tiban(self):
        """Superset saja tak cukup — nama file harus cocok."""
        up_a, _, _ = self._unggah(["a", "b"], "MUTASI BRI 27-06.csv")
        self._unggah(["a", "b", "c"], "MUTASI BCA 27-06.csv")

        up_a.refresh_from_db()
        self.assertIsNone(up_a.superseded_by_id)
        self.assertFalse(AuditLog.objects.filter(aksi="upload_tiban").exists())

    def test_bukan_superset_tidak_tiban(self):
        """File lama punya baris yang HILANG di file baru (ekspor rolling) -> aman."""
        up_a, _, _ = self._unggah(["a", "b"], "MUTASI BRI 27-06.csv")
        self._unggah(["b", "c"], "MUTASI BRI 27-06.csv")

        up_a.refresh_from_db()
        self.assertIsNone(up_a.superseded_by_id)

    def test_isi_kandidat_termasuk_baris_ter_link(self):
        """Isi file kandidat = baris miliknya + baris dedup ter-link, bukan miliknya saja.

        B memiliki {c} tapi ISI filenya {b,c} (b dicatat upload A). File ketiga tanpa
        b karenanya belum memuat seluruh isi B — B tak boleh ditandai ketiban.
        """
        self._unggah(["a", "b"], "MUTASI BRI 27-06.csv")
        up_b, _, _ = self._unggah(["b", "c"], "MUTASI BRI 27-06.csv")
        self._unggah(["c", "d"], "MUTASI BRI 27-06.csv")

        up_b.refresh_from_db()
        self.assertIsNone(up_b.superseded_by_id)

    def test_kandidat_tanpa_isi_tidak_tiban(self):
        """Upload tanpa baris DAN tanpa link = tanpa bukti apa pun — jangan ditandai."""
        kosong = Upload.objects.create(
            source_type=SourceType.objects.get(key="bank"), toko=self.toko,
            original_name="MUTASI BRI 27-06.csv",
        )
        self._unggah(["a", "b"], "MUTASI BRI 27-06.csv")

        kosong.refresh_from_db()
        self.assertIsNone(kosong.superseded_by_id)

    def test_kandidat_terlalu_tua_tidak_tiban(self):
        """Di luar TIBAN_JENDELA tak lagi jadi kandidat (batas rekayasa, bukan bisnis)."""
        up_a, _, _ = self._unggah(["a", "b"], "MUTASI BRI 27-06.csv")
        self._mundurkan(up_a, services.TIBAN_JENDELA + timedelta(minutes=1))
        self._unggah(["a", "b", "c"], "MUTASI BRI 27-06.csv")

        up_a.refresh_from_db()
        self.assertIsNone(up_a.superseded_by_id)

    def test_kandidat_tepat_di_dalam_jendela_tetap_tiban(self):
        """Sisi dalam batas — menjaga jendela tak menyempit diam-diam."""
        up_a, _, _ = self._unggah(["a", "b"], "MUTASI BRI 27-06.csv")
        self._mundurkan(up_a, services.TIBAN_JENDELA - timedelta(hours=1))
        up_b, _, _ = self._unggah(["a", "b", "c"], "MUTASI BRI 27-06.csv")

        up_a.refresh_from_db()
        self.assertEqual(up_a.superseded_by_id, up_b.pk)

    def test_file_identik_tidak_tiban(self):
        """Upload ulang file yang sama persis tidak menambah baris -> no-op."""
        up_a, _, _ = self._unggah(["a", "b"], "MUTASI BRI 27-06.csv")
        _, created, dup = self._unggah(["a", "b"], "MUTASI BRI 27-06.csv")

        self.assertEqual((created, dup), (0, 2))
        up_a.refresh_from_db()
        self.assertIsNone(up_a.superseded_by_id)

    def test_rantai_a_b_c(self):
        """A⊂B⊂C: C meniban B saja — A sudah ketiban, tak masuk kandidat lagi."""
        up_a, _, _ = self._unggah(["a"], "MUTASI BRI 27-06.csv")
        up_b, _, _ = self._unggah(["a", "b"], "MUTASI BRI 27-06.csv")
        up_c, _, _ = self._unggah(["a", "b", "c"], "MUTASI BRI 27-06.csv")

        up_a.refresh_from_db()
        up_b.refresh_from_db()
        self.assertEqual(up_b.superseded_by_id, up_c.pk)
        self.assertEqual(up_a.superseded_by_id, up_b.pk)

    def test_hapus_upload_baru_membatalkan_tiban(self):
        """SET_NULL: hapus file penindih -> file lama kembali tidak-ketiban."""
        up_a, _, _ = self._unggah(["a", "b"], "MUTASI BRI 27-06.csv")
        up_b, _, _ = self._unggah(["a", "b", "c"], "MUTASI BRI 27-06.csv")
        up_b.delete()

        up_a.refresh_from_db()
        self.assertIsNone(up_a.superseded_by_id)

    def test_retry_integrity_error_menandai_tepat_sekali(self):
        """Balapan ingest ganda mengulang `_persist_rows` sekali — hasilnya tetap tunggal.

        Seluruh jalur simpan (Upload + baris + penandaan) berbagi satu `atomic()`:
        percobaan yang gagal tak meninggalkan Upload sisa, dan file lama ditandai
        sekali saja dengan satu baris audit.
        """
        up_a, _, _ = self._unggah(["a", "b"], "MUTASI BRI 27-06.csv")

        asli = services.Transaction.objects.bulk_create
        panggilan = {"n": 0}

        def flaky(objs, **kw):
            panggilan["n"] += 1
            if panggilan["n"] == 1:
                raise IntegrityError("simulasi balapan ingest ganda")
            return asli(objs, **kw)

        with patch.object(services.Transaction.objects, "bulk_create", side_effect=flaky):
            up_b, created, _ = self._unggah(["a", "b", "c"], "MUTASI BRI 27-06.csv")

        self.assertEqual((panggilan["n"], created), (2, 1))
        up_a.refresh_from_db()
        self.assertEqual(up_a.superseded_by_id, up_b.pk)
        self.assertEqual(AuditLog.objects.filter(aksi="upload_tiban").count(), 1)
        self.assertEqual(Upload.objects.count(), 2)  # percobaan gagal tak meninggalkan sisa

    def test_jalur_cli_tanpa_kwarg_pakai_basename(self):
        """Tanpa `original_name`, nama file tetap diturunkan dari path (perilaku lama)."""
        with patch.dict(services.PARSERS, {"_tiban": _parser("a")}, clear=False):
            up, _, _ = services.ingest("_tiban", "/data/berkas-cli.csv", toko=self.toko)
        self.assertEqual(up.original_name, "berkas-cli.csv")
