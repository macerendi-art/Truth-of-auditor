"""Paket kecil web: log hapus massal ber-nama-file, cari riwayat upload (admin),
ganti nama toko."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog
from sources.models import SourceType, Toko, Upload


def _buat_user(username, role, toko=None):
    u = get_user_model().objects.create_user(
        username=username, password="rahasia123", role=role)
    if toko is not None:
        u.allowed_tokos.add(toko)
    return u


class _Dasar(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.bank = SourceType.objects.get_or_create(
            key="bank", defaults={"name": "Bank"})[0]

    def _login(self, role="admin"):
        user = _buat_user(f"u_{role}", role, self.toko)
        self.client.force_login(user)
        s = self.client.session
        s["active_toko_id"] = self.toko.id
        s.save()
        return user

    def _upload(self, nama):
        return Upload.objects.create(
            source_type=self.bank, toko=self.toko, original_name=nama)


class HapusMassalLogNamaFileTests(_Dasar):
    def test_log_memuat_nama_file_terhapus(self):
        self._login("admin")
        a = self._upload("01_07_BANK_A.csv")
        b = self._upload("01_07_BANK_B.csv")
        r = self.client.post(reverse("bulk_delete_uploads"),
                             {"upload_ids": [a.id, b.id]})
        self.assertEqual(r.status_code, 302)
        log = AuditLog.objects.filter(aksi="hapus_upload_massal").latest("id")
        self.assertIn("01_07_BANK_A.csv", log.detail["files"])
        self.assertIn("01_07_BANK_B.csv", log.detail["files"])


class CariRiwayatUploadTests(_Dasar):
    def setUp(self):
        super().setUp()
        self._upload("17-07-2026 MUL DP BCA ZUNAEDY.CSV")
        self._upload("17-07-2026 MUL DP QRIS FLYER.xlsx")

    def test_admin_bisa_cari_nama_file(self):
        self._login("admin")
        r = self.client.get(reverse("upload"), {"q": "FLYER"})
        self.assertContains(r, "QRIS FLYER.xlsx")
        self.assertNotContains(r, "BCA ZUNAEDY.CSV")

    def test_non_admin_parameter_diabaikan(self):
        self._login("auditor")
        r = self.client.get(reverse("upload"), {"q": "FLYER"})
        self.assertContains(r, "QRIS FLYER.xlsx")
        self.assertContains(r, "BCA ZUNAEDY.CSV")  # daftar penuh

    def test_form_cari_hanya_utk_admin(self):
        self._login("auditor")
        r = self.client.get(reverse("upload"))
        # Bukan 'name="q"' generik — topbar punya cari-transaksi global ber-name="q"
        # di semua halaman (lihat app_base.html) yang tak terkait fitur ini.
        self.assertNotContains(r, 'aria-label="Cari nama file"')


class GantiNamaTokoTests(_Dasar):
    def test_rename_sukses_dan_terlog(self):
        self._login("admin")
        lama = self.toko.name
        r = self.client.post(reverse("kelola_toko"), {
            "action": "rename", "toko_id": self.toko.id,
            "nama_baru": "LBS Sports"})
        self.assertEqual(r.status_code, 302)
        self.toko.refresh_from_db()
        self.assertEqual(self.toko.name, "LBS Sports")
        self.assertEqual(self.toko.key, "lbs")  # key stabil
        log = AuditLog.objects.filter(aksi="ubah_nama_toko").latest("id")
        self.assertEqual(log.detail["nama_lama"], lama)
        self.assertEqual(log.detail["nama_baru"], "LBS Sports")

    def test_nama_kosong_ditolak(self):
        self._login("admin")
        lama = self.toko.name
        self.client.post(reverse("kelola_toko"), {
            "action": "rename", "toko_id": self.toko.id, "nama_baru": "   "})
        self.toko.refresh_from_db()
        self.assertEqual(self.toko.name, lama)

    def test_auditor_ditolak(self):
        self._login("auditor")
        r = self.client.post(reverse("kelola_toko"), {
            "action": "rename", "toko_id": self.toko.id, "nama_baru": "X"})
        self.assertIn(r.status_code, (302, 403))
        self.toko.refresh_from_db()
        self.assertNotEqual(self.toko.name, "X")
