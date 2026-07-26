"""Tes IPAllowlistMiddleware + halaman /kelola/ip/ (allowlist IP auditor/supervisor).

Prinsip keamanan utama: DEFAULT DORMAN (tak ada `AllowedIP` aktif) = middleware
pass-through total, tak boleh mengunci app live. Admin/superuser SELALU bebas
(break-glass alami — admin harus selalu bisa masuk untuk membetulkan daftar
ini sendiri). Saat ada entri aktif, auditor & supervisor hanya lolos dari
IP/CIDR terdaftar; header anti-spoof mengikuti aturan `GeoBlockMiddleware`
(XFF paling kiri = peer asli, header CF hanya dipercaya bila peer memang edge
Cloudflare resmi) — lihat `web/tests_geoblock.py` untuk regresi lubang yang
sama di fitur geo-block.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse, reverse_lazy

from core.models import AuditLog
from web.models import AllowedIP

User = get_user_model()

LOGIN = reverse_lazy("login")
DASH = reverse_lazy("dashboard")

CF_PEER = "104.16.0.1"       # di dalam 104.16.0.0/13 (rentang resmi Cloudflare)
BUKAN_CF = "8.8.8.8"
TIM_IP = "202.178.121.42"    # dipakai sebagai CF-Connecting-IP di beberapa tes

# SENGAJA BUKAN rentang dokumentasi RFC 5737 (203.0.113.0/24 dkk. — "TEST-NET"):
# `ipaddress.ip_address(...).is_private` Python MENGANGGAP rentang itu privat,
# jadi `_ip_is_internal` (dipakai ulang dari GeoBlockMiddleware) akan
# meloloskannya lewat jalur "internal", BUKAN lewat pencocokan allowlist yang
# sebenarnya ingin diuji di sini — pakai IP publik nyata supaya tes benar-benar
# menguji `_ip_in_allowlist`.
KANTOR_IP = "138.201.14.7"
RANGE_CIDR = "138.201.0.0/16"
RANGE_TEST_IP = "138.201.55.9"


class _Dasar(TestCase):
    def setUp(self):
        self.auditor = User.objects.create_user("aud1", password="pw123456", role="auditor")
        self.supervisor = User.objects.create_user("sup1", password="pw123456", role="supervisor")
        self.admin = User.objects.create_user("adm1", password="pw123456", role="admin")
        self.superuser = User.objects.create_superuser("root1", email="", password="pw123456")


class DormanTests(_Dasar):
    """Tanpa entri AllowedIP aktif → fitur dorman, tak ada yang terkunci."""

    def test_auditor_lolos_dari_ip_manapun(self):
        self.client.login(username="aud1", password="pw123456")
        r = self.client.get(DASH, REMOTE_ADDR=BUKAN_CF, HTTP_X_FORWARDED_FOR=BUKAN_CF)
        self.assertNotEqual(r.status_code, 403)

    def test_dorman_meski_ada_entri_nonaktif_saja(self):
        AllowedIP.objects.create(label="Nonaktif", cidr=KANTOR_IP, aktif=False)
        self.client.login(username="aud1", password="pw123456")
        r = self.client.get(DASH, HTTP_X_FORWARDED_FOR=BUKAN_CF)
        self.assertNotEqual(r.status_code, 403)


class MatrixPeranTests(_Dasar):
    def setUp(self):
        super().setUp()
        AllowedIP.objects.create(label="Kantor", cidr=KANTOR_IP)
        AllowedIP.objects.create(label="Range", cidr=RANGE_CIDR)
        AllowedIP.objects.create(label="Nonaktif", cidr="9.9.9.9", aktif=False)

    def test_admin_bebas_dari_ip_asing(self):
        self.client.login(username="adm1", password="pw123456")
        r = self.client.get(DASH, HTTP_X_FORWARDED_FOR=BUKAN_CF)
        self.assertNotEqual(r.status_code, 403)

    def test_superuser_bebas_dari_ip_asing(self):
        self.client.login(username="root1", password="pw123456")
        r = self.client.get(DASH, HTTP_X_FORWARDED_FOR=BUKAN_CF)
        self.assertNotEqual(r.status_code, 403)

    def test_auditor_terblokir_ip_asing(self):
        self.client.login(username="aud1", password="pw123456")
        r = self.client.get(DASH, HTTP_X_FORWARDED_FOR=BUKAN_CF)
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, BUKAN_CF, status_code=403)

    def test_supervisor_terblokir_ip_asing(self):
        self.client.login(username="sup1", password="pw123456")
        r = self.client.get(DASH, HTTP_X_FORWARDED_FOR=BUKAN_CF)
        self.assertEqual(r.status_code, 403)

    def test_auditor_lolos_ip_persis(self):
        self.client.login(username="aud1", password="pw123456")
        r = self.client.get(DASH, HTTP_X_FORWARDED_FOR=KANTOR_IP)
        self.assertNotEqual(r.status_code, 403)

    def test_auditor_lolos_via_cidr(self):
        self.client.login(username="aud1", password="pw123456")
        r = self.client.get(DASH, HTTP_X_FORWARDED_FOR=RANGE_TEST_IP)
        self.assertNotEqual(r.status_code, 403)

    def test_entri_nonaktif_diabaikan(self):
        self.client.login(username="aud1", password="pw123456")
        r = self.client.get(DASH, HTTP_X_FORWARDED_FOR="9.9.9.9")
        self.assertEqual(r.status_code, 403)


class AntiSpoofTests(_Dasar):
    def setUp(self):
        super().setUp()
        self.client.login(username="aud1", password="pw123456")

    def test_xff_paling_kiri_dipakai_sebagai_peer(self):
        AllowedIP.objects.create(label="Peer", cidr="9.9.9.9")
        r = self.client.get(DASH, HTTP_X_FORWARDED_FOR="9.9.9.9, 8.8.8.8")
        self.assertNotEqual(r.status_code, 403)

    def test_header_envoy_dari_peer_non_cf_diabaikan(self):
        # peer asli (XFF[0]) TIDAK ada di allowlist; header Envoy mengarang IP
        # yang justru ADA di allowlist — harus tetap diabaikan (tetap 403).
        AllowedIP.objects.create(label="Palsu", cidr=CF_PEER)
        r = self.client.get(
            DASH, HTTP_X_FORWARDED_FOR=BUKAN_CF,
            HTTP_X_ENVOY_EXTERNAL_ADDRESS=CF_PEER)
        self.assertEqual(r.status_code, 403)

    def test_cf_connecting_ip_dari_peer_non_cf_diabaikan(self):
        # peer bukan edge Cloudflare tapi mengarang CF-Connecting-IP yang ADA
        # di allowlist — harus tetap diabaikan (blokir tetap berlaku).
        AllowedIP.objects.create(label="Palsu", cidr=TIM_IP)
        r = self.client.get(
            DASH, HTTP_X_FORWARDED_FOR=BUKAN_CF,
            HTTP_CF_CONNECTING_IP=TIM_IP)
        self.assertEqual(r.status_code, 403)

    def test_peer_cf_pakai_cf_connecting_ip(self):
        # peer = edge CF asli; allowlist berisi nilai CF-Connecting-IP → lolos
        # (diuji terhadap IP pengguna asli, bukan IP edge).
        AllowedIP.objects.create(label="Tim", cidr=TIM_IP)
        r = self.client.get(
            DASH, HTTP_X_FORWARDED_FOR=CF_PEER,
            HTTP_CF_CONNECTING_IP=TIM_IP)
        self.assertNotEqual(r.status_code, 403)

    def test_allowlist_tidak_pernah_diuji_ke_ip_edge_cf(self):
        # IP edge CF itu sendiri didaftarkan (bukan CF-Connecting-IP) — tetap
        # terblokir karena IP yang diuji adalah CF-Connecting-IP, bukan peer.
        AllowedIP.objects.create(label="Edge", cidr=CF_PEER)
        r = self.client.get(
            DASH, HTTP_X_FORWARDED_FOR=CF_PEER,
            HTTP_CF_CONNECTING_IP=TIM_IP)
        self.assertEqual(r.status_code, 403)


class InternalIpTests(_Dasar):
    def test_internal_loopback_lolos(self):
        AllowedIP.objects.create(label="X", cidr=KANTOR_IP)
        self.client.login(username="aud1", password="pw123456")
        for ip in ("127.0.0.1", "10.1.2.3", "192.168.0.9", "169.254.1.1"):
            r = self.client.get(DASH, REMOTE_ADDR=ip, HTTP_X_FORWARDED_FOR=ip)
            self.assertNotEqual(r.status_code, 403, f"IP privat {ip} seharusnya lolos")


class ExemptPathTests(_Dasar):
    def setUp(self):
        super().setUp()
        AllowedIP.objects.create(label="X", cidr=KANTOR_IP)
        self.client.login(username="aud1", password="pw123456")

    def test_logout_bisa_diakses_saat_terblokir(self):
        r = self.client.post(reverse("logout"), HTTP_X_FORWARDED_FOR=BUKAN_CF)
        self.assertNotEqual(r.status_code, 403)

    def test_aset_statis_bisa_diakses_saat_terblokir(self):
        r = self.client.get("/static/tidak-ada.css", HTTP_X_FORWARDED_FOR=BUKAN_CF)
        self.assertNotEqual(r.status_code, 403)


class AuditTests(_Dasar):
    def setUp(self):
        super().setUp()
        AllowedIP.objects.create(label="X", cidr=KANTOR_IP)

    def test_satu_log_per_sesi_blokir_berulang(self):
        self.client.login(username="aud1", password="pw123456")
        for _ in range(3):
            r = self.client.get(DASH, HTTP_X_FORWARDED_FOR=BUKAN_CF)
            self.assertEqual(r.status_code, 403)
        self.assertEqual(AuditLog.objects.filter(aksi="ip_blokir").count(), 1)

    def test_lolos_reset_flag_blokir_berikutnya_dicatat_lagi(self):
        self.client.login(username="aud1", password="pw123456")
        r1 = self.client.get(DASH, HTTP_X_FORWARDED_FOR=BUKAN_CF)
        self.assertEqual(r1.status_code, 403)
        r2 = self.client.get(DASH, HTTP_X_FORWARDED_FOR=KANTOR_IP)
        self.assertNotEqual(r2.status_code, 403)
        r3 = self.client.get(DASH, HTTP_X_FORWARDED_FOR=BUKAN_CF)
        self.assertEqual(r3.status_code, 403)
        self.assertEqual(AuditLog.objects.filter(aksi="ip_blokir").count(), 2)


class AnonymousTests(TestCase):
    def test_anonymous_login_page_tak_tersentuh(self):
        AllowedIP.objects.create(label="X", cidr=KANTOR_IP)
        r = self.client.get(LOGIN, HTTP_X_FORWARDED_FOR=BUKAN_CF)
        self.assertNotEqual(r.status_code, 403)


class MiddlewareOrderTests(TestCase):
    def test_ip_allowlist_persis_setelah_force_password(self):
        mw = settings.MIDDLEWARE
        i_force = mw.index("web.middleware.ForcePasswordChangeMiddleware")
        i_ip = mw.index("web.middleware.IPAllowlistMiddleware")
        self.assertEqual(i_ip, i_force + 1)


class MustChangePasswordInterplayTests(_Dasar):
    """Interaksi dengan ForcePasswordChangeMiddleware (urutan: ForcePassword
    lebih dulu, IPAllowlist sesudahnya). Perilaku YANG DIAMATI dan sengaja
    dipin: seorang auditor berflag must_change_password yang mengakses dari
    IP tak dipercaya DIALIHKAN dulu ke /ganti-password/ oleh ForcePassword
    (path itu ada di allowlist-nya sendiri), tapi /ganti-password/ TIDAK ada
    di allowlist IPAllowlistMiddleware — jadi GET berikutnya ke sana tetap
    kena 403. Hasil akhir (mengikuti redirect): 403, bukan halaman ganti
    password. Ini disengaja: ganti password dari IP asing tetap digerbang,
    bukan celah untuk melewati allowlist."""

    def test_ganti_password_redirect_tetap_kena_gerbang_ip(self):
        AllowedIP.objects.create(label="X", cidr=KANTOR_IP)
        self.auditor.must_change_password = True
        self.auditor.save(update_fields=["must_change_password"])
        self.client.login(username="aud1", password="pw123456")
        r = self.client.get(DASH, HTTP_X_FORWARDED_FOR=BUKAN_CF, follow=True)
        self.assertEqual(r.status_code, 403)


class BackstopTests(_Dasar):
    """Tanpa XFF sama sekali (dev server telanjang) — REMOTE_ADDR publik tetap
    diblok, REMOTE_ADDR loopback tetap lolos (dev server tak terdampak)."""

    def test_tanpa_xff_ip_publik_diblok(self):
        AllowedIP.objects.create(label="X", cidr=KANTOR_IP)
        self.client.login(username="aud1", password="pw123456")
        r = self.client.get(DASH, REMOTE_ADDR=BUKAN_CF)
        self.assertEqual(r.status_code, 403)

    def test_tanpa_xff_loopback_lolos(self):
        AllowedIP.objects.create(label="X", cidr=KANTOR_IP)
        self.client.login(username="aud1", password="pw123456")
        r = self.client.get(DASH, REMOTE_ADDR="127.0.0.1")
        self.assertNotEqual(r.status_code, 403)


# --- Halaman /kelola/ip/ ----------------------------------------------------

class KelolaIpAksesTests(TestCase):
    def setUp(self):
        User.objects.create_user("aud2", password="pw123456", role="auditor")
        User.objects.create_user("adm2", password="pw123456", role="admin")

    def test_auditor_ditolak(self):
        self.client.login(username="aud2", password="pw123456")
        r = self.client.get(reverse("kelola_ip"), follow=True)
        self.assertContains(r, "Akses ditolak")

    def test_admin_diizinkan(self):
        self.client.login(username="adm2", password="pw123456")
        r = self.client.get(reverse("kelola_ip"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Akses IP")


class KelolaIpCrudTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("adm3", password="pw123456", role="admin")
        self.client.login(username="adm3", password="pw123456")

    def test_create_ip_valid(self):
        self.client.post(reverse("kelola_ip"), {
            "action": "create", "label": "Kantor", "cidr": "203.0.113.7"})
        e = AllowedIP.objects.get(cidr="203.0.113.7")
        self.assertEqual(e.label, "Kantor")
        self.assertTrue(e.aktif)
        self.assertEqual(e.dibuat_oleh, self.admin)
        self.assertTrue(AuditLog.objects.filter(aksi="buat_ip_allow").exists())

    def test_create_cidr_valid(self):
        self.client.post(reverse("kelola_ip"), {
            "action": "create", "label": "Range", "cidr": "198.51.100.0/24"})
        self.assertTrue(AllowedIP.objects.filter(cidr="198.51.100.0/24").exists())

    def test_create_garbage_ditolak(self):
        for bad in ("abc", "300.1.1.1"):
            self.client.post(reverse("kelola_ip"), {"action": "create", "label": "X", "cidr": bad})
        self.assertEqual(AllowedIP.objects.count(), 0)

    def test_create_tanpa_label_ditolak(self):
        self.client.post(reverse("kelola_ip"), {"action": "create", "label": "", "cidr": "203.0.113.7"})
        self.assertEqual(AllowedIP.objects.count(), 0)

    def test_toggle(self):
        e = AllowedIP.objects.create(label="X", cidr="203.0.113.7")
        self.client.post(reverse("kelola_ip"), {"action": "toggle", "ip_id": e.id})
        e.refresh_from_db()
        self.assertFalse(e.aktif)
        self.assertTrue(AuditLog.objects.filter(aksi="toggle_ip_allow").exists())

    def test_delete(self):
        e = AllowedIP.objects.create(label="X", cidr="203.0.113.7")
        self.client.post(reverse("kelola_ip"), {"action": "delete", "ip_id": e.id})
        self.assertFalse(AllowedIP.objects.filter(id=e.id).exists())
        self.assertTrue(AuditLog.objects.filter(aksi="hapus_ip_allow").exists())
