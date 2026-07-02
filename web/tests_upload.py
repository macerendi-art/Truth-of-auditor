from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse


class UploadAnalyzeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345")
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
