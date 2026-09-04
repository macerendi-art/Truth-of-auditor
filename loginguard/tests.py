"""C4: pembatas percobaan login (lockout per username+IP).

Cakupan (definisi selesai butir a):
  - N percobaan salah -> terkunci (sandi benar pun ditolak selama terkunci).
  - Login benar sebelum ambang -> lolos, DAN mereset hitungan.
  - Kunci kedaluwarsa -> percobaan berikutnya diperlakukan sebagai jendela baru.
  - Jalur pemulihan admin (management command) bekerja tanpa HTTP.
Plus: partisi (username, ip) yang benar, kill switch, klem ambang, non-leak
pesan, dan kompatibilitas sesi lama (dua-backend, bukan satu).
"""
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import LoginAttempt
from .throttle import (
    RETENSI_BARIS, bersihkan_kedaluwarsa, buka_kunci, is_locked, kunci_username,
    register_failure, register_success,
)

User = get_user_model()


def _req(ip="203.0.113.9"):
    return RequestFactory().post("/masuk/", REMOTE_ADDR=ip)


class ThrottleUnitTests(TestCase):
    """Unit langsung atas `loginguard.throttle` — tanpa HTTP, tanpa backend.

    `pemakai`/`lain` dibuat sebagai User sungguhan supaya kunci barisnya
    tetap terbaca ("pemakai"); username lain di tes ini (x/y/z/a/b/...) TIDAK
    punya User dan sengaja dibiarkan lewat jalur hash `?...` (P4) — asersinya
    lewat `is_locked`, bukan `LoginAttempt.objects.get(username=...)`."""

    def setUp(self):
        User.objects.create_user("pemakai", password="Pw-Kuat#88", role="auditor")
        User.objects.create_user("lain", password="Pw-Kuat#88", role="auditor")

    # ---- P4: ketikan kolom username tak pernah mendarat di tabel ----------

    def test_username_dikenal_disimpan_kanonik_lowercase(self):
        self.assertEqual(kunci_username("  PemakaI "), "pemakai")

    def test_username_tak_dikenal_disimpan_sebagai_hash_bukan_ketikan(self):
        # Skenario nyata: kata sandi diketik di kolom username. Penguncian
        # harus tetap bekerja (non-leak), tapi string-nya tak boleh ada di
        # kolom mana pun.
        salah_kolom = "Spv-Kuat#88"
        for _ in range(5):
            register_failure(salah_kolom, "203.0.113.9")
        self.assertTrue(is_locked(salah_kolom, "203.0.113.9"))
        self.assertTrue(is_locked(" spv-kuat#88 ", "203.0.113.9"))  # normalisasi sama
        for baris in LoginAttempt.objects.all():
            self.assertNotIn("spv-kuat", baris.username.lower())
            self.assertTrue(baris.username.startswith("?"), baris.username)
        self.assertEqual(LoginAttempt.objects.count(), 1)

    def test_kunci_username_deterministik_dan_tak_idempoten(self):
        k1 = kunci_username("tidak-ada")
        self.assertEqual(k1, kunci_username("TIDAK-ADA"))
        self.assertTrue(k1.startswith("?"))
        # Kunci yang sudah dipetakan BUKAN input yang sah untuk dipetakan lagi
        # (docstring kunci_username) — dijaga supaya tak ada yang "menghemat
        # query" dengan meneruskan kunci alih-alih username mentah.
        self.assertNotEqual(kunci_username(k1), k1)

    def test_buka_kunci_username_tak_dikenal_lewat_pemetaan_yang_sama(self):
        for _ in range(5):
            register_failure("tidak-ada", "1.1.1.1")
        self.assertTrue(is_locked("tidak-ada", "1.1.1.1"))
        self.assertEqual(buka_kunci(username="Tidak-Ada"), 1)
        self.assertFalse(is_locked("tidak-ada", "1.1.1.1"))

    # ---- P5(b): purge baris mati -------------------------------------------

    def test_bersihkan_kedaluwarsa_buang_baris_basi_simpan_kunci_aktif(self):
        now = timezone.now()
        basi = now - RETENSI_BARIS - timedelta(minutes=1)
        # updated_at auto_now: timpa lewat update() supaya nilainya masa lalu.
        LoginAttempt.objects.create(username="?basi", ip="1.1.1.1", fail_count=2)
        LoginAttempt.objects.create(
            username="?basi-kunci-lewat", ip="1.1.1.1", fail_count=5,
            locked_until=now - timedelta(hours=1),
        )
        LoginAttempt.objects.create(
            username="?basi-tapi-masih-terkunci", ip="1.1.1.1", fail_count=5,
            locked_until=now + timedelta(days=2),   # LOGIN_LOCKOUT_MINUTES besar
        )
        LoginAttempt.objects.create(username="?segar", ip="1.1.1.1", fail_count=1)
        LoginAttempt.objects.filter(username__startswith="?basi").update(updated_at=basi)

        jumlah = bersihkan_kedaluwarsa(now=now)

        self.assertEqual(jumlah, 2)
        sisa = set(LoginAttempt.objects.values_list("username", flat=True))
        self.assertEqual(sisa, {"?basi-tapi-masih-terkunci", "?segar"})

    def test_register_success_ikut_membersihkan_baris_basi(self):
        LoginAttempt.objects.create(username="?basi", ip="9.9.9.9", fail_count=1)
        LoginAttempt.objects.filter(username="?basi").update(
            updated_at=timezone.now() - RETENSI_BARIS - timedelta(minutes=1)
        )
        register_failure("pemakai", "1.1.1.1")
        register_success("pemakai", "1.1.1.1")
        self.assertEqual(LoginAttempt.objects.count(), 0)

    def test_register_success_tetap_sukses_bila_pembersihan_gagal(self):
        register_failure("pemakai", "1.1.1.1")
        with mock.patch(
            "loginguard.throttle.bersihkan_kedaluwarsa", side_effect=RuntimeError("db")
        ), self.assertLogs("loginguard.throttle", level="ERROR"):
            register_success("pemakai", "1.1.1.1")   # tidak melempar, tapi BERSUARA
        self.assertFalse(LoginAttempt.objects.filter(username="pemakai").exists())

    def test_belum_ada_baris_tidak_terkunci(self):
        self.assertFalse(is_locked("siapa", "203.0.113.9"))

    def test_gagal_di_bawah_ambang_tidak_terkunci(self):
        for _ in range(4):  # default THRESHOLD=5 -> 4 gagal belum mengunci
            register_failure("pemakai", "203.0.113.9")
        self.assertFalse(is_locked("pemakai", "203.0.113.9"))
        self.assertEqual(
            LoginAttempt.objects.get(username="pemakai", ip="203.0.113.9").fail_count, 4
        )

    def test_gagal_capai_ambang_mengunci(self):
        for _ in range(5):
            register_failure("pemakai", "203.0.113.9")
        self.assertTrue(is_locked("pemakai", "203.0.113.9"))

    @override_settings(LOGIN_LOCKOUT_THRESHOLD=2)
    def test_ambang_bisa_diatur_env(self):
        register_failure("x", "1.2.3.4")
        self.assertFalse(is_locked("x", "1.2.3.4"))
        register_failure("x", "1.2.3.4")
        self.assertTrue(is_locked("x", "1.2.3.4"))

    @override_settings(LOGIN_LOCKOUT_THRESHOLD=0)
    def test_ambang_nol_diklem_ke_satu_bukan_mengunci_semua_di_percobaan_pertama(self):
        # Persyaratan: ambang salah-ketik (0/negatif) tidak boleh mengunci
        # SEMUA orang pada percobaan pertama tanpa toleransi sama sekali --
        # tapi tetap sah untuk mengunci setelah tepat 1 kegagalan (klem ke 1,
        # bukan diam-diam dinaikkan ke default 5).
        self.assertFalse(is_locked("y", "1.2.3.4"))
        register_failure("y", "1.2.3.4")
        self.assertTrue(is_locked("y", "1.2.3.4"))

    @override_settings(LOGIN_LOCKOUT_THRESHOLD=-3)
    def test_ambang_negatif_diklem_ke_satu(self):
        register_failure("z", "1.2.3.4")
        self.assertTrue(is_locked("z", "1.2.3.4"))

    def test_sukses_mereset_hitungan(self):
        for _ in range(3):
            register_failure("pemakai", "203.0.113.9")
        register_success("pemakai", "203.0.113.9")
        self.assertFalse(
            LoginAttempt.objects.filter(username="pemakai", ip="203.0.113.9").exists()
        )
        self.assertFalse(is_locked("pemakai", "203.0.113.9"))

    def test_username_dinormalisasi_kapitalisasi_tidak_membuka_celah(self):
        for _ in range(5):
            register_failure("Pemakai", "203.0.113.9")
        self.assertTrue(is_locked("pemakai", "203.0.113.9"))
        self.assertTrue(is_locked("PEMAKAI", "203.0.113.9"))

    def test_partisi_per_username_dan_ip_bukan_gabungan(self):
        for _ in range(5):
            register_failure("pemakai", "1.1.1.1")
        # IP lain, username sama -> TIDAK ikut terkunci (auditor kantor lain
        # berbagi username institusional tak boleh kena imbas).
        self.assertFalse(is_locked("pemakai", "2.2.2.2"))
        # Username lain, IP sama -> TIDAK ikut terkunci (satu IP kantor tak
        # boleh dianggap satu identitas jahat).
        self.assertFalse(is_locked("pemakai_lain", "1.1.1.1"))

    def test_kunci_kedaluwarsa_mulai_jendela_baru(self):
        obj = LoginAttempt.objects.create(
            username="pemakai", ip="203.0.113.9",
            fail_count=5, locked_until=timezone.now() - timedelta(minutes=1),
        )
        self.assertFalse(is_locked("pemakai", "203.0.113.9"))  # kedaluwarsa
        register_failure("pemakai", "203.0.113.9")
        obj.refresh_from_db()
        # Direset ke 0 lalu +1 -- BUKAN 6 (jendela lama tidak nyambung ke baru).
        self.assertEqual(obj.fail_count, 1)
        self.assertIsNone(obj.locked_until)
        self.assertFalse(is_locked("pemakai", "203.0.113.9"))

    @override_settings(LOGIN_LOCKOUT_ENABLED=False)
    def test_kill_switch_mematikan_penguncian_total(self):
        for _ in range(10):
            register_failure("pemakai", "203.0.113.9")
        self.assertFalse(is_locked("pemakai", "203.0.113.9"))

    def test_buka_kunci_satu_username_semua_ip(self):
        register_failure("pemakai", "1.1.1.1")
        register_failure("pemakai", "2.2.2.2")
        register_failure("lain", "1.1.1.1")
        jumlah = buka_kunci(username="pemakai")
        self.assertEqual(jumlah, 2)
        self.assertFalse(LoginAttempt.objects.filter(username="pemakai").exists())
        self.assertTrue(LoginAttempt.objects.filter(username="lain").exists())

    def test_buka_kunci_semua(self):
        register_failure("a", "1.1.1.1")
        register_failure("b", "2.2.2.2")
        jumlah = buka_kunci(username=None)
        self.assertEqual(jumlah, 2)
        self.assertEqual(LoginAttempt.objects.count(), 0)


