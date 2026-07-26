"""Rekap Bulanan: model overlay (RekapManual/RekapPenyebab) + modul murni web.rekap.

Fokus tes: konvensi TANDA (oracle Excel end user), tie-out tiap baris otomatis
terhadap modul sumbernya, provenance override manual, carry antar-bulan depth-1.
"""
from datetime import date, datetime
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.bonus import rekonsiliasi_bonus
from web.hutang import hutang_piutang
from web.models import RekapManual, RekapPenyebab
from web.rekap import FIELDS, _f, _hitung, _q, rekap_bulanan

TAHUN, BULAN = 2026, 6
TGL = date(2026, 6, 15)


def _rp(x):
    return Decimal(x).quantize(Decimal("0.01"))


class _RekapData(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.st_panel = SourceType.objects.get_or_create(
            key="panel", defaults={"name": "Panel"})[0]
        self.st_bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"})[0]
        self.st_pbonus = SourceType.objects.get(key="panel_bonus")
        self.st_bbonus = SourceType.objects.get(key="bracket_bonus")
        self.uploads = {}
        self._n = 0

    def _upload(self, st):
        if st.key not in self.uploads:
            self.uploads[st.key] = Upload.objects.create(
                source_type=st, toko=self.toko, original_name=f"{st.key}.xlsx")
        return self.uploads[st.key]

    def _tx(self, st, **kw):
        self._n += 1
        tanggal = kw.pop("tanggal", TGL)
        return Transaction.objects.create(
            upload=self._upload(st), source_type=st, toko=self.toko,
            posted_date=tanggal,
            occurred_at=datetime(tanggal.year, tanggal.month, tanggal.day, 10, 0),
            row_hash=f"rk{self._n}", **kw)

    # --- sumber data ------------------------------------------------------
    def panel(self, jenis, amount, tanggal=TGL, is_duplicate=False):
        return self._tx(self.st_panel, jenis=jenis, amount=Decimal(amount),
                        credit_delta=Decimal(amount), tanggal=tanggal,
                        is_duplicate=is_duplicate)

    def fr(self, kategori, delta, tanggal=TGL):
        return self._tx(self.st_bracket, jenis="lainnya",
                        amount=abs(Decimal(delta)), money_delta=Decimal(delta),
                        tanggal=tanggal,
                        raw={"Bank": "BANK BCA | SUSI | DEPOSIT",
                             "Kategori": kategori, "Jam": "10:00"})

    def bonus_panel(self, username, amount, kategori="Bonus Harian", tanggal=TGL):
        return self._tx(self.st_pbonus, jenis="bonus", amount=Decimal(amount),
                        username=username, tanggal=tanggal,
                        description=f"{kategori} {username}",
                        raw={"Kategori": kategori})

    def bonus_bracket(self, username, amount, kategori="Bonus Harian", tanggal=TGL):
        return self._tx(self.st_bbonus, jenis="bonus", amount=Decimal(amount),
                        username=username, tanggal=tanggal,
                        description=f"{kategori} {username}",
                        raw={"Kategori": kategori})

    # --- overlay ----------------------------------------------------------
    def manual(self, field, nilai, tahun=TAHUN, bulan=BULAN, **kw):
        return RekapManual.objects.create(
            toko=self.toko, periode=date(tahun, bulan, 1), field=field,
            nilai=Decimal(nilai), **kw)

    def penyebab(self, label, nilai, urutan=0, tahun=TAHUN, bulan=BULAN):
        return RekapPenyebab.objects.create(
            toko=self.toko, periode=date(tahun, bulan, 1), label=label,
            nilai=Decimal(nilai), urutan=urutan)

    # --- pembantu ---------------------------------------------------------
    def baris(self, tahun=TAHUN, bulan=BULAN, **kw):
        data = rekap_bulanan(self.toko, tahun, bulan, **kw)
        return {r["slug"]: r for s in data["sections"] for r in s["rows"]}

    def nilai(self, slug, **kw):
        return self.baris(**kw)[slug]["nilai"]


class StrukturFieldsTests(_RekapData):
    """Kontrak registry — Task 9 merender langsung dari sini."""

    def test_slug_dan_urutan_persis_kontrak(self):
        harapan = {
            1: ["wl", "akuran", "bonus_harian", "lucky_draw", "bonus_mingguan",
                "bonus_lain", "pulsa", "admin", "admin_qris", "other_expense",
                "total_cost", "other_income", "mistake", "net_profit"],
            2: ["wallet_balance_lalu", "dp", "wd", "bonus", "lucky_draw2",
                "wl_ref", "sisa_dana_member"],
            3: ["titip_saldo_awal", "dana_lebih_lalu_ref", "dana_tampung_pusat",
                "net_profit_ref", "akuran_ref", "oasis", "bank_dp", "qris",
                "bank_lain", "bank_wd", "tampung_web", "bank_beku",
                "mistake_belum_cost", "total_wallet_live", "hutang_web",
                "piutang_web", "akuran_lalu", "pdp_bulan_ini", "pdp_klaim",
                "claim_pdp_lalu", "expired_dana_pending", "total_dana_lebih"],
            4: ["dana_lebih_lalu", "selisih", "penyebab_total", "different",
                "dana_lebih_fnc", "selisih_fnc"],
        }
        for seksi, slugs in harapan.items():
            self.assertEqual([f.slug for f in FIELDS if f.seksi == seksi], slugs,
                             f"urutan seksi {seksi} berubah")

    def test_slug_unik_dan_kind_dikenal(self):
        slugs = [f.slug for f in FIELDS]
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertLessEqual({f.kind for f in FIELDS},
                             {"manual", "auto", "carry", "computed"})

    def test_empat_seksi_dengan_judul(self):
        data = rekap_bulanan(self.toko, TAHUN, BULAN)
        self.assertEqual([s["no"] for s in data["sections"]], [1, 2, 3, 4])
        self.assertTrue(all(s["judul"] for s in data["sections"]))
        self.assertEqual(data["periode"], date(TAHUN, BULAN, 1))


class OracleTandaTests(_RekapData):
    """Oracle tanda: angka asli Excel end user harus menghasilkan SISA DANA MEMBER.

    Rangkaian resmi (rupiah penuh):
        WALLET BALANCE bulan lalu   (301.601.680)
        DP                        (5.167.346.330)
        WD                         4.692.080.000
        BONUS                       (245.187.030)
        LUCKY DRAW                    (2.850.000)
        WL                           740.045.170
        --------------------------------------- +
        SISA DANA MEMBER            (284.859.870)

    Catatan: brief menuliskan WL "1.740.045.170"; dengan angka itu jumlahnya
    meleset TEPAT 1.000.000.000 dari SISA DANA MEMBER yang tercetak, jadi digit
    depannya salah salin. Yang di-pin di sini adalah POLA TANDA (DP negatif, WD
    positif, bonus/lucky negatif, WL positif, wallet balance negatif) memakai
    rangkaian yang konsisten secara aritmetika.
    """

    def test_sisa_dana_member_sama_dengan_excel(self):
        self.panel("depo", "5167346330")
        self.panel("wd", "4692080000")
        self.bonus_panel("budi", "200000000", kategori="Bonus Harian")
        self.bonus_panel("sinta", "45187030", kategori="Bonus Mingguan")
        self.bonus_panel("dedi", "2850000", kategori="Lucky Draw")
        self.manual("wl", "740045170")
        self.manual("wallet_balance_lalu", "-301601680")

        b = self.baris()
        self.assertEqual(b["wallet_balance_lalu"]["nilai"], _rp("-301601680"))
        self.assertEqual(b["dp"]["nilai"], _rp("-5167346330"))
        self.assertEqual(b["wd"]["nilai"], _rp("4692080000"))
        self.assertEqual(b["bonus"]["nilai"], _rp("-245187030"))
        self.assertEqual(b["lucky_draw2"]["nilai"], _rp("-2850000"))
        self.assertEqual(b["wl_ref"]["nilai"], _rp("740045170"))
        self.assertEqual(b["sisa_dana_member"]["nilai"], _rp("-284859870"))

    def test_seksi_2_adalah_jumlah_lurus_barisnya(self):
        self.panel("depo", "1000")
        self.panel("wd", "400")
        self.bonus_panel("budi", "50")
        self.manual("wl", "300")
        b = self.baris()
        anggota = ["wallet_balance_lalu", "dp", "wd", "bonus", "lucky_draw2",
                   "wl_ref"]
        self.assertEqual(b["sisa_dana_member"]["nilai"],
                         sum(b[s]["nilai"] for s in anggota))

    def test_net_profit_jumlah_lurus_dan_biaya_negatif(self):
        self.bonus_panel("budi", "50", kategori="Bonus Harian")
        self.fr("Beban Admin Bank", "-25")
        self.manual("wl", "1000")
        self.manual("total_cost", "-100")
        b = self.baris()
        self.assertEqual(b["bonus_harian"]["nilai"], _rp("-50"))
        self.assertEqual(b["admin"]["nilai"], _rp("-25"))
        self.assertEqual(b["net_profit"]["nilai"], _rp("825"))


class TieOutOtomatisTests(_RekapData):
    def test_bonus_klasifikasi_kategori_beragam_kapital(self):
        self.bonus_panel("a", "10", kategori="BONUS HARIAN SLOT")   # cocok
        self.bonus_bracket("a", "10", kategori="BONUS HARIAN SLOT")
        self.bonus_panel("b", "5", kategori="bonus harian")          # panel_only
        self.bonus_panel("c", "7", kategori="Bonus Mingguan Sportbook")
        self.bonus_panel("d", "3", kategori="LUCKY DRAW")
        self.bonus_bracket("z", "99", kategori="Bonus Harian")       # bracket_only

        kat = rekonsiliasi_bonus(self.toko, date(2026, 6, 1), date(2026, 6, 30))
        kat = kat["ringkas"]["kategori"]
        harian = sum(kat[k]["cocok_total"] + kat[k]["panel_only_total"]
                     for k in kat if "harian" in k.lower())
        b = self.baris()
        self.assertEqual(harian, Decimal("15"))
        self.assertEqual(b["bonus_harian"]["nilai"], _rp("-15"))  # sisi panel saja
        self.assertEqual(b["bonus_mingguan"]["nilai"], _rp("-7"))
        self.assertEqual(b["lucky_draw"]["nilai"], _rp("-3"))
        self.assertEqual(b["bonus"]["nilai"], _rp("-22"))          # harian+mingguan

    def test_bonus_di_luar_bulan_tidak_ikut(self):
        self.bonus_panel("a", "10", tanggal=date(2026, 5, 31))
        self.bonus_panel("b", "4", tanggal=date(2026, 6, 1))
        self.bonus_panel("c", "6", tanggal=date(2026, 7, 1))
        self.assertEqual(self.nilai("bonus_harian"), _rp("-4"))

    def test_kategori_fr_admin_qris_dan_pdp(self):
        """`beban other expense` punya barisnya sendiri — tak menempel ADMIN QRIS."""
        self.fr("Beban Admin Bank", "-1000")
        self.fr("beban admin bank", "-500")
        self.fr("Beban Admin QRIS", "-300")
        self.fr("Beban Other Expense", "-200")
        self.fr("Pending DP", "750")
        self.fr("Deposit", "999999")          # kategori lain tak boleh bocor
        b = self.baris()
        self.assertEqual(b["admin"]["nilai"], _rp("-1500"))
        self.assertEqual(b["admin_qris"]["nilai"], _rp("-300"))
        self.assertEqual(b["other_expense"]["nilai"], _rp("-200"))
        self.assertEqual(b["pdp_bulan_ini"]["nilai"], _rp("750"))

    def test_other_expense_tak_menggelembungkan_admin_qris(self):
        """Angka nyata: "Cost Tagihan 28 Juni" (386 jt) 30x lipat beban QRIS."""
        self.fr("Beban Admin QRIS", "-7600000")
        self.fr("Beban Other Expense", "-386837314")
        b = self.baris()
        self.assertEqual(b["admin_qris"]["nilai"], _rp("-7600000"))
        self.assertEqual(b["other_expense"]["nilai"], _rp("-386837314"))
        # keduanya tetap anggota NET PROFIT — pemisahan bukan penghilangan
        self.assertEqual(b["net_profit"]["nilai"], _rp("-394437314"))

    def test_hutang_piutang_tie_out_modul_asal(self):
        self.fr("Hutang", "-30000000")
        self.fr("Piutang", "12000000")
        asal = hutang_piutang(self.toko, date(2026, 6, 1), date(2026, 6, 30))
        b = self.baris()
        # Tanda DIBALIK terhadap modul asal (lihat OracleHutangPiutangTests).
        self.assertEqual(b["hutang_web"]["nilai"], -_rp(asal["total_hutang"]))
        self.assertEqual(b["piutang_web"]["nilai"], -_rp(asal["total_piutang"]))
        self.assertEqual(b["hutang_web"]["nilai"], _rp("30000000"))
        self.assertEqual(b["piutang_web"]["nilai"], _rp("-12000000"))

    def test_dp_wd_panel_hormati_duplikat_jenis_dan_rentang(self):
        self.panel("depo", "1000")
        self.panel("depo", "250", is_duplicate=True)          # duplikat: keluar
        self.panel("depo", "999", tanggal=date(2026, 5, 30))  # bulan lain: keluar
        self.panel("wd", "400")
        self.panel("bonus", "77")                             # jenis lain: keluar
        b = self.baris()
        self.assertEqual(b["dp"]["nilai"], _rp("-1000"))
        self.assertEqual(b["wd"]["nilai"], _rp("400"))

    def test_toko_lain_tidak_bocor(self):
        lain = Toko.objects.exclude(pk=self.toko.pk).first()
        up = Upload.objects.create(source_type=self.st_panel, toko=lain)
        Transaction.objects.create(
            upload=up, source_type=self.st_panel, toko=lain, jenis="depo",
            amount=Decimal("500"), posted_date=TGL, row_hash="lain1")
        self.assertEqual(self.nilai("dp"), _rp("0"))


class KlasifikasiBonusTests(_RekapData):
    """Nama kategori NYATA produksi — tak satu rupiah pun boleh menguap.

    Kata kunci lucky/mingguan/harian saja tidak cukup: mayoritas nama nyata
    ("BONUS BOLA 10%", "Redemption Coupon", "CRM", "NEW MEMBER") tak memuat
    satu pun kata itu, jadi harus ada penampung `bonus_lain`.
    """

    NYATA = [
        "BONUS ROLLINGAN SLOT 0.5% DAILY", "BONUS BOLA 10%",
        "Redemption Coupon", "Lucky Draw", "BONUS LOYALTY MURAH (BL1)",
        "CRM", "NEW MEMBER", "ROLLINGAN", "EVENT", "BONUS MINGGUAN SPORTBOOK",
    ]

    def test_nama_produksi_jatuh_ke_baris_yang_benar(self):
        self.bonus_panel("a", "10", kategori="BONUS ROLLINGAN SLOT 0.5% DAILY")
        self.bonus_panel("b", "20", kategori="BONUS BOLA 10%")
        self.bonus_panel("c", "30", kategori="Redemption Coupon")
        self.bonus_panel("d", "40", kategori="Lucky Draw")
        self.bonus_panel("e", "50", kategori="BONUS MINGGUAN SPORTBOOK")
        b = self.baris()
        self.assertEqual(b["bonus_harian"]["nilai"], _rp("-10"))    # DAILY
        self.assertEqual(b["bonus_mingguan"]["nilai"], _rp("-50"))
        self.assertEqual(b["lucky_draw"]["nilai"], _rp("-40"))
        self.assertEqual(b["bonus_lain"]["nilai"], _rp("-50"))      # 20 + 30

    def test_prioritas_lucky_menang_atas_kata_lain(self):
        self.bonus_panel("a", "10", kategori="Lucky Draw Mingguan")
        b = self.baris()
        self.assertEqual(b["lucky_draw"]["nilai"], _rp("-10"))
        self.assertEqual(b["bonus_mingguan"]["nilai"], _rp("0"))
        self.assertEqual(b["bonus_lain"]["nilai"], _rp("0"))

    def test_konservasi_tak_ada_bonus_yang_hilang(self):
        for i, nama in enumerate(self.NYATA):
            self.bonus_panel(f"u{i}", str((i + 1) * 1000), kategori=nama)
        kat = rekonsiliasi_bonus(
            self.toko, date(2026, 6, 1), date(2026, 6, 30))["ringkas"]["kategori"]
        total = sum((d["cocok_total"] + d["panel_only_total"]
                     for d in kat.values()), Decimal("0"))
        b = self.baris()
        empat = sum(b[s]["nilai"] for s in
                    ("bonus_harian", "bonus_mingguan", "lucky_draw", "bonus_lain"))
        self.assertNotEqual(total, Decimal("0"))
        self.assertEqual(empat, _rp(-total))

    def test_bonus_seksi_2_memuat_bonus_lain(self):
        self.bonus_panel("a", "10", kategori="Bonus Harian")
        self.bonus_panel("b", "20", kategori="Bonus Mingguan")
        self.bonus_panel("c", "30", kategori="Redemption Coupon")
        self.bonus_panel("d", "40", kategori="Lucky Draw")
        b = self.baris()
        # BONUS seksi 2 = semua bonus NON-lucky (lucky punya barisnya sendiri)
        self.assertEqual(b["bonus"]["nilai"], _rp("-60"))
        self.assertEqual(b["lucky_draw2"]["nilai"], _rp("-40"))

    def test_bonus_lain_mengekspos_nama_kategorinya(self):
        self.bonus_panel("a", "10", kategori="BONUS BOLA 10%")
        self.bonus_panel("b", "20", kategori="Redemption Coupon")
        self.bonus_panel("c", "30", kategori="Bonus Harian")
        b = self.baris()
        self.assertEqual(b["bonus_lain"]["detail"],
                         ["BONUS BOLA 10%", "Redemption Coupon"])
        self.assertEqual(b["bonus_harian"]["detail"], [])


class OracleHutangPiutangTests(_RekapData):
    """Tanda hutang/piutang DIBALIK terhadap FR — dipin ke angka nyata.

    Baris FR asli: Kategori "Hutang", money_delta +30.000.000
    ("( HUTANG ) G25 PINJAM DANA K25 30,000,000"), sedangkan Excel end user
    membukukan HUTANG WEB (30.000.000) NEGATIF dan PIUTANG WEB +130.003.000.
    """

    def test_tanda_hutang_piutang_dibalik(self):
        self.fr("Hutang", "30000000")
        self.fr("Piutang", "-130003000")
        b = self.baris()
        self.assertEqual(b["hutang_web"]["nilai"], _rp("-30000000"))
        self.assertEqual(b["piutang_web"]["nilai"], _rp("130003000"))

    def test_pembalikan_ikut_ke_total_dana_lebih(self):
        self.fr("Hutang", "30000000")
        self.fr("Piutang", "-130003000")
        b = self.baris()
        self.assertEqual(b["total_dana_lebih"]["nilai"], _rp("100003000"))


class ManualOverrideTests(_RekapData):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username="auditor1", password="x")

    def test_manual_menang_atas_auto_dengan_provenance(self):
        self.panel("depo", "1000")
        self.manual("dp", "-900", catatan="koreksi cutoff", dibuat_oleh=self.user)
        r = self.baris()["dp"]
        self.assertEqual(r["nilai"], _rp("-900"))
        self.assertEqual(r["sumber"], "manual")
        self.assertEqual(r["auto"], _rp("-1000"))     # nilai asli tetap terlihat
        self.assertEqual(r["manual"]["catatan"], "koreksi cutoff")
        self.assertEqual(r["manual"]["oleh"], "auditor1")
        self.assertIsNotNone(r["manual"]["waktu"])

    def test_tanpa_override_sumber_ikut_kind(self):
        self.panel("depo", "1000")
        b = self.baris()
        self.assertEqual(b["dp"]["sumber"], "auto")
        self.assertIsNone(b["dp"]["manual"])
        self.assertEqual(b["wl"]["sumber"], "manual")   # baris FORM kosong
        self.assertEqual(b["wl"]["nilai"], _rp("0"))
        self.assertEqual(b["net_profit"]["sumber"], "computed")

    def test_computed_tidak_bisa_ditimpa(self):
        self.manual("wl", "100")
        self.manual("net_profit", "999999")     # harus DIABAIKAN
        b = self.baris()
        self.assertEqual(b["net_profit"]["nilai"], _rp("100"))
        self.assertEqual(b["net_profit"]["sumber"], "computed")
        self.assertIsNone(b["net_profit"]["manual"])

    def test_override_ikut_ke_seksi_lain_lewat_ref(self):
        self.panel("depo", "1000")
        self.manual("dp", "-900")
        b = self.baris()
        self.assertEqual(b["sisa_dana_member"]["nilai"], _rp("-900"))
        self.assertEqual(b["total_wallet_live"]["nilai"], _rp("-900"))

    def test_unik_per_toko_periode_field(self):
        self.manual("wl", "100")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.manual("wl", "200")

    def test_field_berbeda_boleh_periode_sama(self):
        self.manual("wl", "100")
        self.manual("akuran", "5")
        self.assertEqual(RekapManual.objects.count(), 2)


