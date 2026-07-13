import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

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

    def test_toggle_id_non_numerik_tidak_crash(self):
        r = self.client.post(reverse("kelola_toko"), {"action": "toggle", "toko_id": "abc"})
        self.assertEqual(r.status_code, 302)  # redirect, bukan 500


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


class SidebarAdminTests(TestCase):
    def test_admin_melihat_menu_admin(self):
        User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, 'href="/kelola/user/"')
        self.assertContains(r, 'href="/kelola/toko/"')

    def test_supervisor_tidak_melihat_menu_admin(self):
        u = User.objects.create_user("sup", password="pw123456", role="supervisor")
        self.client.login(username="sup", password="pw123456")
        r = self.client.get(reverse("dashboard"))
        self.assertNotContains(r, 'href="/kelola/user/"')


def _seed_toko_data(toko):
    """Beri satu toko: 1 Upload (+file), 1 Transaction, 1 ReconBatch."""
    st = SourceType.objects.get(key="panel")
    tol = ToleranceProfile.objects.get(name="Default")
    up = Upload.objects.create(source_type=st, toko=toko, original_name=f"{toko.key}.csv")
    up.file.save(f"{toko.key}.csv", ContentFile(b"a,b\n1,2\n"), save=True)
    Transaction.objects.create(upload=up, source_type=st, toko=toko, row_hash=f"h-{toko.key}")
    batch = ReconBatch.objects.create(toko=toko, tolerance=tol)
    return up, batch


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="toa-test-media-"))
class DeleteTokoTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._overridden_settings["MEDIA_ROOT"], ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.lbs_up, self.lbs_batch = _seed_toko_data(self.lbs)
        self.slo_up, self.slo_batch = _seed_toko_data(self.slo)

    def test_hapus_toko_wipes_semua_data_toko_lain_utuh(self):
        r = self.client.post(reverse("delete_toko", args=[self.lbs.pk]))
        self.assertEqual(r.status_code, 302)
        # Toko lbs + seluruh datanya hilang.
        self.assertFalse(Toko.objects.filter(pk=self.lbs.pk).exists())
        self.assertFalse(Transaction.objects.filter(toko=self.lbs).exists())
        self.assertFalse(Upload.objects.filter(toko=self.lbs).exists())
        self.assertFalse(ReconBatch.objects.filter(toko=self.lbs).exists())
        # Toko slo tetap utuh.
        self.assertTrue(Toko.objects.filter(pk=self.slo.pk).exists())
        self.assertEqual(Transaction.objects.filter(toko=self.slo).count(), 1)
        self.assertEqual(Upload.objects.filter(toko=self.slo).count(), 1)
        self.assertEqual(ReconBatch.objects.filter(toko=self.slo).count(), 1)

    def test_hapus_toko_get_tidak_menghapus(self):
        # POST-guarded: GET tidak boleh menghapus.
        self.client.get(reverse("delete_toko", args=[self.lbs.pk]))
        self.assertTrue(Toko.objects.filter(pk=self.lbs.pk).exists())

    def test_hapus_toko_ditolak_non_admin(self):
        User.objects.create_user("aud", password="pw123456", role="auditor")
        c2 = self.client.__class__()
        c2.login(username="aud", password="pw123456")
        r = c2.post(reverse("delete_toko", args=[self.lbs.pk]), follow=True)
        self.assertContains(r, "Akses ditolak")
        self.assertTrue(Toko.objects.filter(pk=self.lbs.pk).exists())


class DeleteUserTests(TestCase):
    def setUp(self):
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.target = User.objects.create_user("budi", password="rahasia123", role="auditor")

    def test_hapus_user(self):
        r = self.client.post(reverse("delete_user", args=[self.target.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(User.objects.filter(username="budi").exists())

    def test_tidak_bisa_hapus_diri_sendiri(self):
        r = self.client.post(reverse("delete_user", args=[self.adm.pk]), follow=True)
        self.assertTrue(User.objects.filter(pk=self.adm.pk).exists())
        self.assertContains(r, "Tidak bisa menghapus akunmu sendiri.")

    def test_hapus_user_ditolak_non_admin(self):
        User.objects.create_user("aud", password="pw123456", role="auditor")
        c2 = self.client.__class__()
        c2.login(username="aud", password="pw123456")
        r = c2.post(reverse("delete_user", args=[self.target.pk]), follow=True)
        self.assertContains(r, "Akses ditolak")
        self.assertTrue(User.objects.filter(username="budi").exists())


class KelolaTokoCountTests(TestCase):
    """Kolom jumlah transaksi/upload per toko di /kelola/toko/.

    Karakterisasi + penjaga dua regresi: (a) hitungan terkali-silang
    (join Toko×Transaction×Upload menggandakan angka bila tanpa distinct),
    (b) bentuk annotate ganda distinct = join-explosion — terukur 29,8 dtk
    di prod (497rb tx), halaman putih; hitungan harus via agregat terpisah."""

    def setUp(self):
        User.objects.create_user("adm", password="pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        st = SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})[0]
        up = Upload.objects.create(source_type=st, toko=self.lbs)
        from datetime import datetime
        from decimal import Decimal
        for i in range(3):  # 3 tx dalam 1 upload: hitungan silang akan menggandakan
            Transaction.objects.create(
                upload=up, source_type=st, toko=self.lbs, jenis="depo",
                amount=Decimal("50000"), money_delta=Decimal("50000"),
                occurred_at=datetime(2026, 6, 27, 10, 0), row_hash=f"kc{i}",
            )

    def test_jumlah_tx_dan_upload_akurat(self):
        r = self.client.get(reverse("kelola_toko"))
        counts = {t.key: (t.n_tx, t.n_up) for t in r.context["tokos"]}
        self.assertEqual(counts["lbs"], (3, 1))   # bukan (3,3)/(9,1) hasil kali-silang
        self.assertEqual(counts["slo"], (0, 0))   # toko tanpa data tetap tampil 0
