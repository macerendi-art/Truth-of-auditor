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


class UploadAnalyzeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345")
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
        User.objects.create_user("aud", "a@a.co", "pw12345")
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


class UploadHistoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.u = User.objects.create_user("aud", "a@a.co", "pw12345")
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
