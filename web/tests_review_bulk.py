"""Review massal: tandai banyak MatchResult sekaligus (cocok / tidak cocok).

Latar: mayoritas hasil re-match & mutasi bank nama-doang mendarat di perlu_tinjau
(weak_name) — ratusan baris per hari tak mungkin di-review satu-satu. Checkbox
per baris + aksi massal, semantik SAMA dengan review per-baris (bucket +
reason_code=manual_override + jejak ReviewAction per baris).
"""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ReviewAction, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


class _Base(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get(name="Default")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        self.run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=self.batch
        )
        up = Upload.objects.create(source_type=self.panel, toko=self.lbs)
        self.results = []
        for i in range(3):
            tx = Transaction.objects.create(
                upload=up, source_type=self.panel, toko=self.lbs, jenis="depo",
                amount=Decimal("50000"), money_delta=Decimal("-50000"),
                occurred_at=datetime(2026, 6, 27, 21, 0), row_hash=f"p{i}",
            )
            self.results.append(MatchResult.objects.create(
                run=self.run, bucket=MatchResult.Bucket.TINJAU, left=tx,
                score=85, reason_code="weak_name",
            ))

    def _bulk(self, ids, action, **extra):
        data = {"result_ids": ids, "action": action}
        data.update(extra)
        return self.client.post(reverse("review_bulk"), data)


class ReviewBulkTests(_Base):
    def test_bulk_tandai_cocok(self):
        r = self._bulk([self.results[0].pk, self.results[1].pk], "mark_matched")
        self.assertEqual(r.status_code, 302)
        for res in self.results[:2]:
            res.refresh_from_db()
            self.assertEqual(res.bucket, MatchResult.Bucket.COCOK)
            self.assertEqual(res.reason_code, "manual_override")
        self.results[2].refresh_from_db()
        self.assertEqual(self.results[2].bucket, MatchResult.Bucket.TINJAU)
        # jejak audit per baris
        self.assertEqual(ReviewAction.objects.filter(action="mark_matched").count(), 2)

    def test_bulk_tandai_tidak_cocok(self):
        self._bulk([self.results[0].pk], "mark_unmatched")
        self.results[0].refresh_from_db()
        self.assertEqual(self.results[0].bucket, MatchResult.Bucket.TIDAK)

    def test_redirect_kembali_ke_next(self):
        next_url = reverse("run_detail", args=[self.run.pk]) + "?bucket=perlu_tinjau"
        r = self._bulk([self.results[0].pk], "mark_matched", next=next_url)
        self.assertEqual(r.url, next_url)

    def test_aksi_tak_dikenal_400(self):
        r = self._bulk([self.results[0].pk], "hapus_semua")
        self.assertEqual(r.status_code, 400)

    def test_rbac_toko_lain_tak_tersentuh(self):
        slo = Toko.objects.get(key="slo")
        batch2 = ReconBatch.objects.create(toko=slo, tolerance=self.tol)
        run2 = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=batch2
        )
        res2 = MatchResult.objects.create(
            run=run2, bucket=MatchResult.Bucket.TINJAU, score=85, reason_code="weak_name"
        )
        aud = User.objects.create_user("aud", password="pw123456", role="auditor")
        aud.allowed_tokos.set([self.lbs])
        self.client.logout()
        self.client.login(username="aud", password="pw123456")
        self._bulk([res2.pk], "mark_matched")
        res2.refresh_from_db()
        self.assertEqual(res2.bucket, MatchResult.Bucket.TINJAU)  # di luar toko-nya → tak berubah

    def test_markup_checkbox_dan_form_massal(self):
        r = self.client.get(reverse("run_detail", args=[self.run.pk]))
        self.assertContains(r, 'id="bulkreview"')
        self.assertContains(r, 'class="rsel"')
        self.assertContains(r, ".rsel:checked")
