"""Test Task 2: halaman Transaksi — badge sumber spesifik (BCA/BRI/NXPAY/...),
tombol filter per-bank, dan Ticket/Username/Nama Lengkap dari hasil rekonsiliasi."""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ToleranceProfile
from sources.models import Account, SourceType, Toko, Upload
from transactions.models import Transaction, provider_from_filename, specific_source_label

_seq = iter(range(1, 10_000))


def mk_tx(upload, st, toko, **kw):
    defaults = dict(
        jenis="depo",
        amount=Decimal("50000"),
        money_delta=Decimal("50000"),
        occurred_at=datetime(2026, 6, 27, 10, 0),
        row_hash=f"txp-{next(_seq)}",
    )
    defaults.update(kw)
    return Transaction.objects.create(upload=upload, source_type=st, toko=toko, **defaults)


class DerivasiLabelSumberTests(TestCase):
    """Unit: turunkan label spesifik dari data tersimpan (bukan tebakan)."""

    def test_token_bank_dari_nama_file_asli(self):
        cases = [
            ("27 JUN 2026 DP BCA IRFAN RUKMANA.pdf", "BCA"),
            ("27 JUN 2026 DP BRI MARGANI.csv", "BRI"),
            ("27_JUNI_2026_WD_MANDIRI_SITINURULWIRDAH.xlsx", "MANDIRI"),
            ("27_JUNI_2026_WD_BCA_HENDI.pdf", "BCA"),
            ("MUTASI DP NXPAY OKE25 27-06.xlsx", "NXPAY"),
            ("MUTASI DP QR FLYER OKE25 27-06.xlsx", "QR FLYER"),
            # varian MUL 17-07: "QRIS FLYER" (bukan "QR FLYER") — dulu jatuh ke
            # "QRIS" anonim sehingga tampak "tidak terbaca" di Rincian Rekening
            ("17-07-2026 MUL DP QRIS FLYER.xlsx", "QR FLYER"),
            ("mutasi_random_27-06.xlsx", ""),
        ]
        for name, expected in cases:
            self.assertEqual(provider_from_filename(name), expected, name)

    def test_panel_bracket_tetap_label_generik(self):
        self.assertEqual(specific_source_label("panel"), "Panel")
        self.assertEqual(specific_source_label("bracket"), "Bracket")

    def test_fallback_bank_bila_tidak_ada_info(self):
        up = Upload(original_name="mutasi_random.xlsx", provider="")
        self.assertEqual(specific_source_label("bank", upload=up), "Bank")


