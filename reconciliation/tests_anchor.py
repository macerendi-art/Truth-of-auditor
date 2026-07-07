"""Aturan anchor UTAMA di matcher uang (Panel/Bracket ↔ Bank).

Nominal + tanggal hanya anchor PENDUKUNG: wajib (memblokir kandidat) tapi tidak
pernah cukup untuk memasangkan. Anchor UTAMA = identitas unik (nama lengkap,
no. HP/VA, no. rekening, username/ticket). Regresi kasus prod: WD "Samsul maarif"
300rb TIDAK boleh dipasangkan ke mutasi "ARI PRIHARTANTO" 300rb hanya karena
nominal+tanggal sama (skor nama 36) — biarkan menunggu settlement H+1.
"""
from datetime import datetime
from decimal import Decimal

from django.test import TestCase

from reconciliation.engine import NAME_REVIEW_FLOOR, NO_MONEY_DETAIL, run_match
from reconciliation.models import MatchResult, ToleranceProfile
from sources.models import SourceType, Upload
from transactions.models import Transaction


class AnchorUtamaMoneyMatcherTests(TestCase):
    def setUp(self):
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(
            key="bank", defaults={"name": "Bank", "is_money_source": True}
        )[0]
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1, "fuzzy_threshold": 85}
        )[0]
        self.up = Upload.objects.create(source_type=self.panel)
        self.upb = Upload.objects.create(source_type=self.bank)

    def _panel(self, jenis, money, name, rh, dt, **kw):
        return Transaction.objects.create(
            upload=self.up, source_type=self.panel, jenis=jenis,
            amount=Decimal(abs(money)), money_delta=Decimal(money),
            counterparty=name, occurred_at=dt, row_hash=rh, **kw,
        )

    def _bank(self, jenis, money, name, rh, dt, **kw):
        return Transaction.objects.create(
            upload=self.upb, source_type=self.bank, jenis=jenis,
            amount=Decimal(abs(money)), money_delta=Decimal(money),
            counterparty=name, occurred_at=dt, row_hash=rh, **kw,
        )

    def test_wd_nama_beda_tidak_dipasangkan(self):
        # Kasus prod Run #41: nominal+tanggal sama, nama skor 36 → JANGAN pasangkan.
        p = self._panel("wd", -300000, "Samsul maarif", "p1",
                        datetime(2026, 7, 1, 23, 22))
        b = self._bank("wd", -300000, "ARI PRIHARTANTO", "b1",
                       datetime(2026, 7, 1, 0, 0))
        run = run_match("panel_bank", self.tol)
        r = MatchResult.objects.get(run=run, left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.TIDAK)
        self.assertEqual(r.reason_code, "no_money")
        self.assertIsNone(r.right)
        # Baris mutasi milik player lain TIDAK ikut terpakai (tak ada hasil right=b).
        self.assertFalse(MatchResult.objects.filter(run=run, right=b).exists())

    def test_nama_mirip_band_jadi_perlu_tinjau(self):
        # Skor 60–84 (nama kepotong bank): "M ADITYA FIRMANSYA" vs full name.
        p = self._panel("depo", 150000, "Muhammad Aditya Firmansyah", "p1",
                        datetime(2026, 7, 1, 9, 0))
        self._bank("depo", 150000, "M ADITYA FIRMANSYA", "b1",
                   datetime(2026, 7, 1, 10, 0))
        run = run_match("panel_bank", self.tol)
        r = MatchResult.objects.get(run=run, left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.TINJAU)
        self.assertEqual(r.reason_code, "name_partial")
        self.assertIsNotNone(r.right)

    def test_band_bawah_dan_skor_penuh_batasnya(self):
        # Skor persis di floor tetap tinjau; di bawah floor → no_money.
        self.assertEqual(NAME_REVIEW_FLOOR, 60)

    def test_assignment_global_skor_tertinggi_menang(self):
        # Dua panel berebut satu mutasi; keduanya di band → skor tertinggi menang,
        # yang kalah jatuh ke no_money (bukan dipaksakan ke mutasi yang sama).
        p_hi = self._panel("depo", 150000, "Muhammad Aditya Firmansyah", "phi",
                           datetime(2026, 7, 1, 9, 0))   # skor ~82
        p_lo = self._panel("depo", 150000, "Ade Firmansyah", "plo",
                           datetime(2026, 7, 1, 9, 5))    # skor ~75
        b = self._bank("depo", 150000, "M ADITYA FIRMANSYA", "b1",
                       datetime(2026, 7, 1, 10, 0))
        run = run_match("panel_bank", self.tol)
        r_hi = MatchResult.objects.get(run=run, left=p_hi)
        r_lo = MatchResult.objects.get(run=run, left=p_lo)
        self.assertEqual(r_hi.bucket, MatchResult.Bucket.TINJAU)
        self.assertEqual(r_hi.right, b)
        self.assertEqual(r_lo.bucket, MatchResult.Bucket.TIDAK)
        self.assertEqual(r_lo.reason_code, "no_money")
        self.assertIsNone(r_lo.right)

    def test_no_money_detail_bedakan_ada_kandidat(self):
        # Ada kandidat nominal+tanggal tapi identitas <60 → detail beri sinyal tunggu.
        p1 = self._panel("wd", -300000, "Samsul maarif", "p1",
                         datetime(2026, 7, 1, 23, 22))
        self._bank("wd", -300000, "ARI PRIHARTANTO", "b1",
                   datetime(2026, 7, 1, 0, 0))
        # Tanpa kandidat nominal sama sekali → detail baku NO_MONEY_DETAIL.
        p2 = self._panel("wd", -777000, "Joko Widodo", "p2",
                         datetime(2026, 7, 1, 20, 0))
        run = run_match("panel_bank", self.tol)
        r1 = MatchResult.objects.get(run=run, left=p1)
        r2 = MatchResult.objects.get(run=run, left=p2)
        self.assertEqual(r1.reason_code, "no_money")
        self.assertIn("menunggu settlement", r1.reason_detail.lower())
        self.assertEqual(r2.reason_detail, NO_MONEY_DETAIL)

    def test_weak_name_tidak_diproduksi(self):
        # Reason code lama 'weak_name' tak boleh muncul lagi.
        self._panel("wd", -300000, "Samsul maarif", "p1",
                    datetime(2026, 7, 1, 23, 22))
        self._bank("wd", -300000, "ARI PRIHARTANTO", "b1",
                   datetime(2026, 7, 1, 0, 0))
        run = run_match("panel_bank", self.tol)
        self.assertFalse(
            MatchResult.objects.filter(run=run, reason_code="weak_name").exists()
        )
