"""Rincian Rekening — breakdown sisi UANG (bank/gateway) per rekening per hari.

Kembaran Breakdown Bracket untuk mutasi bank nyata: Deposit / Withdraw / Admin
/ Net / Trx / Saldo Awal / Saldo Akhir / Selisih Kontrol per rekening operator.
"""
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

import transactions.models as tx_models
from sources.models import Account, SourceType, Toko, Upload
from transactions.models import Transaction
from web.rekening import rekening_breakdown

TGL = date(2026, 6, 28)


class _MoneyData(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.gw = SourceType.objects.get_or_create(key="gateway", defaults={"name": "Gateway"})[0]
        self._n = 0
        self._uploads = {}

    def _upload(self, st, provider, owner):
        key = (st.id, provider, owner)
        if key not in self._uploads:
            self._uploads[key] = Upload.objects.create(
                source_type=st, toko=self.toko, provider=provider, owner_name=owner,
            )
        return self._uploads[key]

    def mv(self, st, provider, owner, money, saldo, jam=10, jenis="depo", tanggal=TGL,
           menit=0, detik=0, account=None):
        """Satu baris mutasi uang. `money` bertanda, `saldo`=balance_after (str|None)."""
        self._n += 1
        return Transaction.objects.create(
            upload=self._upload(st, provider, owner), source_type=st, toko=self.toko,
            jenis=jenis, amount=abs(Decimal(money)), money_delta=Decimal(money),
            balance_after=None if saldo is None else Decimal(saldo),
            occurred_at=datetime(tanggal.year, tanggal.month, tanggal.day, jam, menit, detik),
            row_hash=f"mv{self._n}", account=account,
        )


class RekeningAggregatTests(_MoneyData):
    def test_deposit_withdraw_net_saldo_selisih(self):
        # BCA a/n HENDI: awal 1.000.000, +DP 500rb → 1.500.000, −WD 200rb → 1.300.000
        self.mv(self.bank, "BCA", "HENDI", "500000", "1500000", jam=9)
        self.mv(self.bank, "BCA", "HENDI", "-200000", "1300000", jam=11, jenis="wd")
        (acc,) = rekening_breakdown(self.toko, TGL)["accounts"]
        self.assertEqual(acc["label"], "BCA a/n HENDI")
        self.assertEqual(acc["deposit"], Decimal("500000"))
        self.assertEqual(acc["withdraw"], Decimal("200000"))
        self.assertEqual(acc["net"], Decimal("300000"))
        self.assertEqual(acc["trx"], 2)
        self.assertEqual(acc["saldo_awal"], Decimal("1000000"))
        self.assertEqual(acc["saldo_akhir"], Decimal("1300000"))
        self.assertEqual(acc["selisih"], Decimal("0"))

    def test_fee_admin_terpisah_dan_ikut_saldo(self):
        # WD 100rb + fee admin 2.500 → saldo 897.500 dari awal 1.000.000
        self.mv(self.bank, "BCA", "NIJUN", "-100000", "900000", jam=9, jenis="wd")
        self.mv(self.bank, "BCA", "NIJUN", "-2500", "897500", jam=10, jenis="admin")
        (acc,) = rekening_breakdown(self.toko, TGL)["accounts"]
        self.assertEqual(acc["withdraw"], Decimal("100000"))
        self.assertEqual(acc["admin"], Decimal("-2500"))
        self.assertEqual(acc["trx"], 1)  # fee tidak dihitung sebagai transaksi
        self.assertEqual(acc["mutasi"], Decimal("-102500"))
        self.assertEqual(acc["selisih"], Decimal("0"))

    def test_selisih_terdeteksi_saat_saldo_janggal(self):
        self.mv(self.bank, "BRI", "PANCA", "-50000", "150000", jam=9, jenis="wd")
        self.mv(self.bank, "BRI", "PANCA", "-50000", "120000", jam=10, jenis="wd")
        # awal 200rb, mutasi −100rb → seharusnya 100rb, tapi FR-nya 120rb → selisih +20rb
        (acc,) = rekening_breakdown(self.toko, TGL)["accounts"]
        self.assertEqual(acc["selisih"], Decimal("20000"))

    def test_gateway_tanpa_saldo_selisih_none(self):
        self.mv(self.gw, "QRFLYER", "", "351726000", None, jam=8)
        (acc,) = rekening_breakdown(self.toko, TGL)["accounts"]
        self.assertEqual(acc["label"], "QR FLYER")
        self.assertEqual(acc["deposit"], Decimal("351726000"))
        self.assertIsNone(acc["saldo_awal"])
        self.assertIsNone(acc["selisih"])

    def test_urut_bank_dulu_lalu_gateway(self):
        self.mv(self.gw, "NXPAY", "", "1000", "1000", jam=8)
        self.mv(self.bank, "BCA", "HENDI", "1000", "1000", jam=9)
        labels = [a["label"] for a in rekening_breakdown(self.toko, TGL)["accounts"]]
        self.assertEqual(labels[0], "BCA a/n HENDI")
        self.assertEqual(labels[-1], "NXPAY")

    def test_total_lintas_rekening(self):
        self.mv(self.bank, "BCA", "HENDI", "500000", "500000", jam=9)
        self.mv(self.bank, "BRI", "PANCA", "-100000", "900000", jam=9, jenis="wd")
        tot = rekening_breakdown(self.toko, TGL)["total"]
        self.assertEqual(tot["deposit"], Decimal("500000"))
        self.assertEqual(tot["withdraw"], Decimal("100000"))
        self.assertEqual(tot["net"], Decimal("400000"))
        self.assertEqual(tot["trx"], 2)

    def test_tanggal_lain_tak_ikut(self):
        self.mv(self.bank, "BCA", "HENDI", "500000", "500000", jam=9)
        self.mv(self.bank, "BCA", "HENDI", "999", "999", jam=9, tanggal=date(2026, 6, 27))
        data = rekening_breakdown(self.toko, TGL)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["accounts"][0]["deposit"], Decimal("500000"))


