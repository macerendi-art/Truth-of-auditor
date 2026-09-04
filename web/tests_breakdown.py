"""Breakdown Bracket (FR) — unit agregasi `web.breakdown` + view `/bracket/`.

Kontrak agregasi (lihat docs/superpowers/specs/2026-07-12-breakdown-bracket-design.md):
baris per FR Account (`raw["Bank"]`), pivot per kategori asli (`raw["Kategori"]`),
saldo awal/akhir dari `balance_after` urut `(raw["Jam"], id)`, dan
Selisih Kontrol = saldo_akhir − (saldo_awal + Σ money_delta) — idealnya 0.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.breakdown import _saldo_carry, bracket_breakdown

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

    def test_urutan_acak_dalam_menit_sama_tidak_memicu_alarm_palsu(self):
        # FR nyata mengacak urutan baris DI DALAM menit yang sama. Rantai saldo:
        # 100rb → (+50rb) 150rb → (+30rb) 180rb → (+10rb) 190rb, tapi baris
        # ditulis file dengan urutan acak. Saldo awal/akhir harus tetap benar.
        self.fr("QRIS FLYER | DEPOSIT / WITHDRAW", "Deposit", "30000", "180000", jam="00:01")
        self.fr("QRIS FLYER | DEPOSIT / WITHDRAW", "Deposit", "10000", "190000", jam="00:01")
        self.fr("QRIS FLYER | DEPOSIT / WITHDRAW", "Deposit", "50000", "150000", jam="00:01")
        (acc,) = bracket_breakdown(self.toko, TGL)["accounts"]
        self.assertEqual(acc["saldo_awal"], Decimal("100000"))
        self.assertEqual(acc["saldo_akhir"], Decimal("190000"))
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


class BreakdownQueryShapeTests(_BracketData):
    """Bentuk query WAJIB konstan — invarian inti v1.23.0 (CLAUDE.md 'Performa
    v1.23.0'): halaman ini dulu menyapu seluruh riwayat toko untuk mencari
    saldo penutup `dari−1` (terukur 608 ms/15 hari → 1.605 ms/52 hari, TUMBUH
    SELAMANYA). Sekarang `_saldo_carry` memakai loose index scan rekursif
    (WITH RECURSIVE) — biayanya O(#akun × log N), bukan O(umur data). Tes di
    sini mengunci BENTUK (jumlah query tetap, tak bergantung umur/rentang
    data), bukan milidetik yang rapuh di runner CI berbagi.
    """

    def test_bracket_breakdown_query_konstan_walau_riwayat_jauh_lebih_tua(self):
        """5 query TETAP SAMA baik ada 1 hari riwayat pra-`dari` maupun 60 hari.

        5 = (1) `grup` (GROUP BY Bank×Kategori, sel kategori/mutasi/trx) +
        (2) `_ujung_saldo` (hitungan-bertanda ujung rantai saldo, 1 query raw
        cursor) + `_saldo_carry`: (3) WITH RECURSIVE (akun + tanggal-penutup
        pra-`dari`) + (4) `_ujung_saldo_hari` (penutup per akun×hari-penutup,
        1 query raw cursor lain) — keduanya HANYA berjalan karena ada riwayat
        pra-`dari` (`_saldo_carry` pulang di query (3) saja bila kosong) — plus
        (5) `FRKoreksi.objects.filter(...)` dari `_apply_koreksi` (mode 1-hari
        selalu memanggilnya, walau hasilnya kosong). Tak satu pun tumbuh
        dengan JUMLAH HARI riwayat pra-`dari` — hanya jumlah AKUN yang
        (jika beda-beda) menambah baris hasil, bukan baris query.
        """
        D0 = date(2026, 6, 30)
        self.fr("BANK BRI | MARGANI | DEPOSIT", "Deposit", "500000", "1500000",
                jam="09:00", tanggal=TGL)
        self.fr("BANK BRI | MARGANI | DEPOSIT", "BEBAN ADMIN QRIS", "-4972",
                "1495028", jam="10:30", tanggal=TGL)
        # satu baris riwayat pra-`dari`, cukup memasuki cabang carry 2-query.
        self.fr("BANK BRI | MARGANI | DEPOSIT", "Deposit", "1000000", "1000000",
                jam="08:00", tanggal=D0)

        with self.assertNumQueries(5):
            sebelum = bracket_breakdown(self.toko, TGL)

        # 60 hari riwayat JAUH lebih tua, 5 rekening berbeda — kalau kode
        # kembali menyapu seluruh riwayat (bug yang dilunasi v1.23.0), query
        # ATAU baris yang tersentuh akan ikut naik dengan kedalamannya.
        for d in range(60):
            tgl_lama = D0 - timedelta(days=d + 1)
            for i in range(5):
                self.fr(f"BANK BRI | OLD{i} | DEPOSIT", "Deposit", "1000", "1000",
                        jam="08:00", tanggal=tgl_lama)

        with self.assertNumQueries(5):
            sesudah = bracket_breakdown(self.toko, TGL)

        # baris IN-RANGE tak berubah — hanya akun dorman baru (carry ≠ 0)
        # bertambah, itu memang data baru, bukan kebocoran biaya.
        self.assertEqual(sebelum["count"], sesudah["count"])
        self.assertEqual(len(sesudah["accounts"]), len(sebelum["accounts"]) + 5)

    def test_saldo_carry_biaya_tetap_walau_kedalaman_sejarah_bertambah(self):
        """`_saldo_carry` sendiri: 2 query baik dipotong pada hari ke-3 rantai
        maupun hari ke-83 — pembuktian langsung "biayanya tak tumbuh dengan
        umur data" (docstring `_saldo_carry`). SATU rantai kontinu 83 hari
        dibangun sekali; dipotong di dua titik `dari` berbeda supaya
        perbandingannya adil (data sama, kedalaman riwayat pra-`dari` beda).
        """
        ACC = "BANK BRI | MARGANI | DEPOSIT"
        awal = date(2026, 6, 1)
        bal = 0
        for d in range(83):
            bal += 1000
            self.fr(ACC, "Deposit", "1000", str(bal), jam="08:00",
                    tanggal=awal + timedelta(days=d))

        dari_pendek = awal + timedelta(days=3)  # 3 hari riwayat pra-`dari`
        with self.assertNumQueries(2):
            carry_pendek = _saldo_carry(self.toko, dari_pendek)

        dari_panjang = awal + timedelta(days=83)  # 83 hari riwayat pra-`dari`
        with CaptureQueriesContext(connection) as ctx:
            carry_panjang = _saldo_carry(self.toko, dari_panjang)

        # Kedua potongan tetap 2 query walau titik potong yang KEDUA melihat
        # 83 hari riwayat, bukan 3 — dan nilainya benar-benar mencerminkan
        # kedalaman itu (bukan berhenti di suatu batas lookback tersembunyi).
        self.assertEqual(len(ctx.captured_queries), 2)
        self.assertEqual(carry_pendek[ACC], Decimal("3000"))
        self.assertEqual(carry_panjang[ACC], Decimal("83000"))

        # Jumlah query SAJA tak cukup: sebuah regresi bisa mengganti loose
        # index scan rekursif dengan agregat `Max(posted_date)` GROUP BY atas
        # SELURUH riwayat toko pra-`dari` (bug lama yang dilunasi v1.23.0) dan
        # tetap lolos hitungan-2-query di atas, karena keduanya sama-sama SATU
        # query mentah. Kuncinya harus pada MEKANISMENYA: query pertama WAJIB
        # `WITH RECURSIVE` (loose index scan berbasis index ekspresi
        # `tx_fr_bank_posted_idx`) — bukan `GROUP BY`/`MAX` polos yang menyapu
        # tabel.
        sql_pertama = ctx.captured_queries[0]["sql"]
        self.assertIn("RECURSIVE", sql_pertama.upper(),
                      "loose index scan rekursif hilang — kembali menyapu riwayat?")

    def test_saldo_dorman_terbawa_tanpa_batas_lookback(self):
        """Klaim literal docstring `_saldo_carry`: "Akun dorman bersaldo-lama
        tetap ikut (tak ada batas lookback)". Akun Y HANYA punya satu baris,
        80 hari sebelum `dari`, TIDAK PERNAH bergerak lagi sesudahnya — beda
        dengan tes kedalaman di atas (rantai bergerak TIAP hari, jadi
        `MAX(posted_date)` selalu jatuh di `dari−1` dan sama sekali tak
        menguji seberapa jauh carry boleh menoleh ke belakang).
        """
        Y = "BANK BRI | DORMAN | DEPOSIT"
        awal = date(2026, 6, 1)
        self.fr(Y, "Deposit", "77000", "77000", jam="08:00", tanggal=awal)

        dari = awal + timedelta(days=80)
        with self.assertNumQueries(2):
            carry = _saldo_carry(self.toko, dari)
        self.assertEqual(carry[Y], Decimal("77000"))

    def test_query_konstan_terhadap_jumlah_akun_bukan_n_plus_1(self):
        """21 akun berbeda pada hari yang sama tetap 5 query — GROUP BY di
        SQL untuk sel kategori maupun ujung rantai saldo, bukan satu query
        tambahan per akun (pola N+1)."""
        D0 = date(2026, 6, 30)
        # satu baris carry supaya _saldo_carry mengambil cabang 2-query,
        # sama seperti tes umur-data di atas.
        self.fr("BANK BRI | SEED | DEPOSIT", "Deposit", "1000", "1000",
                jam="08:00", tanggal=D0)
        for i in range(20):
            self.fr(f"BANK BRI | P{i} | DEPOSIT", "Deposit", "1000", "1000",
                    jam="08:00", tanggal=TGL)
        with self.assertNumQueries(5):
            data = bracket_breakdown(self.toko, TGL)
        self.assertEqual(len(data["accounts"]), 21)


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
        # Akun ditutup ke 0 di 2026-07-01 → tak ada saldo carry-forward, jadi
        # tanggal 2026-07-05 memang kosong (bukan akun dorman bersaldo).
        self.fr("QRIS HOKI | DEPOSIT / WITHDRAW", "Deposit", "60000", "60000", jam="09:00")
        self.fr("QRIS HOKI | DEPOSIT / WITHDRAW", "Withdrawal", "-60000", "0", jam="10:00")
        r = self.client.get(reverse("bracket_breakdown"), {"date": "2026-07-05"})
        html = r.content.decode()
        self.assertIn("Belum ada data bracket", html)
        self.assertIn("2026-07-01", html)  # petunjuk tanggal terakhir ber-data

    def test_tanpa_data_sama_sekali(self):
        r = self.client.get(reverse("bracket_breakdown"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("Belum ada data bracket", r.content.decode())
