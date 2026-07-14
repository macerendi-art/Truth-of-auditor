"""Alias historis (K4): sejarah pasangan COCOK mengajari matcher.

Pemain memakai rekening pinjaman BERULANG: deposit hari ini atas nama rekening
yang KEMARIN sudah terbukti milik/dipakai username itu (pasangan cocok lama,
settle terlambat, atau keputusan reviewer). Peta username -> {nama rekening,
nomor tujuan} diturunkan langsung dari MatchResult hidup — tanpa tabel baru;
batch dihapus = buktinya hilang = aliasnya ikut hilang (self-healing).
Kandidat yang cocok peta -> skor min 95, reason `alias_history` di pass 1,
tanpa melonggarkan fuzzy untuk pasangan tanpa sejarah.
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


class AliasHistoryTests(TestCase):
    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.toko2 = Toko.objects.exclude(pk=self.toko.pk).first() or Toko.objects.create(
            key="tk2", name="Toko 2"
        )
        self.panel, self.bank = _st("panel"), _st("bank")
        self.up_panel = Upload.objects.create(
            source_type=self.panel, toko=self.toko, original_name="HISTORI DP PANEL.xlsx"
        )
        self.up_bank = Upload.objects.create(
            source_type=self.bank, toko=self.toko, original_name="27_DP_BCA_HENDI.csv"
        )
        self._n = 0

    def tx(self, st, up, jenis, amount, md, dt, *, ticket="", user="", cp="",
           toko=None, raw=None, consumed=None):
        self._n += 1
        return Transaction.objects.create(
            upload=up, source_type=st, toko=toko or self.toko, jenis=jenis,
            amount=D(amount), money_delta=D(md), occurred_at=dt,
            ticket_no=ticket, username=user, counterparty=cp, raw=raw or {},
            row_hash=f"h{self._n}", consumed_by_batch=consumed,
        )

    def _bukti(self, user, cp_bank, *, reason="amount+date+name",
               bucket=MatchResult.Bucket.COCOK, toko=None, raw_bank=None):
        """Tanam sejarah: pasangan lama user -> rekening bank cp_bank."""
        toko = toko or self.toko
        old_left = self.tx(self.panel, self.up_panel, "depo", "10000", "10000",
                           datetime(2026, 6, 20, 10), ticket=f"D9{self._n}",
                           user=user, cp="NAMA PANEL", toko=toko)
        old_right = self.tx(self.bank, self.up_bank, "depo", "10000", "10000",
                            datetime(2026, 6, 20, 11), cp=cp_bank, toko=toko,
                            raw=raw_bank)
        old_run = MatchRun.objects.create(relation=MatchRun.Relation.PANEL_BANK,
                                          tolerance=self.tol)
        return MatchResult.objects.create(
            run=old_run, bucket=bucket, left=old_left, right=old_right,
            score=90, reason_code=reason,
        )

    def match(self):
        return run_match(MatchRun.Relation.PANEL_BANK, self.tol, toko=self.toko)

    def test_alias_nama_rekening_dari_sejarah(self):
        # Kemarin: agus1 terbukti pakai rekening SITI RAHAYU. Hari ini deposit
        # lagi via rekening yang sama — nama beda total dgn nama panel (skor
        # ~40 < floor), tapi sejarah menaikkannya jadi cocok alias_history.
        self._bukti("agus1", "SITI RAHAYU")
        p = self.tx(self.panel, self.up_panel, "depo", "50000", "50000",
                    datetime(2026, 6, 27, 10), ticket="D801", user="agus1",
                    cp="AGUS SALIM")
        b = self.tx(self.bank, self.up_bank, "depo", "50000", "50000",
                    datetime(2026, 6, 27, 11), cp="SITI RAHAYU")
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.reason_code, "alias_history")
        self.assertEqual(r.right_id, b.id)
        self.assertGreaterEqual(r.score, 95)

    def test_alias_nomor_tujuan_dari_sejarah(self):
        # Bukti lama membawa nomor VA/HP di keterangan; mutasi hari ini memuat
        # nomor yang sama walau nama pengirim kosong.
        self._bukti("budi7", "", raw_bank={"Keterangan": "FTFVA 083822153879 DANA"})
        p = self.tx(self.panel, self.up_panel, "depo", "60000", "60000",
                    datetime(2026, 6, 27, 10), ticket="D802", user="budi7",
                    cp="BUDI SANTOSO")
        b = self.tx(self.bank, self.up_bank, "depo", "60000", "60000",
                    datetime(2026, 6, 27, 11), cp="",
                    raw={"Keterangan": "FTFVA 083822153879 DANA"})
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.reason_code, "alias_history")
        self.assertEqual(r.right_id, b.id)

    def test_keputusan_reviewer_jadi_bukti(self):
        # Reviewer menandai pasangan name_partial jadi cocok (manual_override)
        # -> besok deposit serupa langsung alias_history, tak perlu review ulang.
        self._bukti("cici8", "RENTAL REKENING", reason="manual_override")
        p = self.tx(self.panel, self.up_panel, "depo", "70000", "70000",
                    datetime(2026, 6, 27, 10), ticket="D803", user="cici8",
                    cp="CICI PARAMIDA")
        b = self.tx(self.bank, self.up_bank, "depo", "70000", "70000",
                    datetime(2026, 6, 27, 11), cp="RENTAL REKENING")
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.reason_code, "alias_history")
        self.assertEqual(r.right_id, b.id)

    def test_pasangan_ditolak_bukan_bukti(self):
        # mark_unmatched (bucket TIDAK) = reviewer MENOLAK pasangan — jangan
        # dipakai sebagai alias.
        self._bukti("didi9", "REKENING SALAH", reason="manual_override",
                    bucket=MatchResult.Bucket.TIDAK)
        p = self.tx(self.panel, self.up_panel, "depo", "80000", "80000",
                    datetime(2026, 6, 27, 10), ticket="D804", user="didi9",
                    cp="DIDI KEMPOT")
        self.tx(self.bank, self.up_bank, "depo", "80000", "80000",
                datetime(2026, 6, 27, 11), cp="REKENING SALAH")
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.reason_code, "no_money")

    def test_alias_tak_bocor_antar_username(self):
        self._bukti("eka10", "SITI RAHAYU")
        p = self.tx(self.panel, self.up_panel, "depo", "90000", "90000",
                    datetime(2026, 6, 27, 10), ticket="D805", user="lain99",
                    cp="ORANG LAIN")
        self.tx(self.bank, self.up_bank, "depo", "90000", "90000",
                datetime(2026, 6, 27, 11), cp="SITI RAHAYU")
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.reason_code, "no_money")

    def test_alias_toko_lain_tak_ikut(self):
        up_p2 = Upload.objects.create(source_type=self.panel, toko=self.toko2,
                                      original_name="PANEL2.xlsx")
        up_b2 = Upload.objects.create(source_type=self.bank, toko=self.toko2,
                                      original_name="BANK2.csv")
        old_left = self.tx(self.panel, up_p2, "depo", "10000", "10000",
                           datetime(2026, 6, 20, 10), ticket="D900",
                           user="fafa11", cp="NAMA PANEL", toko=self.toko2)
        old_right = self.tx(self.bank, up_b2, "depo", "10000", "10000",
                            datetime(2026, 6, 20, 11), cp="SITI RAHAYU",
                            toko=self.toko2)
        old_run = MatchRun.objects.create(relation=MatchRun.Relation.PANEL_BANK,
                                          tolerance=self.tol)
        MatchResult.objects.create(run=old_run, bucket=MatchResult.Bucket.COCOK,
                                   left=old_left, right=old_right, score=90,
                                   reason_code="amount+date+name")
        p = self.tx(self.panel, self.up_panel, "depo", "40000", "40000",
                    datetime(2026, 6, 27, 10), ticket="D806", user="fafa11",
                    cp="FAFA")
        self.tx(self.bank, self.up_bank, "depo", "40000", "40000",
                datetime(2026, 6, 27, 11), cp="SITI RAHAYU")
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.reason_code, "no_money")

    def test_identitas_persis_menang_atas_alias(self):
        # Nama bank == nama panel persis (skor 100) -> reason tetap
        # amount+date+name; alias hanya label saat DIA anchor penentunya.
        self._bukti("gina12", "GINA MARLINA")
        p = self.tx(self.panel, self.up_panel, "depo", "30000", "30000",
                    datetime(2026, 6, 27, 10), ticket="D807", user="gina12",
                    cp="GINA MARLINA")
        b = self.tx(self.bank, self.up_bank, "depo", "30000", "30000",
                    datetime(2026, 6, 27, 11), cp="GINA MARLINA")
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.reason_code, "amount+date+name")
        self.assertEqual(r.right_id, b.id)
