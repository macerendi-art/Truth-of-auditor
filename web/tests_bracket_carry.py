"""Breakdown Bracket — saldo carry-forward + rentang tanggal (Fitur I1).

Menguji `web.breakdown.bracket_breakdown` dengan tanda tangan rentang
`(toko, dari, sampai=None, ...)`: saldo awal = penutup (dari−1), agregasi
mutasi lintas hari, akun dorman bersaldo tetap tampil (carry murni), akun
bersaldo-nol disembunyikan, koreksi FR hanya berlaku pada tampilan 1 hari.

DB dev cuma punya 1 hari bracket per toko, jadi semua skenario carry-forward
dibangun dari fixture SINTETIS lintas-hari.
"""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.breakdown import bracket_breakdown, _saldo_carry

D0 = date(2026, 7, 1)   # hari "sebelum"
D1 = date(2026, 7, 2)   # hari filter utama
D2 = date(2026, 7, 3)
D3 = date(2026, 7, 4)


class _CarryData(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"}
        )[0]
        self.up = Upload.objects.create(source_type=self.bracket, toko=self.toko)
        self._n = 0

    def fr(self, bank, kategori, total, saldo, jam="10:00", tanggal=D1):
        self._n += 1
        return Transaction.objects.create(
            upload=self.up, source_type=self.bracket, toko=self.toko,
            jenis="lainnya", amount=abs(Decimal(total)), money_delta=Decimal(total),
            balance_after=None if saldo is None else Decimal(saldo),
            posted_date=tanggal, occurred_at=datetime(2026, 7, 1, 10, 0),
            row_hash=f"br{self._n}",
            raw={"Bank": bank, "Kategori": kategori, "Jam": jam},
        )


ACC = "BANK BRI | MARGANI | DEPOSIT"


class SingleDayBackCompatTests(_CarryData):
    def test_single_day_tanpa_hari_sebelum_sama_dengan_lama(self):
        # 1 hari, akun ber-gerak, TANPA hari sebelumnya → carry kosong →
        # output identik perilaku lama (saldo_awal = pembukaan rantai).
        self.fr(ACC, "Deposit", "500000", "1500000", jam="09:00", tanggal=D1)
        self.fr(ACC, "BEBAN ADMIN QRIS", "-4972", "1495028", jam="10:30", tanggal=D1)
        # dua bentuk pemanggilan harus setara: (toko, D1) dan (toko, D1, D1)
        a1 = bracket_breakdown(self.toko, D1)
        a2 = bracket_breakdown(self.toko, D1, D1)
        self.assertEqual(a1["accounts"], a2["accounts"])
        (acc,) = a1["accounts"]
        self.assertEqual(acc["saldo_awal"], Decimal("1000000"))
        self.assertEqual(acc["saldo_akhir"], Decimal("1495028"))
        self.assertEqual(acc["mutasi"], Decimal("495028"))
        self.assertEqual(acc["selisih"], Decimal("0"))
        self.assertEqual(a1["count"], 2)


class CarryForwardDormanTests(_CarryData):
    def test_akun_dorman_bersaldo_muncul_single_dan_rentang(self):
        # Didanai D0 (penutup 750rb), TIDAK ada baris di D1.
        self.fr(ACC, "Deposit", "750000", "750000", jam="08:00", tanggal=D0)
        for dari, sampai in [(D1, D1), (D1, D3)]:
            data = bracket_breakdown(self.toko, dari, sampai)
            accs = [a for a in data["accounts"] if a["account"] == ACC]
            self.assertEqual(len(accs), 1, f"akun dorman hilang pada {dari}..{sampai}")
            acc = accs[0]
            self.assertEqual(acc["saldo_awal"], Decimal("750000"))
            self.assertEqual(acc["saldo_akhir"], Decimal("750000"))
            self.assertEqual(acc["mutasi"], Decimal("0"))
            self.assertEqual(acc["trx"], 0)
            self.assertEqual(acc["selisih"], Decimal("0"))
            self.assertEqual(acc["kategori"], {})
            self.assertEqual(data["count"], 0)  # tak ada baris in-range

    def test_akun_saldo_nol_lalu_diam_disembunyikan(self):
        # D0 ditutup ke 0; tak ada baris di D1 → akun disembunyikan.
        self.fr(ACC, "Deposit", "100000", "100000", jam="08:00", tanggal=D0)
        self.fr(ACC, "Withdrawal", "-100000", "0", jam="09:00", tanggal=D0)
        data = bracket_breakdown(self.toko, D1, D1)
        self.assertEqual([a for a in data["accounts"] if a["account"] == ACC], [])

    def test_akun_tanpa_histori_tanpa_baris_tak_muncul(self):
        self.fr("LAIN | X | DEPOSIT", "Deposit", "5000", "5000", jam="08:00", tanggal=D1)
        data = bracket_breakdown(self.toko, D2, D2)  # tak ada apa pun pada/ sebelum D2? ada D1
        # akun LAIN punya penutup 5000 di D1 → dorman muncul di D2
        self.assertIn("LAIN | X | DEPOSIT", [a["account"] for a in data["accounts"]])
        # akun yang tak pernah ada → tak muncul
        self.assertNotIn(ACC, [a["account"] for a in data["accounts"]])