class BackendTests(TestCase):
    """`loginguard.backends.LockoutBackend` lewat `django.contrib.auth.authenticate()`."""

    def setUp(self):
        self.user = User.objects.create_user(
            "pemakai", password="Pw-Kuat#88", role="auditor"
        )

    def test_login_benar_sebelum_ambang_lolos(self):
        for _ in range(3):
            self.assertIsNone(
                authenticate(_req(), username="pemakai", password="salah")
            )
        user = authenticate(_req(), username="pemakai", password="Pw-Kuat#88")
        self.assertEqual(user, self.user)

    def test_n_percobaan_salah_mengunci_lalu_sandi_benar_pun_ditolak(self):
        for _ in range(5):
            authenticate(_req(), username="pemakai", password="salah")
        user = authenticate(_req(), username="pemakai", password="Pw-Kuat#88")
        self.assertIsNone(user)  # terkunci -> sandi benar pun ditolak

    def test_login_sukses_mereset_hitungan_untuk_percobaan_berikutnya(self):
        for _ in range(4):
            authenticate(_req(), username="pemakai", password="salah")
        self.assertIsNotNone(
            authenticate(_req(), username="pemakai", password="Pw-Kuat#88")
        )
        # Setelah sukses, 4 kegagalan BARU lagi (bukan 4+4=8) belum mengunci.
        for _ in range(4):
            authenticate(_req(), username="pemakai", password="salah")
        self.assertIsNotNone(
            authenticate(_req(), username="pemakai", password="Pw-Kuat#88")
        )

    def test_ip_berbeda_tidak_ikut_terkunci(self):
        for _ in range(5):
            authenticate(_req(ip="9.9.9.9"), username="pemakai", password="salah")
        user = authenticate(_req(ip="8.8.8.8"), username="pemakai", password="Pw-Kuat#88")
        self.assertEqual(user, self.user)

    def test_username_tak_dikenal_juga_ikut_terkunci_setelah_ambang(self):
        # Penting untuk non-leak: username palsu HARUS ikut kena pola yang
        # sama seperti username asli, supaya "terkunci" tidak jadi oracle
        # keberadaan akun.
        for _ in range(5):
            self.assertIsNone(
                authenticate(_req(), username="tidak-ada", password="apa-saja")
            )
        self.assertTrue(is_locked("tidak-ada", "203.0.113.9"))

    def test_kill_switch_mematikan_pengecekan_di_backend(self):
        with override_settings(LOGIN_LOCKOUT_ENABLED=False):
            for _ in range(10):
                authenticate(_req(), username="pemakai", password="salah")
            user = authenticate(_req(), username="pemakai", password="Pw-Kuat#88")
        self.assertEqual(user, self.user)

    def test_signal_login_gagal_tidak_terkirim_dobel(self):
        # Modul ini MURNI memblokir; pencatatan audit (C6) ada di
        # web/signals.py lewat sinyal `user_login_failed` yang dikirim
        # django.contrib.auth.authenticate() SENDIRI -- pastikan backend ini
        # tidak ikut mengirim sinyal itu sendiri (tidak dobel).
        from django.contrib.auth.signals import user_login_failed

        panggilan = []

        def _tangkap(**kw):
            panggilan.append(kw)

        # weak=False: receiver lokal (bukan method terikat objek hidup)
        # akan langsung tergarbage-collect kalau dihubungkan sbg weak ref.
        user_login_failed.connect(_tangkap, dispatch_uid="tes-dobel", weak=False)
        try:
            authenticate(_req(), username="pemakai", password="salah")
        finally:
            user_login_failed.disconnect(dispatch_uid="tes-dobel")
        self.assertEqual(len(panggilan), 1)


