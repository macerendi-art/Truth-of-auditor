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


class KelolaUserCreateTests(TestCase):
    def setUp(self):
        User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.lbs = Toko.objects.get(key="lbs")

    def _post(self, **over):
        data = {
            "username": "budi", "password": "rahasia123", "nama": "Budi S",
            "role": "auditor", "tokos": [self.lbs.id],
        }
        data.update(over)
        return self.client.post(reverse("kelola_user"), data)

    def test_create_auditor(self):
        self._post()
        u = User.objects.get(username="budi")
        self.assertEqual(u.first_name, "Budi S")
        self.assertEqual(u.role, "auditor")
        self.assertEqual(list(u.allowed_tokos.all()), [self.lbs])
        self.assertTrue(u.check_password("rahasia123"))

    def test_create_supervisor_tanpa_toko(self):
        self._post(username="sinta", role="supervisor", tokos=[])
        self.assertEqual(User.objects.get(username="sinta").allowed_tokos.count(), 0)

    def test_auditor_tanpa_toko_ditolak(self):
        self._post(username="tono", tokos=[])
        self.assertFalse(User.objects.filter(username="tono").exists())

    def test_password_pendek_ditolak(self):
        self._post(username="tini", password="1234567")
        self.assertFalse(User.objects.filter(username="tini").exists())

    def test_username_duplikat_ditolak(self):
        self._post()
        self._post(nama="Budi 2")
        self.assertEqual(User.objects.filter(username="budi").count(), 1)

    def test_list_tampil(self):
        r = self.client.get(reverse("kelola_user"))
        self.assertContains(r, "adm")
        self.assertContains(r, "Kelola Pengguna")


class KelolaUserEditTests(TestCase):
    def setUp(self):
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.target = User.objects.create_user("budi", password="rahasia123", role="auditor")
        self.target.allowed_tokos.add(self.lbs)
        self.url = reverse("kelola_user_edit", args=[self.target.pk])

    def test_save_ubah_nama_role_toko(self):
        self.client.post(self.url, {
            "action": "save", "nama": "Budi Baru", "role": "auditor",
            "tokos": [self.lbs.id, self.slo.id],
        })
        self.target.refresh_from_db()
        self.assertEqual(self.target.first_name, "Budi Baru")
        self.assertEqual(self.target.allowed_tokos.count(), 2)

    def test_save_auditor_tanpa_toko_ditolak(self):
        self.client.post(self.url, {"action": "save", "nama": "X", "role": "auditor", "tokos": []})
        self.target.refresh_from_db()
        self.assertEqual(self.target.allowed_tokos.count(), 1)  # tak berubah

    def test_naik_ke_supervisor_mengosongkan_toko(self):
        self.client.post(self.url, {"action": "save", "nama": "", "role": "supervisor", "tokos": []})
        self.target.refresh_from_db()
        self.assertEqual(self.target.role, "supervisor")
        self.assertEqual(self.target.allowed_tokos.count(), 0)

    def test_reset_password(self):
        self.client.post(self.url, {"action": "reset_password", "password": "barubanget9"})
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("barubanget9"))

    def test_reset_password_pendek_ditolak(self):
        self.client.post(self.url, {"action": "reset_password", "password": "1234567"})
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("rahasia123"))

    def test_toggle_nonaktif_lalu_login_gagal(self):
        self.client.post(self.url, {"action": "toggle"})
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        c2 = self.client.__class__()
        self.assertFalse(c2.login(username="budi", password="rahasia123"))

    def test_tidak_bisa_nonaktifkan_diri_sendiri(self):
        url_self = reverse("kelola_user_edit", args=[self.adm.pk])
        self.client.post(url_self, {"action": "toggle"})
        self.adm.refresh_from_db()
        self.assertTrue(self.adm.is_active)

    def test_tidak_bisa_turunkan_role_sendiri(self):
        url_self = reverse("kelola_user_edit", args=[self.adm.pk])
        self.client.post(url_self, {"action": "save", "nama": "", "role": "auditor", "tokos": [self.lbs.id]})
        self.adm.refresh_from_db()
        self.assertEqual(self.adm.role, "admin")
