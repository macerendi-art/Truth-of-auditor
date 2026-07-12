"""Breakdown Bracket (FR) — unit agregasi `web.breakdown` + view `/bracket/`.

Kontrak agregasi (lihat docs/superpowers/specs/2026-07-12-breakdown-bracket-design.md):
baris per FR Account (`raw["Bank"]`), pivot per kategori asli (`raw["Kategori"]`),
saldo awal/akhir dari `balance_after` urut `(raw["Jam"], id)`, dan
Selisih Kontrol = saldo_akhir − (saldo_awal + Σ money_delta) — idealnya 0.
"""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.breakdown import bracket_breakdown

TGL = date(2026, 7, 1)


class _BracketData(TestCase):
    """Fixture dasar: toko LBS + upload bracket; helper pembuat baris FR."""

    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"}
        )[0]
        self.up = Upload.objects.create(source_type=self.bracket, toko=self.toko)
        self._n = 0

    def fr(self, bank, kategori, total, saldo, jam="10:00", tanggal=TGL, jenis="lainnya"):
        """Satu baris FR: `total` bertanda (str), `saldo` = Saldo Akhir (str|None)."""
        self._n += 1
        return Transaction.objects.create(
            upload=self.up, source_type=self.bracket, toko=self.toko,
            jenis=jenis, amount=abs(Decimal(total)), money_delta=Decimal(total),
            balance_after=None if saldo is None else Decimal(saldo),
            posted_date=tanggal, occurred_at=datetime(2026, 7, 1, 10, 0),
            row_hash=f"br{self._n}",
            raw={"Bank": bank, "Kategori": kategori, "Jam": jam},
        )


