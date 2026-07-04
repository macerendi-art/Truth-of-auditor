"""Kontrak markup untuk modal konfirmasi reusable (ganti confirm() native).

Latar: semua aksi destruktif dulu memakai onsubmit="return confirm(...)".
confirm() native rapuh — sekali user mencentang "jangan tampilkan dialog lagi"
di browser, confirm() langsung return false tanpa tampil sehingga form tak
pernah submit. Kita ganti dengan modal in-app: setiap <form data-confirm="...">
diintersep handler global, ditampilkan kartu konfirmasi, dan hanya form itu yang
disubmit saat user menekan tombol aksi.

Tes di sini menjaga dua hal:
1. Komponen modal + handler global ter-render di app_base untuk halaman login.
2. Semua form destruktif memakai data-confirm dan TIDAK lagi memakai
   onsubmit="return confirm(".
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from reconciliation.engine import run_batch
from reconciliation.models import ToleranceProfile

User = get_user_model()


def _no_native_confirm(html):
    """True bila markup tak lagi memakai onsubmit-confirm native."""
    return 'onsubmit="return confirm(' not in html and "onsubmit='return confirm(" not in html


class ModalComponentRenderTests(TestCase):
    """Modal + handler global harus ada di setiap halaman login-protected."""

    def setUp(self):
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")

    def test_modal_component_terrender_di_app_base(self):
        # dashboard mewakili halaman login-protected mana pun (extends app_base).
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
        # kontainer modal konfirmasi reusable
        self.assertContains(r, 'id="confirm-modal"')
        # handler global yang mengintersep form[data-confirm]
        self.assertContains(r, "data-confirm")

    def test_komentar_template_tidak_bocor_ke_halaman(self):
        # Regresi: {# ... #} Django itu SINGLE-LINE — komentar multi-baris wajib
        # {% comment %}. Yang salah ke-render sebagai teks mentah di atas halaman.
        r = self.client.get(reverse("dashboard"))
        self.assertNotContains(r, "Modal konfirmasi reusable")
        self.assertNotContains(r, "#}")

    def test_tidak_ada_confirm_native_di_app_base(self):
        r = self.client.get(reverse("dashboard"))
        # tak boleh ada pemakaian onsubmit-confirm native di kerangka
        self.assertTrue(_no_native_confirm(r.content.decode()))


class UploadConfirmModalTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.st = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def test_form_bulk_dan_perbaris_pakai_data_confirm(self):
        Upload.objects.create(source_type=self.st, toko=self.lbs, original_name="x.xlsx", rows_parsed=3)
        r = self.client.get(reverse("upload"))
        html = r.content.decode()
        # form bulk & form per-baris memakai data-confirm, bukan confirm() native
        self.assertContains(r, "data-confirm")
        self.assertTrue(_no_native_confirm(html))

    def test_form_bulk_punya_data_confirm_count(self):
        Upload.objects.create(source_type=self.st, toko=self.lbs, original_name="x.xlsx", rows_parsed=3)
        r = self.client.get(reverse("upload"))
        # hitungan dinamis: jumlah checkbox tercentang disisipkan ke pesan
        self.assertContains(r, "data-confirm-count")
        self.assertContains(r, ".upsel:checked")
        # placeholder {n} ada di pesan bulk
        self.assertContains(r, "{n}")


class ReconcileConfirmModalTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get(name="Default")
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def test_reconcile_riwayat_batch_pakai_data_confirm(self):
        run_batch(self.lbs, self.tol)
        r = self.client.get(reverse("reconcile"))
        html = r.content.decode()
        self.assertContains(r, "data-confirm")
        self.assertTrue(_no_native_confirm(html))

    def test_batch_detail_pakai_data_confirm(self):
        b = run_batch(self.lbs, self.tol)
        r = self.client.get(reverse("batch_detail", args=[b.pk]))
        html = r.content.decode()
        self.assertContains(r, "data-confirm")
        self.assertTrue(_no_native_confirm(html))


class KelolaConfirmModalTests(TestCase):
    def setUp(self):
        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.other = User.objects.create_user("other", password="pw123456", role="auditor")
        self.client.login(username="adm", password="pw123456")

    def test_kelola_user_list_pakai_data_confirm(self):
        r = self.client.get(reverse("kelola_user"))
        html = r.content.decode()
        self.assertContains(r, "data-confirm")
        self.assertTrue(_no_native_confirm(html))

    def test_kelola_user_edit_pakai_data_confirm(self):
        r = self.client.get(reverse("kelola_user_edit", args=[self.other.pk]))
        html = r.content.decode()
        # halaman edit punya toggle status + hapus permanen, keduanya destruktif
        self.assertContains(r, "data-confirm")
        self.assertTrue(_no_native_confirm(html))

    def test_kelola_toko_pakai_data_confirm(self):
        r = self.client.get(reverse("kelola_toko"))
        html = r.content.decode()
        self.assertContains(r, "data-confirm")
        self.assertTrue(_no_native_confirm(html))
