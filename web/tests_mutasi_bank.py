"""Sub-menu Mutasi Bank: mutasi bank + gateway QRIS urut sesuai file asli,
lookup HP -> nama player dari panel, kolom Fee (gateway RECORD FEE / Fee)."""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()
_seq = iter(range(1, 100000))


class MutasiBankBase(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.slo = Toko.objects.get(key="slo")
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.gateway = SourceType.objects.get_or_create(key="gateway", defaults={"name": "Gateway"})[0]
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def _up(self, st, name="f.csv", toko=None, owner=""):
        return Upload.objects.create(
            source_type=st, toko=toko or self.lbs, original_name=name, owner_name=owner,
        )

    def _tx(self, up, st, *, toko=None, jenis="depo", counterparty="", description="",
            amount="10000", balance=None, fee="0", dt=datetime(2026, 6, 27, 10, 0)):
        return Transaction.objects.create(
            upload=up, source_type=st, toko=toko or self.lbs, jenis=jenis,
            amount=Decimal(amount), money_delta=Decimal(amount),
            fee=Decimal(fee),
            balance_after=None if balance is None else Decimal(balance),
            occurred_at=dt, counterparty=counterparty, description=description,
            raw={}, row_hash=f"mb-{next(_seq)}",
        )


class MutasiBankScopeTests(MutasiBankBase):
    def test_hanya_sumber_uang_toko_aktif(self):
        upb = self._up(self.bank, "27_JUNI_2026_WD_BCA_HENDI.pdf", owner="HENDI")
        self._tx(upb, self.bank, counterparty="SUPRIADI BANKROW")
        upp = self._up(self.panel, "panel.xlsx")
        self._tx(upp, self.panel, counterparty="PANEL GUY")
        upo = self._up(self.bank, "bca.csv", toko=self.slo)
        self._tx(upo, self.bank, toko=self.slo, counterparty="TOKO LAIN")
        r = self.client.get(reverse("bank_mutations"))
        self.assertContains(r, "SUPRIADI BANKROW")
        self.assertNotContains(r, "PANEL GUY")
        self.assertNotContains(r, "TOKO LAIN")

    def test_label_sumber_dengan_owner(self):
        upb = self._up(self.bank, "27_JUNI_2026_WD_BCA_HENDI.pdf", owner="HENDI")
        self._tx(upb, self.bank, counterparty="X")
        r = self.client.get(reverse("bank_mutations"))
        self.assertContains(r, "BCA a/n HENDI")

    def test_sidebar_link(self):
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "Mutasi Bank")
        self.assertContains(r, reverse("bank_mutations"))


class MutasiBankOrderTests(MutasiBankBase):
    def test_urut_file_asli_per_upload(self):
        """Grup per file (upload terbaru dulu), di dalam file urut id (= urutan parse)."""
        up1 = self._up(self.bank, "file1.csv")
        a = self._tx(up1, self.bank, counterparty="A-ROW", dt=datetime(2026, 6, 27, 23, 0))
        b = self._tx(up1, self.bank, counterparty="B-ROW", dt=datetime(2026, 6, 27, 1, 0))
        up2 = self._up(self.bank, "file2.csv")
        c = self._tx(up2, self.bank, counterparty="C-ROW", dt=datetime(2026, 6, 27, 12, 0))
        r = self.client.get(reverse("bank_mutations"))
        html = r.content.decode()
        # upload terbaru (file2) dulu; dalam file1: A sebelum B (urutan insert, BUKAN waktu)
        self.assertLess(html.index("C-ROW"), html.index("A-ROW"))
        self.assertLess(html.index("A-ROW"), html.index("B-ROW"))


class MutasiBankFilterTests(MutasiBankBase):
    def setUp(self):
        super().setUp()
        self.upb = self._up(self.bank, "bca.csv")
        self._tx(self.upb, self.bank, jenis="depo", counterparty="DP-BANK",
                 dt=datetime(2026, 6, 27, 10, 0))
        self._tx(self.upb, self.bank, jenis="wd", counterparty="WD-BANK",
                 amount="-5000", dt=datetime(2026, 6, 28, 10, 0))
        self.upg = self._up(self.gateway, "MUTASI DP QR FLYER OKE25 27-06.xlsx")
        self._tx(self.upg, self.gateway, jenis="depo", counterparty="GW-ROW")

    def test_filter_source_bank(self):
        r = self.client.get(reverse("bank_mutations"), {"source": "bank"})
        self.assertContains(r, "DP-BANK")
        self.assertNotContains(r, "GW-ROW")

    def test_filter_source_gateway(self):
        r = self.client.get(reverse("bank_mutations"), {"source": "gateway"})
        self.assertContains(r, "GW-ROW")
        self.assertNotContains(r, "DP-BANK")

    def test_filter_upload(self):
        r = self.client.get(reverse("bank_mutations"), {"upload": self.upg.id})
        self.assertContains(r, "GW-ROW")
        self.assertNotContains(r, "DP-BANK")

    def test_dropdown_file_ikut_tombol_sumber(self):
        # tombol Bank -> dropdown cuma file bank; Gateway -> cuma file gateway
        r = self.client.get(reverse("bank_mutations"), {"source": "bank"})
        self.assertContains(r, "bca.csv")
        self.assertNotContains(r, "QR FLYER")
        r = self.client.get(reverse("bank_mutations"), {"source": "gateway"})
        self.assertContains(r, "QR FLYER")
        self.assertNotContains(r, "bca.csv")

    def test_combobox_cari_file_terpasang(self):
        """Wiring: class file-pick + skrip combobox global (search box File mutasi)."""
        r = self.client.get(reverse("bank_mutations"))
        html = r.content.decode()
        self.assertEqual(r.status_code, 200)
        self.assertIn('name="upload"', html)
        self.assertIn("file-pick", html)
        self.assertIn("toko-picker.js", html)
        self.assertIn("tp-combo-file", html)

    def test_ganti_sumber_reset_pilihan_file(self):
        # file gateway dipilih tapi sumber=bank -> pilihan diabaikan (tampil semua bank)
        r = self.client.get(reverse("bank_mutations"), {"source": "bank", "upload": self.upg.id})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "DP-BANK")
        self.assertNotContains(r, "GW-ROW")

    def test_filter_upload_toko_lain_diabaikan(self):
        upo = self._up(self.bank, "x.csv", toko=self.slo)
        self._tx(upo, self.bank, toko=self.slo, counterparty="LAIN")
        r = self.client.get(reverse("bank_mutations"), {"upload": upo.id})
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "LAIN")  # upload toko lain tak bocor

    def test_filter_flow(self):
        r = self.client.get(reverse("bank_mutations"), {"flow": "wd"})
        self.assertContains(r, "WD-BANK")
        self.assertNotContains(r, "DP-BANK")

    def test_filter_flow_cm_tombol_ada(self):
        r = self.client.get(reverse("bank_mutations"))
        self.assertContains(r, "Sesama CM")
        self.assertContains(r, "flow=cm")

    def test_filter_tanggal(self):
        r = self.client.get(reverse("bank_mutations"), {"from": "2026-06-28"})
        self.assertContains(r, "WD-BANK")
        self.assertNotContains(r, "DP-BANK")


