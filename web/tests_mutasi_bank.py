"""Sub-menu Mutasi Bank: mutasi bank + gateway QRIS urut sesuai file asli,
lookup HP -> nama player dari panel, kolom saldo bila tersedia."""
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
            amount="10000", balance=None, dt=datetime(2026, 6, 27, 10, 0)):
        return Transaction.objects.create(
            upload=up, source_type=st, toko=toko or self.lbs, jenis=jenis,
            amount=Decimal(amount), money_delta=Decimal(amount),
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

    def test_filter_tanggal(self):
        r = self.client.get(reverse("bank_mutations"), {"from": "2026-06-28"})
        self.assertContains(r, "WD-BANK")
        self.assertNotContains(r, "DP-BANK")


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


class MutasiBankSaldoTests(MutasiBankBase):
    def test_saldo_tampil_dan_none_aman(self):
        upb = self._up(self.bank, "bca.csv")
        self._tx(upb, self.bank, counterparty="ADA-SALDO", balance="4964637.00")
        self._tx(upb, self.bank, counterparty="TANPA-SALDO", balance=None)
        r = self.client.get(reverse("bank_mutations"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "4.964.637")  # locale id
        self.assertContains(r, "TANPA-SALDO")
