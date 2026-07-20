"""Dashboard: kartu "Metode Pembayaran" — breakdown Bank Title panel per metode.

Permintaan klien: berapa trx & nilai deposit per Bank/QRIS/E-wallet dan
withdraw per Bank/Nexuspay/QRIS, acuan Bank Title panel ("buat QR pakai
acuan Bank Title bank kita"). Total kartu WAJIB sama dengan strip
Ringkasan Panel — sumbernya queryset panel_sum yang satu dan sama.
"""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.channels import breakdown_metode, kelas_metode

User = get_user_model()


class KelasMetodeTests(SimpleTestCase):
    """Aturan klasifikasi substring per jenis (case-insensitive)."""

    def test_dp_qr_dicek_paling_awal(self):
        # contoh nyata klien: "NXPAY DEPOSIT QR" dihitung QRIS (huruf QR-nya)
        self.assertEqual(kelas_metode("depo", "NXPAY DEPOSIT QR"), "QRIS")
        self.assertEqual(kelas_metode("depo", "QRIS"), "QRIS")
        self.assertEqual(kelas_metode("depo", "qris"), "QRIS")  # case-insensitive

    def test_dp_ewallet(self):
        for kode in ("DANA", "OVO", "GOPAY", "SHOPEEPAY", "LINKAJA", "SAKUKU"):
            self.assertEqual(kelas_metode("depo", kode), "E-wallet", kode)
        self.assertEqual(kelas_metode("depo", "dana"), "E-wallet")

    def test_dp_danamon_tetap_bank(self):
        # "DANAMON" (bank) memuat substring "DANA" — jangan nyasar ke E-wallet
        self.assertEqual(kelas_metode("depo", "DANAMON"), "Bank")

    def test_dp_selain_itu_ada_isi_berarti_bank(self):
        self.assertEqual(kelas_metode("depo", "BCA"), "Bank")
        self.assertEqual(kelas_metode("depo", "NXPAY DEPOSIT VA BRI"), "Bank")
        self.assertEqual(kelas_metode("depo", "AXIS (AUTO)"), "Bank")

    def test_dp_kosong_masuk_lainnya(self):
        self.assertEqual(kelas_metode("depo", ""), "Lainnya")
        self.assertEqual(kelas_metode("depo", None), "Lainnya")

    def test_wd_nexuspay_dicek_sebelum_qr_dan_bank(self):
        # contoh nyata klien: WD lewat akun "QRIS NEXUSPAY" dihitung Nexuspay
        self.assertEqual(kelas_metode("wd", "QRIS NEXUSPAY"), "Nexuspay")
        self.assertEqual(kelas_metode("wd", "NXPAY WITHDRAWAL BANK"), "Nexuspay")

    def test_wd_qris_bank_lainnya(self):
        self.assertEqual(kelas_metode("wd", "QRIS BCA"), "QRIS")
        self.assertEqual(kelas_metode("wd", "BCA"), "Bank")
        self.assertEqual(kelas_metode("wd", ""), "Lainnya")


class _DataDasar(TestCase):
    """Fixture bersama: toko lbs + batch + baris panel yang terkonsumsi."""

    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.panel = SourceType.objects.get(key="panel")
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)
        self._rh = 0

    def _batch(self, toko=None, d=date(2026, 7, 19)):
        return ReconBatch.objects.create(
            toko=toko or self.lbs, tolerance=self.tol, recon_date=d,
        )

    def _tx(self, jenis, amount, batch, bank_title="", toko=None,
            is_duplicate=False, upload=None):
        self._rh += 1
        return Transaction.objects.create(
            upload=upload or self.up, source_type=self.panel,
            toko=toko or self.lbs, jenis=jenis, amount=Decimal(amount),
            occurred_at=datetime(2026, 7, 19, 10, 0), row_hash=f"r{self._rh}",
            consumed_by_batch=batch, is_duplicate=is_duplicate,
            bank_title=bank_title,
        )

    def _qs(self, batch):
        # queryset PERSIS seperti `_pr` (panel_sum) di view dashboard
        return Transaction.objects.filter(
            consumed_by_batch=batch, source_type__key="panel", is_duplicate=False,
        )