class RentangAgregasiTests(_CarryData):
    def test_saldo_awal_dari_penutup_h1(self):
        # D0 penutup = 200rb; D1 ada gerak. saldo_awal harus 200rb (penutup D0),
        # bukan pembukaan rantai D1.
        self.fr(ACC, "Deposit", "50000", "150000", jam="09:00", tanggal=D0)
        self.fr(ACC, "Deposit", "50000", "200000", jam="10:00", tanggal=D0)
        self.fr(ACC, "Deposit", "100000", "300000", jam="09:00", tanggal=D1)
        (acc,) = [a for a in bracket_breakdown(self.toko, D1, D1)["accounts"]
                  if a["account"] == ACC]
        self.assertEqual(acc["saldo_awal"], Decimal("200000"))  # penutup D0
        self.assertEqual(acc["saldo_akhir"], Decimal("300000"))
        self.assertEqual(acc["mutasi"], Decimal("100000"))
        self.assertEqual(acc["selisih"], Decimal("0"))

    def test_rentang_multi_hari_agregasi(self):
        # D0 penutup 100rb; D1 +200rb → 300rb; D2 +50rb → 350rb.
        self.fr(ACC, "Deposit", "100000", "100000", jam="08:00", tanggal=D0)
        self.fr(ACC, "Deposit", "200000", "300000", jam="09:00", tanggal=D1)
        self.fr(ACC, "Deposit", "50000", "350000", jam="09:00", tanggal=D2)
        data = bracket_breakdown(self.toko, D1, D2)
        (acc,) = [a for a in data["accounts"] if a["account"] == ACC]
        self.assertEqual(acc["saldo_awal"], Decimal("100000"))   # penutup D0 (dari−1)
        self.assertEqual(acc["saldo_akhir"], Decimal("350000"))  # penutup D2 (sampai)
        self.assertEqual(acc["mutasi"], Decimal("250000"))       # Σ lintas 2 hari
        self.assertEqual(acc["kategori"]["deposit"], Decimal("250000"))
        self.assertEqual(acc["selisih"], Decimal("0"))
        self.assertEqual(data["count"], 2)

    def test_rentang_gap_hari_tengah(self):
        # baris di D1 dan D3, kosong D2; rentang [D1,D3].
        self.fr(ACC, "Deposit", "100000", "100000", jam="09:00", tanggal=D1)
        self.fr(ACC, "Deposit", "40000", "140000", jam="09:00", tanggal=D3)
        data = bracket_breakdown(self.toko, D1, D3)
        (acc,) = [a for a in data["accounts"] if a["account"] == ACC]
        self.assertEqual(acc["saldo_akhir"], Decimal("140000"))  # dari D3
        self.assertEqual(acc["mutasi"], Decimal("140000"))
        self.assertEqual(acc["selisih"], Decimal("0"))

    def test_total_termasuk_akun_carried(self):
        # akun ber-gerak + akun dorman → total menjumlah saldo keduanya.
        self.fr(ACC, "Deposit", "100000", "100000", jam="09:00", tanggal=D1)
        self.fr("LAIN | Y | DEPOSIT", "Deposit", "300000", "300000", jam="08:00", tanggal=D0)
        data = bracket_breakdown(self.toko, D1, D1)
        tot = data["total"]
        self.assertEqual(tot["saldo_awal"], Decimal("300000"))   # 0(gerak,pembukaan)+300rb(carry)
        self.assertEqual(tot["saldo_akhir"], Decimal("400000"))  # 100rb + 300rb
        self.assertEqual(tot["mutasi"], Decimal("100000"))       # carry tak menambah mutasi


