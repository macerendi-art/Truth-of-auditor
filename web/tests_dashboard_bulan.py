"""Dashboard: filter bulanan (?bulan=YYYY-MM) terpisah dari tanggal spesifik.

Kontrak:
- `?bulan=YYYY-MM` = mode filter rentang tgl 1–akhir bulan + tren vs bulan lalu.
- Filter tanggal `?dari=&sampai=` tetap seperti dulu (tanpa tren bulanan).
- Mode multi (Semua / Pusat / Partner) + bulan → tren gabungan + per toko.
- Tanpa parameter = perilaku lama (potret batch terakhir).
"""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.channels import snapshot_metode_panel, tren_bulanan
from web.views import _parse_bulan, _rentang_bulan

User = get_user_model()

JUL = date(2026, 7, 15)
AGU1 = date(2026, 8, 1)
AGU15 = date(2026, 8, 15)
AGU31 = date(2026, 8, 31)


class ParseBulanTests(SimpleTestCase):
    def test_sah(self):
        self.assertEqual(_parse_bulan("2026-08"), (2026, 8))
        self.assertEqual(_rentang_bulan(2026, 8), (AGU1, AGU31))

    def test_invalid(self):
        self.assertIsNone(_parse_bulan(""))
        self.assertIsNone(_parse_bulan("2026-8"))
        self.assertIsNone(_parse_bulan("2026-13"))
        self.assertIsNone(_parse_bulan("pisang"))


class TrenBulananUnitTests(SimpleTestCase):
    def test_naik_turun_datar(self):
        cur = {
            "trx_n": 120, "trx_v": 1_000_000.0,
            "QRIS": {"n": 80, "v": 700_000.0},
            "Bank": {"n": 30, "v": 250_000.0},
            "E-wallet": {"n": 10, "v": 50_000.0},
        }
        prev = {
            "trx_n": 100, "trx_v": 900_000.0,
            "QRIS": {"n": 90, "v": 800_000.0},
            "Bank": {"n": 10, "v": 80_000.0},
            "E-wallet": {"n": 0, "v": 0.0},
        }
        t = tren_bulanan(cur, prev)
        self.assertEqual(t["trx"]["arah"], "naik")
        self.assertEqual(t["trx"]["pct"], 20.0)
        by = {m["label"]: m for m in t["metode"]}
        self.assertEqual(by["QRIS"]["arah"], "turun")
        self.assertEqual(by["Bank"]["arah"], "naik")
        self.assertEqual(by["E-wallet"]["arah"], "naik")
        self.assertEqual(by["E-wallet"]["pct"], 100.0)  # dari 0

    def test_datar_nol(self):
        t = tren_bulanan(None, None)
        self.assertEqual(t["trx"]["arah"], "datar")
        self.assertIsNone(t["trx"]["pct"])


class _Base(TestCase):
    def setUp(self):
        User.objects.create_user("adm", "a@a.co", "pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")
        self.toko = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})
        self.panel = SourceType.objects.get(key="panel")
        self.up = Upload.objects.create(source_type=self.panel, toko=self.toko)
        self._n = 0

    def batch(self, d, toko=None):
        return ReconBatch.objects.create(
            toko=toko or self.toko, tolerance=self.tol, recon_date=d,
            summary={"dp": {"selisih": 0}, "wd": {"selisih": 0}},
        )

    def tx(self, jenis, amount, batch, bank_title="", toko=None, upload=None):
        self._n += 1
        return Transaction.objects.create(
            upload=upload or self.up, source_type=self.panel,
            toko=toko or self.toko, jenis=jenis, amount=Decimal(amount),
            occurred_at=datetime(2026, 8, 15, 10, 0),
            row_hash=f"tb{self._n}", consumed_by_batch=batch,
            bank_title=bank_title,
        )


