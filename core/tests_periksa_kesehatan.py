"""Penjaga `python manage.py periksa_kesehatan`.

Perintah ini dipasang di runbook/cron: nilainya HANYA sebesar kesetiaannya
melapor. Dua sifat yang paling gampang hilang diam-diam saat kode disunting,
dan karena itu dikunci di sini:

1. **Laporannya utuh.** Satu pemeriksaan yang gagal tidak boleh menghentikan
   yang lain, dan `CommandError` cuma boleh dilempar di AKHIR.
2. **Ia tidak berpura-pura bersih di SQLite.** Setengah pemeriksaannya
   bersandar pada katalog PostgreSQL; di dev/tes ia wajib bilang "Tidak
   berlaku", bukan "OK".

Ambangnya diuji sebagai fungsi murni (tanpa DB, pola sama dengan
`periksa_index.periksa` dan `web/penjaga.py`). Tanggal di tes SELALU
diturunkan dari `date.today()` — tanggal mati akan membuat tes ini
kedaluwarsa sendiri tanpa ada yang sadar.
"""

import json
import tempfile
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from core.management.commands.periksa_kesehatan import (
    BAHAYA, BATCH_BAHAYA, INFO, OK, PERHATIAN, laju_tumbuh, nilai_disk,
    nilai_ref, nilai_sequence, nilai_umur_batch, ukuran,
)
from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko


class AmbangMurniTests(SimpleTestCase):
    """Aturannya, tanpa DB dan tanpa Django."""

    def test_disk_lega_ok(self):
        self.assertEqual(nilai_disk(100, 88)[0], OK)

    def test_disk_menipis_perhatian(self):
        status, persen = nilai_disk(1000, 150)
        self.assertEqual(status, PERHATIAN)
        self.assertAlmostEqual(persen, 15.0)

    def test_disk_kritis_bahaya(self):
        """Insiden 2026-07-04: volume 500 MB penuh oleh pg_wal dan aplikasi
        mati. Inilah satu-satunya angka di perintah ini yang benar-benar
        pernah menjatuhkan produksi."""
        self.assertEqual(nilai_disk(1000, 50)[0], BAHAYA)

    def test_disk_tanpa_total_jadi_info_bukan_ok(self):
        self.assertEqual(nilai_disk(0, 0), (INFO, None))

    def test_sequence_bigint_praktis_nol(self):
        status, rasio = nilai_sequence(8_842_701, 9223372036854775807)
        self.assertEqual(status, OK)
        self.assertLess(rasio, 1e-8)

    def test_sequence_int4_hampir_habis_bahaya(self):
        """2,1 miliar bukan angka teoretis untuk tabel yang tumbuh 185 rb
        baris/hari — satu kolom int4 yang lolos akan meledak."""
        self.assertEqual(nilai_sequence(2_100_000_000, 2_147_483_647)[0], BAHAYA)

    def test_sequence_tiga_perempat_perhatian(self):
        self.assertEqual(nilai_sequence(1_700_000_000, 2_147_483_647)[0], PERHATIAN)

    def test_sequence_belum_terpakai_info(self):
        self.assertEqual(nilai_sequence(None, 2_147_483_647), (INFO, None))

    def test_umur_batch(self):
        self.assertEqual(nilai_umur_batch(0), OK)
        self.assertEqual(nilai_umur_batch(2), OK)
        self.assertEqual(nilai_umur_batch(3), PERHATIAN)
        self.assertEqual(nilai_umur_batch(7), BAHAYA)

    def test_toko_tanpa_batch_perhatian_bukan_bahaya(self):
        """Merek yang baru di-onboard sah belum punya batch. Kalau ini BAHAYA,
        perintahnya keluar ≠ 0 di hari pertama tiap brand baru — dan orang
        berhenti mempercayainya dalam seminggu."""
        self.assertEqual(nilai_umur_batch(None), PERHATIAN)

    def test_ref_kosong_bahaya(self):
        self.assertEqual(nilai_ref(0), BAHAYA)
        self.assertEqual(nilai_ref(4), OK)

    def test_laju_tumbuh_dihitung_per_hari(self):
        hasil = laju_tumbuh({"tanggal": "2026-08-01", "ukuran_db": 1000},
                            {"tanggal": "2026-08-11", "ukuran_db": 3000})
        self.assertEqual(hasil["hari"], 10)
        self.assertEqual(hasil["delta"], 2000)
        self.assertEqual(hasil["per_hari"], 200)

    def test_laju_tumbuh_hari_sama_tidak_membagi_nol(self):
        """Dua potret di hari yang sama tidak menghasilkan laju — bukan
        `ZeroDivisionError`, dan bukan pula angka fantasi."""
        self.assertIsNone(laju_tumbuh({"tanggal": "2026-08-01", "ukuran_db": 1},
                                      {"tanggal": "2026-08-01", "ukuran_db": 9}))

    def test_laju_tumbuh_potret_rusak_diabaikan(self):
        """Berkas potret disunting tangan / ditulis versi lama — pembanding
        yang rusak tak boleh menjatuhkan pemeriksaan kesehatan."""
        baru = {"tanggal": "2026-08-11", "ukuran_db": 3000}
        self.assertIsNone(laju_tumbuh({"tanggal": "bukan-tanggal", "ukuran_db": 1}, baru))
        self.assertIsNone(laju_tumbuh({"ukuran_db": 1}, baru))
        self.assertIsNone(laju_tumbuh(None, baru))

    def test_ukuran_pakai_koma_desimal(self):
        self.assertEqual(ukuran(1536), "1,5 KB")
        self.assertEqual(ukuran(None), "—")


