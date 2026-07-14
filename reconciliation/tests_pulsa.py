"""DP pulsa (K5): uangnya TIDAK lewat bank/gateway — keluar dari jalur fuzzy.

Deposit pulsa (Bank Title = provider seluler '(AUTO)') dikonversi terpisah;
mutasinya tak akan pernah muncul di bank/gateway. Tanpa pass khusus, baris ini:
(a) dipasangkan fuzzy ke uang orang lain, atau (b) jadi no_money yang carried
"menunggu settlement" SELAMANYA — mencemari pending_settlement_count. Solusi:
pass 0 -> perlu_tinjau `pulsa_manual` (cocokkan dgn laporan konversi pulsa),
tanpa mengambil uang siapa pun. Hanya DP; WD tak disapu.
"""
from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase

from reconciliation.engine import pending_settlement_count, run_batch, run_match
from reconciliation.models import MatchResult, MatchRun, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

D = Decimal


def _st(key):
    return SourceType.objects.get_or_create(key=key, defaults={"name": key.title()})[0]


class PulsaManualTests(TestCase):
    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.panel, self.bank = _st("panel"), _st("bank")
        self.up_panel = Upload.objects.create(
            source_type=self.panel, toko=self.toko, original_name="HISTORI DP PANEL.xlsx"
        )
        self.up_bank = Upload.objects.create(
            source_type=self.bank, toko=self.toko, original_name="27_DP_BCA_HENDI.csv"
        )
        self._n = 0

    def tx(self, st, up, jenis, amount, md, dt, *, ticket="", user="", cp="",
           bank_title="", raw=None):
        self._n += 1
        return Transaction.objects.create(
            upload=up, source_type=st, toko=self.toko, jenis=jenis,
            amount=D(amount), money_delta=D(md), occurred_at=dt,
            ticket_no=ticket, username=user, counterparty=cp,
            bank_title=bank_title, raw=raw or {}, row_hash=f"h{self._n}",
        )

    def match(self):
        return run_match(MatchRun.Relation.PANEL_BANK, self.tol, toko=self.toko)

    def test_dp_pulsa_jadi_tinjau_tanpa_mengambil_uang(self):
        # Nama pemain kebetulan sama dengan pengirim mutasi bank senominal —
        # fuzzy akan salah sanding. Pass pulsa harus menang lebih dulu dan uang
        # bank tetap bebas untuk pemiliknya.
        p_pulsa = self.tx(self.panel, self.up_panel, "depo", "50000", "50000",
                          datetime(2026, 6, 27, 10), ticket="D701", user="agus1",
                          cp="AGUS SALIM", bank_title="TELKOMSEL (AUTO)",
                          raw={"Bank Title": "Telkomsel (AUTO)|AGUS SALIM|0812"})
        b = self.tx(self.bank, self.up_bank, "depo", "50000", "50000",
                    datetime(2026, 6, 27, 11), cp="AGUS SALIM")
        self.match()
        r = MatchResult.objects.get(left=p_pulsa)
        self.assertEqual(r.bucket, MatchResult.Bucket.TINJAU)
        self.assertEqual(r.reason_code, "pulsa_manual")
        self.assertIsNone(r.right_id)
        self.assertIn("pulsa", r.reason_detail.lower())
        # Uang bank tidak dikonsumsi hasil pulsa (tetap tanpa pasangan).
        self.assertFalse(MatchResult.objects.filter(right=b).exists())

    def test_wd_pulsa_tidak_disapu(self):
        # Hanya DP: WD tak pernah dibayar pakai pulsa — jalur normal berlaku.
        p = self.tx(self.panel, self.up_panel, "wd", "50000", "-50000",
                    datetime(2026, 6, 27, 10), ticket="W702", user="budi2",
                    cp="BUDI", bank_title="TELKOMSEL (AUTO)")
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.reason_code, "no_money")

    def test_bank_title_biasa_tak_kena(self):
        p = self.tx(self.panel, self.up_panel, "depo", "50000", "50000",
                    datetime(2026, 6, 27, 10), ticket="D703", user="cici3",
                    cp="CICI", bank_title="BCA")
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.reason_code, "no_money")

    def test_fallback_raw_bank_title(self):
        # Baris lama (pra-backfill) tanpa field bank_title: baca dari raw.
        p = self.tx(self.panel, self.up_panel, "depo", "25000", "25000",
                    datetime(2026, 6, 27, 10), ticket="D704", user="didi4",
                    cp="DIDI", raw={"Bank Title": "XL (AUTO)|DIDI|0817"})
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.reason_code, "pulsa_manual")

    def test_dp_pulsa_tidak_carried_menunggu_settlement(self):
        # Inti K5 di arsitektur carry-over: tanpa pass pulsa baris ini jadi
        # no_money yang menunggu settlement SELAMANYA. pulsa_manual terminal:
        # dikonsumsi batch harian, pending settlement = 0.
        p = self.tx(self.panel, self.up_panel, "depo", "50000", "50000",
                    datetime(2026, 6, 27, 10), ticket="D705", user="eka5",
                    cp="EKA", bank_title="TELKOMSEL (AUTO)")
        batch = run_batch(
            self.toko, self.tol,
            date_from=date(2026, 6, 27), date_to=date(2026, 6, 27),
            recon_date=date(2026, 6, 27),
        )
        p.refresh_from_db()
        self.assertEqual(p.consumed_by_batch_id, batch.id)
        self.assertEqual(pending_settlement_count(self.toko), 0)
        self.assertEqual(batch.summary["buckets"]["perlu_tinjau"], 1)