class RefDanRumusTests(_RekapData):
    def test_net_profit_ref_dibalik_tandanya(self):
        self.manual("wl", "1000")
        self.manual("akuran", "40")
        b = self.baris()
        self.assertEqual(b["net_profit"]["nilai"], _rp("1040"))
        self.assertEqual(b["net_profit_ref"]["nilai"], _rp("-1040"))
        self.assertEqual(b["akuran_ref"]["nilai"], _rp("40"))

    def test_total_dana_lebih_jumlah_lurus_barisnya(self):
        self.manual("wl", "1000")
        self.manual("bank_dp", "500")
        self.manual("qris", "250")
        self.fr("Hutang", "-100")
        b = self.baris()
        anggota = [f.slug for f in FIELDS
                   if f.seksi == 3 and f.slug != "total_dana_lebih"]
        self.assertEqual(b["total_dana_lebih"]["nilai"],
                         sum(b[s]["nilai"] for s in anggota))
        # -net_profit + wl(live via sisa) + bank_dp + qris + hutang(tanda dibalik)
        self.assertEqual(b["total_dana_lebih"]["nilai"], _rp("850"))

    def test_selisih_penyebab_different_dan_fnc(self):
        self.manual("bank_dp", "1000")
        self.manual("dana_lebih_lalu", "400")   # ikut lewat dana_lebih_lalu_ref
        self.manual("dana_lebih_fnc", "1500")
        self.penyebab("Auto Pulsa", "250", urutan=1)
        self.penyebab("Mistake credit", "150", urutan=0)
        b = self.baris()
        self.assertEqual(b["dana_lebih_lalu_ref"]["nilai"], _rp("400"))
        self.assertEqual(b["total_dana_lebih"]["nilai"], _rp("1400"))
        self.assertEqual(b["selisih"]["nilai"], _rp("1000"))
        self.assertEqual(b["penyebab_total"]["nilai"], _rp("400"))
        self.assertEqual(b["different"]["nilai"], _rp("600"))
        self.assertEqual(b["selisih_fnc"]["nilai"], _rp("100"))

    def test_penyebab_urut_dan_terekspos(self):
        self.penyebab("Kedua", "10", urutan=2)
        self.penyebab("Pertama", "20", urutan=1)
        data = rekap_bulanan(self.toko, TAHUN, BULAN)
        self.assertEqual([p["label"] for p in data["penyebab"]],
                         ["Pertama", "Kedua"])
        self.assertEqual(data["penyebab"][0]["nilai"], _rp("20"))
        self.assertTrue(all("id" in p for p in data["penyebab"]))

    def test_penyebab_bulan_lain_tidak_ikut(self):
        self.penyebab("Bulan lalu", "999", bulan=5)
        data = rekap_bulanan(self.toko, TAHUN, BULAN)
        self.assertEqual(data["penyebab"], [])
        self.assertEqual(data["totals"]["different"], _rp("0"))

    def test_totals_konsisten_dengan_baris(self):
        self.manual("wl", "1000")
        self.manual("bank_dp", "500")
        data = rekap_bulanan(self.toko, TAHUN, BULAN)
        b = {r["slug"]: r for s in data["sections"] for r in s["rows"]}
        for k in ("net_profit", "sisa_dana_member", "total_dana_lebih",
                  "selisih", "different", "selisih_fnc"):
            self.assertEqual(data["totals"][k], b[k]["nilai"], k)


