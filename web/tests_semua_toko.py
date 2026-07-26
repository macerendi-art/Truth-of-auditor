"""Mode "Semua Toko" (khusus admin) — sentinel sesi, dashboard gabungan,
dan filter ceklis multi-toko di halaman Hutang/Piutang.

Risiko utama fitur ini: `active_toko_id` yang biasanya berisi id numerik kini
bisa berisi string sentinel "all". Setiap view single-toko memanggil
`_active_toko`, dan `allowed.filter(id="all")` MELEDAK (ValueError di sqlite
maupun Postgres). Karena itu kelas pertama di berkas ini menyapu SELURUH rute
tanpa argumen dengan sesi "all" — pagar yang harus selalu hijau.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import URLPattern, reverse

from sources.models import Toko
from web.urls import urlpatterns

User = get_user_model()

# Rute tanpa argumen = halaman/aksi yang bisa di-GET langsung. Rute ber-<int:pk>
# dilewati (butuh objek nyata; guard sesi-nya sama saja karena lewat
# `_active_toko` yang identik).
RUTE_TANPA_ARG = sorted({
    p.name for p in urlpatterns
    if isinstance(p, URLPattern) and p.name and not p.pattern.regex.groupindex
})


def _sesi_semua(client):
    """Setel sesi ke mode Semua Toko (seperti hasil POST set_toko)."""
    s = client.session
    s["active_toko_id"] = "all"
    s.save()


class SentinelSesiTests(TestCase):
    """Sesi "all" tidak boleh membuat satu halaman pun meledak."""

    def setUp(self):
        User.objects.create_user("adm", password="pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")

    def test_semua_rute_tanpa_arg_tidak_meledak(self):
        _sesi_semua(self.client)
        for nama in RUTE_TANPA_ARG:
            with self.subTest(rute=nama):
                r = self.client.get(reverse(nama))
                self.assertLess(
                    r.status_code, 500,
                    f"rute {nama} balas {r.status_code} saat sesi mode Semua Toko",
                )

    def test_active_toko_tetap_objek_toko_nyata(self):
        """±17 pemanggil `_active_toko` mengandalkan objek Toko — bukan string."""
        from web.views import _active_toko

        req = self.client.request().wsgi_request
        req.session["active_toko_id"] = "all"
        t = _active_toko(req)
        self.assertIsInstance(t, Toko)


class SetTokoSentinelTests(TestCase):
    """`set_toko` menerima "all" HANYA dari admin."""

    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")

    def _login(self, role):
        User.objects.create_user("u1", password="pw12345", role=role)
        if role == "auditor":
            User.objects.get(username="u1").allowed_tokos.set([self.lbs])
        self.client.login(username="u1", password="pw12345")

    def test_admin_boleh_pilih_semua(self):
        self._login("admin")
        self.client.post(reverse("set_toko"), {"toko_id": "all"})
        self.assertEqual(self.client.session.get("active_toko_id"), "all")

    def test_auditor_tak_boleh_pilih_semua(self):
        self._login("auditor")
        self.client.post(reverse("set_toko"), {"toko_id": "all"})
        self.assertIsNone(self.client.session.get("active_toko_id"))

    def test_supervisor_tak_boleh_pilih_semua(self):
        self._login("supervisor")
        self.client.post(reverse("set_toko"), {"toko_id": "all"})
        self.assertIsNone(self.client.session.get("active_toko_id"))

    def test_pilih_toko_biasa_keluar_dari_mode_semua(self):
        self._login("admin")
        self.client.post(reverse("set_toko"), {"toko_id": "all"})
        self.client.post(reverse("set_toko"), {"toko_id": str(self.lbs.id)})
        self.assertEqual(self.client.session.get("active_toko_id"), self.lbs.id)

    def test_nilai_ngawur_diabaikan(self):
        self._login("admin")
        self.client.post(reverse("set_toko"), {"toko_id": "semua"})
        self.assertIsNone(self.client.session.get("active_toko_id"))
