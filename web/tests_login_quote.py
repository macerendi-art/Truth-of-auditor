"""Rotasi tagline pada halaman login (FITUR I4).

Tagline profesional soal rekonsiliasi/ketelitian dipilih acak server-side per
GET halaman login, disisipkan ke context (`login_tagline`) dan dirender di
kartu login. Daftar dijaga terpisah dari pool MOTIVATION toast agar tidak saling
mengganggu.
"""
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from web import quotes


class LoginTaglinePoolTests(TestCase):
    def test_pool_ukuran_wajar(self):
        # Klien minta 8-12 tagline terkurasi.
        self.assertGreaterEqual(len(quotes.LOGIN_TAGLINES), 8)
        self.assertLessEqual(len(quotes.LOGIN_TAGLINES), 16)

    def test_pool_valid_dan_tanpa_duplikat(self):
        for q in quotes.LOGIN_TAGLINES:
            self.assertIsInstance(q, str)
            self.assertTrue(q.strip(), "tagline kosong tidak boleh ada")
        norm = [q.strip().lower() for q in quotes.LOGIN_TAGLINES]
        self.assertEqual(len(norm), len(set(norm)), "ada tagline duplikat")

    def test_tanpa_emoji(self):
        # Elegan/profesional: tidak ada emoji-as-icon. Tanda baca tipografis
        # (mis. em dash U+2014) tetap boleh; yang dilarang blok simbol/emoji
        # (misc symbols & dingbats 0x2600+ hingga bidang emoji).
        for q in quotes.LOGIN_TAGLINES:
            for ch in q:
                self.assertLess(
                    ord(ch), 0x2600, f"karakter mencurigakan (emoji?) di: {q!r}"
                )

    def test_random_login_tagline_dari_pool(self):
        for _ in range(30):
            self.assertIn(quotes.random_login_tagline(), quotes.LOGIN_TAGLINES)

    def test_random_login_tagline_pakai_choice(self):
        with mock.patch(
            "web.quotes.random.choice", return_value=quotes.LOGIN_TAGLINES[0]
        ) as m:
            self.assertEqual(quotes.random_login_tagline(), quotes.LOGIN_TAGLINES[0])
            m.assert_called_once_with(quotes.LOGIN_TAGLINES)


class LoginTaglineRenderTests(TestCase):
    def test_halaman_login_200_dan_form_ada(self):
        r = self.client.get(reverse("login"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'name="username"')
        self.assertContains(r, 'name="password"')
        self.assertContains(r, "<form method=\"post\">")

    def test_context_memuat_tagline_dari_pool(self):
        r = self.client.get(reverse("login"))
        self.assertIn("login_tagline", r.context)
        self.assertIn(r.context["login_tagline"], quotes.LOGIN_TAGLINES)

    def test_tagline_terpilih_dirender(self):
        pilihan = quotes.LOGIN_TAGLINES[1]
        with mock.patch("web.views.random_login_tagline", return_value=pilihan):
            r = self.client.get(reverse("login"))
        self.assertContains(r, pilihan)

    def test_dua_render_bisa_beda(self):
        a, b = quotes.LOGIN_TAGLINES[0], quotes.LOGIN_TAGLINES[-1]
        self.assertNotEqual(a, b)
        with mock.patch("web.views.random_login_tagline", side_effect=[a, b]):
            r1 = self.client.get(reverse("login"))
            r2 = self.client.get(reverse("login"))
        self.assertEqual(r1.context["login_tagline"], a)
        self.assertEqual(r2.context["login_tagline"], b)

    def test_hero_kinetik_tidak_terganggu(self):
        # Wordmark partikel & h1 .kin harus utuh (rotasi hanya di .sub).
        r = self.client.get(reverse("login"))
        self.assertContains(r, "TRUTH OF AUDITOR")
        self.assertContains(r, 'class="kin"')
