from django.contrib.auth import get_user_model
from django.test import TestCase
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
