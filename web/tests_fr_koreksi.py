"""Koreksi sel FR (paket A): model overlay + agregasi + view popup."""
from datetime import date, datetime
from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase

from sources.models import Toko, SourceType, Upload
from transactions.models import Transaction
from web.breakdown import bracket_breakdown, KATEGORI_KANONIK

TGL = date(2026, 7, 1)


class FRKoreksiModelTests(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")

    def _buat(self, **over):
        from web.models import FRKoreksi
        base = dict(toko=self.toko, tanggal=TGL,
                    account="BANK BCA | SUSILAWATI | DEPOSIT",
                    kolom="deposit", nilai=Decimal("123000"),
                    alasan="mistake_cs", catatan="salah input CS")
        base.update(over)
        return FRKoreksi.objects.create(**base)

    def test_buat_dan_str(self):
        k = self._buat()
        self.assertIn("BANK BCA", str(k))
        self.assertIn("deposit", str(k))
        self.assertEqual(k.get_alasan_display(), "Mistake CS")

    def test_satu_koreksi_per_sel(self):
        self._buat()
        with self.assertRaises(IntegrityError):
            self._buat(nilai=Decimal("999"))

    def test_sel_beda_boleh(self):
        self._buat()
        self._buat(kolom="saldo_awal")
        self._buat(tanggal=date(2026, 7, 2))
        from web.models import FRKoreksi
        self.assertEqual(FRKoreksi.objects.count(), 3)


class _BracketKoreksiData(TestCase):
    """Fixture bracket + helper baris FR (pola web/tests_breakdown.py)."""

    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"})[0]
        self.up = Upload.objects.create(source_type=self.bracket, toko=self.toko)
        self._n = 0

    def fr(self, bank, kategori, total, saldo, jam="10:00"):
        self._n += 1
        return Transaction.objects.create(
            upload=self.up, source_type=self.bracket, toko=self.toko,
            jenis="lainnya", amount=abs(Decimal(total)), money_delta=Decimal(total),
            balance_after=None if saldo is None else Decimal(saldo),
            posted_date=TGL, occurred_at=datetime(2026, 7, 1, 10, 0),
            row_hash=f"frk{self._n}",
            raw={"Bank": bank, "Kategori": kategori, "Jam": jam},
        )

    def koreksi(self, kolom, nilai, account="BANK BCA | SUSI | DEPOSIT", **over):
        from web.models import FRKoreksi
        base = dict(toko=self.toko, tanggal=TGL, account=account,
                    kolom=kolom, nilai=Decimal(nilai), alasan="mistake_cs")
        base.update(over)
        return FRKoreksi.objects.create(**base)


class OverlayKoreksiTests(_BracketKoreksiData):
    AKUN = "BANK BCA | SUSI | DEPOSIT"

    def _dasar(self):
        # saldo awal 1.000.000 → depo +500rb (saldo 1.500.000) → beban −4.972
        self.fr(self.AKUN, "Deposit", "500000", "1500000", jam="09:00")
        self.fr(self.AKUN, "BEBAN ADMIN QRIS", "-4972", "1495028", jam="10:30")

    def test_tanpa_koreksi_perilaku_lama_persis(self):
        self._dasar()
        data = bracket_breakdown(self.toko, TGL)
        (acc,) = data["accounts"]
        self.assertEqual(acc["koreksi"], {})
        self.assertEqual(acc["mutasi"], Decimal("495028"))
        self.assertEqual(acc["selisih"], Decimal("0"))

    def test_koreksi_sel_kategori_mengubah_mutasi_selisih_total(self):
        self._dasar()
        self.koreksi("deposit", "450000", catatan="salah input")
        data = bracket_breakdown(self.toko, TGL)
        (acc,) = data["accounts"]
        self.assertEqual(acc["kategori"]["deposit"], Decimal("450000"))
        self.assertEqual(acc["mutasi"], Decimal("445028"))       # 450000 − 4972
        self.assertEqual(acc["selisih"], Decimal("50000"))       # akhir − (awal+mutasi)
        self.assertEqual(data["total"]["kategori"]["deposit"], Decimal("450000"))
        self.assertEqual(data["total"]["mutasi"], Decimal("445028"))
        info = acc["koreksi"]["deposit"]
        self.assertEqual(info["asli"], Decimal("500000"))
        self.assertEqual(info["nilai"], Decimal("450000"))
        self.assertEqual(info["alasan"], "Mistake CS")
        self.assertEqual(info["catatan"], "salah input")

    def test_koreksi_saldo_awal(self):
        self._dasar()
        self.koreksi("saldo_awal", "900000")
        data = bracket_breakdown(self.toko, TGL)
        (acc,) = data["accounts"]
        self.assertEqual(acc["saldo_awal"], Decimal("900000"))
        self.assertEqual(acc["selisih"], Decimal("100000"))
        self.assertEqual(acc["koreksi"]["saldo_awal"]["asli"], Decimal("1000000"))

    def test_koreksi_kategori_belum_muncul_menambah_kolom(self):
        self._dasar()
        self.koreksi("beban mistake cs", "-25000")
        data = bracket_breakdown(self.toko, TGL)
        (acc,) = data["accounts"]
        self.assertEqual(acc["kategori"]["beban mistake cs"], Decimal("-25000"))
        self.assertIn("beban mistake cs", [s for s, _ in data["kolom"]])
        self.assertIsNone(acc["koreksi"]["beban mistake cs"]["asli"])

    def test_dengan_koreksi_false_nilai_asli(self):
        self._dasar()
        self.koreksi("deposit", "450000")
        data = bracket_breakdown(self.toko, TGL, dengan_koreksi=False)
        (acc,) = data["accounts"]
        self.assertEqual(acc["kategori"]["deposit"], Decimal("500000"))
        self.assertEqual(acc["koreksi"], {})

    def test_koreksi_akun_tak_hadir_diabaikan(self):
        self._dasar()
        self.koreksi("deposit", "1", account="BANK LAIN | X | DEPOSIT")
        data = bracket_breakdown(self.toko, TGL)
        (acc,) = data["accounts"]
        self.assertEqual(acc["kategori"]["deposit"], Decimal("500000"))


class UrutanHeaderTests(TestCase):
    def test_acuan_kuning_other_expense_sebelum_mistake_cs(self):
        slugs = [s for s, _ in KATEGORI_KANONIK]
        i_biaya = slugs.index("biaya transaksi")
        i_other = slugs.index("beban other expense")
        i_cs = slugs.index("beban mistake cs")
        self.assertLess(i_biaya, i_other)
        self.assertLess(i_other, i_cs)
