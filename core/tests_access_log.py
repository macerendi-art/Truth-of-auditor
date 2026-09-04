"""B3 (Gelombang 1, 04-09-2026): log akses gunicorn.

`core/tests_start_command.py` sudah menjaga Procfile ↔ railway.json identik
dan aritmetika workers×threads — modul TERPISAH ini (bukan menambah ke
berkas itu, di luar wewenang tulis eksklusif gelombang ini) menjaga butir B3
sendiri: tanpa `--access-logfile -`, gunicorn TIDAK mencatat satu baris pun
permintaan HTTP yang masuk (akses log mati total, hanya error yang tampak).
Juga menjaga `--access-logformat` (bila ada) TIDAK memuat token request-line
mentah `%(r)s` — itu menyertakan query string, yang bisa memuat data (mis.
`?q=<nama pemain>`) yang tak seharusnya menetap di log teks polos.
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


def _normalisasi(perintah: str) -> str:
    perintah = perintah.replace("\\\n", " ")
    return " ".join(perintah.split())


class _BacaPerintahMixin:
    def setUp(self):
        akar = Path(settings.BASE_DIR)
        procfile = (akar / "Procfile").read_text(encoding="utf-8")
        for baris in procfile.replace("\\\n", " ").splitlines():
            if baris.strip().startswith("web:"):
                self.cmd_procfile = _normalisasi(baris.strip()[len("web:"):])
                break
        else:
            self.fail("Procfile tidak punya proses `web:`")

        data = json.loads((akar / "railway.json").read_text(encoding="utf-8"))
        self.cmd_railway = _normalisasi(data["deploy"]["startCommand"])


class AccessLogTests(_BacaPerintahMixin, SimpleTestCase):
    def test_access_logfile_stdout_di_kedua_berkas(self):
        for label, perintah in (("Procfile", self.cmd_procfile), ("railway.json", self.cmd_railway)):
            with self.subTest(berkas=label):
                self.assertIn(
                    "--access-logfile -",
                    perintah,
                    f"[{label}] tanpa --access-logfile, gunicorn tak mencatat satu baris "
                    "pun permintaan HTTP — hanya error yang terlihat di log.",
                )

    def test_access_logformat_tidak_memuat_request_line_mentah(self):
        # %(r)s = "GET /path?query HTTP/1.1" APA ADANYA, termasuk query
        # string. Kalau formatnya diubah, jangan sampai token itu ikut.
        for label, perintah in (("Procfile", self.cmd_procfile), ("railway.json", self.cmd_railway)):
            with self.subTest(berkas=label):
                cocok = re.search(r"--access-logformat[ =]'([^']*)'", perintah)
                if cocok is None:
                    continue  # format default gunicorn dipakai — tak ada token custom untuk diperiksa
                fmt = cocok.group(1)
                self.assertNotIn(
                    "%(r)s",
                    fmt,
                    f"[{label}] --access-logformat memuat %(r)s (request line mentah, "
                    "termasuk query string) — pakai %(m)s/%(U)s/%(H)s untuk method/path/"
                    "protokol tanpa query string.",
                )

    def test_access_logformat_menyertakan_waktu_respons_bila_diset(self):
        for label, perintah in (("Procfile", self.cmd_procfile), ("railway.json", self.cmd_railway)):
            with self.subTest(berkas=label):
                cocok = re.search(r"--access-logformat[ =]'([^']*)'", perintah)
                if cocok is None:
                    continue
                fmt = cocok.group(1)
                self.assertTrue(
                    any(tok in fmt for tok in ("%(L)s", "%(D)s", "%(T)s")),
                    f"[{label}] --access-logformat custom sebaiknya menyertakan waktu "
                    "respons (%(L)s/%(D)s/%(T)s) — itulah nilai tambah utama format kustom.",
                )
