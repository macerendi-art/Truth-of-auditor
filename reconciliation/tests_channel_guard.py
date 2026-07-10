"""Kunci kanal gateway: uang gateway X tidak boleh dipasangkan pass identitas
dengan baris panel yang bank_title-nya menunjuk gateway Y yang dikenal berbeda.

Kasus nyata M77 09-07: pemain deposit nominal sama via RPay DAN NXPay di hari
yang sama; file uang NXPay belum diupload -> uang RPay "dicuri" baris NXPAY
(21 salah-jodoh). Panel sudah mendeklarasikan kanalnya (bank_title "QRISRPAY" /
"NXPAY DEPOSIT QR") — deklarasi itu harus dihormati. Fail-open: kanal tak
dikenal/kosong = tanpa larangan (perilaku lama).
"""
from datetime import datetime
from decimal import Decimal

from django.test import TestCase

from reconciliation.engine import run_match
from reconciliation.models import MatchResult, ToleranceProfile
from sources.models import SourceType, Upload
from transactions.models import Transaction


class ChannelGuardTests(TestCase):
    def setUp(self):
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.gw = SourceType.objects.get_or_create(
            key="gateway", defaults={"name": "Gateway", "is_money_source": True}
        )[0]
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1, "fuzzy_threshold": 85}
        )[0]
        self.up = Upload.objects.create(source_type=self.panel)
        self.upg = Upload.objects.create(source_type=self.gw, original_name="dp rpay.csv")
        self.dt = datetime(2026, 7, 9, 23, 58)

    def _panel(self, rh, username, bank_title, amount=25000):
        return Transaction.objects.create(
            upload=self.up, source_type=self.panel, jenis="depo",
            amount=Decimal(amount), money_delta=Decimal(amount),
            username=username, bank_title=bank_title,
            occurred_at=self.dt, row_hash=rh,
        )

    def _rpay(self, rh, username, amount=25000):
        return Transaction.objects.create(
            upload=self.upg, source_type=self.gw, jenis="depo",
            amount=Decimal(amount), money_delta=Decimal(amount),
            username=username, description="RPay 619180666745",
            occurred_at=self.dt, row_hash=rh,
        )

    def test_uang_rpay_tidak_menyedot_baris_nxpay(self):
        # Panel menunjuk NXPAY -> uang RPay DILARANG melamar, biar menunggu file NXPay.
        p = self._panel("p1", "budi99", "NXPAY DEPOSIT QR")
        b = self._rpay("g1", "budi99")
        run = run_match("panel_bank", self.tol)
        r = MatchResult.objects.get(run=run, left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.TIDAK)
        self.assertEqual(r.reason_code, "no_money")
        self.assertFalse(MatchResult.objects.filter(run=run, right=b).exists())

    def test_kanal_sama_jodoh_username(self):
        p = self._panel("p1", "budi99", "QRISRPAY")
        b = self._rpay("g1", "budi99")
        run = run_match("panel_bank", self.tol)
        r = MatchResult.objects.get(run=run, left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.right_id, b.id)

    def test_kembar_dua_kanal_uang_jatuh_ke_qrisrpay(self):
        # Deposit kembar (username+nominal+tanggal sama) beda kanal:
        # satu-satunya uang RPay harus jatuh ke baris QRISRPAY, bukan NXPAY.
        p_nx = self._panel("p1", "budi99", "NXPAY DEPOSIT QR")
        p_rp = self._panel("p2", "budi99", "QRISRPAY")
        b = self._rpay("g1", "budi99")
        run = run_match("panel_bank", self.tol)
        self.assertEqual(MatchResult.objects.get(run=run, left=p_rp).right_id, b.id)
        r_nx = MatchResult.objects.get(run=run, left=p_nx)
        self.assertEqual(r_nx.reason_code, "no_money")

    def test_fail_open_bank_title_kosong(self):
        # Tanpa deklarasi kanal -> perilaku lama (username exact tetap jodoh).
        p = self._panel("p1", "budi99", "")
        b = self._rpay("g1", "budi99")
        run = run_match("panel_bank", self.tol)
        self.assertEqual(MatchResult.objects.get(run=run, left=p).right_id, b.id)

    def test_fail_open_uang_gateway_tanpa_kanal_dikenal(self):
        # Gateway yang description-nya tak memuat token kanal (mis. UNO "QRIS COR ...")
        # tidak pernah diblokir — meski panel menunjuk kanal lain.
        p = self._panel("p1", "budi99", "QRISRPAY")
        b = Transaction.objects.create(
            upload=self.upg, source_type=self.gw, jenis="depo",
            amount=Decimal(25000), money_delta=Decimal(25000),
            username="budi99", description="QRIS COR 1pysbjp67783",
            occurred_at=self.dt, row_hash="g1",
        )
        run = run_match("panel_bank", self.tol)
        self.assertEqual(MatchResult.objects.get(run=run, left=p).right_id, b.id)
