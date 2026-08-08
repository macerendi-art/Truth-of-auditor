"""Detail FR/Bracket — rincian baris di balik tiap sel Control Bracket.

Nilai halaman ini SELURUHNYA bergantung pada satu sifat: rinciannya harus
menjumlah balik PERSIS ke angka sel di /bracket/. Kalau meleset, halaman ini
lebih buruk daripada tidak ada — orang akan memercayai angka yang salah.
Karena itu tes pertama di sini bukan tes tampilan, melainkan tes tie-out atas
SETIAP sel (akun × kategori) sekaligus totalnya.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.breakdown import bracket_breakdown
from web.detail_fr import detail_fr


class _Basis(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "aud", "a@a.co", "pw12345", role="supervisor"
        )
        self.toko = Toko.objects.get(key="lbs")
        self.st = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"}
        )[0]
        self.up = Upload.objects.create(
            source_type=self.st, toko=self.toko, original_name="FR.xlsx",
            status=Upload.PARSED,
        )
        self._n = 0

    def fr(self, bank, kategori, total, tgl=date(2026, 8, 3), jam="10:00",
           member="", desc="", saldo=None):
        """Satu baris FR. `total` bertanda, persis seperti kolom Total di file."""
        self._n += 1
        return Transaction.objects.create(
            upload=self.up, source_type=self.st, toko=self.toko,
            occurred_at=None, posted_date=tgl, jenis="lainnya",
            amount=abs(Decimal(total)), credit_delta=Decimal("0"),
            money_delta=Decimal(total), fee=Decimal("0"), bonus=Decimal("0"),
            balance_after=(Decimal(saldo) if saldo is not None else None),
            counterparty=member, description=desc,
            raw={"Bank": bank, "Kategori": kategori, "Jam": jam},
            row_hash=f"det-{self._n}",
        )


class TieOutTest(_Basis):
    """Setiap sel breakdown = jumlah baris detail dengan penyaring yang sama."""

    def _isi_beragam(self):
        """Sengaja memuat ejaan varian dan spasi ganda: normalisasi kunci hanya
        terjadi di Python (`_norm_akun`, `_slug_kategori`), jadi penyaring yang
        naif di SQL akan diam-diam kehilangan baris."""
        A = "BANK BCA | IGNATIUS IVAN | WITHDRAW"
        B = "  BANK BCA | IGNATIUS IVAN | WITHDRAW  "    # spasi TEPI → akun SAMA
        C = "QRIS UNOPAY | - | DEPOSIT / WITHDRAW"
        self.fr(A, "Adjustment", "-200000", jam="09:00")
        self.fr(B, "adjustment", "-150000", jam="09:30")  # huruf kecil → slug sama
        self.fr(A, "ADJUSTMENT", "-100000", jam="11:00")
        self.fr(A, "Withdraw", "-108987401", jam="12:00")     # varian ejaan…
        self.fr(A, "Withdrawal", "-500000", jam="12:30")      # …→ slug sama
        self.fr(C, "Deposit", "680160355", jam="08:00")
        self.fr(C, "Beban Admin QRIS", "-9226288", jam="23:00")

    def test_tiap_sel_breakdown_sama_dengan_jumlah_detailnya(self):
        self._isi_beragam()
        bd = bracket_breakdown(self.toko, date(2026, 8, 3), dengan_koreksi=False)

        diperiksa = 0
        for acc in bd["accounts"]:
            for slug, nilai_sel in acc["kategori"].items():
                d = detail_fr(self.toko, date(2026, 8, 3), akun=acc["account"],
                              kategori=slug)
                self.assertEqual(
                    d["total"], nilai_sel,
                    f"sel {acc['account']} / {slug}: detail {d['total']} != sel {nilai_sel}",
                )
                self.assertEqual(d["jumlah"], len(d["baris"]))
                diperiksa += 1
        self.assertGreaterEqual(diperiksa, 4, "fixture harus menguji beberapa sel")

    def test_total_seluruh_baris_sama_dengan_total_mutasi_breakdown(self):
        self._isi_beragam()
        bd = bracket_breakdown(self.toko, date(2026, 8, 3), dengan_koreksi=False)

        d = detail_fr(self.toko, date(2026, 8, 3))

        self.assertEqual(d["total"], bd["total"]["mutasi"])
        self.assertEqual(d["jumlah"], bd["count"])

    def test_ejaan_varian_kategori_tidak_hilang(self):
        """'Withdraw' dan 'Withdrawal' satu sel — detailnya harus memuat keduanya."""
        self._isi_beragam()
        d = detail_fr(self.toko, date(2026, 8, 3),
                      akun="BANK BCA | IGNATIUS IVAN | WITHDRAW", kategori="withdrawal")

        self.assertEqual(d["jumlah"], 2)
        self.assertEqual(d["total"], Decimal("-109487401"))

    def test_spasi_tepi_pada_nama_akun_tidak_memecah_baris(self):
        self._isi_beragam()
        d = detail_fr(self.toko, date(2026, 8, 3),
                      akun="BANK BCA | IGNATIUS IVAN | WITHDRAW", kategori="adjustment")

        self.assertEqual(d["jumlah"], 3)
        self.assertEqual(d["total"], Decimal("-450000"))   # kasus end user

    def test_spasi_GANDA_di_tengah_tetap_akun_berbeda_seperti_breakdown(self):
        """`_norm_akun` hanya memangkas spasi TEPI. Spasi ganda di tengah nama
        memang menghasilkan akun terpisah — dan breakdown berperilaku sama.
        Tes ini mengunci kesetaraan itu: siapa pun yang kelak "merapikan"
        `_norm_akun` harus memperbaikinya di SATU tempat, bukan sebelah saja."""
        self.fr("BANK BCA | X | DEPOSIT", "Deposit", "100")
        self.fr("BANK  BCA | X | DEPOSIT", "Deposit", "200")   # dua spasi

        bd = bracket_breakdown(self.toko, date(2026, 8, 3), dengan_koreksi=False)
        akun_breakdown = {a["account"] for a in bd["accounts"]}
        akun_detail = {a["account"] for a in detail_fr(self.toko, date(2026, 8, 3))["akun_pilihan"]}

        self.assertEqual(akun_detail, akun_breakdown)
        self.assertEqual(len(akun_breakdown), 2, "dua ejaan = dua akun, di KEDUA modul")


class CakupanBarisTest(_Basis):
    """Populasi barisnya harus SAMA PERSIS dengan breakdown — termasuk yang
    biasanya disaring di tempat lain di aplikasi ini."""

    def test_baris_admin_ikut_dihitung(self):
        """`jenis='admin'` dibuang dari total WD & pencocokan, TAPI breakdown FR
        memasukkannya. Detail harus mengikuti breakdown, bukan kebiasaan engine."""
        t = self.fr("BANK BCA | A | DEPOSIT", "Beban Admin Bank", "-15000")
        Transaction.objects.filter(pk=t.pk).update(jenis="admin")

        self.assertEqual(detail_fr(self.toko, date(2026, 8, 3))["jumlah"], 1)

    def test_baris_yang_sudah_dikonsumsi_batch_ikut_dihitung(self):
        from reconciliation.models import ReconBatch, ToleranceProfile

        b = ReconBatch.objects.create(
            toko=self.toko, recon_date=date(2026, 8, 3),
            tolerance=ToleranceProfile.objects.get(name="Default"),
        )
        t = self.fr("BANK BCA | A | DEPOSIT", "Deposit", "50000")
        Transaction.objects.filter(pk=t.pk).update(consumed_by_batch=b)

        self.assertEqual(detail_fr(self.toko, date(2026, 8, 3))["jumlah"], 1)

    def test_memakai_posted_date_bukan_occurred_at(self):
        """Breakdown memilah dengan `posted_date`; baris FR bahkan boleh tanpa
        `occurred_at` sama sekali."""
        self.fr("BANK BCA | A | DEPOSIT", "Deposit", "50000", tgl=date(2026, 8, 3))
        self.fr("BANK BCA | A | DEPOSIT", "Deposit", "70000", tgl=date(2026, 8, 4))

        self.assertEqual(detail_fr(self.toko, date(2026, 8, 3))["jumlah"], 1)
        self.assertEqual(detail_fr(self.toko, date(2026, 8, 3), date(2026, 8, 4))["jumlah"], 2)

    def test_toko_lain_tidak_bocor(self):
        lain = Toko.objects.exclude(pk=self.toko.pk).first()
        Transaction.objects.create(
            upload=self.up, source_type=self.st, toko=lain, posted_date=date(2026, 8, 3),
            jenis="lainnya", amount=Decimal("1"), credit_delta=Decimal("0"),
            money_delta=Decimal("1"), fee=Decimal("0"), bonus=Decimal("0"),
            raw={"Bank": "X | Y | DEPOSIT", "Kategori": "Deposit"}, row_hash="lain",
        )
        self.assertEqual(detail_fr(self.toko, date(2026, 8, 3))["jumlah"], 0)


class UrutanDanIsiBarisTest(_Basis):
    def test_urut_kronologis_seperti_rantai_saldo(self):
        self.fr("BANK BCA | A | DEPOSIT", "Deposit", "3", jam="23:00", saldo="30")
        self.fr("BANK BCA | A | DEPOSIT", "Deposit", "1", jam="08:00", saldo="10")
        self.fr("BANK BCA | A | DEPOSIT", "Deposit", "2", jam="12:00", saldo="20")

        nominal = [b["nominal"] for b in detail_fr(self.toko, date(2026, 8, 3))["baris"]]

        self.assertEqual(nominal, [Decimal("1"), Decimal("2"), Decimal("3")])

    def test_baris_membawa_keterangan_member_dan_saldo(self):
        self.fr("BANK BCA | A | DEPOSIT", "Deposit", "50000",
                member="BUDI", desc="DP via QRIS", saldo="123456")

        b = detail_fr(self.toko, date(2026, 8, 3))["baris"][0]

        self.assertEqual(b["member"], "BUDI")
        self.assertEqual(b["keterangan"], "DP via QRIS")
        self.assertEqual(b["saldo"], Decimal("123456"))
        self.assertEqual(b["jam"], "10:00")
        self.assertEqual(b["kategori_label"], "Deposit")

    def test_pencarian_teks_menyaring_keterangan_member_username(self):
        self.fr("BANK BCA | A | DEPOSIT", "Deposit", "1", desc="transfer BUDI")
        self.fr("BANK BCA | A | DEPOSIT", "Deposit", "2", member="SITI")
        self.fr("BANK BCA | A | DEPOSIT", "Deposit", "3", desc="lain")

        self.assertEqual(detail_fr(self.toko, date(2026, 8, 3), q="budi")["jumlah"], 1)
        self.assertEqual(detail_fr(self.toko, date(2026, 8, 3), q="siti")["jumlah"], 1)

    def test_pilihan_filter_ikut_isi_hari_itu(self):
        self.fr("BANK BCA | A | DEPOSIT", "Deposit", "1")
        self.fr("QRIS UNOPAY | - | DEPOSIT / WITHDRAW", "Adjustment", "-2")

        d = detail_fr(self.toko, date(2026, 8, 3))

        self.assertEqual({a["account"] for a in d["akun_pilihan"]},
                         {"BANK BCA | A | DEPOSIT", "QRIS UNOPAY | - | DEPOSIT / WITHDRAW"})
        self.assertEqual({k["slug"] for k in d["kategori_pilihan"]}, {"deposit", "adjustment"})


class KoreksiFRTest(_Basis):
    """Sel yang dikoreksi manual TIDAK akan sama dengan jumlah baris aslinya —
    itu memang maksud koreksi. Yang haram adalah membiarkannya diam-diam beda."""

    def _koreksi(self, akun, kolom, nilai):
        from web.models import FRKoreksi

        return FRKoreksi.objects.create(
            toko=self.toko, tanggal=date(2026, 8, 3), account=akun,
            kolom=kolom, nilai=Decimal(nilai), dibuat_oleh=self.user,
        )

    def test_detail_menyebutkan_adanya_koreksi(self):
        akun = "BANK BCA | A | DEPOSIT"
        self.fr(akun, "Adjustment", "-450000")
        self._koreksi(akun, "adjustment", "-400000")

        d = detail_fr(self.toko, date(2026, 8, 3), akun=akun, kategori="adjustment")

        self.assertEqual(d["total"], Decimal("-450000"))       # isi asli apa adanya
        self.assertIsNotNone(d["koreksi"])
        self.assertEqual(d["koreksi"]["nilai"], Decimal("-400000"))

    def test_tanpa_koreksi_tidak_ada_catatan(self):
        akun = "BANK BCA | A | DEPOSIT"
        self.fr(akun, "Adjustment", "-450000")

        d = detail_fr(self.toko, date(2026, 8, 3), akun=akun, kategori="adjustment")

        self.assertIsNone(d["koreksi"])

    def test_koreksi_tidak_dilihat_pada_mode_rentang(self):
        """Koreksi berkunci pada SATU tanggal — sama seperti /bracket/."""
        akun = "BANK BCA | A | DEPOSIT"
        self.fr(akun, "Adjustment", "-450000")
        self._koreksi(akun, "adjustment", "-400000")

        d = detail_fr(self.toko, date(2026, 8, 3), date(2026, 8, 4),
                      akun=akun, kategori="adjustment")

        self.assertIsNone(d["koreksi"])


class HalamanTest(_Basis):
    def setUp(self):
        super().setUp()
        self.client.login(username="aud", password="pw12345")
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})

    def test_halaman_render_dan_menampilkan_baris(self):
        self.fr("BANK BCA | IGNATIUS IVAN | WITHDRAW", "Adjustment", "-450000",
                member="BUDI", desc="koreksi selisih")

        r = self.client.get(reverse("bracket_detail"), {
            "dari": "2026-08-03", "sampai": "2026-08-03",
            "akun": "BANK BCA | IGNATIUS IVAN | WITHDRAW", "kategori": "adjustment",
        })

        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "koreksi selisih")
        self.assertContains(r, "450.000")

    def test_tautan_submenu_ada_di_sidebar(self):
        r = self.client.get(reverse("bracket_detail"))

        self.assertContains(r, "Detail FR/Bracket")
        self.assertContains(r, reverse("bracket_detail"))

    def test_tanpa_data_tetap_render(self):
        r = self.client.get(reverse("bracket_detail"))

        self.assertEqual(r.status_code, 200)


class TautanDariPanelKoreksiTest(_Basis):
    """Jalan pintas dari sel Control Bracket ke rinciannya.

    Ditempatkan DI DALAM panel koreksi yang sudah terbuka, bukan sebagai menu
    pilihan sebelum panel: koreksi adalah pekerjaan harian dan harus tetap satu
    klik, sedangkan melihat rincian sifatnya sesekali."""

    def setUp(self):
        super().setUp()
        self.client.login(username="aud", password="pw12345")
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})
        self.akun = "BANK BCA | IGNATIUS IVAN | WITHDRAW"

    def _panel(self, kolom, akun=None):
        return self.client.get(reverse("fr_koreksi_form"), {
            "date": "2026-08-03", "account": akun or self.akun, "kolom": kolom,
        })

    def test_panel_menawarkan_tautan_rincian_dengan_jumlah_barisnya(self):
        for n in ("-200000", "-150000", "-100000"):
            self.fr(self.akun, "Adjustment", n)

        r = self._panel("adjustment")

        self.assertContains(r, "Lihat 3 baris penyusunnya")
        self.assertContains(r, reverse("bracket_detail"))
        self.assertContains(r, "kategori=adjustment")

    def test_tautan_membawa_penyaring_yang_benar_dan_terenkode(self):
        """Nama akun memuat spasi dan '|' — harus ter-encode, bukan memutus URL."""
        self.fr(self.akun, "Adjustment", "-450000")

        r = self._panel("adjustment")
        html = r.content.decode()

        self.assertIn("dari=2026-08-03", html)
        self.assertIn("sampai=2026-08-03", html)
        self.assertIn("akun=BANK%20BCA%20%7C%20IGNATIUS%20IVAN%20%7C%20WITHDRAW", html)

    def test_form_koreksi_tetap_utuh_satu_klik(self):
        """Kontrak lama: panel yang sama tetap memuat formnya — tautan rincian
        adalah tambahan, bukan pengganti."""
        self.fr(self.akun, "Adjustment", "-450000")

        r = self._panel("adjustment")

        self.assertContains(r, 'name="nilai"')
        self.assertContains(r, "Simpan")
        self.assertContains(r, reverse("fr_koreksi_simpan"))

    def test_sel_saldo_tidak_dapat_tautan(self):
        """Saldo awal/akhir bukan jumlah dari baris mana pun — menautkannya ke
        daftar baris justru menyesatkan."""
        self.fr(self.akun, "Deposit", "50000", saldo="100000")

        for kolom in ("saldo_awal", "saldo_akhir"):
            r = self._panel(kolom)
            self.assertNotContains(r, "baris penyusunnya", msg_prefix=kolom)

    def test_sel_kategori_kosong_menyebut_kosong_bukan_tautan_menyesatkan(self):
        self.fr(self.akun, "Deposit", "50000")

        r = self._panel("adjustment")

        self.assertContains(r, "Tidak ada baris FR di sel ini")
        self.assertNotContains(r, "baris penyusunnya")
