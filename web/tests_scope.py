from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction


class ScopeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        up = Upload.objects.create(source_type=panel, toko=self.lbs)
        Transaction.objects.create(
            upload=up, source_type=panel, toko=self.lbs, jenis="depo", username="lbsuser",
            amount=Decimal("1"), money_delta=Decimal("1"),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash="lbs-tx",
        )
        Transaction.objects.create(
            upload=up, source_type=panel, toko=self.slo, jenis="depo", username="slouser",
            amount=Decimal("1"), money_delta=Decimal("1"),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash="slo-tx",
        )

    def test_transactions_scoped_to_active_toko(self):
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.get(reverse("transactions"))
        self.assertContains(r, "lbsuser")
        self.assertNotContains(r, "slouser")

    def test_set_toko_external_next_redirects_to_dashboard(self):
        r = self.client.post(
            reverse("set_toko"),
            {"toko_id": self.lbs.id, "next": "https://evil.example"},
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("dashboard"))
        self.assertNotIn("evil.example", r.url)

    def test_set_toko_safe_next_is_honored(self):
        r = self.client.post(
            reverse("set_toko"),
            {"toko_id": self.lbs.id, "next": reverse("transactions")},
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("transactions"))
