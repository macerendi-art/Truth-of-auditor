"""Log Audit admin: snapshot username, pencatatan aksi kelola, halaman /kelola/log/."""
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.audit import catat
from core.models import AuditLog
from sources.models import Toko

User = get_user_model()


class UsernameSnapshotTests(TestCase):
    def test_catat_menyimpan_snapshot_username(self):
        u = User.objects.create_user("pelaku", password="X-Kuat#88", role="admin")
        catat(u, "buat_user", "target1")
        log = AuditLog.objects.latest("id")
        self.assertEqual(log.username, "pelaku")
        self.assertEqual(log.user_id, u.pk)

    def test_snapshot_hidup_setelah_user_dihapus(self):
        u = User.objects.create_user("pelaku2", password="X-Kuat#88", role="admin")
        catat(u, "hapus_toko", "TOKO X")
        u.delete()
        log = AuditLog.objects.latest("id")
        self.assertIsNone(log.user)  # FK SET_NULL
        self.assertEqual(log.username, "pelaku2")  # identitas tetap hidup


class PencatatanAksiKelolaTests(TestCase):
    """Tiap aksi kelola user/toko + ganti password menulis 1 baris AuditLog."""

    def setUp(self):
        self.adm = User.objects.create_user("adm", password="Adm-Kuat#88", role="admin")
        self.client.login(username="adm", password="Adm-Kuat#88")
        self.lbs = Toko.objects.get(key="lbs")

    def _log(self, aksi):
        return AuditLog.objects.filter(aksi=aksi).latest("id")

    def test_buat_user(self):
        self.client.post(reverse("kelola_user"), {
            "username": "budi", "password": "Budi-Kuat#88", "nama": "Budi",
            "role": "auditor", "tokos": [self.lbs.id],
        })
        log = self._log("buat_user")
        self.assertEqual(log.objek, "budi")
        self.assertEqual(log.username, "adm")
        self.assertEqual(log.detail.get("role"), "auditor")

    def test_ubah_user(self):
        t = User.objects.create_user("tgt", password="Tgt-Kuat#88", role="supervisor")
        self.client.post(reverse("kelola_user_edit", args=[t.pk]), {
            "action": "save", "nama": "Target", "role": "supervisor",
        })
        self.assertEqual(self._log("ubah_user").objek, "tgt")

    def test_reset_password(self):
        t = User.objects.create_user("tgt2", password="Tgt-Kuat#88", role="supervisor")
        self.client.post(reverse("kelola_user_edit", args=[t.pk]), {
            "action": "reset_password", "password": "Baru-Kuat#99",
        })
        self.assertEqual(self._log("reset_password").objek, "tgt2")

    def test_toggle_user(self):
        t = User.objects.create_user("tgt3", password="Tgt-Kuat#88", role="supervisor")
        self.client.post(reverse("kelola_user_edit", args=[t.pk]), {"action": "toggle"})
        self.assertEqual(self._log("nonaktifkan_user").objek, "tgt3")
        self.client.post(reverse("kelola_user_edit", args=[t.pk]), {"action": "toggle"})
        self.assertEqual(self._log("aktifkan_user").objek, "tgt3")

    def test_hapus_user(self):
        t = User.objects.create_user("tgt4", password="Tgt-Kuat#88", role="supervisor")
        self.client.post(reverse("delete_user", args=[t.pk]))
        self.assertEqual(self._log("hapus_user").objek, "tgt4")

    def test_buat_toko(self):
        self.client.post(reverse("kelola_toko"), {
            "action": "create", "kode": "ZZQ", "panel": Toko.PANEL_NEXUS,
            "kepemilikan": Toko.KEPEMILIKAN_PARTNER,
        })
        self.assertEqual(self._log("buat_toko").objek, "ZZQ")
        t = Toko.objects.get(key="zzq")
        self.assertEqual(t.kepemilikan, Toko.KEPEMILIKAN_PARTNER)
    def test_toggle_toko(self):
        t = Toko.objects.create(key="zzt", name="ZZT")
        self.client.post(reverse("kelola_toko"), {"action": "toggle", "toko_id": str(t.id)})
        self.assertEqual(self._log("nonaktifkan_toko").objek, "ZZT")

    def test_hapus_toko(self):
        t = Toko.objects.create(key="zzh", name="ZZH")
        self.client.post(reverse("delete_toko", args=[t.pk]))
        log = self._log("hapus_toko")
        self.assertEqual(log.objek, "ZZH")
        self.assertIn("n_tx", log.detail)

    def test_ganti_password_sendiri(self):
        self.client.post(reverse("ganti_password"), {
            "old_password": "Adm-Kuat#88",
            "new_password1": "Adm-Baru#99", "new_password2": "Adm-Baru#99",
        })
        log = self._log("ganti_password")
        self.assertEqual(log.objek, "adm")
        self.assertEqual(log.username, "adm")