class OracleFncTests(_RekapData):
    """SELISIH FNC dipin ke angka Excel end user (kurung = negatif).

        DANA LEBIH FNC      (885.426.217)
        TOTAL DANA LEBIH    (888.276.217)
        ------------------------------- −
        SELISIH FNC            2.850.000
    """

    def test_selisih_fnc_sama_dengan_excel(self):
        self.manual("titip_saldo_awal", "-888276217")
        self.manual("dana_lebih_fnc", "-885426217")
        b = self.baris()
        self.assertEqual(b["total_dana_lebih"]["nilai"], _rp("-888276217"))
        self.assertEqual(b["dana_lebih_fnc"]["nilai"], _rp("-885426217"))
        self.assertEqual(b["selisih_fnc"]["nilai"], _rp("2850000"))


class CarryTests(_RekapData):
    """Carry antar-bulan depth-1: bulan N membaca hasil hitung N-1, dan N-1
    hanya membaca carry-nya sendiri dari RekapManual (tanpa rekursi lebih dalam).
    """

    def test_carry_depth_1_tiga_bulan(self):
        self.manual("bank_dp", "999", bulan=4)          # April
        self.manual("bank_dp", "500", bulan=5)          # Mei
        self.manual("wl", "100", bulan=5)
        self.manual("akuran", "7", bulan=5)

        mei = self.baris(bulan=5)
        self.assertEqual(mei["dana_lebih_lalu"]["nilai"], _rp("999"))
        self.assertEqual(mei["dana_lebih_lalu_ref"]["nilai"], _rp("999"))
        self.assertEqual(mei["sisa_dana_member"]["nilai"], _rp("100"))
        self.assertEqual(mei["total_dana_lebih"]["nilai"], _rp("1499"))

        juni = self.baris(bulan=6)
        # Mei dihitung ulang dengan _carry=False → 999 April TIDAK ikut lagi.
        self.assertEqual(juni["dana_lebih_lalu"]["nilai"], _rp("500"))
        self.assertEqual(juni["wallet_balance_lalu"]["nilai"], _rp("100"))
        self.assertEqual(juni["akuran_lalu"]["nilai"], _rp("7"))
        self.assertEqual(juni["dana_lebih_lalu"]["sumber"], "carry")

    def test_carry_false_hanya_manual(self):
        self.manual("bank_dp", "999", bulan=5)
        b = self.baris(bulan=6, _carry=False)
        self.assertEqual(b["dana_lebih_lalu"]["nilai"], _rp("0"))
        self.assertEqual(b["wallet_balance_lalu"]["nilai"], _rp("0"))
        self.manual("wallet_balance_lalu", "-25", bulan=6)
        b = self.baris(bulan=6, _carry=False)
        self.assertEqual(b["wallet_balance_lalu"]["nilai"], _rp("-25"))
        self.assertEqual(b["wallet_balance_lalu"]["sumber"], "manual")

    def test_carry_bisa_ditimpa_manual_dengan_auto_tersimpan(self):
        self.manual("wl", "100", bulan=5)
        self.manual("wallet_balance_lalu", "-50", bulan=6)
        r = self.baris(bulan=6)["wallet_balance_lalu"]
        self.assertEqual(r["nilai"], _rp("-50"))
        self.assertEqual(r["sumber"], "manual")
        self.assertEqual(r["auto"], _rp("100"))

    def test_carry_lintas_tahun_januari_baca_desember(self):
        self.manual("bank_dp", "321", tahun=2025, bulan=12)
        b = self.baris(tahun=2026, bulan=1)
        self.assertEqual(b["dana_lebih_lalu"]["nilai"], _rp("321"))


