"""Mode "Semua Toko" (khusus admin) — sentinel sesi, dashboard gabungan,
dan filter ceklis multi-toko di halaman Hutang/Piutang.

Risiko utama fitur ini: `active_toko_id` yang biasanya berisi id numerik kini
bisa berisi string sentinel "all". Setiap view single-toko memanggil
`_active_toko`, dan `allowed.filter(id="all")` MELEDAK (ValueError di sqlite
maupun Postgres). Karena itu kelas pertama di berkas ini menyapu SELURUH rute
tanpa argumen dengan sesi "all" — pagar yang harus selalu hijau.
"""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import URLPattern, reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.breakdown import ringkas_bracket_hari
from web.models import FRKoreksi
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


class _DataGabungan(TestCase):
    """Dua toko, tanggal batch BERBEDA — potret gabungan harus memakai batch
    terakhir MASING-MASING toko, bukan satu tanggal seragam."""

    TGL_LBS = date(2026, 7, 1)
    TGL_SLO = date(2026, 7, 3)

    def setUp(self):
        User.objects.create_user("adm", password="pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")
        _sesi_semua(self.client)
        self.tol = ToleranceProfile.objects.get(name="Default")
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.panel = SourceType.objects.get(key="panel")
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"})[0]
        self._n = 0

    def batch(self, toko, d):
        return ReconBatch.objects.create(
            toko=toko, tolerance=self.tol, recon_date=d,
            summary={"dp": {"selisih": 0}, "wd": {"selisih": 0}})

    def panel_tx(self, toko, batch, jenis, amount, bank_title="BCA"):
        self._n += 1
        up = Upload.objects.create(source_type=self.panel, toko=toko)
        return Transaction.objects.create(
            upload=up, source_type=self.panel, toko=toko, jenis=jenis,
            amount=Decimal(amount), bank_title=bank_title,
            occurred_at=datetime(2026, 7, 1, 10, 0), row_hash=f"p{self._n}",
            consumed_by_batch=batch)

    def fr(self, toko, tanggal, bank, kategori, total):
        self._n += 1
        up = Upload.objects.create(source_type=self.bracket, toko=toko)
        return Transaction.objects.create(
            upload=up, source_type=self.bracket, toko=toko, jenis="lainnya",
            amount=abs(Decimal(total)), money_delta=Decimal(total),
            posted_date=tanggal, occurred_at=datetime(2026, 7, 1, 10, 0),
            row_hash=f"b{self._n}",
            raw={"Bank": bank, "Kategori": kategori, "Jam": "10:00"})

    def seed(self):
        """LBS: batch 01/07 (+ batch lama 30/06 yang HARUS diabaikan);
        SLO: batch 03/07."""
        lama = self.batch(self.lbs, date(2026, 6, 30))
        self.panel_tx(self.lbs, lama, "depo", "999000")
        self.b_lbs = self.batch(self.lbs, self.TGL_LBS)
        self.b_slo = self.batch(self.slo, self.TGL_SLO)
        self.panel_tx(self.lbs, self.b_lbs, "depo", "100000")
        self.panel_tx(self.lbs, self.b_lbs, "wd", "40000")
        self.panel_tx(self.slo, self.b_slo, "depo", "70000", bank_title="NXPAY QR")
        self.fr(self.lbs, self.TGL_LBS, "BCA A", "Deposit", "100000")
        self.fr(self.lbs, self.TGL_LBS, "BCA A", "Withdrawal", "-40000")
        self.fr(self.lbs, date(2026, 6, 30), "BCA A", "Deposit", "999000")
        self.fr(self.slo, self.TGL_SLO, "BRI B", "Deposit", "70000")


