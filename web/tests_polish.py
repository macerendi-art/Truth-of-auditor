"""Polish temuan minor review: separator baris panel, chip #run dashboard, guard REL_LABELS."""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.views import REL_LABELS

User = get_user_model()


class ResultRowSeparatorTests(TestCase):
    """Baris kedua sel Panel tidak boleh diawali separator yatim ' · '."""

    def setUp(self):
        User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.lbs = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        up = Upload.objects.create(source_type=panel, toko=self.lbs)
        self.batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        self.run = MatchRun.objects.create(
            relation="panel_bank", tolerance=self.tol, batch=self.batch
        )
        self.tx = Transaction.objects.create(
            upload=up, source_type=panel, toko=self.lbs, jenis="depo",
            amount=Decimal("50000"), occurred_at=datetime(2026, 6, 27, 10, 0),
            username="", counterparty="BUDI SANTOSO", row_hash="pol1",
        )
        MatchResult.objects.create(
            run=self.run, bucket=MatchResult.Bucket.COCOK, left=self.tx, score=90
        )

    def test_username_kosong_tanpa_separator_yatim(self):
        r = self.client.get(reverse("run_detail", args=[self.run.pk]))
        self.assertContains(r, "BUDI SANTOSO")
        self.assertNotContains(r, 'style="font-size:12px"> · ')


class DashboardRunChipTests(TestCase):
    """Chip '#<pk global>' run di dashboard dihapus — membingungkan vs nomor batch per-toko."""

    def setUp(self):
        User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.lbs = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        self.run = MatchRun.objects.create(
            relation="panel_bank", tolerance=self.tol, batch=batch
        )

    def test_dashboard_tanpa_pk_global_run(self):
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, self.run.get_relation_display())  # daftar run tetap tampil
        self.assertNotContains(r, f"#{self.run.pk}</span>")


class RelLabelsGuardTests(TestCase):
    """REL_LABELS harus selalu selaras dengan enum MatchRun.Relation (jaga dari rename diam-diam)."""

    def test_rel_labels_selaras_dengan_enum(self):
        self.assertEqual(set(REL_LABELS), {rel.value for rel in MatchRun.Relation})
