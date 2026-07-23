"""Tes GeoBlockMiddleware (fitur K4 — geo-block / kunci wilayah).

Prinsip keamanan utama: DEFAULT MATI (GEO_BLOCK_ENABLED=False) = middleware
pass-through total, tak boleh mengunci app live. Saat ON, hanya negara dalam
GEO_BLOCK_COUNTRIES yang lolos; sisanya 403 halaman "Trust No One".

Resolver negara di-mock supaya deterministik tanpa DB GeoIP nyata.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse_lazy

User = get_user_model()

# Path publik yang selalu ada (halaman masuk) — GET tanpa login → 200.
LOGIN = reverse_lazy("login")


def _lc(mapping):
    """Buat pengganti _lookup_country: dict IP→kode, default 'ID'."""

    def _fn(ip):
        return mapping.get(ip, "ID")

    return _fn


class GeoBlockDefaultOffTests(TestCase):
    """DEFAULT MATI: tak ada request yang terblok apa pun negaranya."""

    def test_default_off_non_kh_tidak_terblok(self):
        # Tanpa override apa pun (default settings) → tak 403 walau IP non-KH.
        r = self.client.get(LOGIN, REMOTE_ADDR="8.8.8.8", HTTP_X_FORWARDED_FOR="8.8.8.8")
        self.assertNotEqual(r.status_code, 403)
        self.assertNotContains(r, "Trust No One")

    @override_settings(GEO_BLOCK_ENABLED=False)
    def test_eksplisit_off_dengan_resolver_non_kh_tetap_lolos(self):
        with mock.patch("web.middleware._lookup_country", _lc({})):
            r = self.client.get(LOGIN, HTTP_X_FORWARDED_FOR="8.8.8.8")
        self.assertNotEqual(r.status_code, 403)


@override_settings(
    GEO_BLOCK_ENABLED=True,
    GEO_BLOCK_COUNTRIES={"KH"},
    GEO_BLOCK_ALLOWLIST=[],
    GEO_BLOCK_BYPASS_STAFF=True,
)
class GeoBlockOnTests(TestCase):
    def test_non_kh_diblok_dengan_halaman_trust_no_one(self):
        with mock.patch("web.middleware._lookup_country", _lc({"8.8.8.8": "ID"})):
            r = self.client.get(LOGIN, HTTP_X_FORWARDED_FOR="8.8.8.8")
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "Trust No One", status_code=403)

    def test_kh_lolos(self):
        with mock.patch("web.middleware._lookup_country", _lc({"1.1.1.1": "KH"})):
            r = self.client.get(LOGIN, HTTP_X_FORWARDED_FOR="1.1.1.1")
        self.assertNotEqual(r.status_code, 403)

    def test_ip_privat_loopback_lolos(self):
        # 127.0.0.1 dan 10.x = health-check internal Railway + dev → selalu lolos.
        for ip in ("127.0.0.1", "10.1.2.3", "192.168.0.9", "169.254.1.1"):
            with mock.patch("web.middleware._lookup_country", _lc({})):
                r = self.client.get(LOGIN, HTTP_X_FORWARDED_FOR=ip, REMOTE_ADDR=ip)
            self.assertNotEqual(r.status_code, 403, f"IP privat {ip} seharusnya lolos")

    @override_settings(GEO_BLOCK_ALLOWLIST=["203.0.113.7", "198.51.100.0/24"])
    def test_allowlist_ip_dan_cidr_lolos(self):
        with mock.patch("web.middleware._lookup_country", _lc({})):
            r = self.client.get(LOGIN, HTTP_X_FORWARDED_FOR="203.0.113.7")
            self.assertNotEqual(r.status_code, 403)
            r2 = self.client.get(LOGIN, HTTP_X_FORWARDED_FOR="198.51.100.55")
            self.assertNotEqual(r2.status_code, 403)

    def test_resolver_gagal_fail_open(self):
        # Lib/DB GeoIP tak termuat → lempar → FAIL-OPEN (jangan brick app).
        def _boom(ip):
            raise ImportError("geoip2fast tidak terpasang")

        with mock.patch("web.middleware._lookup_country", _boom):
            r = self.client.get(LOGIN, HTTP_X_FORWARDED_FOR="8.8.8.8")
        self.assertNotEqual(r.status_code, 403)

    def test_anti_spoof_xff_pakai_hop_kanan(self):
        # Klien memalsukan hop kiri (KH), infra menambah hop kanan (ID nyata).
        # Middleware harus memakai yang KANAN → ID → 403 (bukan lolos).
        resolver = _lc({"9.9.9.9": "KH", "8.8.8.8": "ID"})
        with mock.patch("web.middleware._lookup_country", resolver):
            r = self.client.get(LOGIN, HTTP_X_FORWARDED_FOR="9.9.9.9, 8.8.8.8")
        self.assertEqual(r.status_code, 403)

    def test_envoy_header_diprioritaskan(self):
        resolver = _lc({"5.5.5.5": "KH", "8.8.8.8": "ID"})
        with mock.patch("web.middleware._lookup_country", resolver):
            r = self.client.get(
                LOGIN,
                HTTP_X_ENVOY_EXTERNAL_ADDRESS="5.5.5.5",
                HTTP_X_FORWARDED_FOR="8.8.8.8",
            )
        self.assertNotEqual(r.status_code, 403)

    def test_aset_statis_exempt(self):
        with mock.patch("web.middleware._lookup_country", _lc({})):
            r = self.client.get("/static/tidak-ada.css", HTTP_X_FORWARDED_FOR="8.8.8.8")
        self.assertNotEqual(r.status_code, 403)


@override_settings(
    GEO_BLOCK_ENABLED=True,
    GEO_BLOCK_COUNTRIES={"KH"},
    GEO_BLOCK_ALLOWLIST=[],
)
class GeoBlockStaffBypassTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser(
            "geostaff", email="", password="pw123456"
        )

    @override_settings(GEO_BLOCK_BYPASS_STAFF=True)
    def test_staff_non_kh_lolos_saat_bypass_on(self):
        self.client.login(username="geostaff", password="pw123456")
        with mock.patch("web.middleware._lookup_country", _lc({"8.8.8.8": "ID"})):
            r = self.client.get(LOGIN, HTTP_X_FORWARDED_FOR="8.8.8.8")
        self.assertNotEqual(r.status_code, 403)

    @override_settings(GEO_BLOCK_BYPASS_STAFF=False)
    def test_staff_non_kh_tetap_diblok_saat_bypass_off(self):
        self.client.login(username="geostaff", password="pw123456")
        with mock.patch("web.middleware._lookup_country", _lc({"8.8.8.8": "ID"})):
            r = self.client.get(LOGIN, HTTP_X_FORWARDED_FOR="8.8.8.8")
        self.assertEqual(r.status_code, 403)


# --- Origin-lock Cloudflare -------------------------------------------------
# Sejak app diproxy Cloudflare, penentu negara adalah header CF-IPCountry, TAPI
# hanya boleh dipercaya kalau peer-nya memang edge Cloudflare. Kalau tidak,
# siapa pun yang menembak origin Railway langsung bisa mengarang "CF-IPCountry: KH".
CF_PEER = "104.16.0.1"      # di dalam 104.16.0.0/13 (rentang resmi Cloudflare)
BUKAN_CF = "8.8.8.8"        # bukan Cloudflare


@override_settings(
    GEO_BLOCK_ENABLED=True, GEO_BLOCK_COUNTRIES={"KH"},
    GEO_BLOCK_BYPASS_STAFF=False, GEO_BLOCK_ALLOWLIST=[],
)
class GeoBlockCloudflareTests(TestCase):
    def test_header_cf_dipercaya_bila_peer_cloudflare(self):
        # Lewat CF + CF-IPCountry=KH → lolos, TANPA menyentuh geoip sama sekali.
        with mock.patch("web.middleware._lookup_country", _lc({})):  # default 'ID'
            r = self.client.get(
                LOGIN, HTTP_X_FORWARDED_FOR=CF_PEER,
                HTTP_CF_IPCOUNTRY="KH", HTTP_CF_CONNECTING_IP="202.178.121.42")
        self.assertNotEqual(r.status_code, 403)

    def test_header_cf_dari_peer_palsu_TIDAK_dipercaya(self):
        """INTI ANTI-SPOOF: peer bukan Cloudflare tapi mengarang CF-IPCountry=KH.
        Header harus diabaikan → jatuh ke geoip (ID) → tetap DIBLOKIR."""
        with mock.patch("web.middleware._lookup_country", _lc({BUKAN_CF: "ID"})):
            r = self.client.get(
                LOGIN, HTTP_X_FORWARDED_FOR=BUKAN_CF,
                HTTP_CF_IPCOUNTRY="KH", HTTP_CF_CONNECTING_IP="202.178.121.42")
        self.assertEqual(r.status_code, 403)

    def test_via_cloudflare_negara_lain_tetap_diblok(self):
        with mock.patch("web.middleware._lookup_country", _lc({})):
            r = self.client.get(
                LOGIN, HTTP_X_FORWARDED_FOR=CF_PEER, HTTP_CF_IPCOUNTRY="ID")
        self.assertEqual(r.status_code, 403)

    def test_allowlist_diuji_pada_ip_pengguna_asli_bukan_edge(self):
        """IP tim ada di CF-Connecting-IP; peer-nya edge CF. Allowlist harus
        tetap kena — kalau diuji ke IP edge, break-glass jadi percuma."""
        with override_settings(GEO_BLOCK_ALLOWLIST=["202.178.121.42"]):
            with mock.patch("web.middleware._lookup_country", _lc({})):
                r = self.client.get(
                    LOGIN, HTTP_X_FORWARDED_FOR=CF_PEER,
                    HTTP_CF_IPCOUNTRY="ID",  # sengaja negara salah
                    HTTP_CF_CONNECTING_IP="202.178.121.42")
        self.assertNotEqual(r.status_code, 403)

    def test_cf_ipcountry_XX_jatuh_ke_geoip(self):
        # CF membalas 'XX' (tak diketahui) → jangan dipakai, pakai geoip.
        with mock.patch("web.middleware._lookup_country", _lc({CF_PEER: "KH"})):
            r = self.client.get(
                LOGIN, HTTP_X_FORWARDED_FOR=CF_PEER, HTTP_CF_IPCOUNTRY="XX")
        self.assertNotEqual(r.status_code, 403)


@override_settings(
    GEO_BLOCK_ENABLED=True, GEO_BLOCK_COUNTRIES={"KH"},
    GEO_BLOCK_BYPASS_STAFF=False, GEO_BLOCK_ALLOWLIST=[],
)
class GeoBlockRequireCfTests(TestCase):
    @override_settings(GEO_BLOCK_REQUIRE_CF=True)
    def test_akses_origin_langsung_ditolak_walau_negara_benar(self):
        """Penutup celah bypass: walau geoip bilang KH, request yang tidak
        lewat Cloudflare tetap 403 saat origin-lock menyala."""
        with mock.patch("web.middleware._lookup_country", _lc({BUKAN_CF: "KH"})):
            r = self.client.get(LOGIN, HTTP_X_FORWARDED_FOR=BUKAN_CF)
        self.assertEqual(r.status_code, 403)

    @override_settings(GEO_BLOCK_REQUIRE_CF=True)
    def test_lewat_cloudflare_tetap_lolos_saat_origin_lock_on(self):
        with mock.patch("web.middleware._lookup_country", _lc({})):
            r = self.client.get(
                LOGIN, HTTP_X_FORWARDED_FOR=CF_PEER, HTTP_CF_IPCOUNTRY="KH")
        self.assertNotEqual(r.status_code, 403)

    @override_settings(GEO_BLOCK_REQUIRE_CF=False)
    def test_default_off_akses_origin_tidak_diubah(self):
        """Default MATI → origin-lock tak mengubah perilaku apa pun."""
        with mock.patch("web.middleware._lookup_country", _lc({BUKAN_CF: "KH"})):
            r = self.client.get(LOGIN, HTTP_X_FORWARDED_FOR=BUKAN_CF)
        self.assertNotEqual(r.status_code, 403)

    @override_settings(GEO_BLOCK_REQUIRE_CF=True)
    def test_health_check_internal_tetap_lolos(self):
        """Railway health-check datang dari IP privat — jangan sampai mati."""
        r = self.client.get(LOGIN, HTTP_X_FORWARDED_FOR="10.0.0.5")
        self.assertNotEqual(r.status_code, 403)