class DashboardSemuaTests(_DataGabungan):
    def test_render_template_khusus(self):
        self.seed()
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("web/dashboard_all.html", [t.name for t in r.templates])
        self.assertTrue(r.context["semua_toko_page"])

    def test_bar_penjelas_tak_muncul_di_halaman_gabungan(self):
        self.seed()
        self.assertNotContains(self.client.get(reverse("dashboard")),
                               "Mode Semua Toko aktif")

    def test_non_admin_tetap_dashboard_tunggal(self):
        self.seed()
        u = User.objects.create_user("a2", password="pw12345", role="auditor")
        u.allowed_tokos.set([self.lbs])
        self.client.logout()
        self.client.login(username="a2", password="pw12345")
        _sesi_semua(self.client)
        r = self.client.get(reverse("dashboard"))
        self.assertIn("web/dashboard.html", [t.name for t in r.templates])

    def test_panel_gabungan_sama_dengan_jumlah_per_toko(self):
        self.seed()
        r = self.client.get(reverse("dashboard"))
        ps = r.context["panel_sum"]
        # LBS batch 01/07: DP 100.000 + WD 40.000 · SLO batch 03/07: DP 70.000.
        # Batch lama 30/06 (999.000) TIDAK ikut.
        self.assertEqual(ps["dp"], {"n": 2, "v": 170000.0})
        self.assertEqual(ps["wd"], {"n": 1, "v": 40000.0})
        self.assertEqual(ps["total_n"], 3)
        self.assertEqual(ps["net"], 130000.0)

    def test_metode_pembayaran_klop_dengan_strip_panel(self):
        self.seed()
        r = self.client.get(reverse("dashboard"))
        metode = r.context["metode"]
        self.assertEqual(sum(x["v"] for x in metode["dp"]),
                         r.context["panel_sum"]["dp"]["v"])
        self.assertEqual({x["label"] for x in metode["dp"] if x["n"]},
                         {"Bank", "QRIS"})

    def test_bracket_gabungan_sama_dengan_jumlah_ringkas_per_toko(self):
        self.seed()
        r = self.client.get(reverse("dashboard"))
        harap_dp = (ringkas_bracket_hari(self.lbs, self.TGL_LBS)["dp"]["v"]
                    + ringkas_bracket_hari(self.slo, self.TGL_SLO)["dp"]["v"])
        harap_wd = (ringkas_bracket_hari(self.lbs, self.TGL_LBS)["wd"]["v"]
                    + ringkas_bracket_hari(self.slo, self.TGL_SLO)["wd"]["v"])
        self.assertEqual(r.context["bracket_sum"]["dp"]["v"], harap_dp)
        self.assertEqual(r.context["bracket_sum"]["wd"]["v"], harap_wd)

    def test_bracket_gabungan_ikut_overlay_koreksi(self):
        """Koreksi FR harus terpakai juga di mode gabungan — kalau tidak, angka
        dashboard gabungan berbeda dari dashboard toko itu sendiri."""
        self.seed()
        FRKoreksi.objects.create(toko=self.lbs, tanggal=self.TGL_LBS,
                                 account="BCA A", kolom="deposit",
                                 nilai=Decimal("123000"), alasan="mistake_cs")
        r = self.client.get(reverse("dashboard"))
        harap = (ringkas_bracket_hari(self.lbs, self.TGL_LBS)["dp"]["v"]
                 + ringkas_bracket_hari(self.slo, self.TGL_SLO)["dp"]["v"])
        self.assertEqual(harap, Decimal("193000"))  # 123.000 (dikoreksi) + 70.000
        self.assertEqual(r.context["bracket_sum"]["dp"]["v"], harap)

    def test_tabel_per_toko_bawa_tanggal_batch_masing_masing(self):
        self.seed()
        r = self.client.get(reverse("dashboard"))
        baris = {b["toko"].key: b for b in r.context["rows"]}
        self.assertEqual(baris["lbs"]["last"]["recon_date"], self.TGL_LBS)
        self.assertEqual(baris["slo"]["last"]["recon_date"], self.TGL_SLO)
        self.assertEqual(baris["lbs"]["dp"], 100000.0)
        self.assertEqual(baris["slo"]["dp"], 70000.0)
        # tombol pindah toko per baris
        self.assertContains(r, reverse("set_toko"))

    def test_kalender_ambil_status_terburuk_lintas_toko(self):
        """Satu toko seimbang + satu toko selisih besar pada hari yang sama →
        sel kalender harus MERAH (jangan menyembunyikan masalah)."""
        hari = date.today()
        b1 = self.batch(self.lbs, hari)
        b1.summary = {"dp": {"selisih": 0}, "wd": {"selisih": 0}}
        b1.save()
        b2 = self.batch(self.slo, hari)
        b2.summary = {"dp": {"selisih": 50_000_000}, "wd": {"selisih": 0}}
        b2.save()
        r = self.client.get(reverse("dashboard"))
        sel = {k["d"]: k for k in r.context["kal"]}
        self.assertEqual(sel[hari]["st"], "bad")
        self.assertEqual(sel[hari]["n"], 2)

    def test_seksi_belum_tersedia_disembunyikan_dengan_penjelasan(self):
        self.seed()
        r = self.client.get(reverse("dashboard"))
        self.assertNotContains(r, "Tren selisih")
        self.assertNotContains(r, "Kerjakan hari ini")
        self.assertNotContains(r, "Uang periksa")
        self.assertContains(r, "belum tersedia di mode gabungan")

    def test_tanpa_batch_sama_sekali_tetap_200(self):
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context["panel_sum"])