class MutasiBankSesamaCmTests(MutasiBankBase):
    """Filter flow=cm: pindah dana antar rekening CM — identitas dari FR Sesama CM
    (+ pelengkap owner upload bank).

    Kasus Mul: file owner NASRUL menerima dari KIKI SUASANTO → Sesama CM;
    WD NASRUL ke member eksternal → bukan Sesama CM (nama di deskripsi = owner sendiri).
    """

    def setUp(self):
        super().setUp()
        from web.sesama_cm import clear_cm_cache
        clear_cm_cache()
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"}
        )[0]
        self.up_nasrul = self._up(self.bank, "bri_nasrul.csv", owner="NASRUL")
        self.up_kiki = self._up(self.bank, "bri_kiki.csv", owner="KIKI SUASANTO")
        # FR Sesama CM — sumber nama + no.rek (otoritatif, selaras Control Bracket)
        self.up_fr = self._up(self.bracket, "fr.xlsx")
        self._fr_cm(
            "BANK BRI | KIKI SUASANTO | TAMPUNG LAYER 2",
            "BRI 119101022152500",
            amount="5000000",
        )
        self._fr_cm(
            "BANK BCA | YULIYANTI PRATIWI | TAMPUNG LAYER 1",
            "BCA 8447072062",
            amount="970000",
        )
        self._fr_cm(
            "BANK BRI | NASRUL | WITHDRAW",
            "BRI 058801037387506",
            amount="5000000",
        )
        # Baris pindah dana: masuk ke rekening Nasrul dari Kiki (nama).
        self.cm_depo = self._tx(
            self.up_nasrul, self.bank, jenis="depo", counterparty="Kikisuasanto",
            description="NBMB Kikisuasanto TO NASRUL ESB:NBMB:0001500F:1",
            amount="5000000", dt=datetime(2026, 8, 21, 10, 0),
        )
        # WD member biasa dari rekening Nasrul — deskripsi memuat "Nasrul" (owner sendiri).
        self.wd_member = self._tx(
            self.up_nasrul, self.bank, jenis="wd", counterparty="ANWAR",
            description="NBMB Nasrul TO ANWAR ESB:NBMB:0001500F:2",
            amount="-350000", dt=datetime(2026, 8, 21, 11, 0),
        )
        # WD Sesama CM via no.rek FR (nama di bank bisa beda ejaan).
        self.cm_wd = self._tx(
            self.up_nasrul, self.bank, jenis="wd", counterparty="YULI",
            description="Transfer BI Fast Ke BCA 8447072062",
            amount="-970000", dt=datetime(2026, 8, 21, 12, 0),
        )
        # Depo member biasa — counterparty bukan nama CM.
        self.dp_member = self._tx(
            self.up_nasrul, self.bank, jenis="depo", counterparty="BUDI SANTOSO",
            description="TRSF E-BANKING CR BUDI SANTOSO",
            amount="100000", dt=datetime(2026, 8, 21, 13, 0),
        )
        clear_cm_cache()

    def _fr_cm(self, bank, rek, amount="1000000"):
        return Transaction.objects.create(
            upload=self.up_fr, source_type=self.bracket, toko=self.lbs,
            jenis="lainnya", amount=Decimal(amount), money_delta=Decimal(amount),
            occurred_at=datetime(2026, 8, 21, 9, 0), posted_date=datetime(2026, 8, 21).date(),
            description="PINDAH DANA",
            raw={
                "Kategori": "Sesama CM",
                "Bank": bank,
                "No. Rek Bank Member": rek,
                "Description": "PINDAH DANA",
            },
            row_hash=f"mb-fr-{next(_seq)}",
        )

    def test_filter_cm_hanya_pindah_antar_cm(self):
        r = self.client.get(reverse("bank_mutations"), {"flow": "cm"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Kikisuasanto")
        self.assertContains(r, "8447072062")  # match via no.rek FR
        self.assertNotContains(r, "ANWAR")
        self.assertNotContains(r, "BUDI SANTOSO")
        self.assertContains(r, "Sesama CM")

    def test_badge_cm_di_daftar_semua(self):
        r = self.client.get(reverse("bank_mutations"))
        rows = list(r.context["page"].object_list)
        by_cp = {(t.counterparty or ""): t for t in rows}
        self.assertTrue(getattr(by_cp["Kikisuasanto"], "is_sesama_cm", False))
        self.assertTrue(getattr(by_cp["YULI"], "is_sesama_cm", False))  # norek
        self.assertFalse(getattr(by_cp["ANWAR"], "is_sesama_cm", False))
        self.assertFalse(getattr(by_cp["BUDI SANTOSO"], "is_sesama_cm", False))

    def test_identitas_dari_fr_bukan_hanya_upload(self):
        """Nama hanya di FR (tanpa upload owner) tetap menggerakkan filter."""
        from web.sesama_cm import clear_cm_cache, nama_cm_toko, identitas_cm_toko
        clear_cm_cache()
        # FR punya FITRIA; tidak ada upload owner FITRIA
        self._fr_cm("BANK BNI | FITRIA | DEPOSIT", "BNI 1929696573")
        clear_cm_cache()
        names = nama_cm_toko(self.lbs.id)
        self.assertTrue(any("FITRIA" in n.upper() for n in names))
        _, reks = identitas_cm_toko(self.lbs.id)
        self.assertIn("1929696573", reks)
        # mutasi ke FITRIA via nama
        self._tx(
            self.up_nasrul, self.bank, jenis="wd", counterparty="FITRIA RAHMA",
            description="TRSF KE FITRIA", amount="-100000",
            dt=datetime(2026, 8, 21, 14, 0),
        )
        r = self.client.get(reverse("bank_mutations"), {"flow": "cm"})
        self.assertContains(r, "FITRIA")

    def test_helper_bersih_nama_buang_sufiks(self):
        from web.sesama_cm import _bersih_nama, _nama_dari_bank_fr
        self.assertEqual(_bersih_nama("KIKI SUASANTO TAMPUNG LAYER ARUBBXY"), "KIKI SUASANTO")
        self.assertEqual(_bersih_nama("NASRUL YGLWHAK"), "NASRUL")
        self.assertEqual(_bersih_nama("NXPAY"), "")
        self.assertEqual(_bersih_nama("YOGA"), "")
        self.assertEqual(
            _nama_dari_bank_fr("BANK BRI | KIKI SUASANTO | TAMPUNG LAYER 2"),
            "KIKI SUASANTO",
        )

    def test_qrflyer_tampung_selalu_sesama_cm_meski_penerima_bukan_daftar_cm(self):
        """MUTASI TAMPUNG QR FLYER = pindah dana float → rekening; seluruh baris Sesama CM.

        Prod MUL: 10/81 baris ke STANLEY/UBAY (bukan di identitas FR) kosong di
        filter flow=cm — padahal file tampung seluruhnya internal.
        """
        from web.sesama_cm import clear_cm_cache, q_sesama_cm, tandai_sesama_cm
        gw = SourceType.objects.get_or_create(key="gateway", defaults={"name": "Gateway"})[0]
        up = self._up(gw, "MUTASI TAMPUNG QR FLYER MUL 22-08.csv", owner="MUL ZMGZCRT")
        # penerima TIDAK ada di FR Sesama CM
        t_out = self._tx(
            up, gw, jenis="wd", counterparty="STANLEY",
            description="QRFLYER TAMPUNG BCA 5370534162 STANLEY",
            amount="-35000000", dt=datetime(2026, 8, 22, 8, 0),
        )
        t_in = self._tx(
            up, gw, jenis="wd", counterparty="KIKISUASANTO",
            description="QRFLYER TAMPUNG BRI 119101022152500 KIKISUASANTO",
            amount="-23787096", dt=datetime(2026, 8, 22, 8, 44),
        )
        # member gateway biasa — BUKAN tampung
        t_member = self._tx(
            up, gw, jenis="depo", counterparty="PLAYER",
            description="QRFLYER deposit PLAYER ticket D1",
            amount="100000", dt=datetime(2026, 8, 22, 9, 0),
        )
        clear_cm_cache()
        self.assertTrue(
            Transaction.objects.filter(id=t_out.id).filter(q_sesama_cm(self.lbs.id)).exists()
        )
        self.assertTrue(
            Transaction.objects.filter(id=t_in.id).filter(q_sesama_cm(self.lbs.id)).exists()
        )
        self.assertFalse(
            Transaction.objects.filter(id=t_member.id).filter(q_sesama_cm(self.lbs.id)).exists()
        )
        rows = [t_out, t_in, t_member]
        tandai_sesama_cm(rows, self.lbs.id)
        self.assertTrue(t_out.is_sesama_cm)
        self.assertTrue(t_in.is_sesama_cm)
        self.assertFalse(t_member.is_sesama_cm)
        r = self.client.get(reverse("bank_mutations"), {"flow": "cm", "source": "gateway"})
        self.assertContains(r, "STANLEY")
        self.assertContains(r, "QRFLYER TAMPUNG")
        self.assertNotContains(r, "deposit PLAYER")

    def test_qris_elite_tampung_selalu_sesama_cm(self):
        from web.sesama_cm import clear_cm_cache, q_sesama_cm
        gw = SourceType.objects.get_or_create(key="gateway", defaults={"name": "Gateway"})[0]
        up = self._up(gw, "MUTASI TAMPUNG QR ELITE.csv", owner="")
        t = self._tx(
            up, gw, jenis="wd", counterparty="ORANG LUAR",
            description="QRISELITE TAMPUNG 1191010221 ORANG LUAR REF1",
            amount="-24996500", dt=datetime(2026, 8, 22, 12, 0),
        )
        clear_cm_cache()
        self.assertTrue(
            Transaction.objects.filter(id=t.id).filter(q_sesama_cm(self.lbs.id)).exists()
        )

    def test_qhoki_dp_bukan_sesama_cm_meski_owner_hoki_mirip_fr(self):
        """BTS: DP QRIS HOKI (owner=HOKI) jangan jadi Sesama CM lewat FR TP QRISHOKI UNITED.

        Badge harus Deposit; Sesama CM gateway hanya tampung.
        """
        from web.sesama_cm import (
            clear_cm_cache,
            cm_names_match,
            q_sesama_cm,
            tandai_sesama_cm,
        )
        br = SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})[0]
        # FR channel label — mirip owner HOKI bila substring longgar
        Upload.objects.create(
            source_type=br, toko=self.lbs, original_name="fr.xlsx",
        )
        fr_up = Upload.objects.filter(toko=self.lbs, source_type=br).latest("id")
        Transaction.objects.create(
            upload=fr_up, source_type=br, toko=self.lbs, jenis="lainnya",
            amount=Decimal("0"), money_delta=Decimal("0"),
            occurred_at=datetime(2026, 8, 23, 10, 0),
            raw={
                "Kategori": "Sesama CM",
                "Bank": "BANK BCA | TP QRISHOKI UNITED | TAMPUNG",
                "No. Rek Bank Member": "BCA 5830314051",
            },
            row_hash=f"fr-hoki-{next(_seq)}",
        )
        gw = SourceType.objects.get_or_create(key="gateway", defaults={"name": "Gateway"})[0]
        up = self._up(gw, "23-08-2026 BTS MUTASI DP QRIS HOKI.csv", owner="HOKI")
        t_dp = self._tx(
            up, gw, jenis="depo", counterparty="",
            description="QHOKI 623533338726",
            amount="25000", dt=datetime(2026, 8, 23, 16, 49),
        )
        t_wd = self._tx(
            up, gw, jenis="wd", counterparty="",
            description="QHOKI 999888777666",
            amount="-30000", dt=datetime(2026, 8, 23, 17, 0),
        )
        clear_cm_cache()
        self.assertFalse(cm_names_match("HOKI", "TP QRISHOKI UNITED"))
        self.assertFalse(
            Transaction.objects.filter(id=t_dp.id).filter(q_sesama_cm(self.lbs.id)).exists()
        )
        self.assertFalse(
            Transaction.objects.filter(id=t_wd.id).filter(q_sesama_cm(self.lbs.id)).exists()
        )
        rows = [t_dp, t_wd]
        tandai_sesama_cm(rows, self.lbs.id)
        self.assertFalse(t_dp.is_sesama_cm)
        self.assertFalse(t_wd.is_sesama_cm)
        # UI: flow deposit masih menampilkan baris; flow cm tidak
        r_dp = self.client.get(reverse("bank_mutations"), {"flow": "depo", "source": "gateway"})
        self.assertContains(r_dp, "QHOKI 623533338726")
        r_cm = self.client.get(reverse("bank_mutations"), {"flow": "cm", "source": "gateway"})
        self.assertNotContains(r_cm, "QHOKI 623533338726")

    def test_bank_file_dp_bukan_sesama_cm_meski_norek_fr_di_desc(self):
        """TGS/BTS: MUTASI DP BRI a/n CM — BFST/DANA + norek FR tetap Deposit.

        File bertoken DP = uang masuk; jangan badge Sesama CM lewat norek/opaque.
        """
        from web.sesama_cm import clear_cm_cache, q_sesama_cm, tandai_sesama_cm
        br = SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})[0]
        fr_up = Upload.objects.create(source_type=br, toko=self.lbs, original_name="fr.xlsx")
        Transaction.objects.create(
            upload=fr_up, source_type=br, toko=self.lbs, jenis="lainnya",
            amount=Decimal("0"), money_delta=Decimal("0"),
            occurred_at=datetime(2026, 8, 23, 10, 0),
            raw={
                "Kategori": "Sesama CM",
                "Bank": "BANK BRI | KARIS NATHALIA FEBRIN | TAMPUNG",
                "No. Rek Bank Member": "BRI 7800588426",
            },
            row_hash=f"fr-karis-{next(_seq)}",
        )
        Transaction.objects.create(
            upload=fr_up, source_type=br, toko=self.lbs, jenis="lainnya",
            amount=Decimal("0"), money_delta=Decimal("0"),
            occurred_at=datetime(2026, 8, 23, 10, 1),
            raw={
                "Kategori": "Sesama CM",
                "Bank": "BANK BRI | ELISA PRATIWI | TAMPUNG",
                "No. Rek Bank Member": "BRI 040401063175505",
            },
            row_hash=f"fr-elisa-{next(_seq)}",
        )
        up = self._up(
            self.bank,
            "23-08-2026 TGS MUTASI DP BRI KARIS NATHALIA FEBRIN.csv",
            owner="KARIS NATHALIA FEBRIN",
        )
        t_nbmb = self._tx(
            up, self.bank, jenis="depo", counterparty="ALEX SANJAYA",
            description="NBMB ALEX SANJAYA TO KARIS NATHALIA FE ESB:NBMB:0001500F:199476140562",
            amount="500000", dt=datetime(2026, 8, 23, 15, 43),
        )
        t_bfst = self._tx(
            up, self.bank, jenis="wd", counterparty="",
            description="BFST7800588426 NBMB:CENAIDJA 20260823BRINIDJA010O0240710105",
            amount="-550000", dt=datetime(2026, 8, 23, 15, 44),
        )
        t_dana = self._tx(
            up, self.bank, jenis="depo", counterparty="",
            description="BFST040401063175505SITI AZLINA :BMRIIDJA 20260823BMRIIDJA010O022602595",
            amount="25000", dt=datetime(2026, 8, 23, 20, 12),
        )
        clear_cm_cache()
        for t in (t_nbmb, t_bfst, t_dana):
            self.assertFalse(
                Transaction.objects.filter(id=t.id).filter(q_sesama_cm(self.lbs.id)).exists(),
                msg=t.description,
            )
        rows = [t_nbmb, t_bfst, t_dana]
        tandai_sesama_cm(rows, self.lbs.id)
        self.assertFalse(t_nbmb.is_sesama_cm)
        self.assertFalse(t_bfst.is_sesama_cm)
        self.assertFalse(t_dana.is_sesama_cm)
        r_cm = self.client.get(reverse("bank_mutations"), {"flow": "cm", "source": "bank"})
        self.assertNotContains(r_cm, "BFST7800588426")
        self.assertNotContains(r_cm, "SITI AZLINA")

    def test_muhammad_depan_umum_tidak_telan_wd_member(self):
        """BTS 25-08: CM FR «MUHAMMAD YUDHA» jangan badge Sesama CM ke WD member
        «MUHAMMAD ICHSAN» / «MUHAMMAD ILHAM…» (token depan umum).

        Transfer benar ke MUHAMMAD YUDHA tetap Sesama CM.
        """
        from web.sesama_cm import (
            _varian,
            clear_cm_cache,
            cm_names_match,
            q_sesama_cm,
            tandai_sesama_cm,
        )
        br = SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})[0]
        fr_up = Upload.objects.create(source_type=br, toko=self.lbs, original_name="fr.xlsx")
        Transaction.objects.create(
            upload=fr_up, source_type=br, toko=self.lbs, jenis="lainnya",
            amount=Decimal("0"), money_delta=Decimal("0"),
            occurred_at=datetime(2026, 8, 25, 10, 0),
            raw={
                "Kategori": "Sesama CM",
                "Bank": "BANK BCA | MUHAMMAD YUDHA | TAMPUNG",
                "No. Rek Bank Member": "BCA 5830314051",
            },
            row_hash=f"fr-yudha-{next(_seq)}",
        )
        up = self._up(
            self.bank,
            "25-08-2026 BTS MUTASI WD BCA DIMAS BAYU LEGOWO.CSV",
            owner="DIMAS BAYU LEGOWO",
        )
        t_ichsan = self._tx(
            up, self.bank, jenis="wd", counterparty="MUHAMMAD ICHSAN",
            description="TRSF E-BANKING DB 2508/FTSCY/WS95031         100000.00MUHAMMAD ICHSAN",
            amount="-100000", dt=datetime(2026, 8, 25, 0, 0),
        )
        t_ilham = self._tx(
            up, self.bank, jenis="wd", counterparty="MUHAMMAD ILHAM RAM",
            description="TRSF E-BANKING DB 2508/FTSCY/WS95031         800000.00MUHAMMAD ILHAM R",
            amount="-800000", dt=datetime(2026, 8, 25, 0, 1),
        )
        t_misbah = self._tx(
            up, self.bank, jenis="wd", counterparty="MUHAMMAD MISBAHUDDM-BCA",
            description="BI-FAST DB TRANSFER   KE 542 MUHAMMAD MISBAHUDDM-BCA",
            amount="-600000", dt=datetime(2026, 8, 25, 0, 2),
        )
        t_yudha = self._tx(
            up, self.bank, jenis="depo", counterparty="MUHAMMAD YUDHA",
            description="TRSF E-BANKING CR 2508/FTSCY/WS95271         640000.00MUHAMMAD YUDHA",
            amount="640000", dt=datetime(2026, 8, 25, 0, 3),
        )
        clear_cm_cache()
        vars_y = _varian("MUHAMMAD YUDHA")
        self.assertNotIn("MUHAMMAD", [v.upper() for v in vars_y])
        self.assertFalse(cm_names_match("MUHAMMAD ICHSAN", "MUHAMMAD YUDHA"))
        self.assertFalse(cm_names_match("MUHAMMAD ILHAM RAM", "MUHAMMAD YUDHA"))
        self.assertTrue(cm_names_match("MUHAMMAD YUDHA", "MUHAMMAD YUDHA"))
        self.assertTrue(cm_names_match("SERVA", "SERVA MUHAMAD SEBASTIAN"))
        for t in (t_ichsan, t_ilham, t_misbah):
            self.assertFalse(
                Transaction.objects.filter(id=t.id).filter(q_sesama_cm(self.lbs.id)).exists(),
                msg=t.counterparty,
            )
        self.assertTrue(
            Transaction.objects.filter(id=t_yudha.id).filter(q_sesama_cm(self.lbs.id)).exists()
        )
        rows = [t_ichsan, t_ilham, t_misbah, t_yudha]
        tandai_sesama_cm(rows, self.lbs.id)
        self.assertFalse(t_ichsan.is_sesama_cm)
        self.assertFalse(t_ilham.is_sesama_cm)
        self.assertFalse(t_misbah.is_sesama_cm)
        self.assertTrue(t_yudha.is_sesama_cm)
        r_cm = self.client.get(reverse("bank_mutations"), {"flow": "cm", "source": "bank"})
        self.assertContains(r_cm, "MUHAMMAD YUDHA")
        self.assertNotContains(r_cm, "MUHAMMAD ICHSAN")
        self.assertNotContains(r_cm, "MUHAMMAD ILHAM")
        self.assertNotContains(r_cm, "MISBAHUDDM")


