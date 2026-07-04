from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from sources import services
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class UploadAnalyzeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")

    def test_analyze_detects_bri(self):
        f = SimpleUploadedFile(
            "bri.csv",
            b"TGL_TRAN,MUTASI_DEBET,MUTASI_KREDIT,DESK_TRAN\n",
            content_type="text/csv",
        )
        r = self.client.post(reverse("upload"), {"action": "analyze", "files": [f]})
        self.assertEqual(r.status_code, 200)
        preview = r.context["preview"]
        self.assertEqual(len(preview), 1)
        self.assertEqual(preview[0]["parser_key"], "bri")
        self.assertFalse(preview[0]["needs_confirm"])

    def test_password_field_readonly_when_not_encrypted(self):
        # File tak terkunci → kolom Password harus readonly (tak bisa diisi).
        f = SimpleUploadedFile(
            "bri.csv",
            b"TGL_TRAN,MUTASI_DEBET,MUTASI_KREDIT,DESK_TRAN\n",
            content_type="text/csv",
        )
        r = self.client.post(reverse("upload"), {"action": "analyze", "files": [f]})
        self.assertFalse(r.context["preview"][0]["needs_password"])
        self.assertContains(r, 'name="password"')
        self.assertContains(r, 'readonly tabindex="-1"')

    def test_password_field_enabled_when_encrypted(self):
        # File xlsx terenkripsi (OLE2 magic) → kolom Password aktif (tak readonly).
        f = SimpleUploadedFile(
            "locked.xlsx",
            b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1padding-encrypted",
            content_type="application/vnd.ms-excel",
        )
        r = self.client.post(reverse("upload"), {"action": "analyze", "files": [f]})
        self.assertTrue(r.context["preview"][0]["needs_password"])
        self.assertContains(r, 'name="password"')
        self.assertNotContains(r, 'readonly tabindex="-1"')


_ROW = {
    "occurred_at": datetime(2026, 6, 27, 10, 0), "posted_date": None, "jenis": "depo",
    "amount": Decimal("50000"), "credit_delta": Decimal("-50000"), "money_delta": Decimal("50000"),
    "fee": Decimal("0"), "bonus": Decimal("0"), "balance_after": None, "ticket_no": "D1",
    "username": "budi", "reference": "", "counterparty": "", "description": "", "raw": {},
    "row_hash": "commit-row-1",
}


class _DummyBracket:
    source_key = "bracket"

    def parse(self, path, flow=""):
        return [dict(_ROW)]


class UploadCommitTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})
        self.lbs = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def test_commit_ingests_and_sets_toko(self):
        staged = default_storage.save("staging/x.csv", ContentFile(b"dummy"))
        with patch.dict(services.PARSERS, {"dummy": _DummyBracket}, clear=False):
            r = self.client.post(reverse("upload"), {
                "action": "commit", "staged": [staged],
                "parser_key": ["dummy"], "flow": [""], "provider": "Nexus",
            })
        self.assertEqual(r.status_code, 302)
        up = Upload.objects.latest("id")
        self.assertEqual(up.toko, self.lbs)
        self.assertEqual(up.provider, "Nexus")
        self.assertEqual(up.rows_parsed, 1)
        self.assertFalse(default_storage.exists(staged))

    def test_commit_rejects_non_staging_path(self):
        n_up = Upload.objects.count()
        n_tx = Transaction.objects.count()
        with patch.dict(services.PARSERS, {"dummy": _DummyBracket}, clear=False), \
                patch("web.views.ingest", side_effect=AssertionError("must not ingest")):
            r = self.client.post(reverse("upload"), {
                "action": "commit", "staged": ["uploads/x"],
                "parser_key": ["dummy"], "flow": [""], "provider": "Nexus",
            })
        self.assertEqual(r.status_code, 302)  # redirect, tidak crash
        self.assertEqual(Upload.objects.count(), n_up)  # tidak ada upload dibuat
        self.assertEqual(Transaction.objects.count(), n_tx)

    def test_commit_rejects_path_traversal(self):
        n_up = Upload.objects.count()
        with patch.dict(services.PARSERS, {"dummy": _DummyBracket}, clear=False), \
                patch("web.views.ingest", side_effect=AssertionError("must not ingest")):
            r = self.client.post(reverse("upload"), {
                "action": "commit", "staged": ["staging/../etc/passwd"],
                "parser_key": ["dummy"], "flow": [""], "provider": "Nexus",
            })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Upload.objects.count(), n_up)


class UploadHistoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.u = User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.bracket = SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})[0]

    def test_history_scoped_to_active_toko(self):
        Upload.objects.create(source_type=self.bracket, toko=self.lbs, original_name="lbs-file.xlsx", uploaded_by=self.u)
        Upload.objects.create(source_type=self.bracket, toko=self.slo, original_name="slo-file.xlsx", uploaded_by=self.u)
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.get(reverse("upload"))
        self.assertContains(r, "lbs-file.xlsx")
        self.assertNotContains(r, "slo-file.xlsx")