MOD = "core.management.commands.periksa_kesehatan"


class PerintahTests(TestCase):
    """Jalur nyata di SQLite — persis lingkungan tes & dev.

    Data referensi (SourceType, ToleranceProfile "Default", Toko) datang dari
    migrasi data, jadi DB tes sudah membawanya.
    """

    def jalankan(self, **opts):
        out = StringIO()
        opts.setdefault("tanpa_simpan", True)
        call_command("periksa_kesehatan", stdout=out, stderr=out, **opts)
        return out.getvalue()

    def test_sqlite_bilang_tidak_berlaku_bukan_ok(self):
        """Bagian yang bersandar pada katalog PostgreSQL wajib mengaku tak
        berlaku. "OK" di sini adalah jaminan palsu."""
        teks = self.jalankan()
        self.assertIn("Tidak berlaku", teks)
        self.assertIn("sqlite", teks)

    def test_semua_bagian_muncul(self):
        """Laporan yang putus di tengah menyembunyikan temuan berikutnya."""
        teks = self.jalankan()
        for judul in ("Ukuran basis data", "Ruang disk", "Index",
                      "Tabel terbesar", "Umur batch terakhir per toko",
                      "Sequence", "Tabel referensi", "Kueri patokan",
                      "Ringkasan"):
            self.assertIn(judul, teks)

    def test_referensi_terisi_maka_ok(self):
        teks = self.jalankan()
        self.assertIn("SourceType", teks)
        self.assertNotIn("KOSONG", teks)

    def test_referensi_kosong_bahaya_dan_keluar_tak_nol(self):
        """Kelas gagal senyap yang paling mahal: DB hasil restore yang
        kehilangan seed migrasi data terlihat sehat sampai rekonsiliasi
        pertama gagal."""
        SourceType.objects.all().delete()
        with self.assertRaises(CommandError) as cm:
            self.jalankan()
        self.assertIn("BAHAYA", str(cm.exception))

    def test_laporan_tetap_lengkap_walau_ada_bahaya(self):
        """`CommandError` dilempar di AKHIR — bagian setelah temuan tetap
        tercetak."""
        ToleranceProfile.objects.filter(name="Default").delete()
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command("periksa_kesehatan", stdout=out, stderr=out,
                         tanpa_simpan=True)
        teks = out.getvalue()
        self.assertIn("Kueri patokan", teks)   # bagian TERAKHIR sebelum ringkasan
        self.assertIn("Ringkasan", teks)

    def test_batch_basi_jadi_bahaya(self):
        toko = Toko.objects.create(key="uji-basi", name="Uji Basi")
        tol = ToleranceProfile.objects.get(name="Default")
        ReconBatch.objects.create(
            toko=toko, tolerance=tol,
            recon_date=date.today() - timedelta(days=BATCH_BAHAYA))
        with self.assertRaises(CommandError):
            self.jalankan()

    def test_batch_kemarin_tidak_membunyikan_alarm(self):
        toko = Toko.objects.create(key="uji-segar", name="Uji Segar")
        tol = ToleranceProfile.objects.get(name="Default")
        ReconBatch.objects.create(toko=toko, tolerance=tol,
                                  recon_date=date.today() - timedelta(days=1))
        teks = self.jalankan()
        self.assertIn("uji-segar", teks)
        self.assertIn("1 hari lalu", teks)

    def test_potret_ditulis_lalu_dibandingkan(self):
        """Laju tumbuh: run pertama menyimpan, run kedua membandingkan.

        Ukuran DB dipalsukan karena basis data tes SQLite in-memory tak punya
        berkas untuk diukur — yang diuji di sini adalah aritmetika potret,
        bukan cara membaca ukurannya."""
        with tempfile.TemporaryDirectory() as d, \
                patch(f"{MOD}.Command._ukuran_db", return_value=10 * 1024**3):
            jalur = Path(d) / "kesehatan.json"
            teks = self.jalankan(tanpa_simpan=False, berkas_status=str(jalur))
            self.assertIn("belum ada pembanding", teks)
            self.assertTrue(jalur.is_file())
            # Potret "dua hari lalu" supaya rentangnya > 0 hari.
            data = json.loads(jalur.read_text())
            self.assertEqual(data["ukuran_db"], 10 * 1024**3)
            data["tanggal"] = (date.today() - timedelta(days=2)).isoformat()
            data["ukuran_db"] = 8 * 1024**3
            jalur.write_text(json.dumps(data))
            teks = self.jalankan(tanpa_simpan=False, berkas_status=str(jalur))
            self.assertIn("Laju tumbuh:", teks)
            self.assertIn("1,0 GB/hari", teks)

    def test_ukuran_tak_terbaca_tidak_menelan_bagian_lain(self):
        """Basis data tes tak punya berkas untuk diukur. Bagian ini dulu
        `return` di titik itu dan ikut membuang baris laju tumbuh —
        pelanggaran "laporan selalu utuh" dalam bentuk paling halus."""
        teks = self.jalankan()
        self.assertIn("tidak terbaca", teks)
        self.assertIn("belum ada pembanding", teks)

    def test_potret_tak_bisa_ditulis_tidak_menggagalkan(self):
        """Berkas potret adalah alat bantu, bukan sumber kebenaran: sistem
        berkas read-only tidak boleh mengubah verdict kesehatan."""
        with patch(f"{MOD}.open",
                   side_effect=OSError("read-only file system")):
            teks = self.jalankan(tanpa_simpan=False)
        self.assertIn("Gagal menyimpan potret", teks)
        self.assertIn("Ringkasan", teks)

    def test_logika_index_dipakai_ulang_bukan_disalin(self):
        """Kalau `periksa_index` berganti nama fungsi, ini yang merah lebih
        dulu — bukan produksi yang diam-diam berhenti memeriksa index."""
        import core.management.commands.periksa_kesehatan as pk
        from core.management.commands import periksa_index as pi
        self.assertIs(pk.periksa, pi.periksa)
        self.assertIs(pk.baca_katalog, pi.baca_katalog)
