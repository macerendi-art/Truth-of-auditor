"""Dashboard: filter tanggal (?dari=&sampai=) — melihat tanggal lampau & rentang.

Kontrak inti:
- TANPA parameter = perilaku lama byte-per-byte (potret batch terakhir).
- Mode filter mengagregasi SEMUA batch dalam jendela [dari, sampai]:
  panel_sum/metode (baris terkunci lintas batch), selisih & Uang periksa (D)
  dijumlah, tren = batch jendela, kalender ber-anchor `sampai`.
- Kartu Bracket rentang memakai `ringkas_bracket_rentang` yang tie out dengan
  `bracket_breakdown(toko, dari, sampai)["total"]` (rentang>1 hari TANPA
  overlay FRKoreksi — aturan yang sama dengan halaman /bracket/ rentang).
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.breakdown import (
    bracket_breakdown,
    ringkas_bracket_hari,
    ringkas_bracket_rentang,
)
from web.models import FRKoreksi

User = get_user_model()

D1 = date(2026, 7, 20)
D2 = date(2026, 7, 23)
AKUN_A = "BANK BCA | SUSI | DEPOSIT"
AKUN_B = "BANK BRI | YOGA | WITHDRAW"


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
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"}
        )[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.toko)
        self.up_fr = Upload.objects.create(source_type=self.bracket, toko=self.toko)
        self._n = 0

    def batch(self, d, dp_sel=0, wd_sel=0, um_d=0):
        return ReconBatch.objects.create(
            toko=self.toko, tolerance=self.tol, recon_date=d,
            summary={"dp": {"selisih": dp_sel}, "wd": {"selisih": wd_sel},
                     "unmatched_money": {"d": {"n": um_d}}},
        )

    def tx(self, jenis, amount, batch, toko=None):
        self._n += 1
        return Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=toko or self.toko,
            jenis=jenis, amount=Decimal(amount),
            occurred_at=datetime(2026, 7, 20, 10, 0),
            row_hash=f"p{self._n}", consumed_by_batch=batch,
        )

    def fr(self, bank, kategori, total, tanggal):
        self._n += 1
        return Transaction.objects.create(
            upload=self.up_fr, source_type=self.bracket, toko=self.toko,
            jenis="lainnya", amount=abs(Decimal(total)),
            money_delta=Decimal(total), posted_date=tanggal,
            occurred_at=datetime(2026, 7, 20, 10, 0),
            row_hash=f"f{self._n}",
            raw={"Bank": bank, "Kategori": kategori, "Jam": "10:00"},
        )


class DefaultTetapTests(_Base):
    """Tanpa parameter: perilaku lama tidak berubah sedikit pun."""

    def test_tanpa_param_potret_batch_terakhir(self):
        b1 = self.batch(D1)
        b2 = self.batch(D2, dp_sel=5000)
        self.tx("depo", "100000", b1)
        self.tx("depo", "40000", b2)
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context["mode_filter"])
        # panel_sum HANYA batch terakhir — bukan gabungan
        self.assertEqual(r.context["panel_sum"]["dp"], {"n": 1, "v": 40000.0})
        self.assertEqual(r.context["last"].pk, b2.pk)
        self.assertEqual(r.context["last_sel"], 5000)
        self.assertContains(r, "Rekon terakhir")
        self.assertContains(r, "tanpa filter — potret rekon terakhir")
        # prefill bar = tanggal batch terakhir
        self.assertEqual(r.context["bar_dari"], D2)
        self.assertEqual(r.context["bar_sampai"], D2)

    def test_param_invalid_jatuh_ke_default(self):
        b = self.batch(D2)
        self.tx("depo", "40000", b)
        r = self.client.get(reverse("dashboard"), {"dari": "pisang", "sampai": ""})
        self.assertFalse(r.context["mode_filter"])
        self.assertEqual(r.context["panel_sum"]["dp"], {"n": 1, "v": 40000.0})

    def test_default_setara_filter_tanggal_terakhir(self):
        b1 = self.batch(D1)
        b2 = self.batch(D2, um_d=3)
        self.tx("depo", "100000", b1)
        self.tx("wd", "20000", b2)
        base = self.client.get(reverse("dashboard"))
        flt = self.client.get(reverse("dashboard"),
                              {"dari": D2.isoformat(), "sampai": D2.isoformat()})
        self.assertEqual(base.context["panel_sum"], flt.context["panel_sum"])
        self.assertEqual(base.context["um_d"], flt.context["um_d"])
        self.assertEqual(base.context["last"].pk, flt.context["last"].pk)


class FilterTanggalTests(_Base):
    def test_tanggal_lampau_tunggal(self):
        b1 = self.batch(D1, dp_sel=7000, um_d=2)
        b2 = self.batch(D2)
        self.tx("depo", "100000", b1)
        self.tx("depo", "40000", b2)
        r = self.client.get(reverse("dashboard"),
                            {"dari": D1.isoformat(), "sampai": D1.isoformat()})
        self.assertTrue(r.context["mode_filter"])
        self.assertEqual(r.context["n_batch"], 1)
        self.assertEqual(r.context["panel_sum"]["dp"], {"n": 1, "v": 100000.0})
        self.assertEqual(r.context["last"].pk, b1.pk)
        self.assertEqual(r.context["last_sel"], 7000)
        self.assertEqual(r.context["um_d"], {"n": 2})
        self.assertContains(r, "Rekon dipilih")
        # kartu tetap link ke batch tanggal itu
        self.assertContains(r, reverse("batch_detail", args=[b1.pk]))

    def test_rentang_agregat_lintas_batch(self):
        b1 = self.batch(D1, dp_sel=7000, um_d=2)
        b2 = self.batch(D2, wd_sel=-3000, um_d=1)
        self.tx("depo", "100000", b1)
        self.tx("depo", "40000", b2)
        self.tx("wd", "30000", b2)
        r = self.client.get(reverse("dashboard"),
                            {"dari": D1.isoformat(), "sampai": D2.isoformat()})
        self.assertEqual(r.context["n_batch"], 2)
        self.assertEqual(
            r.context["panel_sum"],
            {"dp": {"n": 2, "v": 140000.0}, "wd": {"n": 1, "v": 30000.0},
             "total_n": 3, "net": 110000.0},
        )
        self.assertEqual(r.context["last_sel"], 10000)  # |7000| + |-3000|
        self.assertEqual(r.context["um_d"], {"n": 3})
        # tren = batch jendela saja
        self.assertEqual([t["b"].pk for t in r.context["tren"]], [b1.pk, b2.pk])
        # kalender ber-anchor sampai
        self.assertEqual(r.context["kal"][-1]["d"], D2)

    def test_dari_terbalik_ditukar(self):
        b1 = self.batch(D1)
        self.tx("depo", "100000", b1)
        r = self.client.get(reverse("dashboard"),
                            {"dari": D2.isoformat(), "sampai": D1.isoformat()})
        self.assertEqual(r.context["f_dari"], D1)
        self.assertEqual(r.context["f_sampai"], D2)
        self.assertEqual(r.context["n_batch"], 1)

    def test_satu_sisi_saja_jadi_satu_hari(self):
        self.batch(D1)
        r = self.client.get(reverse("dashboard"), {"dari": D1.isoformat()})
        self.assertEqual(r.context["f_dari"], D1)
        self.assertEqual(r.context["f_sampai"], D1)

    def test_rentang_kosong_tetap_render(self):
        self.batch(D2)
        r = self.client.get(reverse("dashboard"),
                            {"dari": "2026-01-01", "sampai": "2026-01-05"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["n_batch"], 0)
        self.assertIsNone(r.context["panel_sum"])
        self.assertIsNone(r.context["last"])
        self.assertContains(r, "Tidak ada batch dalam rentang")
        self.assertContains(r, "tidak ada batch dalam rentang")

    def test_runs_terfilter_jendela(self):
        b1 = self.batch(D1)
        b2 = self.batch(D2)
        r1 = MatchRun.objects.create(relation="panel_bank", tolerance=self.tol, batch=b1)
        MatchRun.objects.create(relation="panel_bank", tolerance=self.tol, batch=b2)
        r = self.client.get(reverse("dashboard"),
                            {"dari": D1.isoformat(), "sampai": D1.isoformat()})
        self.assertEqual([x.pk for x in r.context["runs"]], [r1.pk])

    def test_next_date_tetap_live(self):
        # "rekonsiliasi berikutnya" mengacu batch terakhir toko, bukan jendela
        self.batch(D1)
        self.batch(D2)
        r = self.client.get(reverse("dashboard"),
                            {"dari": D1.isoformat(), "sampai": D1.isoformat()})
        self.assertEqual(r.context["next_date"], D2 + timedelta(days=1))


class BracketRentangTests(_Base):
    def _seed_fr(self):
        # D1: deposit A 500rb, wd B -300rb; D2: deposit A 200rb, wd B -150rb
        # (ejaan alternatif "withdraw"), bonus (bukan dp/wd)
        self.fr(AKUN_A, "Deposit", "500000", D1)
        self.fr(AKUN_B, "Withdrawal", "-300000", D1)
        self.fr(AKUN_A, "Deposit", "200000", D2)
        self.fr(AKUN_B, "withdraw", "-150000", D2)
        self.fr(AKUN_A, "Bonus", "10000", D2)

    def test_tie_out_dengan_bracket_breakdown_rentang(self):
        self._seed_fr()
        # koreksi di salah satu hari jendela: rentang>1 hari HARUS mengabaikannya
        FRKoreksi.objects.create(
            toko=self.toko, tanggal=D1, account=AKUN_A, kolom="deposit",
            nilai=Decimal("999999"), alasan="mistake_cs",
        )
        data = bracket_breakdown(self.toko, D1, D2)
        hasil = ringkas_bracket_rentang(self.toko, D1, D2)
        self.assertEqual(hasil["dp"]["v"], data["total"]["deposit"])
        self.assertEqual(hasil["wd"]["v"], data["total"]["withdraw"])
        self.assertEqual(hasil["total_n"], data["total"]["trx"])
        self.assertEqual(hasil["dp"]["v"], Decimal("700000"))
        self.assertEqual(hasil["wd"]["v"], Decimal("450000"))
        self.assertEqual(hasil["dp"]["n"], 2)
        self.assertEqual(hasil["wd"]["n"], 2)
        self.assertEqual(hasil["net"], Decimal("250000"))

    def test_abs_per_akun_bukan_global(self):
        # akun B net wd POSITIF (refund > wd) — abs per akun harus tetap
        # tie out dengan bracket_breakdown, bukan abs global.
        self.fr(AKUN_A, "Withdrawal", "-100000", D1)
        self.fr(AKUN_B, "Withdrawal", "-20000", D1)
        self.fr(AKUN_B, "Withdrawal", "50000", D2)
        data = bracket_breakdown(self.toko, D1, D2)
        hasil = ringkas_bracket_rentang(self.toko, D1, D2)
        self.assertEqual(hasil["wd"]["v"], data["total"]["withdraw"])
        self.assertEqual(hasil["wd"]["v"], Decimal("130000"))  # 100rb + |30rb|

    def test_satu_hari_delegasi_ke_versi_hari(self):
        self.fr(AKUN_A, "Deposit", "500000", D1)
        FRKoreksi.objects.create(
            toko=self.toko, tanggal=D1, account=AKUN_A, kolom="deposit",
            nilai=Decimal("550000"), alasan="mistake_cs",
        )
        self.assertEqual(
            ringkas_bracket_rentang(self.toko, D1, D1),
            ringkas_bracket_hari(self.toko, D1),
        )
        # overlay 1-hari tetap berlaku
        self.assertEqual(
            ringkas_bracket_rentang(self.toko, D1, D1)["dp"]["v"],
            Decimal("550000"),
        )

    def test_none_tanpa_baris_dalam_rentang(self):
        self.fr(AKUN_A, "Deposit", "500000", date(2026, 6, 1))
        self.assertIsNone(ringkas_bracket_rentang(self.toko, D1, D2))

    def test_query_budget_rentang(self):
        self._seed_fr()
        with self.assertNumQueries(1):
            ringkas_bracket_rentang(self.toko, D1, D2)

    def test_dashboard_kartu_bracket_rentang_tanpa_batch(self):
        # jendela tanpa batch tapi ada baris FR → kartu bracket tetap tampil
        self._seed_fr()
        r = self.client.get(reverse("dashboard"),
                            {"dari": D1.isoformat(), "sampai": D2.isoformat()})
        self.assertEqual(r.context["n_batch"], 0)
        self.assertEqual(r.context["bracket_sum"]["dp"]["v"], Decimal("700000"))
        self.assertContains(r, "Ringkasan Bracket")
        # link kartu membawa rentang ke halaman /bracket/
        self.assertContains(
            r, f"?dari={D1.isoformat()}&amp;sampai={D2.isoformat()}"
        )


class SemuaTokoParamTests(_Base):
    def test_mode_semua_dengan_param_tak_crash(self):
        self.client.post(reverse("set_toko"), {"toko_id": "all"})
        r = self.client.get(reverse("dashboard"),
                            {"dari": D1.isoformat(), "sampai": D2.isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "web/dashboard_all.html")
