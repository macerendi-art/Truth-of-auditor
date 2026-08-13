"""Penjaga perintah start produksi (`Procfile` + `railway.json`).

Perintah start hidup di DUA berkas dengan isi yang WAJIB identik: `Procfile`
(dipakai Nixpacks/Heroku-style) dan `railway.json` → `deploy.startCommand`.
Sampai modul ini ada, tak satu pun tes menjaga kembarannya — kalau nanti hanya
salah satu yang diubah, produksi memakai satu nilai sementara berkas yang lain
"mendokumentasikan" nilai lain, dan tak ada yang berteriak.

Aritmetika kapasitas yang dijaga tes kedua
------------------------------------------
Gunicorn dijalankan dengan `--worker-class gthread`. Django menyimpan koneksi
database **per thread** (thread-local), dan `conn_max_age=600`
(`truth_auditor/settings.py`) membuat tiap thread MENAHAN koneksinya selama 600
detik. Jadi batas atas koneksi persisten bukan jumlah worker, melainkan:

    koneksi persisten worst-case = workers × threads

Konfigurasi saat ini 4 × 8 = **32** koneksi, ditambah ~1 (migrate saat boot),
~2 (sesi psql operasional) dan 3 (`superuser_reserved_connections`) = **38 dari
`max_connections=100`**. Margin 62.

Kontainer web berjatah 24 CPU / 24 GB dan dengan 2 worker hanya memakai 283 MB,
jadi memori bukan kendala — databaselah kendalanya. Karena itu 8 worker × 8
thread (= 70/100) sengaja DITOLAK sebagai terlalu ketat, dan 12 × 8 = 96 +
overhead ≈ 100 berarti database mulai menolak koneksi.

Tes di bawah menerjemahkan aritmetika itu jadi pagar yang DIEKSEKUSI, bukan
komentar yang bisa basi diam-diam.
"""

import json
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

# Ambang konservatif: 10 slot disisihkan untuk migrate saat boot, sesi psql
# operasional, dan superuser_reserved_connections.
MAX_CONNECTIONS = 100
CADANGAN = 10


def _normalisasi(perintah: str) -> str:
    """Rapikan perintah shell supaya dua berkas bisa dibandingkan apa adanya.

    Menyambung kelanjutan baris (`\\` di ujung baris) dan meratakan setiap
    rentetan spasi/tab/newline jadi satu spasi. Perlakuannya sama untuk kedua
    sisi, jadi normalisasi ini tidak bisa menyembunyikan perbedaan isi.
    """
    perintah = perintah.replace("\\\n", " ")
    return " ".join(perintah.split())


class PerintahStartTests(SimpleTestCase):
    """Tak butuh DB — semuanya membaca berkas di akar repo."""

    def setUp(self):
        akar = Path(settings.BASE_DIR)
        self.procfile_path = akar / "Procfile"
        self.railway_path = akar / "railway.json"
        self.assertTrue(self.procfile_path.exists(), "Procfile tidak ditemukan")
        self.assertTrue(self.railway_path.exists(), "railway.json tidak ditemukan")

        self.cmd_procfile = self._baca_procfile()
        self.cmd_railway = self._baca_railway()

    def _baca_procfile(self) -> str:
        isi = self.procfile_path.read_text(encoding="utf-8")
        # Sambung dulu kelanjutan baris, baru cari proses `web:` — kalau tidak,
        # baris lanjutan bisa terbaca sebagai proses tersendiri.
        for baris in isi.replace("\\\n", " ").splitlines():
            if baris.strip().startswith("web:"):
                return _normalisasi(baris.strip()[len("web:"):])
        self.fail("Procfile tidak punya proses `web:`")

    def _baca_railway(self) -> str:
        data = json.loads(self.railway_path.read_text(encoding="utf-8"))
        perintah = data.get("deploy", {}).get("startCommand")
        self.assertIsNotNone(perintah, "railway.json tidak punya deploy.startCommand")
        return _normalisasi(perintah)

    def _angka(self, perintah: str, bendera: str) -> int:
        cocok = re.search(rf"--{bendera}[ =](\d+)", perintah)
        self.assertIsNotNone(cocok, f"perintah start tidak menyebut --{bendera}: {perintah}")
        return int(cocok.group(1))

    # -- 1. dua berkas, satu kebenaran -----------------------------------

    def test_procfile_dan_railway_json_perintah_identik(self):
        self.assertEqual(
            self.cmd_procfile,
            self.cmd_railway,
            "Perintah start di Procfile dan railway.json BERBEDA. Keduanya harus "
            "diubah bersamaan — kalau tidak, produksi menjalankan satu nilai "
            "sementara berkas yang lain mengaku nilai lain.\n"
            f"  Procfile     : {self.cmd_procfile}\n"
            f"  railway.json : {self.cmd_railway}",
        )

    # -- 2. kapasitas koneksi database -----------------------------------

    def test_koneksi_worst_case_di_bawah_max_connections(self):
        """workers × threads + cadangan harus muat di `max_connections`.

        Diperiksa pada KEDUA perintah secara terpisah, supaya pagar ini tetap
        berbunyi walau tes identik-nya sedang merah karena sebab lain.
        """
        for label, perintah in (
            ("Procfile", self.cmd_procfile),
            ("railway.json", self.cmd_railway),
        ):
            with self.subTest(berkas=label):
                workers = self._angka(perintah, "workers")
                threads = self._angka(perintah, "threads")
                dipakai = workers * threads + CADANGAN
                self.assertLessEqual(
                    dipakai,
                    MAX_CONNECTIONS,
                    f"[{label}] {workers} worker × {threads} thread = "
                    f"{workers * threads} koneksi persisten, + {CADANGAN} cadangan "
                    f"= {dipakai}, MELEBIHI max_connections={MAX_CONNECTIONS}. "
                    "gthread menyimpan koneksi Django per THREAD (thread-local) dan "
                    "conn_max_age=600 di truth_auditor/settings.py membuat tiap thread "
                    "menahannya 600 detik, jadi batas atasnya workers×threads — bukan "
                    "jumlah worker. Cadangan 10 = migrate saat boot + sesi psql "
                    "operasional + superuser_reserved_connections. Lewat ambang ini "
                    "database mulai MENOLAK koneksi dan aplikasi mati, bukan melambat.",
                )

    # -- 3. urutan tahap boot --------------------------------------------

    def test_urutan_perintah_start_tetap(self):
        """collectstatic → migrate → gunicorn.

        Migrasi index bergantung pada urutan ini: skema harus sudah naik
        sebelum gunicorn menerima permintaan.
        """
        for label, perintah in (
            ("Procfile", self.cmd_procfile),
            ("railway.json", self.cmd_railway),
        ):
            with self.subTest(berkas=label):
                posisi = {}
                for tahap in ("collectstatic", "migrate", "gunicorn"):
                    self.assertIn(tahap, perintah, f"[{label}] tahap `{tahap}` hilang dari perintah start")
                    posisi[tahap] = perintah.index(tahap)
                self.assertLess(
                    posisi["collectstatic"],
                    posisi["migrate"],
                    f"[{label}] collectstatic harus dijalankan SEBELUM migrate",
                )
                self.assertLess(
                    posisi["migrate"],
                    posisi["gunicorn"],
                    f"[{label}] migrate harus selesai SEBELUM gunicorn melayani permintaan",
                )
