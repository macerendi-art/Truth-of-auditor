from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import Toko


class TokoSelectorTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.u = User.objects.create_user("aud", "a@a.co", "pw12345")
        self.client.login(username="aud", password="pw12345")

    def test_set_toko_updates_session(self):
        slo = Toko.objects.get(key="slo")
        self.client.post(reverse("set_toko"), {"toko_id": slo.id, "next": reverse("dashboard")})
        self.assertEqual(self.client.session["active_toko_id"], slo.id)

    def test_dashboard_renders_toko_selector(self):
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "LBS")
