"""Dashboard: kartu 'Ringkasan Bracket' (trx & nilai DP/WD FR harian).

`ringkas_bracket_hari` adalah versi RINGAN dari `bracket_breakdown` — tanpa
`_saldo_carry` (full-history scan) — tapi harus tetap TIE OUT persis dengan
total deposit/withdraw `bracket_breakdown` untuk tanggal yang sama, termasuk
overlay `FRKoreksi` dan aturan skip-akun-absen.
"""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.breakdown import bracket_breakdown, ringkas_bracket_hari
from web.models import FRKoreksi

User = get_user_model()

TGL = date(2026, 7, 1)
AKUN_A = "BANK BCA | SUSI | DEPOSIT"
AKUN_B = "BANK BRI | YOGA | WITHDRAW"


class _BracketData(TestCase):
    """Fixture bracket dasar (pola web/tests_breakdown.py)."""

    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"}
        )[0]
        self.up = Upload.objects.create(source_type=self.bracket, toko=self.toko)
        self._n = 0

    def fr(self, bank, kategori, total, saldo=None, jam="10:00", tanggal=TGL):
        self._n += 1
        return Transaction.objects.create(
            upload=self.up, source_type=self.bracket, toko=self.toko,
            jenis="lainnya", amount=abs(Decimal(total)), money_delta=Decimal(total),
            balance_after=None if saldo is None else Decimal(saldo),
            posted_date=tanggal, occurred_at=datetime(2026, 7, 1, 10, 0),
            row_hash=f"rb{self._n}",
            raw={"Bank": bank, "Kategori": kategori, "Jam": jam},
        )

    def koreksi(self, kolom, nilai, account=AKUN_A, **over):
        base = dict(toko=self.toko, tanggal=TGL, account=account,
                    kolom=kolom, nilai=Decimal(nilai), alasan="mistake_cs")
        base.update(over)
        return FRKoreksi.objects.create(**base)


class TieOutTests(_BracketData):
    """Skenario inti: 2 akun, Pending DP, ejaan 'withdraw', bonus, 1 koreksi."""

    def _seed(self):
        # akun A: deposit asli 500rb + pending dp (keluar) + bonus (keluar)
        self.fr(AKUN_A, "Deposit", "500000", jam="09:00")
        self.fr(AKUN_A, "Pending DP", "20000", jam="09:05")
        self.fr(AKUN_A, "Bonus", "10000", jam="09:10")
        # akun B: withdrawal ejaan normal + ejaan alternatif "withdraw"
        self.fr(AKUN_B, "Withdrawal", "-300000", jam="11:00")
        self.fr(AKUN_B, "withdraw", "-150000", jam="11:30")
        # koreksi: timpa sel deposit akun A 500.000 → 550.000
        self.koreksi("deposit", "550000", account=AKUN_A)

    def test_tie_out_dengan_bracket_breakdown(self):
        self._seed()
        data = bracket_breakdown(self.toko, TGL)
        hasil = ringkas_bracket_hari(self.toko, TGL)
        self.assertEqual(hasil["dp"]["v"], data["total"]["deposit"])
        self.assertEqual(hasil["wd"]["v"], data["total"]["withdraw"])
        self.assertEqual(hasil["dp"]["v"], Decimal("550000"))
        self.assertEqual(hasil["wd"]["v"], Decimal("450000"))

    def test_hitungan_trx_dan_ringkasan_lengkap(self):
        self._seed()
        hasil = ringkas_bracket_hari(self.toko, TGL)
        # n TETAP dari baris nyata — koreksi tak mengubah jumlah trx.
        self.assertEqual(hasil["dp"]["n"], 1)
        self.assertEqual(hasil["wd"]["n"], 2)
        self.assertEqual(hasil["total_n"], 3)
        self.assertEqual(hasil["net"], Decimal("100000"))

    def test_koreksi_akun_absen_diabaikan(self):
        self._seed()
        # koreksi tambahan pada akun yang sama sekali tak punya baris hari ini
        self.koreksi("deposit", "999999999", account="BANK MANDIRI | HANTU | DEPOSIT")
        hasil = ringkas_bracket_hari(self.toko, TGL)
        # hasil identik dengan sebelum koreksi hantu ditambahkan
        self.assertEqual(hasil["dp"]["v"], Decimal("550000"))
        self.assertEqual(hasil["dp"]["n"], 1)

    def test_tanpa_koreksi_sum_mentah(self):
        self._seed()
        hasil = ringkas_bracket_hari(self.toko, TGL, dengan_koreksi=False)
        # tanpa overlay: deposit akun A tetap 500.000 (nilai asli, bukan 550.000)
        self.assertEqual(hasil["dp"]["v"], Decimal("500000"))
        self.assertEqual(hasil["wd"]["v"], Decimal("450000"))

    def test_query_budget(self):
        self._seed()
        with self.assertNumQueries(2):
            ringkas_bracket_hari(self.toko, TGL)


class TanpaBarisTests(_BracketData):
    def test_none_bila_tak_ada_baris_bracket(self):
        self.assertIsNone(ringkas_bracket_hari(self.toko, TGL))

    def test_none_tak_terpengaruh_tanggal_lain(self):
        self.fr(AKUN_A, "Deposit", "100000", tanggal=date(2026, 6, 30))
        self.assertIsNone(ringkas_bracket_hari(self.toko, TGL))


class DashboardCardTests(_BracketData):
    def setUp(self):
        super().setUp()
        User.objects.create_user("adm", "a@a.co", "pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})

    def _batch(self, d=TGL):
        return ReconBatch.objects.create(toko=self.toko, tolerance=self.tol, recon_date=d)

    def test_dashboard_render_kartu_bracket(self):
        self._batch()
        self.fr(AKUN_A, "Deposit", "500000")
        self.fr(AKUN_B, "Withdrawal", "-200000")
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Ringkasan Bracket")
        self.assertEqual(r.context["bracket_sum"]["dp"], {"n": 1, "v": Decimal("500000")})
        self.assertEqual(r.context["bracket_sum"]["wd"], {"n": 1, "v": Decimal("200000")})

    def test_tanpa_baris_bracket_kartu_absen(self):
        self._batch()
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context["bracket_sum"])
        self.assertNotContains(r, "Ringkasan Bracket")

    def test_tanpa_batch_dashboard_tetap_render(self):
        # toko aktif belum punya batch sama sekali — dashboard tidak boleh crash.
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context["bracket_sum"])
        self.assertNotContains(r, "Ringkasan Bracket")