class RekeningRentangTests(_MoneyData):
    """Rentang [dari, sampai] — mengikuti pola kembaran Breakdown Bracket."""

    def test_rentang_agregasi_lintas_hari_dan_carry(self):
        # BCA a/n HENDI: 27 Jun awal 1jt, +DP 500rb → 1,5jt; 28 Jun −WD 200rb → 1,3jt.
        # Rantai saldo nyambung lintas hari → saldo_awal=1jt (sebelum baris in-range
        # pertama), saldo_akhir=1,3jt, selisih 0, mutasi & trx gabungan 2 hari.
        self.mv(self.bank, "BCA", "HENDI", "500000", "1500000", jam=9,
                tanggal=date(2026, 6, 27))
        self.mv(self.bank, "BCA", "HENDI", "-200000", "1300000", jam=11, jenis="wd",
                tanggal=date(2026, 6, 28))
        data = rekening_breakdown(self.toko, date(2026, 6, 27), date(2026, 6, 28))
        self.assertEqual(data["count"], 2)
        (acc,) = data["accounts"]
        self.assertEqual(acc["deposit"], Decimal("500000"))
        self.assertEqual(acc["withdraw"], Decimal("200000"))
        self.assertEqual(acc["trx"], 2)
        self.assertEqual(acc["saldo_awal"], Decimal("1000000"))
        self.assertEqual(acc["saldo_akhir"], Decimal("1300000"))
        self.assertEqual(acc["selisih"], Decimal("0"))

    def test_sampai_none_setara_satu_hari(self):
        # sampai=None (dan sampai==dari) HARUS identik dengan mode satu-hari lama.
        self.mv(self.bank, "BCA", "HENDI", "500000", "500000", jam=9, tanggal=TGL)
        self.mv(self.bank, "BCA", "HENDI", "999", "999", jam=9, tanggal=date(2026, 6, 27))
        satu = rekening_breakdown(self.toko, TGL)
        rentang1 = rekening_breakdown(self.toko, TGL, TGL)
        self.assertEqual(satu["count"], 1)
        self.assertEqual(rentang1["count"], 1)
        self.assertEqual(satu["accounts"][0]["deposit"], rentang1["accounts"][0]["deposit"])

    def test_dari_sampai_terbalik_ditukar(self):
        self.mv(self.bank, "BCA", "HENDI", "500000", "500000", jam=9, tanggal=TGL)
        data = rekening_breakdown(self.toko, date(2026, 6, 29), date(2026, 6, 27))
        self.assertEqual(data["dari"], date(2026, 6, 27))
        self.assertEqual(data["sampai"], date(2026, 6, 29))
        self.assertEqual(data["count"], 1)

    def test_data_membawa_dari_sampai(self):
        data = rekening_breakdown(self.toko, date(2026, 6, 27), date(2026, 6, 28))
        self.assertEqual(data["dari"], date(2026, 6, 27))
        self.assertEqual(data["sampai"], date(2026, 6, 28))

    def test_batas_tengah_malam_ikut_terhitung(self):
        """Detik pertama & terakhir rentang ikut; tetangganya tidak.

        Penyaringan tanggal memakai rentang datetime setengah-terbuka
        (`>= dari 00:00:00`, `< sampai+1 00:00:00`) demi index — tes ini yang
        menjaga batasnya persis sama dengan `occurred_at__date__range` lama.
        Nominal sengaja dibuat beda-beda supaya baris yang salah ikut ketahuan.
        """
        d26, d27, d28, d29 = (date(2026, 6, x) for x in (26, 27, 28, 29))
        self.mv(self.bank, "BCA", "HENDI", "1", None, jam=23, menit=59, detik=59, tanggal=d26)
        self.mv(self.bank, "BCA", "HENDI", "10", None, jam=0, menit=0, detik=0, tanggal=d27)
        self.mv(self.bank, "BCA", "HENDI", "100", None, jam=23, menit=59, detik=59, tanggal=d28)
        self.mv(self.bank, "BCA", "HENDI", "1000", None, jam=0, menit=0, detik=0, tanggal=d29)

        data = rekening_breakdown(self.toko, d27, d28)
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["accounts"][0]["deposit"], Decimal("110"))

        # mode satu-hari (dari==sampai) memakai batas yang sama
        satu27 = rekening_breakdown(self.toko, d27)
        self.assertEqual(satu27["count"], 1)
        self.assertEqual(satu27["accounts"][0]["deposit"], Decimal("10"))
        satu28 = rekening_breakdown(self.toko, d28)
        self.assertEqual(satu28["count"], 1)
        self.assertEqual(satu28["accounts"][0]["deposit"], Decimal("100"))