def _mk_tx(upload, st, toko, row_hash):
    return Transaction.objects.create(
        upload=upload, source_type=st, toko=toko, jenis="depo",
        amount=Decimal("1"), money_delta=Decimal("1"),
        occurred_at=datetime(2026, 6, 27, 10, 0), row_hash=row_hash,
    )


class BulkDeleteUploadTests(TestCase):
    """Bagian B — hapus banyak upload sekaligus dari halaman Riwayat Upload."""

    def setUp(self):
        User = get_user_model()
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.st = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")

    def _mk(self, toko, name, with_file=False):
        up = Upload.objects.create(source_type=self.st, toko=toko, original_name=name)
        if with_file:
            up.file.save(name, ContentFile(b"data"), save=True)
        return up

    def test_happy_path_hapus_dua_upload_dan_transaksi(self):
        a = self._mk(self.lbs, "a.xlsx", with_file=True)
        b = self._mk(self.lbs, "b.xlsx", with_file=True)
        path_a, path_b = a.file.name, b.file.name
        _mk_tx(a, self.st, self.lbs, "bulk-a-1")
        _mk_tx(a, self.st, self.lbs, "bulk-a-2")
        _mk_tx(b, self.st, self.lbs, "bulk-b-1")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.post(reverse("bulk_delete_uploads"), {"upload_ids": [a.pk, b.pk]})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Upload.objects.filter(pk__in=[a.pk, b.pk]).exists())
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertFalse(default_storage.exists(path_a))
        self.assertFalse(default_storage.exists(path_b))
        msgs = [str(m) for m in list(r.wsgi_request._messages)]
        self.assertTrue(any("2 file" in m and "3 transaksi" in m for m in msgs), msgs)

    def test_non_admin_ditolak(self):
        a = self._mk(self.lbs, "a.xlsx")
        User = get_user_model()
        aud = User.objects.create_user("aud1", password="pw123456", role="auditor")
        aud.allowed_tokos.add(self.lbs)
        self.client.login(username="aud1", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.post(reverse("bulk_delete_uploads"), {"upload_ids": [a.pk]})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Upload.objects.filter(pk=a.pk).exists())

    def test_id_toko_lain_dan_id_tak_ada_di_skip_aman(self):
        # 'other' milik toko yang TIDAK sedang aktif; 'ghost' pk tak ada.
        mine = self._mk(self.lbs, "mine.xlsx")
        other = self._mk(self.slo, "other.xlsx")
        ghost_pk = 999999
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.post(
            reverse("bulk_delete_uploads"),
            {"upload_ids": [mine.pk, other.pk, ghost_pk]},
        )
        self.assertEqual(r.status_code, 302)  # tidak crash
        self.assertFalse(Upload.objects.filter(pk=mine.pk).exists())  # toko aktif → terhapus
        self.assertTrue(Upload.objects.filter(pk=other.pk).exists())  # toko lain → aman

    def test_get_tidak_menghapus(self):
        a = self._mk(self.lbs, "a.xlsx")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.get(reverse("bulk_delete_uploads"))
        self.assertTrue(Upload.objects.filter(pk=a.pk).exists())

    def test_tanpa_seleksi_tidak_menghapus(self):
        a = self._mk(self.lbs, "a.xlsx")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.post(reverse("bulk_delete_uploads"), {})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Upload.objects.filter(pk=a.pk).exists())


class UploadPageAffordanceTests(TestCase):
    """Bagian A (UX empty-state) + render checkbox/tombol bulk per peran."""

    def setUp(self):
        User = get_user_model()
        self.lbs = Toko.objects.get(key="lbs")
        self.st = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")

    def test_empty_state_mengarahkan_ganti_toko(self):
        # Bagian A: toko tanpa upload → pesan mengarahkan user ganti toko di pemilih.
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.get(reverse("upload"))
        self.assertContains(r, "pemilih")  # arahkan ke pemilih toko kanan-atas

    def test_admin_lihat_checkbox_dan_tombol_bulk(self):
        Upload.objects.create(source_type=self.st, toko=self.lbs, original_name="x.xlsx")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.get(reverse("upload"))
        self.assertContains(r, 'name="upload_ids"')  # checkbox per baris
        self.assertContains(r, reverse("bulk_delete_uploads"))  # form action bulk
        self.assertContains(r, "Hapus terpilih")

    def test_auditor_tidak_lihat_bulk(self):
        Upload.objects.create(source_type=self.st, toko=self.lbs, original_name="x.xlsx")
        User = get_user_model()
        aud = User.objects.create_user("aud2", password="pw123456", role="auditor")
        aud.allowed_tokos.add(self.lbs)
        self.client.login(username="aud2", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.get(reverse("upload"))
        self.assertNotContains(r, 'name="upload_ids"')
        self.assertNotContains(r, "Hapus terpilih")
