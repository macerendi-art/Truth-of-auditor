"""Produksi (DEBUG=False) tanpa env SECRET_KEY harus GAGAL CEPAT — jangan diam-diam
jalan memakai kunci default yang ter-commit di repo."""
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

BASE_DIR = Path(__file__).resolve().parent.parent


def _import_settings(extra_env):
    """Import truth_auditor.settings di subprocess bersih; return CompletedProcess."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("SECRET_KEY", "DEBUG", "DATABASE_URL")}
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", "import truth_auditor.settings"],
        env=env, capture_output=True, text=True, cwd=BASE_DIR, timeout=60,
    )


class SecretKeyGuardTests(SimpleTestCase):
    def test_prod_tanpa_secret_key_gagal_cepat(self):
        p = _import_settings({"DEBUG": "False"})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("SECRET_KEY", p.stderr)

    def test_prod_dengan_secret_key_jalan(self):
        p = _import_settings({"DEBUG": "False", "SECRET_KEY": "x" * 60})
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_dev_tanpa_secret_key_tetap_jalan(self):
        p = _import_settings({})  # DEBUG default True — fallback dev diperbolehkan
        self.assertEqual(p.returncode, 0, p.stderr)
