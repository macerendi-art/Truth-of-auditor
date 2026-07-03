from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import Toko

User = get_user_model()

PENGINGAT_TEXT = "Pastikan toko aktif sudah tepat"


class LoginPopupTests(TestCase):
    def setUp(self):
        User.objects.create_user("audpopup", password="pw123456", role="supervisor")

    def test_popup_muncul_sekali_setelah_login(self):
        r = self.client.post(
            reverse("login"),
            {"username": "audpopup", "password": "pw123456"},
            follow=True,
        )
        self.assertContains(r, PENGINGAT_TEXT)
        self.assertContains(r, "Sendy Auditor")
        self.assertContains(r, "Pak Bertus DM")
        self.assertContains(r, "https://checkerboard.online/")
        self.assertContains(r, "https://draw-to-data-magic.lovable.app/app")

    def test_popup_tidak_muncul_lagi_di_get_kedua(self):
        self.client.post(
            reverse("login"),
            {"username": "audpopup", "password": "pw123456"},
            follow=True,
        )
        r = self.client.get(reverse("dashboard"))
        self.assertNotContains(r, PENGINGAT_TEXT)

    def test_user_tanpa_toko_tidak_error(self):
        User.objects.create_user("audnotoko", password="pw123456", role="auditor")
        # role auditor tanpa assigned_users -> tokos_for() kosong -> no_toko.html
        self.client.post(
            reverse("login"),
            {"username": "audnotoko", "password": "pw123456"},
            follow=True,
        )
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