class BreakdownMetodeTests(_DataDasar):
    def test_total_breakdown_sama_dengan_agregat_panel_sum(self):
        batch = self._batch()
        self._tx("depo", "100000", batch, "QRIS")
        self._tx("depo", "250000", batch, "NXPAY DEPOSIT QR")
        self._tx("depo", "50000", batch, "DANA")
        self._tx("depo", "75000", batch, "BCA")
        self._tx("depo", "25000", batch, "")
        self._tx("wd", "300000", batch, "BCA")
        self._tx("wd", "40000", batch, "BNI")
        self._tx("wd", "60000", batch, "NXPAY WITHDRAWAL BANK")
        # pengganggu: duplikat & jenis non-DP/WD tak boleh ikut terhitung
        self._tx("depo", "999999", batch, "QRIS", is_duplicate=True)
        self._tx("bonus", "888888", batch, "BCA")

        qs = self._qs(batch)
        metode = breakdown_metode(qs)
        agg = {
            r["jenis"]: r for r in qs.filter(jenis__in=["depo", "wd"])
            .values("jenis").annotate(n=Count("id"), v=Sum("amount"))
        }
        for grup, jenis in (("dp", "depo"), ("wd", "wd")):
            self.assertEqual(sum(r["n"] for r in metode[grup]), agg[jenis]["n"])
            self.assertEqual(
                sum(r["v"] for r in metode[grup]), float(agg[jenis]["v"]))

    def test_dp_nxpay_deposit_qr_dihitung_qris(self):
        batch = self._batch()
        self._tx("depo", "100000", batch, "NXPAY DEPOSIT QR")
        self._tx("depo", "50000", batch, "BCA")
        rows = {r["label"]: r for r in breakdown_metode(self._qs(batch))["dp"]}
        self.assertEqual(rows["QRIS"]["n"], 1)
        self.assertEqual(rows["QRIS"]["v"], 100000.0)
        self.assertEqual(rows["Bank"]["n"], 1)
        self.assertNotIn("Nexuspay", rows)  # DP tak punya kategori Nexuspay

    def test_wd_qris_nexuspay_dihitung_nexuspay(self):
        batch = self._batch()
        self._tx("wd", "150000", batch, "QRIS NEXUSPAY")
        rows = {r["label"]: r for r in breakdown_metode(self._qs(batch))["wd"]}
        self.assertEqual(rows["Nexuspay"]["n"], 1)
        self.assertEqual(rows["Nexuspay"]["v"], 150000.0)
        self.assertEqual(rows["QRIS"]["n"], 0)

    def test_bank_title_kosong_masuk_lainnya(self):
        batch = self._batch()
        self._tx("depo", "10000", batch, "")
        self._tx("wd", "20000", batch, "")
        m = breakdown_metode(self._qs(batch))
        dp = {r["label"]: r for r in m["dp"]}
        wd = {r["label"]: r for r in m["wd"]}
        self.assertEqual(dp["Lainnya"], {"label": "Lainnya", "n": 1,
                                         "v": 10000.0, "pct": 100.0})
        self.assertEqual(wd["Lainnya"]["n"], 1)

    def test_lainnya_disembunyikan_saat_nol(self):
        batch = self._batch()
        self._tx("depo", "10000", batch, "QRIS")
        self._tx("wd", "20000", batch, "BCA")
        m = breakdown_metode(self._qs(batch))
        # kategori tetap tampil walau 0 trx; "Lainnya" saja yang disembunyikan
        self.assertEqual({r["label"] for r in m["dp"]},
                         {"QRIS", "E-wallet", "Bank"})
        self.assertEqual({r["label"] for r in m["wd"]},
                         {"Nexuspay", "QRIS", "Bank"})

    def test_toko_dan_batch_lain_tidak_bocor(self):
        slo = Toko.objects.get(key="slo")
        up_slo = Upload.objects.create(source_type=self.panel, toko=slo)
        b_lbs = self._batch()
        b_lbs2 = self._batch(d=date(2026, 7, 20))
        b_slo = self._batch(toko=slo)
        self._tx("depo", "40000", b_lbs, "QRIS")
        self._tx("depo", "111111", b_lbs2, "QRIS")  # batch lain, toko sama
        self._tx("depo", "999999", b_slo, "QRIS", toko=slo, upload=up_slo)
        dp = {r["label"]: r for r in breakdown_metode(self._qs(b_lbs))["dp"]}
        self.assertEqual(dp["QRIS"]["n"], 1)
        self.assertEqual(dp["QRIS"]["v"], 40000.0)

    def test_urut_nilai_terbesar_dan_pct(self):
        batch = self._batch()
        self._tx("depo", "300000", batch, "QRIS")
        self._tx("depo", "100000", batch, "BCA")
        self._tx("depo", "600000", batch, "DANA")
        m = breakdown_metode(self._qs(batch))
        self.assertEqual([r["label"] for r in m["dp"]],
                         ["E-wallet", "QRIS", "Bank"])
        self.assertEqual([r["pct"] for r in m["dp"]], [60.0, 30.0, 10.0])


class DashboardMetodeViewTests(_DataDasar):
    def setUp(self):
        super().setUp()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def test_context_metode_dan_kartu_tampil(self):
        batch = self._batch()
        self._tx("depo", "100000", batch, "NXPAY DEPOSIT QR")
        self._tx("wd", "50000", batch, "QRIS NEXUSPAY")
        r = self.client.get(reverse("dashboard"))
        dp = {x["label"]: x for x in r.context["metode"]["dp"]}
        wd = {x["label"]: x for x in r.context["metode"]["wd"]}
        self.assertEqual(dp["QRIS"]["n"], 1)
        self.assertEqual(wd["Nexuspay"]["n"], 1)
        self.assertContains(r, "Metode Pembayaran")
        # total kartu == strip Ringkasan Panel (querysetnya satu dan sama)
        ps = r.context["panel_sum"]
        self.assertEqual(
            sum(x["n"] for x in r.context["metode"]["dp"]), ps["dp"]["n"])
        self.assertEqual(
            sum(x["v"] for x in r.context["metode"]["wd"]), ps["wd"]["v"])

    def test_tanpa_batch_kartu_tak_tampil(self):
        r = self.client.get(reverse("dashboard"))
        self.assertIsNone(r.context["metode"])
        self.assertNotContains(r, "Metode Pembayaran")