class KelolaLogPageTests(TestCase):
    """Halaman /kelola/log/: khusus admin, filter & search bekerja."""

    def setUp(self):
        self.adm = User.objects.create_user("adm", password="Adm-Kuat#88", role="admin")
        self.spv = User.objects.create_user("spv", password="Spv-Kuat#88", role="supervisor")
        self.lbs = Toko.objects.get(key="lbs")
        catat(self.adm, "buat_user", "budi", role="auditor")
        catat(self.adm, "hapus_batch", "Batch #3", toko=self.lbs, batch_pk=3)
        catat(self.spv, "reconcile", "Batch #4", toko=self.lbs, batch_pk=4)

    def _login_admin(self):
        self.client.login(username="adm", password="Adm-Kuat#88")

    def test_admin_bisa_buka_dan_isi_tampil(self):
        self._login_admin()
        r = self.client.get(reverse("kelola_log"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "budi")
        self.assertContains(r, "Batch #3")
        self.assertContains(r, "adm")

    def test_supervisor_ditolak(self):
        self.client.login(username="spv", password="Spv-Kuat#88")
        r = self.client.get(reverse("kelola_log"))
        self.assertRedirects(r, reverse("dashboard"))

    def test_filter_aksi(self):
        self._login_admin()
        r = self.client.get(reverse("kelola_log"), {"aksi": "buat_user"})
        self.assertContains(r, "budi")
        self.assertNotContains(r, "Batch #3")

    def test_search_q(self):
        self._login_admin()
        r = self.client.get(reverse("kelola_log"), {"q": "Batch #4"})
        self.assertContains(r, "Batch #4")
        self.assertNotContains(r, "budi")

    def test_filter_user(self):
        self._login_admin()
        r = self.client.get(reverse("kelola_log"), {"user": str(self.spv.pk)})
        self.assertContains(r, "Batch #4")
        self.assertNotContains(r, "budi")

    def test_filter_tanggal_kosongkan_masa_depan(self):
        self._login_admin()
        r = self.client.get(reverse("kelola_log"), {"from": "2099-01-01"})
        self.assertContains(r, "Belum ada log")

    def test_link_sidebar_hanya_admin(self):
        self._login_admin()
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, reverse("kelola_log"))
        self.client.login(username="spv", password="Spv-Kuat#88")
        r = self.client.get(reverse("dashboard"))
        self.assertNotContains(r, reverse("kelola_log"))


class AksiLabelAutentikasiTests(TestCase):
    """`AKSI_LABELS` (web/templatetags/web_extras.py) harus mengenal ketiga kode
    aksi autentikasi yang ditulis `web/signals.py` (C6): `login`/`logout`/
    `login_gagal`. Tanpa entri di dict, filter `aksi_label` jatuh ke fallback
    "kode apa adanya" dan halaman /kelola/log/ menampilkan kode mentah alih-
    alih label rapih — inilah yang diuji di sini, langsung lewat filter DAN
    lewat rendering halaman sungguhan."""

    def test_filter_aksi_label_mengenal_ketiga_kode(self):
        from web.templatetags.web_extras import aksi_label, aksi_tone

        self.assertEqual(aksi_label("login"), "Login")
        self.assertEqual(aksi_label("logout"), "Logout")
        self.assertEqual(aksi_label("login_gagal"), "Login gagal")
        # login_gagal harus beda nada dari login sukses — bukan cuma beda label.
        self.assertNotEqual(aksi_tone("login"), aksi_tone("login_gagal"))

    def test_halaman_kelola_log_tampilkan_label_bukan_kode_mentah(self):
        adm = User.objects.create_user("admlbl", password="Adm-Kuat#88", role="admin")
        catat(adm, "login", "admlbl")
        catat(None, "login_gagal", "siapa")
        catat(adm, "logout", "admlbl")
        self.client.login(username="admlbl", password="Adm-Kuat#88")
        r = self.client.get(reverse("kelola_log"))
        self.assertContains(r, "Login gagal")
        self.assertContains(r, "Logout")
        # "Login" bisa jadi substring "Login gagal", jadi diperiksa lewat badge utuh.
        self.assertContains(r, ">Login<")