class CarryTerkunciTests(_RekapData):
    """Carry hanya sedalam 1 bulan → nilainya WAJIB dikunci (disimpan) tiap bulan."""

    CARRY = ["wallet_balance_lalu", "akuran_lalu", "dana_lebih_lalu"]

    def _mei_berisi(self):
        self.manual("bank_dp", "999", bulan=5)
        self.manual("wl", "100", bulan=5)

    def test_carry_belum_dikunci_ditandai_dan_diperingatkan(self):
        self._mei_berisi()
        data = rekap_bulanan(self.toko, TAHUN, BULAN)
        b = {r["slug"]: r for s in data["sections"] for r in s["rows"]}
        for slug in self.CARRY:
            self.assertIs(b[slug]["tersimpan"], False, slug)
        self.assertIn("kunci", data["petunjuk"].lower())

    def test_carry_dikunci_menghapus_peringatan(self):
        self._mei_berisi()
        for slug, nilai in (("wallet_balance_lalu", "100"),
                            ("akuran_lalu", "0"),
                            ("dana_lebih_lalu", "999")):
            self.manual(slug, nilai)
        data = rekap_bulanan(self.toko, TAHUN, BULAN)
        b = {r["slug"]: r for s in data["sections"] for r in s["rows"]}
        for slug in self.CARRY:
            self.assertIs(b[slug]["tersimpan"], True, slug)
        self.assertEqual(data["petunjuk"], "")

    def test_bulan_lalu_kosong_tak_perlu_peringatan(self):
        data = rekap_bulanan(self.toko, TAHUN, BULAN)
        self.assertEqual(data["petunjuk"], "")

    def test_baris_non_carry_tak_ikut_ditandai(self):
        b = self.baris()
        self.assertIsNone(b["wl"]["tersimpan"])
        self.assertIsNone(b["net_profit"]["tersimpan"])


