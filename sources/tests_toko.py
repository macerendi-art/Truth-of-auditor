from django.test import TestCase

from sources.models import Toko


class TokoModelTests(TestCase):
    def test_str_returns_name(self):
        t = Toko.objects.create(key="xyz", name="XYZ")
        self.assertEqual(str(t), "XYZ")

    def test_seed_creates_lbs_and_slo(self):
        self.assertTrue(Toko.objects.filter(key="lbs").exists())
        self.assertTrue(Toko.objects.filter(key="slo").exists())
