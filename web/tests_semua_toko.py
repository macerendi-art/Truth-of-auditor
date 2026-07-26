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


class ContextProcessorTests(TestCase):
    """Flag `semua_toko` + `active_toko` fallback + badge tinjau lintas toko."""

    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")

    def _ctx(self, path="/upload/"):
        return self.client.get(path).context

    def test_admin_mode_semua_flag_hidup(self):
        User.objects.create_user("adm", password="pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")
        _sesi_semua(self.client)
        ctx = self._ctx()
        self.assertTrue(ctx["semua_toko"])
        self.assertIsInstance(ctx["active_toko"], Toko)

    def test_tanpa_sentinel_flag_mati(self):
        User.objects.create_user("adm", password="pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")
        self.assertFalse(self._ctx()["semua_toko"])

    def test_non_admin_sentinel_tak_mengaktifkan_mode(self):
        """Sesi warisan (mis. user diturunkan perannya) tak boleh membuka mode."""
        u = User.objects.create_user("a2", password="pw12345", role="auditor")
        u.allowed_tokos.set([self.lbs])
        self.client.login(username="a2", password="pw12345")
        _sesi_semua(self.client)
        ctx = self._ctx()
        self.assertFalse(ctx["semua_toko"])
        self.assertEqual(ctx["active_toko"], self.lbs)


class BadgeTinjauLintasTokoTests(TestCase):
    """`pending_review_count` ikut mode: lintas toko saat Semua Toko."""

    def setUp(self):
        from reconciliation.models import ToleranceProfile

        User.objects.create_user("adm", password="pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")
        self.tol = ToleranceProfile.objects.get(name="Default")
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")

    def _tinjau(self, toko, n):
        from reconciliation.models import MatchResult, MatchRun, ReconBatch

        import datetime

        b = ReconBatch.objects.create(toko=toko, tolerance=self.tol,
                                      recon_date=datetime.date(2026, 7, 1))
        run = MatchRun.objects.create(
            batch=b, tolerance=self.tol,
            relation=MatchRun.Relation.PANEL_BANK, summary={})
        for _ in range(n):
            MatchResult.objects.create(run=run, bucket=MatchResult.Bucket.TINJAU,
                                       reason_code="name_partial")

    def test_mode_semua_menjumlah_semua_toko(self):
        self._tinjau(self.lbs, 2)
        self._tinjau(self.slo, 3)
        _sesi_semua(self.client)
        self.assertEqual(self.client.get("/upload/").context["pending_review_count"], 5)

    def test_mode_tunggal_hanya_toko_aktif(self):
        self._tinjau(self.lbs, 2)
        self._tinjau(self.slo, 3)
        s = self.client.session
        s["active_toko_id"] = self.lbs.id
        s.save()
        self.assertEqual(self.client.get("/upload/").context["pending_review_count"], 2)

    def test_badge_lintas_toko_tetap_satu_query(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from web.context_processors import toko as cp_toko

        self._tinjau(self.lbs, 1)
        _sesi_semua(self.client)
        req = self.client.get("/upload/").wsgi_request
        with CaptureQueriesContext(connection) as ctx:
            hasil = cp_toko(req)
        self.assertEqual(hasil["pending_review_count"], 1)
        # 1 query daftar toko + 1 query hitung tinjau — bukan per toko.
        self.assertEqual(len(ctx), 2, [q["sql"][:90] for q in ctx])


class PickerDanBarTests(TestCase):
    """Opsi "Semua Toko" di picker + bar penjelas di halaman single-toko."""

    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")

    def _admin(self):
        User.objects.create_user("adm", password="pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")

    def test_admin_melihat_opsi_semua_toko(self):
        self._admin()
        self.assertContains(self.client.get("/upload/"), 'value="all"')

    def test_non_admin_tak_melihat_opsi(self):
        u = User.objects.create_user("a2", password="pw12345", role="auditor")
        u.allowed_tokos.set([self.lbs])
        self.client.login(username="a2", password="pw12345")
        self.assertNotContains(self.client.get("/upload/"), 'value="all"')

    def test_opsi_terpilih_saat_mode_aktif(self):
        self._admin()
        _sesi_semua(self.client)
        self.assertContains(self.client.get("/upload/"), '<option value="all" selected>')

    def test_bar_muncul_di_halaman_single_toko(self):
        self._admin()
        _sesi_semua(self.client)
        r = self.client.get("/upload/")
        self.assertContains(r, "Mode Semua Toko aktif")
        # bar menyebut toko fallback yang sedang ditampilkan
        self.assertContains(r, f"<b>{_active_name(r)}</b>")

    def test_bar_tak_muncul_saat_mode_mati(self):
        self._admin()
        self.assertNotContains(self.client.get("/upload/"), "Mode Semua Toko aktif")


def _active_name(response):
    return response.context["active_toko"].name
