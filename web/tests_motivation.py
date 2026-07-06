from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import Toko
from web import quotes

User = get_user_model()


class QuotePoolTests(TestCase):
    def test_pool_cukup_besar_dan_valid(self):
        self.assertGreaterEqual(len(quotes.MOTIVATION), 150)
        for q in quotes.MOTIVATION:
            self.assertIsInstance(q, str)
            self.assertTrue(q.strip(), "kutipan kosong tidak boleh ada")

    def test_pool_tanpa_duplikat(self):
        norm = [q.strip().lower() for q in quotes.MOTIVATION]
        self.assertEqual(len(norm), len(set(norm)), "ada kutipan duplikat")

    def test_random_quote_dari_pool(self):
        q = quotes.random_quote()
        self.assertIn(q, quotes.MOTIVATION)


class MotivationProcessorTests(TestCase):
    def test_context_menyediakan_kutipan(self):
        from web.context_processors import motivation

        req = type("R", (), {})()
        ctx = motivation(req)
        self.assertIn("motivation_quote", ctx)
        self.assertIn(ctx["motivation_quote"], quotes.MOTIVATION)


class ToastRenderTests(TestCase):
    def setUp(self):
        User.objects.create_user("admtoast", password="pw123456", role="supervisor")
        self.toko = Toko.objects.get(key="lbs")

    def test_toast_muncul_di_halaman_kerja(self):
        self.client.login(username="admtoast", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})
        # Muat pertama mengonsumsi pop-up pengingat toko (muncul sekali setelah login).
        self.client.get(reverse("dashboard"))
        # Muat berikutnya: pengingat sudah lewat, toast motivasi tampil.
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, 'id="motivToast"')

    def test_toast_tidak_muncul_bersama_modal_pengingat(self):
        # follow login => show_toko_reminder aktif (modal pengingat toko tampil)
        r = self.client.post(
            reverse("login"),
            {"username": "admtoast", "password": "pw123456"},
            follow=True,
        )
        self.assertContains(r, "Pastikan toko aktif sudah tepat")  # modal ada
        self.assertNotContains(r, 'id="motivToast"')               # toast ditahan
