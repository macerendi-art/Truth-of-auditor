from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


def _mk_upload(toko, with_file=False):
    st = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
    up = Upload.objects.create(source_type=st, toko=toko, original_name="f.xlsx")
    if with_file:
        up.file.save("f.xlsx", ContentFile(b"data"), save=True)
    return up, st


class DeleteUploadTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        User.objects.create_user("adm", password="pw123456", role="admin")

    def test_admin_hapus_upload_beserta_tx_dan_file(self):
        from datetime import datetime
        from decimal import Decimal
        up, st = _mk_upload(self.lbs, with_file=True)
        path = up.file.name
        Transaction.objects.create(
            upload=up, source_type=st, toko=self.lbs, jenis="depo",
            amount=Decimal("1"), money_delta=Decimal("1"),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash="del-1",
        )
        self.client.login(username="adm", password="pw123456")
        r = self.client.post(reverse("delete_upload", args=[up.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Upload.objects.filter(pk=up.pk).exists())
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertFalse(default_storage.exists(path))

    def test_auditor_ditolak(self):
        up, _ = _mk_upload(self.lbs)
        aud = User.objects.create_user("aud1", password="pw123456", role="auditor")
        aud.allowed_tokos.add(self.lbs)
        self.client.login(username="aud1", password="pw123456")
        self.client.post(reverse("delete_upload", args=[up.pk]))
        self.assertTrue(Upload.objects.filter(pk=up.pk).exists())

    def test_get_tidak_menghapus(self):
        up, _ = _mk_upload(self.lbs)
        self.client.login(username="adm", password="pw123456")
        self.client.get(reverse("delete_upload", args=[up.pk]))
        self.assertTrue(Upload.objects.filter(pk=up.pk).exists())

    def test_tombol_hanya_untuk_admin(self):
        _mk_upload(self.lbs)
        aud = User.objects.create_user("aud2", password="pw123456", role="auditor")
        aud.allowed_tokos.add(self.lbs)
        self.client.login(username="aud2", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.get(reverse("upload"))
        self.assertNotContains(r, "/delete/")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.get(reverse("upload"))
        self.assertContains(r, "/delete/")