class TransaksiPageBase(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.gateway = SourceType.objects.get_or_create(key="gateway", defaults={"name": "Gateway"})[0]
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def mk_upload(self, st, **kw):
        return Upload.objects.create(source_type=st, toko=self.lbs, **kw)


class BadgeSumberSpesifikTests(TransaksiPageBase):
    def test_badge_bank_dari_nama_file(self):
        up = self.mk_upload(self.bank, original_name="27_JUNI_2026_WD_BCA_HENDI.pdf")
        mk_tx(up, self.bank, self.lbs, counterparty="HENDI GUNAWAN")
        r = self.client.get(reverse("transactions"))
        self.assertContains(r, "BCA")
        self.assertNotContains(r, '<span class="badge src">bank</span>')

    def test_badge_gateway_qr_flyer(self):
        up = self.mk_upload(self.gateway, original_name="MUTASI DP QR FLYER OKE25 27-06.xlsx")
        mk_tx(up, self.gateway, self.lbs)
        r = self.client.get(reverse("transactions"))
        self.assertContains(r, "QR FLYER")

    def test_account_provider_menang_atas_nama_file(self):
        acc = Account.objects.create(kind="bank", provider="BRI", name="BRI MARGANI", toko=self.lbs)
        up = self.mk_upload(self.bank, account=acc, original_name="27_JUNI_2026_WD_BCA_HENDI.pdf")
        mk_tx(up, self.bank, self.lbs, account=acc)
        r = self.client.get(reverse("transactions"))
        self.assertContains(r, '<span class="badge src">BRI</span>', html=False)

    def test_badge_panel_tetap_panel(self):
        up = self.mk_upload(self.panel, original_name="HISTORI DP PANEL OKE25 27-06.xlsx")
        mk_tx(up, self.panel, self.lbs, username="budi88x")
        r = self.client.get(reverse("transactions"))
        self.assertContains(r, '<span class="badge src">Panel</span>', html=False)

    def test_fallback_bank_bila_nama_file_tak_dikenal(self):
        up = self.mk_upload(self.bank, original_name="mutasi_random.xlsx")
        mk_tx(up, self.bank, self.lbs)
        r = self.client.get(reverse("transactions"))
        self.assertContains(r, '<span class="badge src">Bank</span>', html=False)


class FilterPerBankTests(TransaksiPageBase):
    def setUp(self):
        super().setUp()
        up_bca = self.mk_upload(self.bank, original_name="27_JUNI_2026_WD_BCA_HENDI.pdf")
        up_bri = self.mk_upload(self.bank, original_name="27 JUN 2026 DP BRI MARGANI.csv")
        mk_tx(up_bca, self.bank, self.lbs, counterparty="HENDI GUNAWAN")
        mk_tx(up_bri, self.bank, self.lbs, counterparty="MARGANI PUTRA")

    def test_tombol_muncul_hanya_saat_source_bank(self):
        r = self.client.get(reverse("transactions"), {"source": "bank"})
        self.assertContains(r, "bank=BCA")
        self.assertContains(r, "bank=BRI")
        self.assertContains(r, "Semua")
        r2 = self.client.get(reverse("transactions"))
        self.assertNotContains(r2, "bank=BCA")

    def test_filter_bank_bekerja(self):
        r = self.client.get(reverse("transactions"), {"source": "bank", "bank": "BCA"})
        self.assertContains(r, "HENDI GUNAWAN")
        self.assertNotContains(r, "MARGANI PUTRA")

    def test_filter_bank_diabaikan_untuk_sumber_lain(self):
        up = self.mk_upload(self.panel)
        mk_tx(up, self.panel, self.lbs, username="budi88x")
        r = self.client.get(reverse("transactions"), {"source": "panel", "bank": "BCA"})
        self.assertContains(r, "budi88x")
        self.assertEqual(r.context["bank"], "")


class TicketUsernameNamaLengkapTests(TransaksiPageBase):
    def setUp(self):
        super().setUp()
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.up_panel = self.mk_upload(self.panel, original_name="HISTORI DP PANEL.xlsx")
        self.up_bank = self.mk_upload(self.bank, original_name="27_JUNI_2026_WD_BCA_HENDI.pdf")
        self.tx_panel = mk_tx(
            self.up_panel, self.panel, self.lbs,
            ticket_no="TKT778899", username="budi88x", counterparty="BUDI SANTOSO",
        )
        self.tx_bank = mk_tx(
            self.up_bank, self.bank, self.lbs, jenis="lainnya",
            counterparty="BD SANTOSO RAW",
        )
        self.run = MatchRun.objects.create(relation="panel_bank", tolerance=self.tol)

    def match(self, left, right, bucket="cocok", score=100, run=None):
        return MatchResult.objects.create(
            run=run or self.run, bucket=bucket, left=left, right=right, score=score
        )

    def test_baris_bank_tampilkan_ticket_username_nama_panel(self):
        self.match(self.tx_panel, self.tx_bank)
        r = self.client.get(reverse("transactions"), {"source": "bank"})
        self.assertContains(r, "TKT778899")
        self.assertContains(r, "budi88x")
        self.assertContains(r, "BUDI SANTOSO")
        self.assertContains(r, "≈")  # penanda nilai turunan dari match

    def test_bank_tanpa_match_tampil_strip(self):
        r = self.client.get(reverse("transactions"), {"source": "bank"})
        self.assertNotContains(r, "≈")
        self.assertNotContains(r, "TKT778899")

    def test_panel_tampilkan_nilai_sendiri_tanpa_penanda(self):
        self.match(self.tx_panel, self.tx_bank)
        r = self.client.get(reverse("transactions"), {"source": "panel"})
        self.assertContains(r, "TKT778899")
        self.assertContains(r, "budi88x")
        self.assertContains(r, "BUDI SANTOSO")
        self.assertNotContains(r, "≈")

    def test_pilih_match_terbaik_cocok_menang(self):
        panel2 = mk_tx(
            self.up_panel, self.panel, self.lbs,
            ticket_no="D9999999", username="lain99", counterparty="ORANG LAIN",
        )
        self.match(panel2, self.tx_bank, bucket="perlu_tinjau", score=99)
        self.match(self.tx_panel, self.tx_bank, bucket="cocok", score=80)
        r = self.client.get(reverse("transactions"), {"source": "bank"})
        self.assertContains(r, "TKT778899")
        self.assertNotContains(r, "D9999999")

    def test_tidak_cocok_manual_tidak_dipakai(self):
        self.match(self.tx_panel, self.tx_bank, bucket="tidak_cocok", score=10)
        r = self.client.get(reverse("transactions"), {"source": "bank"})
        self.assertNotContains(r, "TKT778899")
        self.assertNotContains(r, "≈")

    def test_nilai_sendiri_menang_atas_match(self):
        self.tx_bank.ticket_no = "BK-777"
        self.tx_bank.save(update_fields=["ticket_no"])
        self.match(self.tx_panel, self.tx_bank)
        r = self.client.get(reverse("transactions"), {"source": "bank"})
        self.assertContains(r, "BK-777")
        self.assertNotContains(r, "≈ TKT778899")

    def test_kolom_nama_lengkap_ada(self):
        r = self.client.get(reverse("transactions"))
        self.assertContains(r, "Nama Lengkap")