class MutasiBankPhoneLookupTests(MutasiBankBase):
    def test_baris_ewallet_tampilkan_hp_dan_nama_panel(self):
        # panel: HP player di segmen ke-3 Player Bank (pola COR "KODE|NAMA|ACCT")
        upp = self._up(self.panel, "panel.xlsx")
        Transaction.objects.create(
            upload=upp, source_type=self.panel, toko=self.lbs, jenis="depo",
            amount=Decimal("10000"), occurred_at=datetime(2026, 6, 27, 9, 0),
            counterparty="BUDI SANTOSO", username="budi82",
            raw={"Player Bank": "DANA|BUDI SANTOSO|082279003062"},
            row_hash=f"mb-{next(_seq)}",
        )
        upb = self._up(self.bank, "bca.csv")
        self._tx(upb, self.bank, jenis="wd", counterparty="",
                 description="TRSF E-BANKING DB 2606/FTFVA/WS9501139010/DANA - - 82279003062")
        r = self.client.get(reverse("bank_mutations"))
        self.assertContains(r, "82279003062")     # nomor HP tampil
        self.assertContains(r, "BUDI SANTOSO")    # nama dari panel

    def test_tanpa_kandidat_panel_hanya_hp(self):
        upb = self._up(self.bank, "bca.csv")
        self._tx(upb, self.bank, jenis="wd", counterparty="",
                 description="GOPAY TOPUP - - 085767555197")
        r = self.client.get(reverse("bank_mutations"))
        self.assertContains(r, "085767555197")


