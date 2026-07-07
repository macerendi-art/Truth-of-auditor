"""Kelola user harus memakai validator password Django penuh (bukan cuma panjang):
password umum / semua-angka ditolak saat BUAT user maupun RESET password."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import Toko

User = get_user_model()


class PasswordPolicyTests(TestCase):
    def setUp(self):
        User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.toko = Toko.objects.get(key="lbs")

    def _create(self, username, password):
        return self.client.post(reverse("kelola_user"), {
            "username": username, "password": password, "nama": "X",
            "role": "auditor", "tokos": [self.toko.id],
        }, follow=True)

    def test_password_umum_ditolak_saat_buat_user(self):
        self._create("tuti", "password")  # 8 char — lolos cek panjang, tapi umum
        self.assertFalse(User.objects.filter(username="tuti").exists())

    def test_password_semua_angka_ditolak_saat_buat_user(self):
        self._create("tati", "1234567890")
        self.assertFalse(User.objects.filter(username="tati").exists())

    def test_password_kuat_tetap_diterima(self):
        self._create("tino", "Audit-Kuat#77")
        self.assertTrue(User.objects.filter(username="tino").exists())

    def test_password_umum_ditolak_saat_reset(self):
        target = User.objects.create_user("resetme", password="Lama-Kuat#88", role="supervisor")
        self.client.post(reverse("kelola_user_edit", args=[target.pk]),
                         {"action": "reset_password", "password": "password"})
        target.refresh_from_db()
        self.assertTrue(target.check_password("Lama-Kuat#88"))  # tak berubah

    def test_reset_password_kuat_berhasil(self):
        target = User.objects.create_user("resetme2", password="Lama-Kuat#88", role="supervisor")
        self.client.post(reverse("kelola_user_edit", args=[target.pk]),
                         {"action": "reset_password", "password": "Baru-Kuat#99"})
        target.refresh_from_db()
        self.assertTrue(target.check_password("Baru-Kuat#99"))