class LabelMemoTests(_MoneyData):
    """Memoisasi label rekening: kecepatan boleh berubah, labelnya tidak."""

    def test_label_tetap_beda_untuk_upload_berbeda(self):
        self.mv(self.bank, "BCA", "HENDI", "500000", None, jam=9)
        self.mv(self.bank, "BRI", "PANCA", "700000", None, jam=9)
        labels = {a["label"] for a in rekening_breakdown(self.toko, TGL)["accounts"]}
        self.assertEqual(labels, {"BCA a/n HENDI", "BRI a/n PANCA"})

    def test_label_beda_untuk_rekening_berbeda_di_upload_sama(self):
        """Kunci memo TIDAK boleh cuma upload — `account.provider` menang."""
        acc = Account.objects.create(
            kind="bank", provider="BRI", name="BRI HENDI", toko=self.toko)
        self.mv(self.bank, "BCA", "HENDI", "500000", None, jam=9)
        self.mv(self.bank, "BCA", "HENDI", "300000", None, jam=10, account=acc)
        accounts = rekening_breakdown(self.toko, TGL)["accounts"]
        hasil = {a["label"]: a["deposit"] for a in accounts}
        self.assertEqual(
            hasil, {"BCA a/n HENDI": Decimal("500000"),
                    "BRI a/n HENDI": Decimal("300000")})

    def test_label_tidak_dihitung_ulang_per_baris(self):
        acc = Account.objects.create(
            kind="bank", provider="BRI", name="BRI HENDI", toko=self.toko)
        for i in range(4):                                     # kombinasi 1
            self.mv(self.bank, "BCA", "HENDI", "1000", None, jam=9, menit=i)
        for i in range(3):                                     # kombinasi 2
            self.mv(self.bank, "BRI", "PANCA", "1000", None, jam=10, menit=i)
        for i in range(2):                                     # kombinasi 3
            self.mv(self.bank, "BCA", "HENDI", "1000", None, jam=11, menit=i,
                    account=acc)

        asli = tx_models.specific_source_label
        with patch("transactions.models.specific_source_label", wraps=asli) as m:
            data = rekening_breakdown(self.toko, TGL)

        self.assertEqual(data["count"], 9)
        # 3 kombinasi (source_type, account, upload), bukan 9 baris
        self.assertEqual(m.call_count, 3)