class ResolveWalletNamesNbmbFallbackTests(MutasiBankBase):
    """Unit test langsung atas _resolve_wallet_names (web/views.py): baris BRI LAMA
    (counterparty kosong di DB, ingest sebelum perbaikan regex NBMB varian tanpa-ESB,
    lihat sources.parsers.banks.NBMB_RE) -> atribut tampilan r.player_name terisi
    murni saat render, TANPA menulis balik ke Transaction."""

    DESC_TANPA_ESB = "NBMB Cantika Irsad TO DHAVIT PEBRIYANTO"
    DESC_BRIVA = ("BRIVA30135083144889247NBMBAxxxx Pxxxx "
                  "BRIVA 30135083144889247NBMBAxxxx ESB:NBMB:0200200P:174837810133")

    def _row(self, desc, jenis, amount):
        return Transaction(
            source_type=self.bank, toko=self.lbs, jenis=jenis,
            amount=abs(Decimal(amount)), money_delta=Decimal(amount),
            counterparty="", description=desc, raw={"DESK_TRAN": desc},
        )

    def test_dp_ambil_pengirim(self):
        from web.views import _resolve_wallet_names
        t = self._row(self.DESC_TANPA_ESB, "depo", "15000")
        _resolve_wallet_names([t], self.lbs)
        self.assertEqual(t.player_name, "Cantika Irsad")
        self.assertEqual(getattr(t, "phone", ""), "")  # bukan jalur HP

    def test_wd_ambil_penerima(self):
        from web.views import _resolve_wallet_names
        t = self._row(self.DESC_TANPA_ESB, "wd", "-15000")
        _resolve_wallet_names([t], self.lbs)
        self.assertEqual(t.player_name, "DHAVIT PEBRIYANTO")

    def test_briva_tak_tersentuh(self):
        from web.views import _resolve_wallet_names
        t = self._row(self.DESC_BRIVA, "wd", "-70000")
        _resolve_wallet_names([t], self.lbs)
        self.assertEqual(getattr(t, "player_name", ""), "")
        self.assertEqual(getattr(t, "phone", ""), "")

    def test_tak_menyentuh_field_tersimpan(self):
        # Murni tampilan: atribut Python transient, TIDAK ditulis ke DB.
        from web.views import _resolve_wallet_names
        t = Transaction.objects.create(
            upload=self._up(self.bank, "bca.csv"), source_type=self.bank, toko=self.lbs,
            jenis="depo", amount=Decimal("15000"), money_delta=Decimal("15000"),
            counterparty="", description=self.DESC_TANPA_ESB,
            raw={"DESK_TRAN": self.DESC_TANPA_ESB}, row_hash=f"mb-{next(_seq)}",
        )
        _resolve_wallet_names([t], self.lbs)
        self.assertEqual(t.player_name, "Cantika Irsad")
        t.refresh_from_db()
        self.assertEqual(t.counterparty, "")  # kolom DB tetap kosong


