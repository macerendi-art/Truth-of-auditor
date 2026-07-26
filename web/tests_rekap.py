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
from web.rekap import FIELDS, rekap_bulanan

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
                "pulsa", "admin", "admin_qris", "total_cost", "other_income",
                "mistake", "net_profit"],
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
        self.fr("Beban Admin Bank", "-1000")
        self.fr("beban admin bank", "-500")
        self.fr("Beban Admin QRIS", "-300")
        self.fr("Beban Other Expense", "-200")
        self.fr("Pending DP", "750")
        self.fr("Deposit", "999999")          # kategori lain tak boleh bocor
        b = self.baris()
        self.assertEqual(b["admin"]["nilai"], _rp("-1500"))
        self.assertEqual(b["admin_qris"]["nilai"], _rp("-500"))
        self.assertEqual(b["pdp_bulan_ini"]["nilai"], _rp("750"))

    def test_hutang_piutang_tie_out_modul_asal(self):
        self.fr("Hutang", "-30000000")
        self.fr("Piutang", "12000000")
        asal = hutang_piutang(self.toko, date(2026, 6, 1), date(2026, 6, 30))
        b = self.baris()
        self.assertEqual(b["hutang_web"]["nilai"], _rp(asal["total_hutang"]))
        self.assertEqual(b["piutang_web"]["nilai"], _rp(asal["total_piutang"]))
        self.assertEqual(b["hutang_web"]["nilai"], _rp("-30000000"))
        self.assertEqual(b["piutang_web"]["nilai"], _rp("12000000"))

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
        # -net_profit + wl(live via sisa) + bank_dp + qris + hutang
        self.assertEqual(b["total_dana_lebih"]["nilai"], _rp("650"))

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
