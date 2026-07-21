"""Fitur I3 — Alasan pada aksi review Setujui/Tinjau.

Daftar alasan REUSE milik FRKoreksi (web.models) — satu sumber kebenaran.
POST tanpa alasan harus tetap berperilaku persis seperti sebelumnya
(kompatibilitas mundur), alasan hanya lapisan opsional di atasnya.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import (
    MatchResult,
    MatchRun,
    ReconBatch,
    ReviewAction,
    ToleranceProfile,
)
from sources.models import Toko
from web.models import FRKoreksi


def _buat_hasil(toko, tol, n=2, bucket=MatchResult.Bucket.TINJAU):
    """Batch + run + n hasil polos (tanpa transaksi — cukup utk uji view review)."""
    batch = ReconBatch.objects.create(
        toko=toko, tolerance=tol,
        summary={"buckets": {"cocok": 0, "perlu_tinjau": n, "tidak_cocok": 0},
                 "dp": {"panel": 0.0}, "wd": {"panel": 0.0}},
    )
    run = MatchRun.objects.create(
        relation=MatchRun.Relation.PANEL_BANK, tolerance=tol, batch=batch,
        summary={"cocok": 0, "perlu_tinjau": n, "tidak_cocok": 0},
    )
    results = [
        MatchResult.objects.create(run=run, bucket=bucket, reason_code="name_partial")
        for _ in range(n)
    ]
    return batch, run, results


class AlasanReviewSingleTests(TestCase):
    """Aksi review satu baris: simpan alasan (+catatan) opsional ke ReviewAction."""

    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.batch, self.run, (self.r1, self.r2) = _buat_hasil(self.toko, self.tol)
        self.url = reverse("review", args=[self.r1.pk])

    def test_simpan_alasan_dan_catatan(self):
        r = self.client.post(self.url, {
            "action": "mark_matched", "alasan": "mistake_cs", "catatan": "salah input CS",
        })
        self.assertEqual(r.status_code, 200)
        self.r1.refresh_from_db()
        self.assertEqual(self.r1.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(self.r1.reason_code, "manual_override")
        ra = ReviewAction.objects.get(result=self.r1)
        self.assertEqual(ra.alasan, "mistake_cs")
        self.assertEqual(ra.reason, "salah input CS")
        # baris hasil swap HTMX langsung menampilkan chip alasannya
        self.assertContains(r, 'data-alasan="mistake_cs"')
        self.assertContains(r, "Mistake CS")

    def test_tanpa_alasan_tetap_sukses_perilaku_lama(self):
        r = self.client.post(self.url, {"action": "mark_matched"})
        self.assertEqual(r.status_code, 200)
        ra = ReviewAction.objects.get(result=self.r1)
        self.assertEqual(ra.alasan, "")
        self.assertEqual(ra.reason, "")

    def test_alasan_tak_dikenal_ditolak_tanpa_efek(self):
        r = self.client.post(self.url, {"action": "mark_matched", "alasan": "ngawur"})
        self.assertEqual(r.status_code, 400)
        self.r1.refresh_from_db()
        self.assertEqual(self.r1.bucket, MatchResult.Bucket.TINJAU)
        self.assertEqual(ReviewAction.objects.count(), 0)

    def test_semua_kode_frkoreksi_diterima(self):
        """Set kode yang diterima view == persis daftar milik FRKoreksi."""
        for kode, _nama in FRKoreksi.ALASAN_KOREKSI:
            r = self.client.post(self.url, {"action": "mark_review", "alasan": kode})
            self.assertEqual(r.status_code, 200, f"kode {kode} harusnya diterima")
        tersimpan = list(
            ReviewAction.objects.filter(result=self.r1)
            .order_by("id").values_list("alasan", flat=True)
        )
        self.assertEqual(tersimpan, [k for k, _ in FRKoreksi.ALASAN_KOREKSI])


class AlasanFormModalTests(TestCase):
    """Modal kecil per-baris (GET, HTMX) — pilihan identik dgn FRKoreksi + guard toko."""

    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.batch, self.run, (self.r1, self.r2) = _buat_hasil(self.toko, self.tol)

    def test_form_memuat_semua_pilihan_frkoreksi(self):
        url = reverse("review_alasan_form", args=[self.r1.pk])
        r = self.client.get(url + "?action=mark_matched")
        self.assertEqual(r.status_code, 200)
        for kode, nama in FRKoreksi.ALASAN_KOREKSI:
            self.assertContains(r, f'value="{kode}"')
            self.assertContains(r, nama)

    def test_form_aksi_tak_dikenal_ditolak(self):
        url = reverse("review_alasan_form", args=[self.r1.pk])
        r = self.client.get(url + "?action=hapus_semua")
        self.assertEqual(r.status_code, 400)

    def test_form_toko_lain_404(self):
        User = get_user_model()
        aud = User.objects.create_user("aud2", "b@a.co", "pw12345", role="auditor")
        aud.allowed_tokos.add(Toko.objects.get(key="slo"))
        self.client.logout()
        self.client.login(username="aud2", password="pw12345")
        url = reverse("review_alasan_form", args=[self.r1.pk])
        r = self.client.get(url + "?action=mark_matched")
        self.assertEqual(r.status_code, 404)


class AlasanBulkReviewTests(TestCase):
    """Bulk per-run (run_detail): satu alasan untuk semua baris terpilih."""

    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.batch, self.run, self.results = _buat_hasil(self.toko, self.tol, n=3)

    def test_bulk_simpan_alasan_tiap_baris(self):
        ids = [str(r.pk) for r in self.results[:2]]
        r = self.client.post(reverse("bulk_review", args=[self.run.pk]), {
            "action": "mark_matched", "result_ids": ids,
            "alasan": "dana_pending", "catatan": "tunggu settle",
        })
        self.assertEqual(r.status_code, 302)
        for pk in ids:
            ra = ReviewAction.objects.get(result_id=pk)
            self.assertEqual(ra.alasan, "dana_pending")
            self.assertEqual(ra.reason, "tunggu settle")

    def test_bulk_tanpa_alasan_tetap_sukses_perilaku_lama(self):
        ids = [str(self.results[0].pk)]
        r = self.client.post(reverse("bulk_review", args=[self.run.pk]),
                             {"action": "mark_matched", "result_ids": ids})
        self.assertEqual(r.status_code, 302)
        ra = ReviewAction.objects.get(result_id=ids[0])
        self.assertEqual(ra.alasan, "")
        self.assertEqual(ra.reason, "bulk")  # penanda lama dipertahankan

    def test_bulk_alasan_tak_dikenal_ditolak(self):
        ids = [str(self.results[0].pk)]
        r = self.client.post(reverse("bulk_review", args=[self.run.pk]),
                             {"action": "mark_matched", "result_ids": ids,
                              "alasan": "ngawur"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(ReviewAction.objects.count(), 0)
        self.results[0].refresh_from_db()
        self.assertEqual(self.results[0].bucket, MatchResult.Bucket.TINJAU)


class AlasanBulkQueueTests(TestCase):
    """Bulk lintas-run dari Area Pengecekan (/tinjau/)."""

    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        _, self.run1, (self.ra1, _) = _buat_hasil(self.toko, self.tol)
        _, self.run2, (self.rb1, _) = _buat_hasil(self.toko, self.tol)

    def test_bulk_queue_simpan_alasan_lintas_run(self):
        ids = [str(self.ra1.pk), str(self.rb1.pk)]
        r = self.client.post(reverse("bulk_review_queue"), {
            "action": "mark_matched", "result_ids": ids,
            "alasan": "cutoff_mutation",
        })
        self.assertEqual(r.status_code, 302)
        for pk in ids:
            ra = ReviewAction.objects.get(result_id=pk)
            self.assertEqual(ra.alasan, "cutoff_mutation")
            self.assertEqual(ra.reason, "bulk")  # tanpa catatan -> penanda lama

    def test_bulk_queue_tanpa_alasan_tetap_sukses(self):
        r = self.client.post(reverse("bulk_review_queue"), {
            "action": "mark_review", "result_ids": [str(self.ra1.pk)],
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(ReviewAction.objects.get(result=self.ra1).alasan, "")

    def test_bulk_queue_alasan_tak_dikenal_ditolak(self):
        r = self.client.post(reverse("bulk_review_queue"), {
            "action": "mark_matched", "result_ids": [str(self.ra1.pk)],
            "alasan": "ngawur",
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(ReviewAction.objects.count(), 0)


class AlasanTampilTests(TestCase):
    """Alasan tersimpan tampil sebagai chip di run_detail & Area Pengecekan."""

    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.batch, self.run, (self.r1, self.r2) = _buat_hasil(self.toko, self.tol)

    def test_chip_alasan_di_run_detail(self):
        self.client.post(reverse("review", args=[self.r1.pk]),
                         {"action": "mark_matched", "alasan": "mistake_cs"})
        r = self.client.get(reverse("run_detail", args=[self.run.pk]))
        self.assertEqual(r.status_code, 200)
        # chip punya data-alasan (opsi <select> modal tidak) — bukti tampil di baris
        self.assertContains(r, 'data-alasan="mistake_cs"')

    def test_chip_alasan_di_area_pengecekan(self):
        # override ke perlu_tinjau supaya tetap di tab default Area Pengecekan
        self.client.post(reverse("review", args=[self.r1.pk]),
                         {"action": "mark_review", "alasan": "bank_title_beda"})
        sesi = self.client.session
        sesi["active_toko_id"] = self.toko.id
        sesi.save()
        r = self.client.get(reverse("review_queue"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-alasan="bank_title_beda"')

    def test_baris_tanpa_alasan_tanpa_chip(self):
        self.client.post(reverse("review", args=[self.r1.pk]), {"action": "mark_matched"})
        r = self.client.get(reverse("run_detail", args=[self.run.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "data-alasan=")

    def test_modal_bulk_ada_di_kedua_halaman(self):
        r = self.client.get(reverse("run_detail", args=[self.run.pk]))
        self.assertContains(r, 'id="bulkPop"')
        self.assertContains(r, "Cutoff Mutation")
        sesi = self.client.session
        sesi["active_toko_id"] = self.toko.id
        sesi.save()
        r = self.client.get(reverse("review_queue"))
        self.assertContains(r, 'id="bulkPop"')
        self.assertContains(r, "Cutoff Mutation")


class HtmxTrFragmenTests(TestCase):
    """Regresi parsing htmx: respons `review` = fragmen <tr> + div OOB penutup modal.

    htmx 1.9.12 default (useTemplateFragments=false) membungkus respons ber-awalan
    <tr> dengan <table><tbody> lalu descend 2 level; parser HTML5 mem-foster-parent
    div non-tabel keluar tabel sehingga hasil parse jadi fragmen KOSONG — baris
    hasil lenyap dari tabel dan modal alasan tak pernah tertutup, padahal POST
    sukses (klik ulang = ReviewAction ganda). Wajib dua-duanya: config
    useTemplateFragments aktif di halaman pemuat baris, dan respons review tetap
    memuat <tr id="res-..."> + div OOB.
    """

    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.batch, self.run, (self.r1, self.r2) = _buat_hasil(self.toko, self.tol)

    def test_respons_review_baris_plus_oob_penutup_modal(self):
        r = self.client.post(reverse("review", args=[self.r1.pk]),
                             {"action": "mark_matched", "alasan": "mistake_cs"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f'id="res-{self.r1.pk}"')
        self.assertContains(r, 'id="reviewPop" hx-swap-oob="innerHTML"')

    def test_config_template_fragments_di_halaman_hasil(self):
        """Meta htmx-config useTemplateFragments wajib ada di run_detail & /tinjau/."""
        r = self.client.get(reverse("run_detail", args=[self.run.pk]))
        self.assertContains(r, 'name="htmx-config"')
        self.assertContains(r, '"useTemplateFragments":true')
        sesi = self.client.session
        sesi["active_toko_id"] = self.toko.id
        sesi.save()
        r = self.client.get(reverse("review_queue"))
        self.assertContains(r, 'name="htmx-config"')
        self.assertContains(r, '"useTemplateFragments":true')