class CarryEfisiensiTests(_CarryData):
    def test_saldo_carry_query_terbatas_bukan_scan_sejarah(self):
        # 5 akun berbeda dengan histori D0 → _saldo_carry harus tetap 2 query
        # (agregat Max per akun + fetch hari-penutup), bukan N+1 per akun.
        for i in range(5):
            self.fr(f"BANK BRI | ORANG{i} | DEPOSIT", "Deposit",
                    "10000", "10000", jam="08:00", tanggal=D0)
        with self.assertNumQueries(2):
            carry = _saldo_carry(self.toko, D1)
        self.assertEqual(len(carry), 5)


class KoreksiHanyaSingleDayTests(_CarryData):
    def _buat_koreksi(self, tanggal, kolom, nilai):
        from web.models import FRKoreksi
        User = get_user_model()
        u = User.objects.create_user("k", "k@k.co", "pw12345", role="admin")
        FRKoreksi.objects.create(
            toko=self.toko, tanggal=tanggal, account=ACC, kolom=kolom,
            nilai=Decimal(nilai), dibuat_oleh=u)

    def test_koreksi_diterapkan_single_diabaikan_rentang(self):
        self.fr(ACC, "Deposit", "100000", "100000", jam="09:00", tanggal=D1)
        self.fr(ACC, "Deposit", "50000", "150000", jam="09:00", tanggal=D2)
        self._buat_koreksi(D1, "deposit", "999999")
        # single-day D1 → koreksi kena
        (acc1,) = [a for a in bracket_breakdown(self.toko, D1, D1)["accounts"]
                   if a["account"] == ACC]
        self.assertEqual(acc1["kategori"]["deposit"], Decimal("999999"))
        self.assertIn("deposit", acc1["koreksi"])
        # rentang [D1,D2] → koreksi diabaikan (nilai mentah Σ = 150rb)
        (accR,) = [a for a in bracket_breakdown(self.toko, D1, D2)["accounts"]
                   if a["account"] == ACC]
        self.assertEqual(accR["kategori"]["deposit"], Decimal("150000"))
        self.assertEqual(accR["koreksi"], {})


class BreakdownRentangViewTests(_CarryData):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})

    def test_default_single_latest_backcompat(self):
        self.fr(ACC, "Deposit", "60000", "100000", tanggal=D1)
        r = self.client.get(reverse("bracket_breakdown"))
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        self.assertEqual(ctx["dari"], D1)
        self.assertEqual(ctx["sampai"], D1)
        self.assertTrue(ctx["koreksi_on"])
        html = r.content.decode()
        self.assertIn('name="dari"', html)
        self.assertIn('name="sampai"', html)
        self.assertIn('value="2026-07-02"', html)

    def test_date_lama_diterima_sebagai_dari_sampai(self):
        self.fr(ACC, "Deposit", "60000", "100000", tanggal=D1)
        r = self.client.get(reverse("bracket_breakdown"), {"date": "2026-07-02"})
        self.assertEqual(r.context["dari"], D1)
        self.assertEqual(r.context["sampai"], D1)

    def test_rentang_mematikan_koreksi_dan_sel_polos(self):
        self.fr(ACC, "Deposit", "60000", "100000", jam="09:00", tanggal=D1)
        self.fr(ACC, "Deposit", "40000", "140000", jam="09:00", tanggal=D2)
        r = self.client.get(reverse("bracket_breakdown"),
                            {"dari": "2026-07-02", "sampai": "2026-07-03"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context["koreksi_on"])
        html = r.content.decode()
        # mode rentang: sel Control Bracket tidak boleh punya hook koreksi
        # (string "cell-edit" tetap ada di blok <style>, jadi cek hook hx-get)
        self.assertNotIn("kolom=saldo_awal", html)
        self.assertIn("koreksi tersedia", html.lower())  # catatan kecil

    def test_single_day_sel_klik_koreksi_hadir(self):
        self.fr(ACC, "Deposit", "60000", "100000", jam="09:00", tanggal=D1)
        r = self.client.get(reverse("bracket_breakdown"), {"dari": "2026-07-02", "sampai": "2026-07-02"})
        html = r.content.decode()
        self.assertIn("kolom=saldo_awal", html)

    def test_prev_next_geser_seluruh_jendela(self):
        self.fr(ACC, "Deposit", "60000", "100000", tanggal=D1)
        r = self.client.get(reverse("bracket_breakdown"),
                            {"dari": "2026-07-02", "sampai": "2026-07-04"})  # span 3 hari
        ctx = r.context
        self.assertEqual(ctx["prev_dari"], date(2026, 6, 29))
        self.assertEqual(ctx["prev_sampai"], date(2026, 7, 1))
        self.assertEqual(ctx["next_dari"], date(2026, 7, 5))
        self.assertEqual(ctx["next_sampai"], date(2026, 7, 7))
