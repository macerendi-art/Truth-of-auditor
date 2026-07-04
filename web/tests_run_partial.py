"""Filter bucket/channel run_detail via htmx: header HX-Request → fragmen tabel saja.

Tab filter dan pager memakai hx-get + hx-push-url; view mengembalikan partial
_run_table.html (tanpa shell) saat request datang dari htmx, halaman penuh saat
navigasi biasa (fallback href tetap bekerja tanpa JS).
"""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


class RunPartialTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get(name="Default")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        self.run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=self.batch
        )
        left = Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=self.lbs, jenis="depo",
            amount=Decimal("50000"), money_delta=Decimal("50000"), ticket_no="D1",
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash="h-D1",
            raw={"Player Bank": "DANA|Eko|0821"},
        )
        MatchResult.objects.create(
            run=self.run, bucket=MatchResult.Bucket.COCOK, left=left, reason_code="x",
        )

    def test_hx_request_dapat_fragmen(self):
        url = reverse("run_detail", args=[self.run.pk])
        r = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertContains(r, 'id="result-table"')
        self.assertNotContains(r, "<aside")   # tanpa shell sidebar
        self.assertNotContains(r, "page-head")

    def test_tanpa_hx_tetap_full_page(self):
        r = self.client.get(reverse("run_detail", args=[self.run.pk]))
        self.assertContains(r, "<aside")
        self.assertContains(r, 'id="result-table"')
        self.assertContains(r, 'id="res-')   # baris hasil tetap dirender
