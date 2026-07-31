"""Bukti wiring combobox pemilih Toko (T5) — kotak cari di bilah atas.

Perilaku modulnya (buka/tutup, saring, panah, Enter/Esc) tidak bisa dijalankan
dari tes Django: suite ini tanpa runner browser. Verifikasi interaksi penuh
dilakukan reviewer manusia. Tes di sini menjaga *pemasangan*-nya:

1. Skrip `toko-picker.js` termuat global lewat app_base.html.
2. Markup `<select name="toko_id">` di server TIDAK berubah — enhancement murni
   sisi klien, jadi tanpa JS pemilih toko tetap berfungsi seperti semula.
3. CSS pendampingnya ikut terkirim (tanpa `.tp-native` select asli tak pernah
   tersembunyi dan pengguna melihat dua pemilih sekaligus).

Preseden gaya: web/tests_dragselect_wired.py.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import Toko

User = get_user_model()


class TokoPickerWiredTests(TestCase):
    def setUp(self):
        # Dua panel berbeda supaya markup <optgroup> ikut ter-render.
        self.lbs = Toko.objects.get(key="lbs")  # nexus
        self.slo = Toko.objects.get(key="slo")  # vigor
        u = User.objects.create_user("aud_tp", password="rahasia123", role="auditor")
        u.allowed_tokos.add(self.lbs, self.slo)
        self.client.force_login(u)
        s = self.client.session
        s["active_toko_id"] = self.lbs.id
        s.save()

    def test_skrip_toko_picker_termuat(self):
        """Modul JS dimuat global lewat app_base.html."""
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("toko-picker.js", r.content.decode())

    def test_markup_select_tidak_berubah(self):
        """Sabuk pengaman: select asli tetap sumber kebenaran (fallback no-JS)."""
        r = self.client.get(reverse("dashboard"))
        html = r.content.decode()
        self.assertIn('<select name="toko_id"', html)
        self.assertIn("<optgroup", html)

    def test_css_kontrol_terpasang(self):
        """Kelas penyembunyi select asli ada di <style> — tanpa itu, setelah JS
        sukses membangun kontrol, pengguna melihat DUA pemilih sekaligus."""
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, ".tp-native{display:none}")
