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


class UploadLockedAnnotationTests(TestCase):
    """Anotasi `locked` di _uploads_for: upload terkunci bila buktinya dipakai
    hasil rekon (MatchResult left/right) ATAU transaksinya dikonsumsi batch.
    Karakterisasi semantik — penjaga saat query-nya dioptimalkan (split Exists;
    bentuk OR-dalam-satu-subquery = seq-scan MatchResult per baris di Postgres,
    terukur 10,8 dtk utk 20 upload di prod)."""

    def setUp(self):
        from reconciliation.models import ToleranceProfile

        User = get_user_model()
        self.u = User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.toko = Toko.objects.get(key="lbs")
        self.st = SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})[0]
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self._n = 0

    def _upload_with_tx(self):
        self._n += 1
        up = Upload.objects.create(source_type=self.st, toko=self.toko,
                                   original_name=f"f{self._n}.xlsx", uploaded_by=self.u)
        tx = Transaction.objects.create(
            upload=up, source_type=self.st, toko=self.toko, jenis="depo",
            amount=Decimal("50000"), money_delta=Decimal("50000"),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash=f"lk{self._n}",
        )
        return up, tx

    def _locked_map(self):
        from web.views import _uploads_for

        return {u.original_name: u.locked for u in _uploads_for(self.toko)}

    def test_locked_bila_left_right_consumed_dan_bebas(self):
        from reconciliation.models import MatchResult, MatchRun, ReconBatch

        run = MatchRun.objects.create(relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol)
        up_left, tx_left = self._upload_with_tx()
        MatchResult.objects.create(run=run, bucket=MatchResult.Bucket.TIDAK,
                                   reason_code="no_money", left=tx_left)
        up_right, tx_right = self._upload_with_tx()
        MatchResult.objects.create(run=run, bucket=MatchResult.Bucket.COCOK, right=tx_right)
        up_cons, tx_cons = self._upload_with_tx()
        batch = ReconBatch.objects.create(toko=self.toko, tolerance=self.tol)
        tx_cons.consumed_by_batch = batch
        tx_cons.save(update_fields=["consumed_by_batch"])
        up_free, _ = self._upload_with_tx()

        locked = self._locked_map()
        self.assertTrue(locked[up_left.original_name], "referensi left harus mengunci")
        self.assertTrue(locked[up_right.original_name], "referensi right harus mengunci")
        self.assertTrue(locked[up_cons.original_name], "konsumsi batch harus mengunci")
        self.assertFalse(locked[up_free.original_name], "upload bebas tidak terkunci")
