"""Penjaga veto pemilik (04-09-2026): `COPY ... FROM PROGRAM` DICABUT dari
`scripts/pemantauan/` dan tidak boleh kembali.

Butir B1 (commit `120e61c`/`8bcb2e1`) sempat memasang
`COPY dfout FROM PROGRAM 'df -kP ...'` di `periksa-kesehatan-terjadwal.sh`
untuk membaca sisa disk PRODUKSI lewat superuser Postgres. Itu primitif
eksekusi-KODE permanen terhadap host database produksi, dipasang di dalam
skrip pemantauan yang berjalan HARIAN, sementara kredensial proxy yang
dipakainya masih menunggu rotasi (butir A3). Agen yang memasangnya sendiri
mengajukannya sebagai keputusan yang bisa di-veto — **pemilik memveto**.
Diganti dengan `pg_database_size(current_database())`, satu SELECT biasa
tanpa superuser/COPY/PROGRAM.

Tes ini membaca berkas TEKS apa adanya (tak menjalankan skrip apa pun — tak
ada SSH, tak ada psql sungguhan, tak ada koneksi produksi) dan sengaja
SADAR-KOMENTAR: baris komentar (`#...`, sintaks yang sama di shell maupun
unit systemd) BOLEH menyebut kata "program" untuk menjelaskan sejarah/veto
ini, tapi kode yang BENAR-BENAR DIEKSEKUSI tidak boleh. Tanpa kesadaran-
komentar ini, tes akan false-positive terhadap komentar yang justru
mendokumentasikan KENAPA `COPY FROM PROGRAM` dilarang."""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

PEMANTAUAN_DIR = Path(settings.BASE_DIR) / "scripts" / "pemantauan"


def _kode_tanpa_komentar(path: Path) -> str:
    """Isi berkas TANPA baris yang diawali `#` (komentar shell & unit systemd)."""
    baris_kode = [
        baris for baris in path.read_text(encoding="utf-8").splitlines()
        if not baris.strip().startswith("#")
    ]
    return "\n".join(baris_kode)


class TidakAdaEksekusiKodeProduksiTests(SimpleTestCase):
    """Tak butuh DB — semuanya membaca berkas apa adanya di `scripts/pemantauan/`."""

    def setUp(self):
        self.assertTrue(PEMANTAUAN_DIR.is_dir(), f"{PEMANTAUAN_DIR} tidak ditemukan")
        self.berkas = sorted(p for p in PEMANTAUAN_DIR.iterdir() if p.is_file())
        self.assertTrue(self.berkas, "scripts/pemantauan/ kosong — tes ini tak menguji apa pun")

    def test_tidak_ada_program_di_kode_yang_dieksekusi(self):
        for path in self.berkas:
            with self.subTest(berkas=path.name):
                kode = _kode_tanpa_komentar(path).lower()
                self.assertNotIn(
                    "program",
                    kode,
                    f"[{path.name}] kode yang DIEKSEKUSI (bukan komentar) masih "
                    "menyebut 'program' -- kemungkinan `COPY ... FROM PROGRAM` "
                    "kembali dipasang. Itu DIVETO pemilik 04-09-2026: primitif "
                    "eksekusi-shell permanen terhadap host database produksi di "
                    "dalam skrip pemantauan harian tidak boleh dipasang lagi, "
                    "terlepas alasannya (lihat komentar kepala "
                    "periksa-kesehatan-terjadwal.sh).",
                )

    def test_periksa_kesehatan_pakai_pg_database_size(self):
        """Pengganti positif -- bukan cuma "tidak ada COPY", tapi "ADA gantinya"."""
        isi = (PEMANTAUAN_DIR / "periksa-kesehatan-terjadwal.sh").read_text(encoding="utf-8")
        self.assertIn(
            "pg_database_size(current_database())",
            isi,
            "periksa-kesehatan-terjadwal.sh harus mengukur ukuran DB produksi "
            "lewat pg_database_size (SELECT biasa, bukan superuser) sebagai "
            "pengganti COPY FROM PROGRAM.",
        )
