"""Halaman /tokos/: ringkasan semua toko (scoped), urut selisih, tombol Buka."""
from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from reconciliation.engine import _carried_results, pending_settlement_count
from reconciliation.models import MatchResult, ReconBatch, ToleranceProfile
from sources.models import Toko
from web.tests_settlement import _SettleData

User = get_user_model()


class TokoOverviewTests(TestCase):
    def setUp(self):
        User.objects.create_user("adm", password="pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")

    def _batch(self, toko, dp_selisih, d):
        return ReconBatch.objects.create(
            toko=toko, tolerance=self.tol, recon_date=d,
            summary={"dp": {"selisih": dp_selisih}, "wd": {"selisih": 0}},
        )

    def test_urut_selisih_terbesar_dulu(self):
        self._batch(self.lbs, 1000, date(2026, 6, 27))
        self._batch(self.slo, 9_000_000, date(2026, 6, 27))
        r = self.client.get(reverse("toko_overview"))
        html = r.content.decode()
        # target sel tabel (<b>…</b>), bukan dropdown toko di topbar
        self.assertLess(html.index("<b>SLO</b>"), html.index("<b>LBS</b>"))

    def test_toko_tanpa_batch_belum_rekon(self):
        r = self.client.get(reverse("toko_overview"))
        self.assertContains(r, "belum rekon")

    def test_rbac_auditor_hanya_tokonya(self):
        u = User.objects.create_user("a2", password="pw12345", role="auditor")
        u.allowed_tokos.set([self.lbs])
        self.client.logout()
        self.client.login(username="a2", password="pw12345")
        r = self.client.get(reverse("toko_overview"))
        self.assertContains(r, ">LBS<")
        self.assertNotContains(r, ">SLO<")

    def test_tombol_buka_ganti_toko(self):
        self._batch(self.lbs, 0, date(2026, 6, 27))
        r = self.client.get(reverse("toko_overview"))
        self.assertContains(r, reverse("set_toko"))


class TokoOverviewDateFilterTests(TokoOverviewTests):
    """Filter tanggal: rentang membatasi batch yang dihitung (selisih = agregat
    rentang, 'rekon terakhir' = batch terakhir DALAM rentang)."""

    def test_filter_satu_hari_ambil_batch_hari_itu(self):
        self._batch(self.lbs, 1000, date(2026, 6, 27))
        self._batch(self.lbs, 5000, date(2026, 6, 28))
        r = self.client.get(reverse("toko_overview"),
                            {"from": "2026-06-28", "to": "2026-06-28"})
        self.assertContains(r, "28/06/2026")   # rekon terakhir dalam rentang
        self.assertContains(r, ">5.000<")      # selisih hanya dari batch 28
        self.assertNotContains(r, ">1.000<")
        self.assertNotContains(r, ">6.000<")

    def test_filter_rentang_agregat_selisih(self):
        self._batch(self.lbs, 1000, date(2026, 6, 27))
        self._batch(self.lbs, 5000, date(2026, 6, 28))
        r = self.client.get(reverse("toko_overview"),
                            {"from": "2026-06-27", "to": "2026-06-28"})
        self.assertContains(r, ">6.000<")      # 1.000 + 5.000

    def test_filter_tanpa_batch_dalam_rentang(self):
        self._batch(self.lbs, 1000, date(2026, 6, 27))
        r = self.client.get(reverse("toko_overview"),
                            {"from": "2026-06-29", "to": "2026-06-30"})
        # batch 27/06 di luar rentang: tak boleh tampil sebagai rekon terakhir
        self.assertNotContains(r, "27/06/2026")
        self.assertNotContains(r, ">1.000<")

    def test_filter_invalid_diabaikan(self):
        self._batch(self.lbs, 1000, date(2026, 6, 27))
        r = self.client.get(reverse("toko_overview"), {"from": "bukan-tanggal"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, ">1.000<")      # fallback perilaku tanpa filter


class PendingCountEngineTests(_SettleData):
    """pending_settlement_count: hitungan di SQL harus setara semantik dict
    _carried_results (dedup per left_id) — bukan jumlah baris MatchResult mentah."""

    def test_hasil_ganda_left_sama_dihitung_sekali(self):
        tx = self.waiting(date(2026, 6, 28), ticket="W1")
        # hasil no_money GANDA untuk baris kredit yang sama (kasus defensif dict)
        MatchResult.objects.create(
            run=self._runs[date(2026, 6, 28)], bucket=MatchResult.Bucket.TIDAK,
            reason_code="no_money", left=tx,
        )
        self.waiting(date(2026, 6, 29), ticket="W2", username="susi")
        self.assertEqual(pending_settlement_count(self.toko), 2)
        self.assertEqual(
            pending_settlement_count(self.toko), len(_carried_results(self.toko))
        )

    def test_count_satu_query_tanpa_materialisasi_objek(self):
        for i, d in enumerate((date(2026, 6, 27), date(2026, 6, 28), date(2026, 6, 29))):
            self.waiting(d, ticket=f"W{i}", username=f"user{i}")
        with CaptureQueriesContext(connection) as ctx:
            n = pending_settlement_count(self.toko)
        self.assertEqual(n, 3)
        self.assertEqual(len(ctx), 1)
        # COUNT dikerjakan database — bukan menarik seluruh baris lalu len() di Python
        # (awas: substring "COUNT" saja ada di kolom acCOUNT_id — wajib bentuk agregatnya)
        self.assertIn(
            "COUNT(DISTINCT", ctx[0]["sql"].upper(),
            f"bukan query agregat: {ctx[0]['sql'][:120]}",
        )


class TokoOverviewQueryGrowthTests(TestCase):
    """Jumlah query /tokos/ harus KONSTAN terhadap jumlah toko (anti N+1).
    Di prod 24 toko × 3 query/toko ≈ 1,5 dtk per klik menu Toko."""

    def setUp(self):
        User.objects.create_user("adm", password="pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")

    def test_query_tidak_tumbuh_saat_toko_bertambah(self):
        self.client.get(reverse("toko_overview"))  # warm-up: cache ContentType dkk.
        with CaptureQueriesContext(connection) as before:
            self.assertEqual(self.client.get(reverse("toko_overview")).status_code, 200)
        for i in range(6):
            Toko.objects.create(key=f"qq{i}", name=f"QQ{i}")
        with CaptureQueriesContext(connection) as after:
            self.assertEqual(self.client.get(reverse("toko_overview")).status_code, 200)
        self.assertEqual(
            len(before), len(after),
            f"query tumbuh {len(before)}→{len(after)} saat toko bertambah (N+1)",
        )
