"""A2: `MEDIA_ROOT` harus bisa diatur lewat env, dengan default PERSIS perilaku
lama (`BASE_DIR / 'media'`) — supaya dev lokal dan seluruh suite tak berubah
sedikit pun sampai pemilik benar-benar men-set env di produksi.

Latar: `sources/models.py` `Upload.file` adalah `FileField` di atas
`MEDIA_ROOT`, dan disk kontainer Railway (`web`, tanpa volume terpasang)
terhapus tiap deploy. Lihat `docs/runbook-media-volume-2026-09-04.md`.

Dua tes pertama memakai pola subprocess `core/tests_settings_guard.py` (import
`truth_auditor.settings` di proses BERSIH) — bukan `importlib.reload` di proses
tes, supaya modul settings yang diuji benar-benar dibaca ulang dari env, bukan
sekadar mengevaluasi ekspresi yang sama dua kali. Tes ketiga (FileField
sungguhan menulis di bawah `MEDIA_ROOT`) memakai `override_settings` di
proses tes ini sendiri karena `FileSystemStorage` bawaan Django membaca ulang
`MEDIA_ROOT` tiap `setting_changed` — tak perlu subprocess untuk itu.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase, override_settings

from sources.models import SourceType, Upload

BASE_DIR = Path(__file__).resolve().parent.parent


def _import_settings(extra_env):
    """Import truth_auditor.settings di subprocess bersih; return CompletedProcess.

    Mencetak `settings.MEDIA_ROOT` ke stdout supaya bisa diperiksa persis apa
    yang benar-benar diresolusi modul settings, bukan diasumsikan.
    """
    env = {k: v for k, v in os.environ.items() if k != "MEDIA_ROOT"}
    env.update(extra_env)
    kode = (
        "import truth_auditor.settings as s; "
        "print(str(s.MEDIA_ROOT)); "
        "print(type(s.MEDIA_ROOT).__name__)"
    )
    return subprocess.run(
        [sys.executable, "-c", kode],
        env=env, capture_output=True, text=True, cwd=BASE_DIR, timeout=60,
    )


class MediaRootEnvTests(SimpleTestCase):
    """(a) tanpa env → path lama persis; (b) dengan env → path baru dipakai."""

    def test_tanpa_env_media_root_persis_base_dir_media(self):
        p = _import_settings({})
        self.assertEqual(p.returncode, 0, p.stderr)
        stdout_lines = p.stdout.strip().splitlines()
        nilai, tipe = stdout_lines[-2], stdout_lines[-1]
        self.assertEqual(nilai, str(BASE_DIR / "media"))
        self.assertEqual(tipe, "PosixPath" if os.name != "nt" else "WindowsPath")

    def test_dengan_env_media_root_dipakai(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "data-volume")
            p = _import_settings({"MEDIA_ROOT": target})
            self.assertEqual(p.returncode, 0, p.stderr)
            stdout_lines = p.stdout.strip().splitlines()
            nilai = stdout_lines[-2]
            self.assertEqual(nilai, target)
            # Bukan default lama — pastikan env benar-benar mengganti, bukan diabaikan.
            self.assertNotEqual(nilai, str(BASE_DIR / "media"))

    def test_env_string_kosong_jatuh_ke_default(self):
        # Railway bisa menyuntik variabel kosong-string, bukan cuma tak-ada —
        # `or` di settings.py (bukan `.get(..., default)` polos) harus
        # menangkap ini juga, sama seperti default lama.
        p = _import_settings({"MEDIA_ROOT": ""})
        self.assertEqual(p.returncode, 0, p.stderr)
        stdout_lines = p.stdout.strip().splitlines()
        nilai = stdout_lines[-2]
        self.assertEqual(nilai, str(BASE_DIR / "media"))


class MediaRootFileFieldTests(TestCase):
    """`FileField` (`Upload.file`) benar-benar menulis DI BAWAH `MEDIA_ROOT` —
    bukan cuma bahwa `settings.MEDIA_ROOT` berubah nilai.

    Catatan tegas: produksi hari ini TIDAK PERNAH mengisi `Upload.file` — lihat
    `docs/runbook-media-volume-2026-09-04.md` bagian "Konsekuensi berkas yang
    sudah hilang". Tes ini membuktikan kesiapan `FileField` seandainya field
    itu suatu hari diisi, bukan bahwa ia sudah dipakai sekarang.
    """

    def setUp(self):
        self.st = SourceType.objects.create(key="panel_uji_media", name="Panel Uji")

    def test_filefield_menulis_di_bawah_media_root_kustom(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(MEDIA_ROOT=tmp):
                up = Upload.objects.create(
                    source_type=self.st,
                    file=ContentFile(b"isi-uji", name="contoh.csv"),
                )
                self.assertTrue(up.file.name)
                disk_path = Path(up.file.path)
                self.assertTrue(str(disk_path).startswith(str(Path(tmp))))
                self.assertTrue(disk_path.exists())
                self.assertEqual(disk_path.read_bytes(), b"isi-uji")