class AgregasiPivotTests(_BracketData):
    def test_pivot_per_kategori_dan_selisih_nol(self):
        # QRIS: saldo awal 1.000.000 → depo +500rb → beban admin −4.972 → 1.495.028
        self.fr("QRIS HOKI | DEPOSIT / WITHDRAW", "Deposit", "500000", "1500000", jam="09:00")
        self.fr("QRIS HOKI | DEPOSIT / WITHDRAW", "BEBAN ADMIN QRIS", "-4972", "1495028", jam="10:30")
        data = bracket_breakdown(self.toko, TGL)
        self.assertEqual(data["count"], 2)
        (acc,) = data["accounts"]
        self.assertEqual(acc["name"], "QRIS HOKI")
        self.assertEqual(acc["role"], "DEPOSIT / WITHDRAW")
        self.assertEqual(acc["kategori"]["deposit"], Decimal("500000"))
        self.assertEqual(acc["kategori"]["beban admin qris"], Decimal("-4972"))
        self.assertEqual(acc["saldo_awal"], Decimal("1000000"))
        self.assertEqual(acc["saldo_akhir"], Decimal("1495028"))
        self.assertEqual(acc["mutasi"], Decimal("495028"))
        self.assertEqual(acc["selisih"], Decimal("0"))

    def test_selisih_terdeteksi_bila_saldo_fr_janggal(self):
        self.fr("BANK BCA | HENDI | WITHDRAW", "Withdrawal", "-100000", "900000", jam="09:00")
        # Saldo akhir FR "melompat" 50rb tanpa mutasi -> selisih kontrol -50rb? bukan:
        # akhir 850.000, padahal awal(1.000.000) + mutasi(-100.000-25.000) = 875.000 → selisih -25.000
        self.fr("BANK BCA | HENDI | WITHDRAW", "BEBAN ADMIN BANK", "-25000", "850000", jam="10:00")
        (acc,) = bracket_breakdown(self.toko, TGL)["accounts"]
        self.assertEqual(acc["selisih"], Decimal("-25000"))

    def test_urutan_jam_menentukan_saldo_awal_akhir(self):
        # Baris dimasukkan TIDAK urut jam — saldo harus mengikuti (Jam, id).
        self.fr("BANK BRI | YOGA | WITHDRAW", "Withdrawal", "-50000", "150000", jam="14:00")
        self.fr("BANK BRI | YOGA | WITHDRAW", "Withdrawal", "-100000", "200000", jam="08:00")
        (acc,) = bracket_breakdown(self.toko, TGL)["accounts"]
        self.assertEqual(acc["saldo_awal"], Decimal("300000"))   # 200rb − (−100rb)
        self.assertEqual(acc["saldo_akhir"], Decimal("150000"))  # baris jam 14:00
        self.assertEqual(acc["selisih"], Decimal("0"))

    def test_varian_withdraw_disatukan_ke_withdrawal(self):
        self.fr("BANK BNI | FITRIA | WITHDRAW", "Withdraw", "-70000", "30000")
        (acc,) = bracket_breakdown(self.toko, TGL)["accounts"]
        self.assertEqual(acc["kategori"]["withdrawal"], Decimal("-70000"))

    def test_kolom_hanya_kategori_yang_muncul_urutan_kanonik(self):
        self.fr("QRIS HOKI | DEPOSIT / WITHDRAW", "BEBAN ADMIN QRIS", "-5000", "95000", jam="11:00")
        self.fr("QRIS HOKI | DEPOSIT / WITHDRAW", "Deposit", "60000", "100000", jam="09:00")
        self.fr("QRIS HOKI | DEPOSIT / WITHDRAW", "Hutang Budi", "-1000", "94000", jam="12:00")
        kolom = bracket_breakdown(self.toko, TGL)["kolom"]
        slugs = [k for k, _ in kolom]
        # kanonik dulu (deposit < beban admin qris), tak dikenal di ujung
        self.assertEqual(slugs, ["deposit", "beban admin qris", "hutang budi"])
        labels = dict(kolom)
        self.assertEqual(labels["beban admin qris"], "Beban Admin QRIS")
        self.assertEqual(labels["hutang budi"], "Hutang Budi")
        self.assertNotIn("withdrawal", slugs)  # tidak muncul hari itu → tak ada kolomnya

    def test_akun_tanpa_bank_dan_balance_none(self):
        self.fr("", "Adjustment", "1000", None)
        (acc,) = bracket_breakdown(self.toko, TGL)["accounts"]
        self.assertEqual(acc["account"], "(Tanpa Akun)")
        self.assertIsNone(acc["saldo_awal"])
        self.assertIsNone(acc["saldo_akhir"])
        self.assertIsNone(acc["selisih"])
        self.assertEqual(acc["mutasi"], Decimal("1000"))

    def test_baris_balance_none_tetap_masuk_mutasi(self):
        self.fr("BANK BCA | HENDI | WITHDRAW", "Withdrawal", "-10000", "90000", jam="09:00")
        self.fr("BANK BCA | HENDI | WITHDRAW", "Adjustment", "-5000", None, jam="10:00")
        (acc,) = bracket_breakdown(self.toko, TGL)["accounts"]
        self.assertEqual(acc["mutasi"], Decimal("-15000"))
        self.assertEqual(acc["saldo_akhir"], Decimal("90000"))  # baris ber-balance terakhir
        self.assertEqual(acc["selisih"], Decimal("5000"))  # anomali: mutasi tanpa jejak saldo

    def test_urutan_akun_per_peran(self):
        self.fr("QRIS HOKI | DEPOSIT / WITHDRAW", "Deposit", "1000", "1000")
        self.fr("BANK BCA | HENDI | WITHDRAW", "Withdrawal", "-1000", "1000")
        self.fr("BANK BCA | IRFAN | DEPOSIT", "Deposit", "1000", "1000")
        self.fr("LAIN | COST", "Adjustment", "1000", "1000")
        names = [a["account"] for a in bracket_breakdown(self.toko, TGL)["accounts"]]
        self.assertEqual(names, [
            "BANK BCA | IRFAN | DEPOSIT",
            "BANK BCA | HENDI | WITHDRAW",
            "QRIS HOKI | DEPOSIT / WITHDRAW",
            "LAIN | COST",
        ])

    def test_kartu_rekap_pending_tak_dihitung(self):
        self.fr("BANK BCA | IRFAN | DEPOSIT", "Deposit", "100000", "100000", jam="09:00")
        self.fr("BANK BCA | IRFAN | DEPOSIT", "Deposit", "50000", "150000", jam="10:00")
        self.fr("BANK BCA | IRFAN | DEPOSIT", "Pending DP", "14000", "164000", jam="11:00")
        self.fr("BANK BCA | IRFAN | DEPOSIT", "Withdrawal", "-30000", "134000", jam="12:00")
        (acc,) = bracket_breakdown(self.toko, TGL)["accounts"]
        self.assertEqual(acc["deposit"], Decimal("150000"))
        self.assertEqual(acc["withdraw"], Decimal("30000"))
        self.assertEqual(acc["net"], Decimal("120000"))
        self.assertEqual(acc["trx"], 3)  # 2 depo + 1 wd; pending TIDAK ikut

    def test_total_lintas_akun(self):
        self.fr("BANK BCA | IRFAN | DEPOSIT", "Deposit", "100000", "150000", jam="09:00")
        self.fr("QRIS HOKI | DEPOSIT / WITHDRAW", "Deposit", "40000", "90000", jam="09:30")
        data = bracket_breakdown(self.toko, TGL)
        tot = data["total"]
        self.assertEqual(tot["kategori"]["deposit"], Decimal("140000"))
        self.assertEqual(tot["saldo_awal"], Decimal("100000"))   # 50rb + 50rb
        self.assertEqual(tot["saldo_akhir"], Decimal("240000"))
        self.assertEqual(tot["mutasi"], Decimal("140000"))
        self.assertEqual(tot["selisih"], Decimal("0"))
        self.assertEqual(tot["trx"], 2)

    def test_tanggal_dan_toko_lain_tak_ikut(self):
        self.fr("BANK BCA | IRFAN | DEPOSIT", "Deposit", "100000", "100000")
        self.fr("BANK BCA | IRFAN | DEPOSIT", "Deposit", "999", "999", tanggal=date(2026, 6, 30))
        toko2 = Toko.objects.exclude(pk=self.toko.pk).first()
        up2 = Upload.objects.create(source_type=self.bracket, toko=toko2)
        Transaction.objects.create(
            upload=up2, source_type=self.bracket, toko=toko2, jenis="lainnya",
            amount=Decimal("5"), money_delta=Decimal("5"), posted_date=TGL,
            row_hash="lain-toko", raw={"Bank": "X | Y | DEPOSIT", "Kategori": "Deposit", "Jam": "09:00"},
        )
        data = bracket_breakdown(self.toko, TGL)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["accounts"][0]["kategori"]["deposit"], Decimal("100000"))


class BreakdownViewTests(_BracketData):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})

    def test_butuh_login(self):
        self.client.logout()
        r = self.client.get(reverse("bracket_breakdown"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("login", r["Location"])

    def test_default_ke_tanggal_terakhir_yang_ada_data(self):
        self.fr("QRIS HOKI | DEPOSIT / WITHDRAW", "Deposit", "60000", "100000")
        r = self.client.get(reverse("bracket_breakdown"))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("QRIS HOKI", html)
        self.assertIn("Control Bracket Transaction", html)
        self.assertIn("Pergerakan per Bank", html)
        self.assertIn('value="2026-07-01"', html)

    def test_tanggal_kosong_empty_state_dengan_link_data_terakhir(self):
        self.fr("QRIS HOKI | DEPOSIT / WITHDRAW", "Deposit", "60000", "100000")
        r = self.client.get(reverse("bracket_breakdown"), {"date": "2026-07-05"})
        html = r.content.decode()
        self.assertIn("Belum ada data bracket", html)
        self.assertIn("2026-07-01", html)  # petunjuk tanggal terakhir ber-data

    def test_tanpa_data_sama_sekali(self):
        r = self.client.get(reverse("bracket_breakdown"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("Belum ada data bracket", r.content.decode())
