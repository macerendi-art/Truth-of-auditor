"""Picker toko berkelompok Pusat/Partner — topbar + reminder.

Grouping murni tampilan/metadata (`Toko.kepemilikan`). Panel client tetap
di halaman Kelola Toko, bukan di picker topbar.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import Toko

User = get_user_model()


def _buat_auditor(username, *tokos):
    u = User.objects.create_user(username=username, password="rahasia123", role="auditor")
    for t in tokos:
        u.allowed_tokos.add(t)
    return u


class TopbarPickerBerkelompokTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")   # pusat (default)
        self.slo = Toko.objects.get(key="slo")
        self.ahk = Toko.objects.get(key="ahk")   # pusat (default)
        # Satu partner supaya dua optgroup muncul.
        self.slo.kepemilikan = Toko.KEPEMILIKAN_PARTNER
        self.slo.save(update_fields=["kepemilikan"])

    def _login(self, user, active_toko):
        self.client.force_login(user)
        s = self.client.session
        s["active_toko_id"] = active_toko.id
        s.save()

    def test_dua_kepemilikan_tampil_optgroup(self):
        u = _buat_auditor("aud_dua_kep", self.lbs, self.slo)
        self._login(u, self.lbs)
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, '<optgroup label="Toko Pusat"')
        self.assertContains(r, '<optgroup label="Toko Partner"')
        self.assertContains(r, f'<option value="{self.lbs.id}"')
        self.assertContains(r, f'<option value="{self.slo.id}"')

    def test_satu_kepemilikan_tampil_flat_tanpa_optgroup(self):
        # lbs + ahk keduanya pusat → satu grup → flat (tanpa header).
        u = _buat_auditor("aud_satu_kep", self.lbs, self.ahk)
        self._login(u, self.lbs)
        r = self.client.get(reverse("dashboard"))
        self.assertNotContains(r, "<optgroup")
        self.assertContains(r, f'<option value="{self.lbs.id}"')
        self.assertContains(r, f'<option value="{self.ahk.id}"')

    def test_reminder_modal_picker_ikut_berkelompok(self):
        u = _buat_auditor("aud_reminder", self.lbs, self.slo)
        self.client.force_login(u)
        s = self.client.session
        s["show_toko_reminder"] = True
        s["active_toko_id"] = self.lbs.id
        s.save()
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "reminderOverlay")
        self.assertContains(r, '<optgroup label="Toko Pusat"')
        self.assertContains(r, '<optgroup label="Toko Partner"')


class KelolaTokoPanelBadgeTests(TestCase):
    def setUp(self):
        User.objects.create_user("adm_badge", password="pw123456", role="admin")
        self.client.login(username="adm_badge", password="pw123456")

    def test_kolom_panel_tampil_dengan_badge(self):
        r = self.client.get(reverse("kelola_toko"))
        self.assertContains(r, "<th>Panel</th>")
        self.assertContains(r, "<th>Pusat / Partner</th>")
        # AHK = nexus (default), SLO = vigor (migrasi 0012).
        self.assertContains(r, 'badge muted plain">Nexus</span>')
        self.assertContains(r, 'badge warn plain">Vigor</span>')
        # default kepemilikan = Pusat
        self.assertContains(r, 'badge ok plain">Pusat</span>')
        self.assertContains(r, 'name="kepemilikan"')
        self.assertContains(r, ">Partner</option>")