class HashSekaliTests(TestCase):
    """P5(a): sandi salah di-hash SATU kali, bukan dua.

    Sebelum perbaikan, `LockoutBackend` mengembalikan None → `authenticate()`
    lanjut ke `ModelBackend` kedua yang meng-hash sandi yang sama lagi
    (user ada: `check_password`; user tak ada: dummy `make_password` untuk
    menyamakan waktu). Keduanya dihitung lewat nama yang diimpor
    `django.contrib.auth.base_user`, tempat `AbstractBaseUser` memanggilnya."""

    def setUp(self):
        self.user = User.objects.create_user(
            "pemakai", password="Pw-Kuat#88", role="auditor"
        )

    def _hitung(self, nama, **cred):
        target = f"django.contrib.auth.base_user.{nama}"
        import django.contrib.auth.base_user as bu
        asli = getattr(bu, nama)
        with mock.patch(target, wraps=asli) as m:
            hasil = authenticate(_req(), **cred)
        return hasil, m.call_count

    def test_sandi_salah_user_ada_hash_sekali(self):
        hasil, n = self._hitung("check_password", username="pemakai", password="salah")
        self.assertIsNone(hasil)
        self.assertEqual(n, 1)

    def test_username_tak_dikenal_dummy_hash_sekali(self):
        hasil, n = self._hitung("make_password", username="tidak-ada", password="salah")
        self.assertIsNone(hasil)
        self.assertEqual(n, 1)

    @override_settings(LOGIN_LOCKOUT_ENABLED=False)
    def test_kill_switch_mati_tetap_hash_sekali(self):
        hasil, n = self._hitung("check_password", username="pemakai", password="salah")
        self.assertIsNone(hasil)
        self.assertEqual(n, 1)

    def test_sandi_benar_tetap_lolos_dan_hash_sekali(self):
        hasil, n = self._hitung("check_password", username="pemakai", password="Pw-Kuat#88")
        self.assertEqual(hasil, self.user)
        self.assertEqual(n, 1)