class RekeningAgregatSQLTests(_MoneyData):
    """Perilaku yang WAJIB bertahan setelah agregasi pindah ke SQL (GROUP BY).

    Semua tes di berkas ini menjaga angkanya; kelas ini menjaga sudut-sudut
    yang justru gampang salah saat menyusun filter Q di SQL — baris yang oleh
    loop Python lama jatuh ke cabang "lain-lain" secara implisit.
    """

    def test_baris_delta_nol_hanya_ikut_mutasi_dan_count(self):
        # Baris non-admin berdelta 0: bukan deposit, bukan withdraw, bukan trx —
        # loop lama: `delta > 0` gagal, `delta < 0` gagal → hanya mutasi += 0.
        self.mv(self.bank, "BCA", "HENDI", "500000", "1500000", jam=9)
        self.mv(self.bank, "BCA", "HENDI", "0", "1500000", jam=10, jenis="lainnya")
        data = rekening_breakdown(self.toko, TGL)
        self.assertEqual(data["count"], 2)
        (acc,) = data["accounts"]
        self.assertEqual(acc["deposit"], Decimal("500000"))
        self.assertEqual(acc["withdraw"], Decimal("0"))
        self.assertEqual(acc["trx"], 1)
        self.assertEqual(acc["mutasi"], Decimal("500000"))

    def test_admin_delta_positif_tetap_admin_bukan_deposit(self):
        # `jenis=admin` MENANG atas arah delta (refund biaya = admin positif):
        # loop lama memeriksa admin duluan, jadi tak pernah masuk deposit/trx.
        self.mv(self.bank, "BCA", "HENDI", "-100000", "900000", jam=9, jenis="wd")
        self.mv(self.bank, "BCA", "HENDI", "2500", "902500", jam=10, jenis="admin")
        (acc,) = rekening_breakdown(self.toko, TGL)["accounts"]
        self.assertEqual(acc["admin"], Decimal("2500"))
        self.assertEqual(acc["deposit"], Decimal("0"))
        self.assertEqual(acc["trx"], 1)
        self.assertEqual(acc["mutasi"], Decimal("-97500"))
        self.assertEqual(acc["selisih"], Decimal("0"))

    def test_skala_decimal_nol_tidak_bergeser(self):
        """Grup all-nol menghasilkan Decimal('0') skala-0, persis loop lama.

        Loop lama memakai `t.money_delta or NOL`, jadi grup yang SEMUA barisnya
        berdelta 0 menghasilkan mutasi Decimal('0') → str '0'. `Sum` polos akan
        mengembalikan '0.00' untuk grup itu — nilainya sama (Decimal('0') ==
        Decimal('0.00')) jadi assertEqual angka tak melihatnya; karena itu
        `mutasi`/`admin` di SQL difilter `~Q(money_delta=0)` sehingga grup
        all-nol → NULL → NOL. Kasus kebalikannya (delta saling meniadakan →
        '0.00' skala-2, ditemukan di data nyata k25 Juli 2026) tak bisa dipin
        di sqlite — agregat sqlite pulang lewat float dan kehilangan skala —
        tapi terbukti identik baris-per-baris di Postgres produksi (VPS).
        Untuk tampilan keduanya netral: template memakai floatformat|intcomma.
        """
        self.mv(self.bank, "BCA", "HENDI", "500000", "1500000", jam=9)
        self.mv(self.bank, "BCA", "HENDI", "-500000", "1000000", jam=10, jenis="wd")
        # rekening 2: semua baris berdelta 0 → skala-0 '0'
        self.mv(self.bank, "BRI", "PANCA", "0", "700000", jam=9, jenis="lainnya")
        hasil = {a["label"]: a for a in rekening_breakdown(self.toko, TGL)["accounts"]}
        self.assertEqual(hasil["BCA a/n HENDI"]["mutasi"], Decimal("0"))
        self.assertEqual(str(hasil["BRI a/n PANCA"]["mutasi"]), "0")
        self.assertEqual(str(hasil["BRI a/n PANCA"]["admin"]), "0")

    def test_label_sama_lintas_upload_melebur_dan_rantai_nyambung(self):
        """Dua Upload berbeda, label sama → SATU baris rekening, rantai saldo utuh.

        Kasus normal produksi pada rentang multi-hari: file bank harian rekening
        yang sama = kombinasi (source_type, account, upload) BERBEDA per hari
        tapi `source_label_full`-nya identik. Agregat per kombinasi wajib
        dilebur per label, dan item rantai saldonya ter-interleave menurut
        (occurred_at, id) global — bukan per-kombinasi berurutan — supaya
        `_saldo_batas` melihat rantai yang sama dengan loop per-baris lama.
        """
        up1 = Upload.objects.create(
            source_type=self.bank, toko=self.toko, provider="BCA", owner_name="HENDI")
        up2 = Upload.objects.create(
            source_type=self.bank, toko=self.toko, provider="BCA", owner_name="HENDI")
        d27, d28 = date(2026, 6, 27), date(2026, 6, 28)

        def baris(up, money, saldo, jam, tanggal, jenis="depo"):
            self._n += 1
            Transaction.objects.create(
                upload=up, source_type=self.bank, toko=self.toko, jenis=jenis,
                amount=abs(Decimal(money)), money_delta=Decimal(money),
                balance_after=Decimal(saldo),
                occurred_at=datetime(tanggal.year, tanggal.month, tanggal.day, jam),
                row_hash=f"mv{self._n}",
            )

        # awal 1.000.000 → +500rb (file hari-1) → −200rb (file hari-2) → +100rb
        baris(up1, "500000", "1500000", 9, d27)
        baris(up2, "-200000", "1300000", 10, d28, jenis="wd")
        baris(up2, "100000", "1400000", 11, d28)
        data = rekening_breakdown(self.toko, d27, d28)
        self.assertEqual(data["count"], 3)
        (acc,) = data["accounts"]  # satu baris rekening, bukan dua
        self.assertEqual(acc["label"], "BCA a/n HENDI")
        self.assertEqual(acc["deposit"], Decimal("600000"))
        self.assertEqual(acc["withdraw"], Decimal("200000"))
        self.assertEqual(acc["trx"], 3)
        self.assertEqual(acc["saldo_awal"], Decimal("1000000"))
        self.assertEqual(acc["saldo_akhir"], Decimal("1400000"))
        self.assertEqual(acc["selisih"], Decimal("0"))


