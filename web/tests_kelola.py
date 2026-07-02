from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import Toko

User = get_user_model()


class KelolaTokoAccessTests(TestCase):
    def test_auditor_dan_supervisor_ditolak(self):
        for role in ("auditor", "supervisor"):
            User.objects.create_user(f"u_{role}", password="pw123456", role=role)
            self.client.login(username=f"u_{role}", password="pw123456")
            r = self.client.get(reverse("kelola_toko"), follow=True)
            self.assertContains(r, "Akses ditolak")

    def test_admin_diizinkan(self):
        User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        r = self.client.get(reverse("kelola_toko"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Kelola Toko")


class KelolaTokoCrudTests(TestCase):
    def setUp(self):
        User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")

    def test_create_toko(self):
        self.client.post(reverse("kelola_toko"), {"action": "create", "kode": "zz9"})
        t = Toko.objects.get(key="zz9")
        self.assertEqual(t.name, "ZZ9")
        self.assertTrue(t.is_active)

    def test_create_duplikat_ditolak(self):
        self.client.post(reverse("kelola_toko"), {"action": "create", "kode": "LBS"})
        self.assertEqual(Toko.objects.filter(key="lbs").count(), 1)

    def test_create_kode_kosong_ditolak(self):
        n = Toko.objects.count()
        self.client.post(reverse("kelola_toko"), {"action": "create", "kode": "  "})
        self.assertEqual(Toko.objects.count(), n)

    def test_toggle_aktif(self):
        t = Toko.objects.get(key="lbs")
        self.client.post(reverse("kelola_toko"), {"action": "toggle", "toko_id": t.id})
        t.refresh_from_db()
        self.assertFalse(t.is_active)