class IPUserAgentTests(TestCase):
    """C5: `catat(request=...)` merekam IP klien + user-agent di kolom asli
    (bukan `detail`) memakai ULANG resolver anti-spoof `web.middleware`
    (`_client_ip` → XFF paling kiri → `_via_cloudflare` → `_real_client_ip`)."""

    def setUp(self):
        self.adm = User.objects.create_user("admip", password="Adm-Kuat#88", role="admin")

    def test_catat_tanpa_request_tetap_bekerja(self):
        """Kompatibilitas mundur — 48 titik panggil lama tanpa `request` tak boleh pecah."""
        catat(self.adm, "buat_user", "tanpa_request")
        log = AuditLog.objects.filter(aksi="buat_user", objek="tanpa_request").latest("id")
        self.assertIsNone(log.ip)
        self.assertEqual(log.user_agent, "")

    def test_catat_dengan_request_merekam_ip_dan_user_agent(self):
        req = RequestFactory().post(
            "/", REMOTE_ADDR="198.51.100.9", HTTP_USER_AGENT="pytest-agent/1.0",
        )
        catat(self.adm, "buat_user", "dengan_request", request=req)
        log = AuditLog.objects.filter(aksi="buat_user", objek="dengan_request").latest("id")
        self.assertEqual(log.ip, "198.51.100.9")
        self.assertEqual(log.user_agent, "pytest-agent/1.0")

    def test_xff_paling_kiri_dipakai_bukan_remote_addr(self):
        # Sama seperti GeoBlockMiddleware/IPAllowlistMiddleware: XFF disanitasi
        # Railway → elemen PALING KIRI = peer asli, bukan REMOTE_ADDR (hop
        # internal) atau elemen kanan XFF.
        req = RequestFactory().post(
            "/", REMOTE_ADDR="10.0.0.5",
            HTTP_X_FORWARDED_FOR="203.0.113.55, 10.0.0.5",
        )
        catat(self.adm, "buat_user", "via_xff", request=req)
        log = AuditLog.objects.filter(aksi="buat_user", objek="via_xff").latest("id")
        self.assertEqual(log.ip, "203.0.113.55")

    def test_ip_tercatat_untuk_aksi_nyata_lewat_test_client(self):
        """Definisi selesai C5: IP tercatat untuk satu aksi nyata lewat test client."""
        self.client.login(username="admip", password="Adm-Kuat#88")
        self.client.post(
            reverse("ganti_password"),
            {
                "old_password": "Adm-Kuat#88",
                "new_password1": "Adm-Baru#99", "new_password2": "Adm-Baru#99",
            },
            REMOTE_ADDR="203.0.113.7", HTTP_USER_AGENT="pytest-client/1.0",
        )
        log = AuditLog.objects.filter(aksi="ganti_password").latest("id")
        self.assertEqual(log.ip, "203.0.113.7")
        self.assertEqual(log.user_agent, "pytest-client/1.0")

    def test_kolom_ip_tampil_di_halaman_kelola_log(self):
        req = RequestFactory().post("/", REMOTE_ADDR="198.51.100.42")
        catat(self.adm, "buat_user", "punya_ip", request=req)
        self.client.login(username="admip", password="Adm-Kuat#88")
        r = self.client.get(reverse("kelola_log"))
        self.assertContains(r, "198.51.100.42")
