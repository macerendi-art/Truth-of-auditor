"""Berkas yang jenisnya tak terdeteksi harus BILANG tak terdeteksi.

Cacat yang ditutup di sini: `_analyze_file` mengembalikan `parser_key=""`
saat `detect_source` tak cocok satu aturan pun, dan template lama merender
`{% if pk == p.parser_key %}selected{% endif %}` sehingga TAK ADA opsi yang
terpilih — peramban lalu menampilkan opsi PERTAMA `sorted(PARSERS)`, yaitu
`bca_csv`. "Saya tidak tahu berkas ini apa" tampil sebagai tebakan yang
terlihat yakin, dan sekali Simpan ditekan berkasnya benar-benar diingest
sebagai `bca_csv`. Kelas yang sama dengan kegagalan senyap QRIS Flyer:
kegagalan yang menyamar jadi keberhasilan.

Paruh keduanya sama pentingnya: cabang commit dulu hanya menaikkan `n_err`
tanpa satu pun pesan, sehingga pemakai melihat "0 file diproses, 1 gagal"
tanpa sebab. Perintah yang menolak harus berisik soal apa yang ditolaknya.
"""
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from sources.models import Toko, Upload
from transactions.models import Transaction

# Header yang sengaja tak cocok satu aturan `detect_source` pun.
ASING = b"kolom_a,kolom_b,kolom_c\n1,2,3\n"
# xlsx terenkripsi dikenali dari 8 byte pertama (OLE2/CDFV2), bukan isinya.
OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32


class _Masuk(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def _analyze(self, nama, isi, tipe="text/csv"):
        f = SimpleUploadedFile(nama, isi, content_type=tipe)
        return self.client.post(reverse("upload"),
                                {"action": "analyze", "files": [f]})


class PratinjauJenisTests(_Masuk):
    def test_placeholder_terpilih_saat_tak_terdeteksi(self):
        r = self._analyze("entahapa.csv", ASING)

        self.assertEqual(r.context["preview"][0]["parser_key"], "")
        html = r.content.decode()
        self.assertIn('value="" selected disabled', html)
        self.assertIn("tidak terdeteksi", html)
        # Inti cacatnya: opsi pertama TIDAK boleh tampil sebagai pilihan.
        self.assertNotIn('value="bca_csv" selected', html)

    def test_placeholder_absen_saat_terdeteksi(self):
        """Placeholder tak boleh bocor ke baris yang deteksinya yakin."""
        r = self._analyze("bri.csv", b"TGL_TRAN,MUTASI_DEBET,MUTASI_KREDIT\n")

        html = r.content.decode()
        self.assertEqual(r.context["preview"][0]["parser_key"], "bri")
        self.assertNotIn('value="" selected disabled', html)
        self.assertIn('value="bri" selected', html)

    def test_select_wajib_diisi(self):
        """`required` yang membuat peramban menolak submit selama placeholder
        (satu-satunya opsi terpilih, dan ia `disabled`) masih terpilih.
        Kelas `parser-pick` memicu combobox + kotak cari di klien."""
        r = self._analyze("entahapa.csv", ASING)

        html = r.content.decode()
        self.assertIn('name="parser_key"', html)
        self.assertIn("parser-pick", html)
        self.assertIn("required", html)
        # Select masih ada (fallback no-JS); enhancement murni klien via toko-picker.js
        self.assertIn("<select", html)

    def test_combobox_cari_jenis_terpasang(self):
        """Wiring: skrip combobox global + kelas parser-pick di preview."""
        r = self._analyze("entahapa.csv", ASING)
        html = r.content.decode()
        self.assertIn("toko-picker.js", html)
        self.assertIn('class="f parser-pick"', html)
        # Placeholder deteksi gagal tetap di markup server
        self.assertIn('value="" selected disabled', html)
        # CSS sel tabel untuk combobox jenis (app_base)
        self.assertIn("td .tp-host.tp-field", html)

    def test_badge_menggantikan_nol_persen(self):
        r = self._analyze("entahapa.csv", ASING)

        html = r.content.decode()
        self.assertIn("tidak terdeteksi", html)
        self.assertNotIn("0% — cek", html)

    def test_password_terkunci_tetap_jatuh_ke_mandiri(self):
        """Non-regresi: xlsx terkunci tak terdeteksi isinya (masih terenkripsi),
        tapi `_analyze_file` sengaja menjatuhkannya ke `mandiri`. Jalur itu
        harus selamat — kalau tidak, e-statement Mandiri ikut kena placeholder."""
        r = self._analyze("mutasi.xlsx", OLE2,
                          tipe="application/vnd.ms-excel")

        p = r.context["preview"][0]
        self.assertEqual(p["parser_key"], "mandiri")
        self.assertTrue(p["needs_password"])
        self.assertNotIn('value="" selected disabled', r.content.decode())


class CommitJenisTests(_Masuk):
    def _commit(self, key):
        staged = default_storage.save("staging/x.csv", ContentFile(ASING))
        return self.client.post(reverse("upload"), {
            "action": "commit", "staged": [staged], "parser_key": [key],
            "flow": [""], "orig_name": ["laporan-aneh.csv"], "provider": "",
        }, follow=True)

    def test_commit_jenis_kosong_ditolak_dan_bersuara(self):
        r = self._commit("")

        self.assertEqual(Upload.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)
        pesan = [str(m) for m in r.context["messages"]]
        self.assertTrue(any("laporan-aneh.csv" in p and "belum dipilih" in p
                            for p in pesan), pesan)

    def test_commit_jenis_asing_ditolak_dan_bersuara(self):
        r = self._commit("tidak_ada")

        self.assertEqual(Upload.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)
        pesan = [str(m) for m in r.context["messages"]]
        self.assertTrue(any("laporan-aneh.csv" in p and "tidak_ada" in p
                            for p in pesan), pesan)
