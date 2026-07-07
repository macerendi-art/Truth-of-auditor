"""Halaman error produksi (404/500) harus branded — bukan halaman polos Django."""
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.views.defaults import page_not_found, server_error


@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
class ErrorPageTests(SimpleTestCase):
    def test_404_memakai_template_branded(self):
        r = self.client.get("/halaman-yang-tidak-ada/")
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, "Truth of Auditor", status_code=404)
        self.assertContains(r, "Dashboard", status_code=404)  # jalan pulang

    def test_500_memakai_template_branded(self):
        req = RequestFactory().get("/")
        r = server_error(req)
        self.assertEqual(r.status_code, 500)
        self.assertIn("Truth of Auditor", r.content.decode())

    def test_404_langsung_render_tanpa_context_error(self):
        # page_not_found dipanggil langsung — template tak boleh butuh context view.
        req = RequestFactory().get("/x/")
        r = page_not_found(req, Exception("boom"))
        self.assertEqual(r.status_code, 404)
        self.assertIn("Truth of Auditor", r.content.decode())