class NormalisasiNilaiTests(_RekapData):
    def test_nol_tak_pernah_bertanda_minus(self):
        self.assertEqual(str(_q(Decimal("-0.001"))), "0.00")
        self.assertEqual(str(_q(Decimal("0") * -1)), "0.00")
        data = rekap_bulanan(self.toko, TAHUN, BULAN)
        for s in data["sections"]:
            for r in s["rows"]:
                self.assertNotIn("-0", str(r["nilai"]), r["slug"])

    def test_hitung_slug_asing_meledak_dengan_pesan_jelas(self):
        with self.assertRaises(KeyError) as cm:
            _hitung(_f("x", "X", 1, "computed", sumber="tidak_ada"), {})
        self.assertIn("tidak dikenal", str(cm.exception))
        with self.assertRaises(KeyError):
            _hitung(_f("y", "Y", 1, "computed", rumus=(("hantu", 1),)), {})


class BulanKosongTests(_RekapData):
    def test_bulan_tanpa_data_semua_nol(self):
        data = rekap_bulanan(self.toko, 2026, 2)   # sekaligus bulan 28 hari
        nilai = [r["nilai"] for s in data["sections"] for r in s["rows"]]
        self.assertTrue(all(v == _rp("0") for v in nilai))
        self.assertEqual(data["penyebab"], [])
        self.assertTrue(all(v == _rp("0") for v in data["totals"].values()))

    def test_rentang_bulan_menutup_hari_terakhir(self):
        self.panel("depo", "10", tanggal=date(2026, 2, 28))
        self.assertEqual(self.nilai("dp", tahun=2026, bulan=2), _rp("-10"))
        self.panel("depo", "20", tanggal=date(2026, 1, 31))
        self.assertEqual(self.nilai("dp", tahun=2026, bulan=1), _rp("-20"))


class MigrasiTests(TestCase):
    def test_tidak_ada_drift_migrasi(self):
        out = StringIO()
        try:
            call_command("makemigrations", "web", "--check", "--dry-run",
                         stdout=out, stderr=out)
        except SystemExit:
            self.fail(f"model berubah tanpa migrasi:\n{out.getvalue()}")