class MutasiBankNbmbFallbackTests(MutasiBankBase):
    """Render penuh /mutasi-bank/: baris BRI LAMA counterparty kosong + DESK_TRAN
    varian tanpa-ESB -> kolom "Nama (sesuai mutasi)" tampil (bukan cuma kolom
    Keterangan yang memang selalu menampilkan deskripsi mentah)."""

    DESC_TANPA_ESB = "NBMB Cantika Irsad TO DHAVIT PEBRIYANTO"
    DESC_BRIVA = ("BRIVA30135083144889247NBMBAxxxx Pxxxx "
                  "BRIVA 30135083144889247NBMBAxxxx ESB:NBMB:0200200P:174837810133")
    MARKER = "Nama dari deskripsi mutasi (varian tanpa kode ESB)"

    def _tx_bri(self, desc, jenis, amount):
        upb = self._up(self.bank, "bca.csv")
        return Transaction.objects.create(
            upload=upb, source_type=self.bank, toko=self.lbs, jenis=jenis,
            amount=abs(Decimal(amount)), money_delta=Decimal(amount),
            occurred_at=datetime(2026, 7, 25, 10, 0), counterparty="",
            description=desc, raw={"DESK_TRAN": desc},
            row_hash=f"mb-{next(_seq)}",
        )

    def test_dp_tanpa_esb_baris_lama_nama_tampil(self):
        self._tx_bri(self.DESC_TANPA_ESB, "depo", "15000")
        r = self.client.get(reverse("bank_mutations"))
        row = r.context["page"].object_list[0]
        self.assertEqual(row.player_name, "Cantika Irsad")  # DP -> pengirim
        self.assertContains(r, self.MARKER)                # kolom Nama, bukan Keterangan

    def test_wd_tanpa_esb_baris_lama_nama_tampil(self):
        self._tx_bri(self.DESC_TANPA_ESB, "wd", "-15000")
        r = self.client.get(reverse("bank_mutations"))
        row = r.context["page"].object_list[0]
        self.assertEqual(row.player_name, "DHAVIT PEBRIYANTO")  # WD -> penerima
        self.assertContains(r, self.MARKER)

    def test_briva_baris_lama_tetap_strip(self):
        self._tx_bri(self.DESC_BRIVA, "wd", "-70000")
        r = self.client.get(reverse("bank_mutations"))
        row = r.context["page"].object_list[0]
        self.assertFalse(getattr(row, "player_name", ""))
        self.assertFalse(getattr(row, "phone", ""))
        self.assertNotContains(r, self.MARKER)
        self.assertContains(r, '<span class="faint">—</span>')


