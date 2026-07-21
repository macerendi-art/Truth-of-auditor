"""Higiene template — penjaga kelas bug "{# #} multi-baris".

Komentar {# #} Django HANYA berlaku satu baris. Versi multi-baris tidak
di-tokenisasi (regex lexer tanpa DOTALL) sehingga bocor sebagai teks halaman.
Insiden nyata: Paket G (rekening.html) dan Paket I (base/app_base — teks
komentar memuat kata literal "<template>" yang jadi tag sungguhan dan MENELAN
seluruh body: semua halaman blank di browser, padahal suite hijau karena
assertContains membaca HTML mentah).
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase


class KomentarMultiBarisTests(SimpleTestCase):
    def test_tidak_ada_komentar_kurung_multibaris_di_sumber(self):
        # Heuristik: "{# " (dengan spasi) tanpa "#}" di baris yang sama =
        # komentar Django yang tak tertutup di baris itu. Selector CSS di
        # media-query satu baris ("){#preloader{...") tidak berspasi sehingga
        # tidak kena.
        pelanggaran = []
        akar = Path(settings.BASE_DIR)
        for pola in ("web/templates/**/*.html", "accounts/templates/**/*.html"):
            for f in akar.glob(pola):
                for i, baris in enumerate(
                        f.read_text(encoding="utf-8").splitlines(), 1):
                    if "{# " in baris and "#}" not in baris:
                        pelanggaran.append(f"{f.relative_to(akar)}:{i}")
        self.assertEqual(
            pelanggaran, [],
            "Komentar {# #} multi-baris bocor ke render — pakai "
            "{% comment %}...{% endcomment %}: " + ", ".join(pelanggaran))


class RenderBersihTests(TestCase):
    def test_halaman_login_tanpa_bocoran_komentar(self):
        resp = self.client.get("/login/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "{# ")
        # Form login harus benar-benar ada di body (bukan tertelan artefak).
        self.assertContains(resp, 'name="username"')
        self.assertContains(resp, 'name="password"')