class HttpLoginTests(TestCase):
    """End-to-end lewat `reverse('login')` -- pesan tidak boleh membedakan
    sandi-salah vs terkunci vs username tak dikenal (persyaratan butir 4)."""

    def setUp(self):
        self.user = User.objects.create_user(
            "pemakai", password="Pw-Kuat#88", role="auditor"
        )
        self.client = Client()

    def _post(self, username, password, ip="203.0.113.9"):
        return self.client.post(
            reverse("login"), {"username": username, "password": password},
            REMOTE_ADDR=ip,
        )

    def test_login_benar_tetap_redirect_seperti_biasa(self):
        r = self._post("pemakai", "Pw-Kuat#88")
        self.assertEqual(r.status_code, 302)

    def test_pesan_sandi_salah_dan_terkunci_identik(self):
        r_salah = self._post("pemakai", "salah", ip="198.51.100.1")
        self.assertContains(r_salah, "Username atau password salah. Coba lagi.")

        for _ in range(5):
            r_lock = self._post("pemakai", "salah", ip="198.51.100.2")
        # Bahkan sandi BENAR pun kena pesan yang SAMA selama terkunci.
        r_lock_pw_benar = self._post("pemakai", "Pw-Kuat#88", ip="198.51.100.2")
        self.assertContains(r_lock_pw_benar, "Username atau password salah. Coba lagi.")
        self.assertEqual(r_salah.status_code, r_lock_pw_benar.status_code)
        # Isi HTML halaman error identik pada kedua kasus (tidak ada penanda
        # "terkunci" tambahan yang membedakan dari sandi-salah biasa).
        self.assertEqual(
            r_salah.content.count(b'class="err"'),
            r_lock_pw_benar.content.count(b'class="err"'),
        )

    def test_username_tak_dikenal_pesan_sama_dengan_sandi_salah(self):
        r_tak_dikenal = self._post("tidak-terdaftar", "apa-saja", ip="198.51.100.3")
        r_salah = self._post("pemakai", "salah", ip="198.51.100.3")
        self.assertContains(r_tak_dikenal, "Username atau password salah. Coba lagi.")
        self.assertContains(r_salah, "Username atau password salah. Coba lagi.")


