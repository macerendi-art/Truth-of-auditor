"""Versi aplikasi yang terlihat pengguna: halaman /versi/, badge sidebar,
footer login, dan stempel versi di workbook ekspor.

Kalau nomor versi berhenti muncul di UI, laporan kendala dari tim auditor jadi
tak bisa dipetakan ke rilis mana pun — makanya keempat titik itu dijaga tes.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from core import version as v
from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import Toko
from web.exports import build_batch_workbook

User = get_user_model()


class RiwayatVersiAksesTests(TestCase):
    def test_wajib_login(self):
        r = self.client.get(reverse("riwayat_versi"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])


class RiwayatVersiHalamanTests(TestCase):
    def setUp(self):
        User.objects.create_user("adm", password="pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")
        self.resp = self.client.get(reverse("riwayat_versi"))

    def test_render_sukses(self):
        self.assertEqual(self.resp.status_code, 200)
        self.assertTemplateUsed(self.resp, "web/versi.html")

    def test_menampilkan_versi_berjalan(self):
        self.assertContains(self.resp, f"v{v.versi()}")
        # Nama rilis bisa memuat "&" → template meng-escape-nya (lihat
        # test_menampilkan_semua_rilis), jadi pembanding ikut di-escape.
        self.assertContains(self.resp, escape(v.rilis_terbaru().nama))

    def test_menampilkan_semua_rilis(self):
        # Nama rilis memuat "&" (mis. "Kode Unik & Kunci Wilayah") → template
        # meng-escape-nya, jadi pembanding ikut di-escape.
        html = self.resp.content.decode()
        for r in v.RILIS:
            self.assertIn(r.label, html, f"{r.label} tidak muncul di halaman")
            self.assertIn(escape(r.nama), html, f"nama rilis {r.label} tidak muncul")

    def test_menampilkan_butir_sorotan(self):
        html = self.resp.content.decode()
        for r in v.RILIS:
            potongan = escape(r.sorotan[0][:40])
            self.assertIn(potongan, html, f"sorotan {r.label} hilang: {potongan!r}")

    def test_menampilkan_hitungan_jenis_rilis(self):
        n = v.ringkasan_jumlah()
        self.assertContains(self.resp, "Rilis besar")
        self.assertContains(self.resp, "Rilis fitur")
        self.assertContains(self.resp, str(len(v.RILIS)))
        self.assertEqual(sum(n.values()), len(v.RILIS))

    def test_urutan_terbaru_di_atas(self):
        html = self.resp.content.decode()
        # Nama di-escape template (mis. "&" → "&amp;") — cari bentuk escape-nya.
        baru, lama = escape(v.RILIS[0].nama), escape(v.RILIS[-1].nama)
        self.assertLess(html.index(baru), html.index(lama))


class BadgeVersiTests(TestCase):
    def setUp(self):
        User.objects.create_user("adm", password="pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")

    def test_sidebar_menampilkan_versi_dan_tautan(self):
        r = self.client.get(reverse("riwayat_versi"))
        self.assertContains(r, f'href="{reverse("riwayat_versi")}"')
        self.assertContains(r, v.versi())

    def test_context_processor_terpasang(self):
        r = self.client.get(reverse("riwayat_versi"))
        self.assertEqual(r.context["app_versi"], v.versi())
        self.assertEqual(r.context["app_rilis"], v.rilis_terbaru())


class SidebarTakPernahTerpotongTests(TestCase):
    """Menu samping bertambah tiap rilis; badge versi sempat mendorong tombol
    Keluar keluar layar di laptop 720px. Perbaikannya: daftar menu dibungkus
    `.nav` yang bergulir sendiri, sedangkan badge versi + identitas pengguna
    berada DI LUAR bungkus itu sehingga selalu menempel di bawah.
    """

    def setUp(self):
        User.objects.create_user("adm", password="pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")
        self.html = self.client.get(reverse("riwayat_versi")).content.decode()

    def test_daftar_menu_dibungkus_nav(self):
        self.assertIn('<div class="nav">', self.html)

    def test_versi_dan_identitas_di_luar_bungkus_bergulir(self):
        tutup_nav = self.html.index("</div>\n  <a class=\"ver\"")
        self.assertLess(
            self.html.index('<div class="nav">'), tutup_nav,
            "bungkus .nav harus dibuka sebelum ditutup",
        )
        self.assertLess(
            tutup_nav, self.html.index('<div class="who">'),
            "identitas pengguna harus berada SETELAH bungkus .nav ditutup, "
            "kalau tidak ia ikut tergulir dan bisa hilang dari layar",
        )


class LoginFooterVersiTests(TestCase):
    def test_halaman_login_menyebut_versi(self):
        """Versi harus terbaca SEBELUM login — tim bisa melapor tanpa masuk dulu."""
        r = self.client.get(reverse("login"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f"v{v.versi()}")


class StempelVersiExportTests(TestCase):
    def test_sheet_ringkasan_memuat_versi_aplikasi(self):
        toko = Toko.objects.get(key="lbs")
        tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        batch = ReconBatch.objects.create(
            toko=toko, tolerance=tol, recon_date=date(2026, 7, 25), summary={}
        )
        wb = build_batch_workbook(batch, 1, ("Kiri", "Kanan"))
        ws = wb["Ringkasan"]
        label = [row[0] for row in ws.iter_rows(values_only=True)]
        nilai = {row[0]: row[1] for row in ws.iter_rows(values_only=True)}
        self.assertIn("Versi aplikasi", label)
        self.assertEqual(nilai["Versi aplikasi"], f"v{v.versi()}")