class FilterBulanViewTests(_Base):
    def test_bulan_jadi_mode_filter_rentang_penuh(self):
        b_jul = self.batch(JUL)
        b_agu = self.batch(AGU15)
        self.tx("depo", "100000", b_jul, "QRIS")
        self.tx("depo", "200000", b_agu, "QRIS")
        self.tx("depo", "50000", b_agu, "BCA")
        r = self.client.get(reverse("dashboard"), {"bulan": "2026-08"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["mode_filter"])
        self.assertTrue(r.context["mode_bulan"])
        self.assertEqual(r.context["f_dari"], AGU1)
        self.assertEqual(r.context["f_sampai"], AGU31)
        self.assertEqual(r.context["n_batch"], 1)
        # panel hanya batch Agustus
        self.assertEqual(r.context["panel_sum"]["dp"]["n"], 2)
        self.assertEqual(r.context["panel_sum"]["dp"]["v"], 250000.0)
        self.assertContains(r, "Tren volume")
        self.assertContains(r, 'type="month"')
        self.assertContains(r, 'name="bulan"')
        self.assertEqual(r.context["sel_bulan"], "2026-08")
        self.assertEqual(r.context["default_bulan"], "2026-08")

    def test_tren_vs_bulan_lalu(self):
        b_jul = self.batch(JUL)
        b_agu = self.batch(AGU15)
        # Juli: 2 QRIS
        self.tx("depo", "100000", b_jul, "QRIS")
        self.tx("depo", "100000", b_jul, "QRIS")
        # Agustus: 1 QRIS + 2 Bank + 1 E-wallet = 4 trx
        self.tx("depo", "50000", b_agu, "QRIS")
        self.tx("depo", "10000", b_agu, "BCA")
        self.tx("depo", "10000", b_agu, "BNI")
        self.tx("depo", "20000", b_agu, "DANA")
        r = self.client.get(reverse("dashboard"), {"bulan": "2026-08"})
        tren = r.context["tren_bulan"]
        self.assertEqual(tren["trx"]["n"], 4)
        self.assertEqual(tren["trx"]["n_prev"], 2)
        self.assertEqual(tren["trx"]["arah"], "naik")
        self.assertEqual(tren["trx"]["pct"], 100.0)
        by = {m["label"]: m for m in tren["metode"]}
        self.assertEqual(by["QRIS"]["n"], 1)
        self.assertEqual(by["QRIS"]["n_prev"], 2)
        self.assertEqual(by["QRIS"]["arah"], "turun")
        self.assertEqual(by["Bank"]["n"], 2)
        self.assertEqual(by["E-wallet"]["n"], 1)
        self.assertEqual(by["E-wallet"]["arah"], "naik")

    def test_tanggal_spesifik_tanpa_tren_bulan(self):
        self.batch(AGU15)
        r = self.client.get(
            reverse("dashboard"),
            {"dari": AGU15.isoformat(), "sampai": AGU15.isoformat()},
        )
        self.assertTrue(r.context["mode_filter"])
        self.assertFalse(r.context["mode_bulan"])
        self.assertIsNone(r.context["tren_bulan"])
        self.assertNotContains(r, "Tren volume")

    def test_default_tanpa_param_tetap(self):
        b = self.batch(AGU15)
        self.tx("depo", "40000", b, "QRIS")
        r = self.client.get(reverse("dashboard"))
        self.assertFalse(r.context["mode_filter"])
        self.assertFalse(r.context["mode_bulan"])
        self.assertIsNone(r.context["tren_bulan"])
        self.assertEqual(r.context["panel_sum"]["dp"]["v"], 40000.0)

    def test_bulan_invalid_jatuh_default(self):
        b = self.batch(AGU15)
        self.tx("depo", "40000", b)
        r = self.client.get(reverse("dashboard"), {"bulan": "bukan"})
        self.assertFalse(r.context["mode_filter"])
        self.assertFalse(r.context["mode_bulan"])

    def test_bulan_menang_atas_dari_sampai(self):
        # bila keduanya dikirim (URL manual), bulan menang
        self.batch(JUL)
        self.batch(AGU15)
        r = self.client.get(
            reverse("dashboard"),
            {"bulan": "2026-08", "dari": JUL.isoformat(), "sampai": JUL.isoformat()},
        )
        self.assertTrue(r.context["mode_bulan"])
        self.assertEqual(r.context["f_dari"], AGU1)

    def test_snapshot_metode_panel_nexuspay_jadi_bank(self):
        b = self.batch(AGU15)
        self.tx("wd", "50000", b, "QRIS NEXUSPAY")
        self.tx("depo", "10000", b, "QRIS")
        snap = snapshot_metode_panel(
            Transaction.objects.filter(consumed_by_batch=b, source_type__key="panel")
        )
        self.assertEqual(snap["QRIS"]["n"], 1)
        self.assertEqual(snap["Bank"]["n"], 1)  # Nexuspay → Bank di tren
        self.assertEqual(snap["trx_n"], 2)


class FilterBulanMultiTokoTests(_Base):
    def test_semua_toko_tabel_tren_per_toko(self):
        slo = Toko.objects.get(key="slo")
        up_slo = Upload.objects.create(source_type=self.panel, toko=slo)
        # Juli lbs 1 trx, Agu lbs 3 trx; Agu slo 1 trx
        b_jul = self.batch(JUL)
        b_agu_lbs = self.batch(AGU15)
        b_agu_slo = self.batch(AGU15, toko=slo)
        self.tx("depo", "100000", b_jul, "QRIS")
        self.tx("depo", "100000", b_agu_lbs, "QRIS")
        self.tx("depo", "100000", b_agu_lbs, "QRIS")
        self.tx("depo", "100000", b_agu_lbs, "BCA")
        self.tx("depo", "50000", b_agu_slo, "DANA", toko=slo, upload=up_slo)

        self.client.post(reverse("set_toko"), {"toko_id": "all"})
        r = self.client.get(reverse("dashboard"), {"bulan": "2026-08"})
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "web/dashboard_all.html")
        self.assertTrue(r.context["mode_bulan"])
        self.assertIsNotNone(r.context["tren_bulan"])
        self.assertContains(r, "Tren volume gabungan")
        self.assertContains(r, "Tren per toko")
        # setiap baris toko punya tren
        rows_by = {row["toko"].key: row for row in r.context["rows"]}
        self.assertIn("lbs", rows_by)
        self.assertIsNotNone(rows_by["lbs"]["tren"])
        self.assertEqual(rows_by["lbs"]["tren"]["trx"]["n"], 3)
        self.assertEqual(rows_by["lbs"]["tren"]["trx"]["n_prev"], 1)
        if "slo" in rows_by and rows_by["slo"]["tren"]:
            self.assertEqual(rows_by["slo"]["tren"]["trx"]["n"], 1)
            by = {m["label"]: m for m in rows_by["slo"]["tren"]["metode"]}
            self.assertEqual(by["E-wallet"]["n"], 1)
