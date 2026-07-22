"""Fitur K2 — Deposit "kode unik" jadi COCOK di _MoneyMatcher.

Aturan anchor TIDAK dilonggarkan: cabang ini hanya mereklasifikasi bucket
untuk pasangan yang SUDAH ber-anchor ticket/reference EXACT (pass 0 / 0b).
Kode unik = ekor kecil (<=999) yang ditambahkan pemain ke DEPOSIT agar
mudah dikenali — bank SELALU lebih besar dari panel. Underpay (bank<panel),
selisih >999, dan semua WD TETAP TINJAU seperti perilaku lama.
"""
from datetime import datetime
from decimal import Decimal

from django.test import TestCase

from reconciliation.engine import run_match
from reconciliation.models import MatchResult, MatchRun, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

D = Decimal


def _st(key):
    return SourceType.objects.get_or_create(key=key, defaults={"name": key.title()})[0]


class _Base(TestCase):
    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.panel, self.gw = _st("panel"), _st("gateway")
        self.up_panel = Upload.objects.create(
            source_type=self.panel, toko=self.toko, original_name="HISTORI DP PANEL.xlsx"
        )
        self.up_qr = Upload.objects.create(
            source_type=self.gw, toko=self.toko, original_name="MUTASI DP QR FLYER.xlsx"
        )
        self._n = 0

    def tx(self, st, up, jenis, amount, md, dt, *, ticket="", user="", cp="", ref="", raw=None):
        self._n += 1
        return Transaction.objects.create(
            upload=up, source_type=st, toko=self.toko, jenis=jenis,
            amount=D(amount), money_delta=D(md), occurred_at=dt,
            ticket_no=ticket, username=user, counterparty=cp, reference=ref,
            raw=raw or {}, row_hash=f"h{self._n}",
        )

    def match(self):
        return run_match(MatchRun.Relation.PANEL_BANK, self.tol, toko=self.toko)


class KodeUnikTicketTests(_Base):
    def _pair(self, panel_md, gw_md, ticket="D700"):
        p = self.tx(self.panel, self.up_panel, "depo", str(abs(int(panel_md))), panel_md,
                    datetime(2026, 6, 27, 10), ticket=ticket, user="uu", cp="U U")
        g = self.tx(self.gw, self.up_qr, "depo", str(abs(int(gw_md))), gw_md,
                    datetime(2026, 6, 27, 10, 5), ticket=ticket, user="uu", cp="QRIS")
        self.match()
        return p, g, MatchResult.objects.get(left=p)

    def test_selisih_250_jadi_cocok_kode_unik(self):
        p, g, r = self._pair("50000", "50250")
        self.assertEqual(r.right_id, g.id)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.reason_code, "kode_unik")
        self.assertEqual(r.reason_detail, "kode unik +250")

    def test_selisih_9_jadi_cocok(self):
        _, _, r = self._pair("50000", "50009", ticket="D701")
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.reason_code, "kode_unik")
        self.assertEqual(r.reason_detail, "kode unik +9")

    def test_selisih_999_batas_masih_cocok(self):
        _, _, r = self._pair("50000", "50999", ticket="D702")
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.reason_code, "kode_unik")

    def test_selisih_1000_tetap_tinjau_ticket_amount(self):
        _, _, r = self._pair("50000", "51000", ticket="D703")
        self.assertEqual(r.bucket, MatchResult.Bucket.TINJAU)
        self.assertEqual(r.reason_code, "ticket_amount")

    def test_bank_kurang_dari_panel_tetap_tinjau(self):
        # underpay (gateway 50.000 < panel 50.250) BUKAN kode unik.
        _, _, r = self._pair("50250", "50000", ticket="D704")
        self.assertEqual(r.bucket, MatchResult.Bucket.TINJAU)
        self.assertEqual(r.reason_code, "ticket_amount")

    def test_wd_selisih_250_tidak_terpengaruh(self):
        # WD (money_delta<0) TIDAK lewat cabang kode unik → tetap ticket_amount.
        p = self.tx(self.panel, self.up_panel, "wd", "50000", "-50000",
                    datetime(2026, 6, 27, 10), ticket="W705", user="uu", cp="U U")
        g = self.tx(self.gw, self.up_qr, "wd", "50250", "-50250",
                    datetime(2026, 6, 27, 10, 5), ticket="W705", user="uu", cp="QRIS")
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.right_id, g.id)
        self.assertEqual(r.bucket, MatchResult.Bucket.TINJAU)
        self.assertEqual(r.reason_code, "ticket_amount")


class KodeUnikReferenceTests(_Base):
    def test_reference_selisih_250_jadi_cocok_kode_unik(self):
        uuid = "11111111-2222-3333-4444-555555555555"
        p = self.tx(self.panel, self.up_panel, "depo", "100000", "100000",
                    datetime(2026, 6, 27, 10), user="qq", cp="Q Q", ref=uuid)
        g = self.tx(self.gw, self.up_qr, "depo", "100250", "100250",
                    datetime(2026, 6, 27, 10, 5), user="qq", cp="QRIS", ref=uuid)
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.right_id, g.id)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.reason_code, "kode_unik")
        self.assertEqual(r.reason_detail, "kode unik +250")