class RekeningQueryShapeTests(_MoneyData):
    """Bentuk query WAJIB konstan — invarian inti v1.23.0 (CLAUDE.md, bagian
    "Performa v1.23.0"): dulu rentang sebulan memateralisasi 267 rb baris jadi
    ~800 rb objek ORM (20,7 dtk di `Model.__init__`); sekarang GROUP BY di SQL
    plus `values_list` ringan HANYA untuk baris ber-`balance_after`. Tes di sini
    mengunci BENTUK (jumlah query, nol materialisasi ORM per baris) — bukan
    milidetik, yang rapuh di runner CI berbagi.
    """

    def test_jumlah_query_konstan_walau_ada_riwayat_jauh_lebih_tua(self):
        """5 query TETAP SAMA baik ada maupun tidak ada riwayat lama di luar
        rentang — invarian "biaya bergantung UKURAN RENTANG, bukan UMUR DATA".

        5 = (1) GROUP BY agregat + (2) `values_list` rantai saldo — keduanya
        atas `dasar` yang sama — PLUS `_label_kombinasi`: (3) `SourceType.in_bulk`
        + (4) `Account.in_bulk` + (5) `Upload.filter(...).select_related`.
        Jumlahnya tak bergantung jumlah baris maupun kombinasi
        (source_type, account, upload) — `Account.in_bulk` cuma benar-benar
        mengeksekusi bila SET id-nya tak kosong (in_bulk({}) = 0 query, Django
        pulang lebih awal), jadi fixture di sini sengaja menyertakan satu baris
        ber-`account` supaya kelima query itu nyata semua.
        """
        acc = Account.objects.create(
            kind="bank", provider="BRI", name="BRI HENDI", toko=self.toko)
        self.mv(self.bank, "BCA", "HENDI", "500000", "500000", jam=9)
        self.mv(self.bank, "BRI", "PANCA", "-100000", "900000", jam=10, account=acc)

        with self.assertNumQueries(5):
            data_sebelum = rekening_breakdown(self.toko, TGL)

        # Riwayat JAUH lebih tua, 30 rekening berbeda, di luar rentang — kalau
        # kode kembali menyapu seluruh riwayat (bug yang dilunasi v1.23.0),
        # query dan/atau baris yang tersentuh ikut naik.
        for i in range(30):
            self.mv(self.bank, f"OLDBANK{i}", f"OWNER{i}", "1000", "1000", jam=8,
                    tanggal=date(2020, 1, 1))

        with self.assertNumQueries(5):
            data_sesudah = rekening_breakdown(self.toko, TGL)

        self.assertEqual(data_sebelum["count"], data_sesudah["count"])
        self.assertEqual(len(data_sebelum["accounts"]), len(data_sesudah["accounts"]))

    def test_query_konstan_terhadap_jumlah_rekening_bukan_n_plus_1(self):
        """18 rekening berbeda dalam SATU rentang tetap 5 query — GROUP BY di
        SQL, bukan satu query tambahan per rekening (pola N+1). Satu baris
        sengaja ber-`account` supaya `Account.in_bulk` benar-benar tereksekusi
        (lihat komentar di tes umur-data di atas)."""
        acc = Account.objects.create(
            kind="bank", provider="BRI", name="BRI HENDI", toko=self.toko)
        self.mv(self.bank, "BRI", "HENDI", "1000", "1000", jam=8, account=acc)
        for i in range(17):
            self.mv(self.bank, f"P{i}", f"O{i}", "1000", "1000", jam=8)
        with self.assertNumQueries(5):
            data = rekening_breakdown(self.toko, TGL)
        self.assertEqual(len(data["accounts"]), 18)

    def test_baris_tidak_dimaterialisasi_jadi_objek_orm(self):
        """`Transaction.from_db` HANYA dipanggil saat queryset mengembalikan
        instance model penuh (iterasi langsung) — `.values()`/`.values_list()`
        melewatinya sama sekali. Nol panggilan membuktikan agregasi benar-benar
        di SQL/tuple ringan, bukan `for t in Transaction.objects.filter(...)`
        yang lalu dijumlah satu-satu di Python (bug lama: 267 rb baris → ~800 rb
        `Model.__init__`, 20,7 dtk)."""
        for i in range(30):
            self.mv(self.bank, "BCA", "HENDI", "1000", "1000", jam=8, menit=i)
        with patch.object(Transaction, "from_db", wraps=Transaction.from_db) as m:
            data = rekening_breakdown(self.toko, TGL)
        self.assertEqual(data["count"], 30)
        self.assertEqual(m.call_count, 0)