class HutangMultiTokoTests(TestCase):
    """`web.hutang.hutang_piutang` menerima list toko; jalur satu toko TAK BOLEH
    berubah sedikit pun (halaman lama memakai kunci baris yang persis ini)."""

    KUNCI_TUNGGAL = {"id", "tanggal", "jam", "account", "kategori", "member",
                     "keterangan", "nominal"}

    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"})[0]
        self._n = 0

    def fr(self, toko, kategori, total, tanggal=date(2026, 7, 1)):
        self._n += 1
        up = Upload.objects.create(source_type=self.bracket, toko=toko)
        return Transaction.objects.create(
            upload=up, source_type=self.bracket, toko=toko, jenis="lainnya",
            amount=abs(Decimal(total)), money_delta=Decimal(total),
            posted_date=tanggal, occurred_at=datetime(2026, 7, 1, 10, 0),
            row_hash=f"hp{self._n}",
            raw={"Bank": "BANK BCA", "Kategori": kategori, "Jam": "10:00",
                 "Member": "BUDI"})

    def test_jalur_satu_toko_tak_berubah(self):
        from web.hutang import hutang_piutang as hitung

        self.fr(self.lbs, "Hutang", "-500000")
        self.fr(self.slo, "Hutang", "-900000")   # toko lain tak boleh bocor
        data = hitung(self.lbs)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["total_hutang"], Decimal("-500000"))
        self.assertEqual(set(data["rows"][0]), self.KUNCI_TUNGGAL)

    def test_list_menggabung_dua_toko(self):
        from web.hutang import hutang_piutang as hitung

        self.fr(self.lbs, "Hutang", "-500000")
        self.fr(self.slo, "Piutang", "250000")
        data = hitung([self.lbs, self.slo])
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["total_hutang"], Decimal("-500000"))
        self.assertEqual(data["total_piutang"], Decimal("250000"))
        self.assertEqual({r["toko"] for r in data["rows"]},
                         {self.lbs.name, self.slo.name})

    def test_list_satu_toko_setara_jalur_tunggal(self):
        from web.hutang import hutang_piutang as hitung

        self.fr(self.lbs, "Hutang", "-500000")
        satu, banyak = hitung(self.lbs), hitung([self.lbs])
        for k in ("count", "total_hutang", "total_piutang", "netto"):
            self.assertEqual(satu[k], banyak[k])
        # hanya kolom Toko yang bertambah di mode banyak
        self.assertEqual(set(banyak["rows"][0]) - set(satu["rows"][0]), {"toko"})

    def test_list_kosong_tanpa_baris(self):
        from web.hutang import hutang_piutang as hitung

        self.fr(self.lbs, "Hutang", "-500000")
        self.assertEqual(hitung([])["count"], 0)