class MutasiBankFeeTests(MutasiBankBase):
    """Kolom Fee (bukan Saldo) + total per halaman + total keseluruhan."""

    def test_header_fee_bukan_saldo(self):
        up = self._up(self.gateway, "elite.csv")
        self._tx(up, self.gateway, counterparty="X", fee="425")
        r = self.client.get(reverse("bank_mutations"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, ">Fee</th>")
        self.assertNotContains(r, ">Saldo</th>")

    def test_fee_tampil_dan_nol_aman(self):
        # Acuan QRIS ELITE RECORD FEE: 425 / 850 — tampil di kolom Fee
        upg = self._up(self.gateway, "26_08_W25_DP_QRIS_ELITE.csv")
        self._tx(upg, self.gateway, counterparty="ADA-FEE", fee="425", amount="50000")
        self._tx(upg, self.gateway, counterparty="TANPA-FEE", fee="0", amount="10000")
        r = self.client.get(reverse("bank_mutations"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "425")
        self.assertContains(r, "TANPA-FEE")
        # balance_after tidak lagi ditampilkan sebagai kolom
        self.assertNotContains(r, ">Saldo</th>")

    def test_total_halaman_dan_keseluruhan(self):
        upg = self._up(self.gateway, "elite.csv")
        self._tx(upg, self.gateway, counterparty="F1", fee="425", amount="50000")
        self._tx(upg, self.gateway, counterparty="F2", fee="850", amount="100000")
        r = self.client.get(reverse("bank_mutations"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["fee_page"], Decimal("1275"))
        self.assertEqual(r.context["fee_all"], Decimal("1275"))
        self.assertEqual(r.context["fee_page_nominal"], Decimal("150000"))
        self.assertEqual(r.context["fee_all_nominal"], Decimal("150000"))
        self.assertEqual(r.context["fee_all_n"], 2)
        self.assertContains(r, "Total halaman ini")
        self.assertContains(r, "Total keseluruhan")
        self.assertContains(r, "1.275")  # locale id total fee
        self.assertContains(r, "150.000")  # locale id total nominal

    def test_tfoot_sticky_marker(self):
        """Total di tfoot harus sticky bottom agar tidak ikut scroll baris."""
        upg = self._up(self.gateway, "elite.csv")
        self._tx(upg, self.gateway, counterparty="F1", fee="100", amount="1000")
        r = self.client.get(reverse("bank_mutations"))
        html = r.content.decode()
        self.assertIn('class="mutasi-foot"', html)
        self.assertIn("mutasi-foot-page", html)
        self.assertIn("mutasi-foot-all", html)
        # CSS sticky di app_base (inline di response layout)
        self.assertIn("#mutasi-table tfoot td", html)
        self.assertIn("position:sticky", html)
        self.assertIn("bottom:0", html)
        # anti bleed-through: collapse separate + pelat solid ::before
        self.assertIn("border-collapse:separate", html)
        self.assertIn("#mutasi-table tfoot td::before", html)
        self.assertIn("background:#fff", html)


class MutasiBankCoverageTests(MutasiBankBase):
    """Dropdown file & banner duplikat: file ekspor bank rolling saling tumpang-
    tindih; dedup row_hash menempatkan baris di upload PERTAMA yang memuatnya.
    Kasus nyata LBS 10/07: file '10_07 BRI' 697 baris -> hanya 47 baru, sisanya
    tercatat di file 08/09-Juli; user mengira 'mutasi kepotong'. UI harus
    menjelaskan: rentang isi nyata per file + banner saat ada duplikat."""

    def test_dropdown_menampilkan_rentang_isi_file(self):
        up = self._up(self.bank, name="10_07_bri.csv")
        self._tx(up, self.bank, dt=datetime(2026, 7, 10, 14, 38))
        self._tx(up, self.bank, dt=datetime(2026, 7, 11, 4, 51))
        r = self.client.get(reverse("bank_mutations"))
        u = next(x for x in r.context["uploads"] if x.id == up.id)
        self.assertEqual(u.cover_lo, datetime(2026, 7, 10, 14, 38))
        self.assertEqual(u.cover_hi, datetime(2026, 7, 11, 4, 51))
        self.assertContains(r, "10/07 14:38")     # rentang tampil di option
        self.assertContains(r, "11/07 04:51")

    def test_banner_duplikat_saat_file_terpilih(self):
        up = self._up(self.bank, name="10_07_bri.csv")
        up.rows_parsed, up.rows_duplicate = 47, 650
        up.save(update_fields=["rows_parsed", "rows_duplicate"])
        self._tx(up, self.bank, dt=datetime(2026, 7, 10, 14, 38))
        r = self.client.get(reverse("bank_mutations"), {"upload": up.id})
        self.assertContains(r, "650")                      # jumlah duplikat disebut
        self.assertContains(r, "duplikat")                 # penjelasan tampil
        self.assertContains(r, "sudah tercatat")           # ...di file lebih awal

    def test_tanpa_duplikat_tidak_ada_banner(self):
        up = self._up(self.bank, name="bersih.csv")
        up.rows_parsed = 1
        up.save(update_fields=["rows_parsed"])
        self._tx(up, self.bank)
        r = self.client.get(reverse("bank_mutations"), {"upload": up.id})
        self.assertNotContains(r, "sudah tercatat")


class MutasiBankFileUtuhTests(MutasiBankBase):
    """Filter per-file = ISI FILE UTUH, bukan hanya baris yang diatribusikan.

    File rolling: baris tumpang-tindih tercatat di upload TERDAHULU (dedup),
    tapi ingest me-link baris itu ke upload barunya (duplicate_transactions).
    Saat file dipilih, view menggabungkan keduanya — kasus nyata LBS 12/07:
    file DP BRI 13 baris hanya tampil 1 baris -> user mengira "gak kebaca full".
    """

    def setUp(self):
        super().setUp()
        self.up1 = self._up(self.bank, name="11_07_bri.csv")
        self.dulu = self._tx(self.up1, self.bank, counterparty="ROW-DULU",
                             dt=datetime(2026, 7, 12, 0, 10))
        self.lain = self._tx(self.up1, self.bank, counterparty="ROW-LAIN-BUKAN-ISI",
                             dt=datetime(2026, 7, 11, 9, 0))
        self.up2 = self._up(self.bank, name="12_07_bri.csv")
        self.up2.rows_parsed, self.up2.rows_duplicate = 1, 1
        self.up2.save(update_fields=["rows_parsed", "rows_duplicate"])
        self.baru = self._tx(self.up2, self.bank, counterparty="ROW-BARU",
                             dt=datetime(2026, 7, 12, 22, 16))
        self.up2.duplicate_transactions.add(self.dulu)

    def test_filter_file_tampilkan_isi_utuh_urut_waktu(self):
        r = self.client.get(reverse("bank_mutations"), {"upload": self.up2.id})
        html = r.content.decode()
        self.assertContains(r, "ROW-DULU")                 # baris duplikat ikut tampil
        self.assertContains(r, "ROW-BARU")
        self.assertNotContains(r, "ROW-LAIN-BUKAN-ISI")    # baris file lain yg BUKAN isi file ini
        self.assertLess(html.index("ROW-DULU"), html.index("ROW-BARU"))  # kronologis

    def test_banner_info_dan_penanda_file_asal(self):
        r = self.client.get(reverse("bank_mutations"), {"upload": self.up2.id})
        self.assertContains(r, "utuh")                     # banner: isi file ditampilkan utuh
        self.assertContains(r, "msg info")
        self.assertNotContains(r, "msg warning")
        self.assertContains(r, "Tercatat lewat file: 11_07_bri.csv")  # tooltip baris duplikat

    def test_file_lama_tanpa_link_fallback_banner_lama(self):
        """Upload sebelum fitur ini (ada rows_duplicate, tanpa link) tetap jujur:
        tampil baris atribusi saja + banner peringatan lama."""
        self.up2.duplicate_transactions.clear()
        r = self.client.get(reverse("bank_mutations"), {"upload": self.up2.id})
        self.assertContains(r, "ROW-BARU")
        self.assertNotContains(r, "ROW-DULU")
        self.assertContains(r, "msg warning")
        self.assertContains(r, "sudah tercatat")

    def test_dropdown_jumlah_dan_rentang_gabungan(self):
        r = self.client.get(reverse("bank_mutations"))
        u = next(x for x in r.context["uploads"] if x.id == self.up2.id)
        self.assertEqual(u.n_rows_file, 2)                          # 1 baru + 1 link
        self.assertEqual(u.cover_lo, datetime(2026, 7, 12, 0, 10))  # rentang mencakup baris link
        self.assertEqual(u.cover_hi, datetime(2026, 7, 12, 22, 16))

    def test_filter_flow_dan_tanggal_tetap_berlaku(self):
        wd_dulu = self._tx(self.up1, self.bank, jenis="wd", counterparty="ROW-WD-DULU",
                           amount="-7000", dt=datetime(2026, 7, 12, 6, 58))
        self.up2.duplicate_transactions.add(wd_dulu)
        r = self.client.get(reverse("bank_mutations"), {"upload": self.up2.id, "flow": "depo"})
        self.assertContains(r, "ROW-DULU")
        self.assertNotContains(r, "ROW-WD-DULU")           # flow filter tetap meng-AND
