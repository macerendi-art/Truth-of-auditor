"""Log Audit admin: snapshot username, pencatatan aksi kelola, halaman /kelola/log/."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.audit import catat
from core.models import AuditLog
from sources.models import Toko

User = get_user_model()


class UsernameSnapshotTests(TestCase):
    def test_catat_menyimpan_snapshot_username(self):
        u = User.objects.create_user("pelaku", password="X-Kuat#88", role="admin")
        catat(u, "buat_user", "target1")
        log = AuditLog.objects.latest("id")
        self.assertEqual(log.username, "pelaku")
        self.assertEqual(log.user_id, u.pk)

    def test_snapshot_hidup_setelah_user_dihapus(self):
        u = User.objects.create_user("pelaku2", password="X-Kuat#88", role="admin")
        catat(u, "hapus_toko", "TOKO X")
        u.delete()
        log = AuditLog.objects.latest("id")
        self.assertIsNone(log.user)  # FK SET_NULL
        self.assertEqual(log.username, "pelaku2")  # identitas tetap hidup
