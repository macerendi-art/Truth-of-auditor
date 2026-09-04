"""Penjaga pola "tukar-setelah-terbukti" di `scripts/cadangan/backup-harian.sh`.

Versi lama menjalankan `rm -rf "$DUMPDIR"` tepat SEBELUM `pg_dump`. Karena nama
direktori berbasis tanggal (`dump-$STAMP`), menjalankan skrip dua kali dalam
satu hari menghancurkan salinan bagus **sebelum** penggantinya ada — sehingga
dump yang gagal di tengah meninggalkan hari itu tanpa cadangan sama sekali.
Terlihat langsung 04-09-2026: menjalankan ulang secara manual membuat direktori
dump hari itu kosong dan sedang dibangun ulang dari nol, sementara salinan
01-09 sudah lebih dulu terhapus retensi.

Perbaikannya: `pg_dump` menulis ke direktori KERJA (`.dump-$STAMP.partial`),
lalu ditukar ke `$DUMPDIR` hanya SETELAH `pg_restore -l` membuktikan arsipnya
terbaca. `mv` dalam satu filesystem = `rename(2)`, atomik.

Tes ini membaca berkas TEKS apa adanya — tidak menjalankan skrip apa pun, tidak
ber-SSH, tidak menyentuh produksi. Sengaja SADAR-KOMENTAR (pola sama dengan
`core/tests_pemantauan_program.py`): komentar BOLEH menyebut `rm -rf "$DUMPDIR"`
untuk menjelaskan sejarah ini, yang dilarang adalah kode yang dieksekusi.
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SKRIP = Path(settings.BASE_DIR) / "scripts" / "cadangan" / "backup-harian.sh"


def _baris_kode(path: Path) -> list[str]:
    """Baris yang BENAR-BENAR dieksekusi: buang komentar shell dan baris kosong."""
    out = []
    for baris in path.read_text(encoding="utf-8").splitlines():
        telanjang = baris.strip()
        if not telanjang or telanjang.startswith("#"):
            continue
        out.append(baris)
    return out


class CadanganTukarSetelahTerbuktiTests(SimpleTestCase):
    def setUp(self):
        self.assertTrue(SKRIP.is_file(), f"{SKRIP} hilang")
        self.kode = _baris_kode(SKRIP)
        self.teks_kode = "\n".join(self.kode)

    def test_pg_dump_menulis_ke_direktori_kerja_bukan_tujuan_akhir(self):
        """`pg_dump --file=` tidak boleh langsung menunjuk $DUMPDIR."""
        baris_dump = [b for b in self.kode if "--file=" in b]
        self.assertTrue(baris_dump, "tidak menemukan argumen --file= pada pg_dump")
        for b in baris_dump:
            self.assertIn(
                "$DUMPDIR_KERJA", b,
                "pg_dump harus menulis ke direktori KERJA; menulis langsung ke "
                "tujuan akhir mengembalikan cacat 'salinan bagus hancur sebelum "
                "penggantinya ada'",
            )

    def test_tujuan_akhir_tidak_dihapus_sebelum_pg_dump(self):
        """Urutan wajib: `rm -rf "$DUMPDIR"` hanya BOLEH sesudah pg_dump."""
        idx_dump = next(
            (i for i, b in enumerate(self.kode) if b.strip().startswith("if ! pg_dump")),
            None,
        )
        self.assertIsNotNone(idx_dump, "tidak menemukan pemanggilan pg_dump")
        for i, b in enumerate(self.kode[:idx_dump]):
            self.assertNotIn(
                'rm -rf "$DUMPDIR"', b,
                f"baris kode #{i} menghapus tujuan akhir SEBELUM pg_dump berjalan — "
                "itu cacat yang justru diperbaiki pola tukar-setelah-terbukti",
            )

    def test_penukaran_terjadi_setelah_toc_terbukti_terbaca(self):
        """`mv` ke tujuan akhir harus SESUDAH gerbang `pg_restore -l`."""
        idx_toc = next(
            (i for i, b in enumerate(self.kode) if "pg_restore -l" in b), None
        )
        idx_mv = next(
            (i for i, b in enumerate(self.kode)
             if 'mv "$DUMPDIR_KERJA" "$DUMPDIR"' in b), None
        )
        self.assertIsNotNone(idx_toc, "gerbang TOC (pg_restore -l) hilang")
        self.assertIsNotNone(idx_mv, "penukaran ke tujuan akhir hilang")
        self.assertLess(
            idx_toc, idx_mv,
            "penukaran mendahului gerbang TOC — arsip yang belum terbukti terbaca "
            "akan menggantikan salinan bagus",
        )

    def test_manifest_sha256_dibuat_setelah_penukaran(self):
        """Manifest merekam jalur relatif `dump-$STAMP/...`.

        Membuatnya dari direktori kerja menghasilkan jalur yang tidak cocok saat
        diverifikasi `sha256sum -c` — gagal senyap yang baru ketahuan saat orang
        benar-benar mencoba memulihkan.
        """
        idx_mv = next(
            (i for i, b in enumerate(self.kode)
             if 'mv "$DUMPDIR_KERJA" "$DUMPDIR"' in b), None
        )
        # Cari baris yang MEMBUAT manifest (redirect `> "$SHA_FILE"`), bukan yang
        # sekadar membacanya -- `tulis_status()` juga memuat `sha256sum "$SHA_FILE"`
        # dan letaknya jauh lebih awal, sehingga pencarian naif menunjuk baris salah.
        idx_sha = next(
            (i for i, b in enumerate(self.kode) if '> "$SHA_FILE"' in b), None
        )
        self.assertIsNotNone(idx_sha, "pembuatan manifest sha256 hilang")
        self.assertLess(idx_mv, idx_sha, "manifest dibuat sebelum penukaran")

    def test_kegagalan_tidak_menyentuh_salinan_terverifikasi(self):
        """`gagal()` membersihkan direktori KERJA, bukan tujuan akhir."""
        i_awal = next(
            (i for i, b in enumerate(self.kode) if b.strip().startswith("gagal()")), None
        )
        self.assertIsNotNone(i_awal, "fungsi gagal() hilang")
        badan = []
        for b in self.kode[i_awal + 1:]:
            if b.strip() == "}":
                break
            badan.append(b)
        gabung = "\n".join(badan)
        self.assertIn("$DUMPDIR_KERJA", gabung, "gagal() tidak membersihkan sisa kerja")
        self.assertNotIn(
            'rm -rf "$DUMPDIR"', gabung,
            "gagal() menghapus salinan terverifikasi — justru saat gagal itulah "
            "salinan kemarin paling dibutuhkan",
        )

    def test_direktori_kerja_tak_terjaring_pola_retensi(self):
        """Retensi menyapu `dump-*`; direktori kerja harus di luar pola itu."""
        baris = [b for b in self.kode if "DUMPDIR_KERJA=" in b]
        self.assertTrue(baris, "DUMPDIR_KERJA tidak didefinisikan")
        self.assertIn(
            "/.dump-", baris[0],
            "nama direktori kerja harus diawali titik; tanpa itu ia ikut terjaring "
            "`find -name 'dump-*'` milik retensi dan bisa terhapus saat berjalan",
        )
