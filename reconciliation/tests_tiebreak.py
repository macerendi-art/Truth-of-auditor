"""Seleksi seri deterministik di pass 2 (near-miss identitas kuat).

Pass 1 & 3 sudah menyortir global (skor, rute, tanggal terdekat) — tapi pass 2
memilih kandidat pertama yang lolos threshold dalam urutan pool yang ARBITRARY
di Postgres (query tanpa ORDER BY). Pada skor seri, pilihan harus jatuh ke:
selisih nominal TERKECIL -> tanggal TERDEKAT ke panel -> id terkecil — bukan
kebetulan urutan queryset.
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


class Pass2TieBreakTests(TestCase):
    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.panel, self.bank = _st("panel"), _st("bank")
        self.up_panel = Upload.objects.create(
            source_type=self.panel, toko=self.toko, original_name="HISTORI WD PANEL.xlsx"
        )
        self.up_bank = Upload.objects.create(
            source_type=self.bank, toko=self.toko, original_name="27_WD_BCA_HENDI.csv"
        )
        self._n = 0

    def tx(self, st, up, jenis, amount, md, dt, *, ticket="", user="", cp=""):
        self._n += 1
        return Transaction.objects.create(
            upload=up, source_type=st, toko=self.toko, jenis=jenis,
            amount=D(amount), money_delta=D(md), occurred_at=dt,
            ticket_no=ticket, username=user, counterparty=cp, raw={},
            row_hash=f"h{self._n}",
        )

    def match(self):
        return run_match(MatchRun.Relation.PANEL_BANK, self.tol, toko=self.toko)

    def test_skor_seri_pilih_selisih_nominal_terkecil(self):
        # Dua kandidat fee-diff bernama identik (skor seri). Yang selisihnya
        # 2.000 sengaja dibuat lebih dulu (urutan pool) — yang 500 harus menang.
        p = self.tx(self.panel, self.up_panel, "wd", "100000", "-100000",
                    datetime(2026, 6, 27, 9), ticket="W10", cp="SITI AMINAH")
        self.tx(self.bank, self.up_bank, "wd", "98000", "-98000",
                datetime(2026, 6, 27, 12), cp="SITI AMINAH")
        b_near = self.tx(self.bank, self.up_bank, "wd", "99500", "-99500",
                         datetime(2026, 6, 27, 12), cp="SITI AMINAH")
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.reason_code, "amount_fee")
        self.assertEqual(r.right_id, b_near.id)

    def test_skor_dan_selisih_seri_pilih_tanggal_terdekat(self):
        # Selisih nominal sama persis; kandidat H+1 sengaja dibuat lebih dulu —
        # uang tanggal yang sama dengan panel harus menang.
        p = self.tx(self.panel, self.up_panel, "wd", "100000", "-100000",
                    datetime(2026, 6, 27, 9), ticket="W11", cp="JOKO WIDODO")
        self.tx(self.bank, self.up_bank, "wd", "99000", "-99000",
                datetime(2026, 6, 28, 12), cp="JOKO WIDODO")
        b_sameday = self.tx(self.bank, self.up_bank, "wd", "99000", "-99000",
                            datetime(2026, 6, 27, 12), cp="JOKO WIDODO")
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.reason_code, "amount_fee")
        self.assertEqual(r.right_id, b_sameday.id)

    def test_h_minus_1_pilih_skor_tertinggi(self):
        # Dua kandidat H-1: nama mirip (lolos threshold) dibuat lebih dulu,
        # nama PERSIS setelahnya — skor tertinggi harus menang, bukan yang
        # pertama ditemui.
        p = self.tx(self.panel, self.up_panel, "wd", "50000", "-50000",
                    datetime(2026, 6, 27, 9), ticket="W12", cp="BAMBANG PAMUNGKAS")
        self.tx(self.bank, self.up_bank, "wd", "50000", "-50000",
                datetime(2026, 6, 26, 12), cp="BAMBANG PAMUNGKAZ")
        b_exact = self.tx(self.bank, self.up_bank, "wd", "50000", "-50000",
                          datetime(2026, 6, 26, 13), cp="BAMBANG PAMUNGKAS")
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.reason_code, "date_before")
        self.assertEqual(r.right_id, b_exact.id)
