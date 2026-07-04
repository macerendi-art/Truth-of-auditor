from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

User = get_user_model()


class LogoutTests(TestCase):
    def setUp(self):
        User.objects.create_user("audlogout", password="pw123456", role="auditor")
        self.client.login(username="audlogout", password="pw123456")

    def test_post_logout_redirects_to_login(self):
        r = self.client.post(reverse("logout"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("login"))

    def test_post_logout_assertredirects(self):
        r = self.client.post(reverse("logout"))
        self.assertRedirects(
            r, reverse("login"), fetch_redirect_response=False
        )

    def test_get_logout_not_allowed(self):
        r = self.client.get(reverse("logout"))
        self.assertEqual(r.status_code, 405)


class CsrfFailureTests(TestCase):
    """Token CSRF basi (tab lama / setelah redeploy) tidak boleh berujung 403 mentah."""

    def setUp(self):
        User.objects.create_user("audcsrf", password="pw123456", role="auditor")

    def _client_tanpa_token(self):
        # enforce_csrf_checks: simulasi submit form dengan token basi/hilang
        c = Client(enforce_csrf_checks=True)
        c.login(username="audcsrf", password="pw123456")
        return c

    def test_logout_token_basi_tetap_logout_dan_ke_login(self):
        c = self._client_tanpa_token()
        r = c.post(reverse("logout"))  # tanpa csrfmiddlewaretoken
        self.assertRedirects(r, reverse("login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", c.session)

    def test_post_lain_token_basi_dapat_halaman_ramah(self):
        c = self._client_tanpa_token()
        r = c.post(reverse("set_toko"), {"toko_id": "1"})
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "kedaluwarsa", status_code=403)
        self.assertContains(r, reverse("login"), status_code=403)

    def test_logout_token_basi_saat_anonim_tetap_ke_login(self):
        c = Client(enforce_csrf_checks=True)  # tidak login sama sekali
        r = c.post(reverse("logout"))
        self.assertRedirects(r, reverse("login"), fetch_redirect_response=False)