class PemulihanCommandTests(TestCase):
    """Jalur pemulihan admin (butir 2 & definisi-selesai butir d) -- SAMA
    SEKALI tanpa HTTP: langsung lewat ORM via management command."""

    def setUp(self):
        self.user = User.objects.create_user(
            "admin1", password="Pw-Kuat#88", role="admin", is_superuser=True
        )

    def test_buka_kunci_login_memulihkan_akun_terkunci(self):
        for _ in range(5):
            authenticate(_req(), username="admin1", password="salah")
        self.assertIsNone(
            authenticate(_req(), username="admin1", password="Pw-Kuat#88")
        )  # masih terkunci

        out = StringIO()
        call_command("buka_kunci_login", "admin1", stdout=out)
        self.assertIn("admin1", out.getvalue())

        user = authenticate(_req(), username="admin1", password="Pw-Kuat#88")
        self.assertEqual(user, self.user)

    def test_buka_kunci_login_semua(self):
        for _ in range(5):
            authenticate(_req(), username="admin1", password="salah")
        out = StringIO()
        call_command("buka_kunci_login", "--semua", stdout=out)
        user = authenticate(_req(), username="admin1", password="Pw-Kuat#88")
        self.assertEqual(user, self.user)

    def test_tanpa_argumen_menolak(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("buka_kunci_login")

    def test_username_dan_semua_bersamaan_menolak(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("buka_kunci_login", "admin1", "--semua")


class SesiLamaKompatibelTests(TestCase):
    """Persyaratan butir 3 (nol perubahan perilaku login benar) diperluas ke
    SESI yang sudah ada: `AUTHENTICATION_BACKENDS` WAJIB tetap memuat
    `ModelBackend` bawaan (bukan diganti total oleh `LockoutBackend`),
    supaya sesi produksi yang sudah login sebelum deploy ini tidak ikut
    ter-logout paksa (`django.contrib.auth.get_user()` menolak sesi bila
    `backend_path` tersimpannya tak lagi ada di `AUTHENTICATION_BACKENDS`)."""

    def test_modelbackend_bawaan_tetap_terdaftar(self):
        from django.conf import settings

        self.assertIn(
            "django.contrib.auth.backends.ModelBackend",
            settings.AUTHENTICATION_BACKENDS,
        )

    def test_sesi_dengan_backend_lama_tetap_valid(self):
        # Uji mekanisme PERSIS yang jadi alasan dua-backend (bukan mengganti
        # AUTHENTICATION_BACKENDS total): django.contrib.auth.get_user()
        # membaca `_auth_user_backend` dari sesi dan menolaknya jadi anonim
        # bila path itu sudah tak terdaftar. Sesi ini dibuat manual dengan
        # backend_path LAMA -- seolah dibuat SEBELUM loginguard dipasang --
        # tanpa bergantung pada view/fixture Toko apa pun.
        from django.contrib.auth import get_user as auth_get_user
        from django.contrib.sessions.backends.db import SessionStore

        user = User.objects.create_user(
            "pemakai", password="Pw-Kuat#88", role="auditor"
        )
        session = SessionStore()
        session["_auth_user_id"] = str(user.pk)
        session["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
        session["_auth_user_hash"] = user.get_session_auth_hash()
        session.save()

        request = RequestFactory().get("/")
        request.session = session
        resolved = auth_get_user(request)
        self.assertTrue(resolved.is_authenticated)
        self.assertEqual(resolved.pk, user.pk)
