"""Healthcheck & logging: deploy rusak harus ketahuan mesin, bukan user."""
from django.conf import settings
from django.test import TestCase


class HealthzTests(TestCase):
    def test_healthz_tanpa_login_200(self):
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")


class LoggingTests(TestCase):
    def test_logging_console_terpasang(self):
        self.assertIn("console", settings.LOGGING["handlers"])
        self.assertIn("console", settings.LOGGING["root"]["handlers"])
