"""Picker toko: kepemilikan (Pusat/Partner) × panel (Nexus/Vigor/TM Gaming).

Grouping murni tampilan/metadata. <optgroup> digabung
\"Toko Pusat · Nexus\" karena HTML tidak mendukung nest.
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
        self.lbs = Toko.objects.get(key="lbs")   # pusat · nexus
        self.slo = Toko.objects.get(key="slo")   # vigor (0012)
        self.ahk = Toko.objects.get(key="ahk")   # pusat · nexus
        self.slo.kepemilikan = Toko.KEPEMILIKAN_PARTNER
        self.slo.save(update_fields=["kepemilikan"])

    def _login(self, user, active_toko):
        self.client.force_login(user)
        s = self.client.session
        s["active_toko_id"] = active_toko.id
        s.save()

    def test_kepemilikan_x_panel_tampil_optgroup(self):
        u = _buat_auditor("aud_dua_kep", self.lbs, self.slo)
        self._login(u, self.lbs)
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, '<optgroup label="Toko Pusat · Nexus"')
        self.assertContains(r, '<optgroup label="Toko Partner · Vigor"')
        self.assertContains(r, f'<option value="{self.lbs.id}"')
        self.assertContains(r, f'<option value="{self.slo.id}"')

    def test_satu_grup_tampil_flat_tanpa_optgroup(self):
        # lbs + ahk = pusat · nexus saja → flat.
        u = _buat_auditor("aud_satu_kep", self.lbs, self.ahk)
        self._login(u, self.lbs)
        r = self.client.get(reverse("dashboard"))
        self.assertNotContains(r, "<optgroup")
        self.assertContains(r, f'<option value="{self.lbs.id}"')
        self.assertContains(r, f'<option value="{self.ahk.id}"')

    def test_satu_kepemilikan_dua_panel_tampil_optgroup(self):
        # keduanya pusat, beda panel → dua header panel di dalam Pusat.
        self.slo.kepemilikan = Toko.KEPEMILIKAN_PUSAT
        self.slo.save(update_fields=["kepemilikan"])
        u = _buat_auditor("aud_dua_panel", self.lbs, self.slo)
        self._login(u, self.lbs)
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, '<optgroup label="Toko Pusat · Nexus"')
        self.assertContains(r, '<optgroup label="Toko Pusat · Vigor"')

    def test_reminder_modal_picker_ikut_berkelompok(self):
        u = _buat_auditor("aud_reminder", self.lbs, self.slo)
        self.client.force_login(u)
        s = self.client.session
        s["show_toko_reminder"] = True
        s["active_toko_id"] = self.lbs.id
        s.save()
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "reminderOverlay")
        self.assertContains(r, '<optgroup label="Toko Pusat · Nexus"')
        self.assertContains(r, '<optgroup label="Toko Partner · Vigor"')


class KelolaTokoPanelBadgeTests(TestCase):
    def setUp(self):
        User.objects.create_user("adm_badge", password="pw123456", role="admin")
        self.client.login(username="adm_badge", password="pw123456")

    def test_kolom_panel_tampil_dengan_badge(self):
        r = self.client.get(reverse("kelola_toko"))
        self.assertContains(r, "<th>Panel</th>")
        self.assertContains(r, "<th>Pusat / Partner</th>")
        self.assertContains(r, 'badge muted plain">Nexus</span>')
        self.assertContains(r, 'badge warn plain">Vigor</span>')
        self.assertContains(r, 'badge ok plain">Pusat</span>')
        self.assertContains(r, 'name="kepemilikan"')
        self.assertContains(r, ">Partner</option>")
