"""Penjaga integritas daftar versi (`core/version.py`).

Peta versi ini dipakai untuk melapor ke manajemen dan untuk menelusuri hasil
ekspor lama, jadi ia harus konsisten dengan dirinya sendiri: urutan menurun,
tanggal ikut menurun, dan lompatan nomor cocok dengan jenis rilis yang
diklaim. `CHANGELOG.md` di repo dibandingkan langsung dengan hasil render
supaya berkas itu tidak bisa diam-diam melenceng.
"""

import re
from pathlib import Path

from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import TestCase

from core import version as v

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class BentukRilisTests(TestCase):
    def test_ada_isinya(self):
        self.assertGreater(len(v.RILIS), 0, "daftar rilis tidak boleh kosong")

    def test_nomor_versi_berbentuk_semver(self):
        for r in v.RILIS:
            self.assertRegex(r.versi, SEMVER, f"nomor versi tak wajar: {r.versi}")

    def test_tiap_rilis_punya_nama_dan_sorotan(self):
        for r in v.RILIS:
            self.assertTrue(r.nama.strip(), f"{r.versi}: nama rilis kosong")
            self.assertGreaterEqual(
                len(r.sorotan), 3, f"{r.versi}: rilis yang layak diumumkan minimal 3 butir"
            )
            for s in r.sorotan:
                self.assertTrue(s.strip(), f"{r.versi}: ada butir sorotan kosong")

    def test_jenis_dikenal(self):
        for r in v.RILIS:
            self.assertIn(r.jenis, v.JENIS_LABEL, f"{r.versi}: jenis '{r.jenis}' tak dikenal")

    def test_tanpa_versi_atau_nama_kembar(self):
        nomor = [r.versi for r in v.RILIS]
        self.assertEqual(len(nomor), len(set(nomor)), "ada nomor versi kembar")
        nama = [r.nama.lower() for r in v.RILIS]
        self.assertEqual(len(nama), len(set(nama)), "ada nama rilis kembar")


class UrutanRilisTests(TestCase):
    """RILIS[0] harus yang TERBARU — halaman & CHANGELOG mengandalkan urutan ini."""

    def test_nomor_menurun_ketat(self):
        for baru, lama in zip(v.RILIS, v.RILIS[1:]):
            self.assertGreater(
                baru.nomor, lama.nomor,
                f"urutan salah: v{baru.versi} harus di atas v{lama.versi}",
            )

    def test_tanggal_tidak_pernah_mundur(self):
        for baru, lama in zip(v.RILIS, v.RILIS[1:]):
            self.assertGreaterEqual(
                baru.tanggal, lama.tanggal,
                f"v{baru.versi} ({baru.tanggal}) lebih tua dari v{lama.versi} ({lama.tanggal})",
            )

    def test_lompatan_nomor_cocok_dengan_jenis(self):
        """mayor→X+1.0.0, minor→x.Y+1.0, patch→x.y.Z+1. Klaim jenis tak boleh bohong."""
        for baru, lama in zip(v.RILIS, v.RILIS[1:]):
            (bma, bmi, bpa), (lma, lmi, lpa) = baru.nomor, lama.nomor
            if baru.jenis == v.MAYOR:
                harusnya = (lma + 1, 0, 0)
            elif baru.jenis == v.PATCH:
                harusnya = (lma, lmi, lpa + 1)
            else:  # minor & pra-rilis sama-sama menaikkan komponen tengah
                harusnya = (lma, lmi + 1, 0)
            self.assertEqual(
                (bma, bmi, bpa), harusnya,
                f"v{baru.versi} mengaku '{baru.jenis}' setelah v{lama.versi}, "
                f"seharusnya bernomor {'.'.join(map(str, harusnya))}",
            )

    def test_pra_rilis_hanya_di_nol_x(self):
        for r in v.RILIS:
            if r.jenis == v.PRA_RILIS:
                self.assertEqual(r.nomor[0], 0, f"v{r.versi}: pra-rilis harus di seri 0.x")
            else:
                self.assertGreaterEqual(r.nomor[0], 1, f"v{r.versi}: seri 0.x harus pra-rilis")

    def test_tepat_satu_rilis_mayor_pertama(self):
        """1.0.0 = cutover produksi 7 Juli 2026 — tonggak yang tak boleh hilang."""
        satu_nol = [r for r in v.RILIS if r.versi == "1.0.0"]
        self.assertEqual(len(satu_nol), 1)
        self.assertEqual(satu_nol[0].jenis, v.MAYOR)


class HelperTests(TestCase):
    def test_versi_menunjuk_rilis_teratas(self):
        self.assertEqual(v.versi(), v.RILIS[0].versi)
        self.assertEqual(v.rilis_terbaru(), v.RILIS[0])

    def test_ringkasan_jumlah_menjumlah_seluruh_rilis(self):
        n = v.ringkasan_jumlah()
        self.assertEqual(sum(n.values()), len(v.RILIS))

    def test_tanggal_id_berbahasa_indonesia(self):
        r = v.RILIS[0]
        self.assertIn(v.BULAN_ID[r.tanggal.month], r.tanggal_id)
        self.assertIn(str(r.tanggal.year), r.tanggal_id)


class ChangelogTests(TestCase):
    """CHANGELOG.md wajib = hasil render RILIS, tanpa kecuali."""

    def setUp(self):
        self.path = Path(settings.BASE_DIR) / "CHANGELOG.md"

    def test_berkas_ada_dan_sinkron(self):
        self.assertTrue(self.path.exists(), "CHANGELOG.md belum dibuat")
        self.assertEqual(
            self.path.read_text(encoding="utf-8"),
            v.changelog_markdown(),
            "CHANGELOG.md melenceng — jalankan `python manage.py changelog`",
        )

    def test_perintah_cek_lolos(self):
        call_command("changelog", "--cek")

    def test_perintah_cek_menjerit_saat_melenceng(self):
        asli = self.path.read_text(encoding="utf-8")
        try:
            self.path.write_text(asli + "\nbaris siluman\n", encoding="utf-8")
            with self.assertRaises(CommandError):
                call_command("changelog", "--cek")
        finally:
            self.path.write_text(asli, encoding="utf-8")

    def test_render_memuat_tiap_rilis(self):
        md = v.changelog_markdown()
        for r in v.RILIS:
            self.assertIn(f"## v{r.versi} — {r.nama}", md)
            for s in r.sorotan:
                self.assertIn(s, md)