class HutangCeklisViewTests(TestCase):
    """Halaman /hutang-piutang/ di mode Semua Toko: ceklis toko + kolom Toko."""

    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"})[0]
        self._n = 0
        User.objects.create_user("adm", password="pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")

    def fr(self, toko, kategori, total):
        self._n += 1
        up = Upload.objects.create(source_type=self.bracket, toko=toko)
        return Transaction.objects.create(
            upload=up, source_type=self.bracket, toko=toko, jenis="lainnya",
            amount=abs(Decimal(total)), money_delta=Decimal(total),
            posted_date=date.today(), occurred_at=datetime(2026, 7, 1, 10, 0),
            row_hash=f"hv{self._n}",
            raw={"Bank": "BANK BCA", "Kategori": kategori, "Jam": "10:00",
                 "Member": "BUDI"})

    def _get(self, **params):
        return self.client.get(reverse("hutang_piutang"),
                               dict({"dari": "2026-01-01",
                                     "sampai": date.today().isoformat()}, **params))

    def test_default_semua_toko(self):
        self.fr(self.lbs, "Hutang", "-500000")
        self.fr(self.slo, "Piutang", "250000")
        _sesi_semua(self.client)
        r = self._get()
        self.assertTrue(r.context["semua_toko_page"])
        self.assertEqual(r.context["data"]["count"], 2)
        self.assertContains(r, "<th>Toko</th>")        # kolom Toko di tabel
        self.assertContains(r, 'name="toko"')          # ceklis toko di filter
        self.assertContains(r, self.slo.name)

    def test_pager_mempertahankan_ceklis(self):
        """Ceklis harus ikut di tautan halaman — kalau tidak, halaman 2 diam-diam
        kembali ke semua toko."""
        self.fr(self.lbs, "Hutang", "-500000")
        _sesi_semua(self.client)
        r = self._get(toko=str(self.lbs.id))
        self.assertIn("toko=%d" % self.lbs.id, r.context["base_qs"])

    def test_subset_lewat_ceklis(self):
        self.fr(self.lbs, "Hutang", "-500000")
        self.fr(self.slo, "Piutang", "250000")
        _sesi_semua(self.client)
        r = self._get(toko=str(self.slo.id))
        self.assertEqual(r.context["data"]["count"], 1)
        self.assertEqual(r.context["data"]["total_piutang"], Decimal("250000"))
        self.assertEqual(r.context["toko_dipilih"], [self.slo.id])

    def test_id_ngawur_diabaikan(self):
        self.fr(self.lbs, "Hutang", "-500000")
        _sesi_semua(self.client)
        r = self._get(toko="bukan-angka")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["data"]["count"], 1)   # jatuh ke default semua

    def test_toko_di_luar_hak_tak_bisa_diminta(self):
        """Ceklis bukan pintu belakang RBAC — id di luar `tokos_for` dibuang."""
        u = User.objects.create_user("sup", password="pw12345", role="admin")
        u.save()
        rahasia = Toko.objects.create(key="zzz", name="ZZZ", is_active=False,
                                      panel="nexus")
        self.fr(rahasia, "Hutang", "-777000")
        _sesi_semua(self.client)
        r = self._get(toko=str(rahasia.id))
        self.assertEqual(r.context["toko_dipilih"], [])
        self.assertNotContains(r, "777.000")

    def test_mode_tunggal_tanpa_ceklis(self):
        self.fr(self.lbs, "Hutang", "-500000")
        self.fr(self.slo, "Piutang", "250000")
        s = self.client.session
        s["active_toko_id"] = self.lbs.id
        s.save()
        r = self._get()
        self.assertFalse(r.context.get("semua_toko_page"))
        self.assertEqual(r.context["data"]["count"], 1)
        self.assertNotContains(r, 'name="toko"')

    def test_tanpa_toko_aktif_jatuh_ke_halaman_no_toko(self):
        """Instalasi tanpa toko aktif: jangan tampilkan tabel kosong tanpa
        konteks — halaman no_toko yang menjelaskan keadaannya."""
        Toko.objects.update(is_active=False)
        _sesi_semua(self.client)
        self.assertIn("web/no_toko.html", [t.name for t in self._get().templates])

    def test_non_admin_tak_dapat_ceklis(self):
        u = User.objects.create_user("a2", password="pw12345", role="auditor")
        u.allowed_tokos.set([self.lbs])
        self.fr(self.lbs, "Hutang", "-500000")
        self.client.logout()
        self.client.login(username="a2", password="pw12345")
        _sesi_semua(self.client)   # sentinel warisan tak boleh membuka mode
        r = self._get()
        self.assertNotContains(r, 'name="toko"')
        self.assertEqual(r.context["data"]["count"], 1)


class DashboardSemuaQueryTests(_DataGabungan):
    """Jumlah query dashboard gabungan harus KONSTAN terhadap jumlah toko —
    di prod ada 24 toko; satu query per toko = dashboard yang tak terpakai."""

    def test_query_tidak_tumbuh_saat_toko_bertambah(self):
        self.seed()
        self.client.get(reverse("dashboard"))  # warm-up cache ContentType dkk.
        with CaptureQueriesContext(connection) as before:
            self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        # Setiap toko baru harus punya batch + baris panel + baris bracket
        # nyata (bukan toko kosong) — toko kosong tak menggerakkan jalur
        # data (panel_sum/bracket_sum/tinjau/pending), jadi tak bisa
        # mendeteksi regresi loop-query-per-toko di jalur itu.
        for i in range(6):
            t = Toko.objects.create(key=f"qq{i}", name=f"QQ{i}", panel="nexus")
            d = date(2026, 7, 5)
            b = self.batch(t, d)
            self.panel_tx(t, b, "depo", "10000")
            self.fr(t, d, "BCA X", "Deposit", "10000")
        with CaptureQueriesContext(connection) as after:
            self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertEqual(
            len(before), len(after),
            f"query tumbuh {len(before)}→{len(after)} saat toko bertambah (N+1)")