class RekeningViewTests(_MoneyData):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})

    def test_butuh_login(self):
        self.client.logout()
        r = self.client.get(reverse("rekening_breakdown"))
        self.assertEqual(r.status_code, 302)

    def test_render_data(self):
        self.mv(self.bank, "BCA", "HENDI", "500000", "500000", jam=9)
        r = self.client.get(reverse("rekening_breakdown"), {"date": "2026-06-28"})
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("BCA a/n HENDI", html)
        self.assertIn("Rincian Rekening", html)

    def test_empty_state(self):
        r = self.client.get(reverse("rekening_breakdown"), {"date": "2026-06-28"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Belum ada mutasi", r.content.decode())

    def test_filter_rentang_dari_sampai(self):
        # Dua hari, dua rekening; rentang 27–28 Jun harus memuat keduanya.
        self.mv(self.bank, "BCA", "HENDI", "500000", "500000", jam=9,
                tanggal=date(2026, 6, 27))
        self.mv(self.bank, "BRI", "PANCA", "700000", "700000", jam=9,
                tanggal=date(2026, 6, 28))
        r = self.client.get(reverse("rekening_breakdown"),
                            {"dari": "2026-06-27", "sampai": "2026-06-28"})
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("BCA a/n HENDI", html)
        self.assertIn("BRI a/n PANCA", html)
        # bar filter seragam dgn Rincian Biaya: dua input Dari & Sampai
        self.assertIn('name="dari"', html)
        self.assertIn('name="sampai"', html)

    def test_date_lama_tetap_jalan(self):
        # back-compat: ?date= lama = rentang 1 hari (dari==sampai).
        self.mv(self.bank, "BCA", "HENDI", "500000", "500000", jam=9,
                tanggal=date(2026, 6, 28))
        r = self.client.get(reverse("rekening_breakdown"), {"date": "2026-06-28"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("BCA a/n HENDI", r.content.decode())

    def test_tanggal_ekstrem_tidak_meledak(self):
        """`?sampai=9999-12-31` harus merender halaman, bukan 500.

        Batas atas rentang dihitung `sampai + 1 hari`; pada `date.max`
        penjumlahan itu melempar `OverflowError` di PYTHON, sebelum query
        dibentuk — jadi bukan halaman kosong melainkan seluruh view mati.
        Bisa dicapai lewat UI biasa: `<input type="date">` di
        `web/templates/web/rekening.html` tanpa atribut `max`, dan spinner
        tahun bawaan browser sampai 9999. Pembatasan di template BUKAN
        penjaga — penjaganya harus di `rekening_breakdown`.
        """
        self.mv(self.bank, "BCA", "HENDI", "500000", "500000", jam=9,
                tanggal=date(2026, 6, 28))
        r = self.client.get(reverse("rekening_breakdown"),
                            {"dari": "2026-06-28", "sampai": "9999-12-31"})
        self.assertEqual(r.status_code, 200)
        # rentangnya benar-benar mencakup barisnya, bukan sekadar tak meledak
        self.assertIn("BCA a/n HENDI", r.content.decode())

    def test_tanggal_ekstrem_langsung_ke_fungsi(self):
        """Panggilan langsung `rekening_breakdown(toko, date.max)` juga aman —
        view bukan satu-satunya pemakai (sheet export per-batch juga)."""
        self.mv(self.bank, "BCA", "HENDI", "500000", "500000", jam=9,
                tanggal=date(2026, 6, 28))
        data = rekening_breakdown(self.toko, date(9999, 12, 31))
        self.assertEqual(data["count"], 0)  # 1 hari di tahun 9999: kosong
        data = rekening_breakdown(self.toko, date(2026, 6, 28), date(9999, 12, 31))
        self.assertEqual(data["count"], 1)


class LatestBadgeTests(_MoneyData):
    """D6 — `web/views.py::rekening_breakdown` (VIEW, bukan modul di berkas
    ini): badge "data terbaru s/d tanggal X" kini memakai `Max("occurred_at")`
    lalu `.date()` di PYTHON, bukan `Max("occurred_at__date")` — `__date`
    membungkus kolomnya (`(occurred_at)::date` di Postgres) sehingga bagian
    tanggal index `tx_toko_src_occurred_idx` mati, persis jebakan yang
    dicatat `transactions/models.py` dan yang modul `rekening_breakdown` di
    berkas ini sendiri hindari lewat rentang datetime setengah-terbuka
    (`test_batas_tengah_malam_ikut_terhitung` di atas). `.date()` monoton
    tak-turun jadi hasilnya WAJIB identik dgn cara lama — dibuktikan di sini
    lewat data sungguhan pada batas tengah malam, bukan cuma argumen.
    Lihat docs/riset-toko-pasif-2026-09-04.md (D6) — manfaat KECEPATANNYA
    belum diverifikasi lewat EXPLAIN Postgres produksi; ini memperbaiki
    KONSISTENSI pola, bukan menjanjikan percepatan terukur."""

    def setUp(self):
        super().setUp()
        User = get_user_model()
        User.objects.create_user("audlatest", "b@b.co", "pw12345", role="supervisor")
        self.client.login(username="audlatest", password="pw12345")
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})

    def test_batas_tengah_malam_latest_ikut_maju(self):
        """Baris tepat 23:59:59 vs baris 00:00:00 keesokan harinya — badge
        `latest` (muncul di state KOSONG, `web/rekening.html` baris 29, sbg
        pranala "Lihat tanggal terakhir yang ada datanya →") harus maju begitu
        baris yang lebih baru (walau cuma selisih 1 detik, melewati batas
        hari) benar-benar ada. Rentang yang DIMINTA sengaja dibuat KOSONG
        (01 Jul) supaya badge-nya yang terlihat, bukan tabel isi."""
        kosong = {"dari": "2026-07-01", "sampai": "2026-07-01"}
        self.mv(self.bank, "BCA", "HENDI", "500000", None,
                jam=23, menit=59, detik=59, tanggal=date(2026, 6, 28))
        r = self.client.get(reverse("rekening_breakdown"), kosong)
        self.assertEqual(r.status_code, 200)
        self.assertIn("28 Jun 2026", r.content.decode())

        # satu baris lagi tepat tengah malam keesokan harinya — latest wajib maju.
        self.mv(self.gw, "NXPAY", "-", "10000", None,
                jam=0, menit=0, detik=0, tanggal=date(2026, 6, 29))
        r = self.client.get(reverse("rekening_breakdown"), kosong)
        self.assertEqual(r.status_code, 200)
        self.assertIn("29 Jun 2026", r.content.decode())
        self.assertNotIn("28 Jun 2026", r.content.decode())

    def test_keluaran_lama_vs_baru_identik(self):
        """Bandingkan langsung `Max("occurred_at__date")` (lama) vs
        `Max("occurred_at").date()` (baru, dipakai view sekarang) pada data
        SAMA — USE_TZ=False jadi keduanya wajib setara persis, termasuk pada
        batas tengah malam."""
        from django.db.models import Max

        self.mv(self.bank, "BCA", "HENDI", "500000", None,
                jam=23, menit=59, detik=59, tanggal=date(2026, 6, 28))
        self.mv(self.gw, "NXPAY", "-", "10000", None,
                jam=0, menit=0, detik=0, tanggal=date(2026, 6, 29))
        self.mv(self.bank, "BRI", "PANCA", "700000", None,
                jam=12, tanggal=date(2026, 6, 20))  # baris lama, tak boleh menang

        qs = Transaction.objects.filter(
            toko=self.toko, source_type__key__in=("bank", "gateway")
        )
        lama = qs.aggregate(m=Max("occurred_at__date"))["m"]
        baru_dt = qs.aggregate(m=Max("occurred_at"))["m"]
        baru = baru_dt.date() if baru_dt else None
        self.assertEqual(lama, baru)
        self.assertEqual(baru, date(2026, 6, 29))

    def test_tanpa_baris_latest_none_di_kedua_cara(self):
        """Toko tanpa baris bank/gateway sama sekali — `latest` tetap `None`
        (bukan melempar `AttributeError` saat `.date()` dipanggil di `None`)."""
        from django.db.models import Max

        qs = Transaction.objects.filter(
            toko=self.toko, source_type__key__in=("bank", "gateway")
        )
        lama = qs.aggregate(m=Max("occurred_at__date"))["m"]
        baru_dt = qs.aggregate(m=Max("occurred_at"))["m"]
        baru = baru_dt.date() if baru_dt else None
        self.assertIsNone(lama)
        self.assertIsNone(baru)
