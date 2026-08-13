"""Hasil rekonsiliasi TIDAK BOLEH bergantung pada urutan baris yang masuk.

Rantai cacatnya nyata dan pernah terbukti:

1. `sides()` mengembalikan queryset TANPA `order_by`, dan `Transaction.Meta`
   tidak punya `ordering` — jadi urutan barisnya murni keputusan query planner.
2. Kunci sort pass 1 / pass 3 `(skor, route, -delta)` TIDAK total (tak ada id).
   `list.sort` stabil, jadi pasangan yang SERI dipecahkan oleh urutan append —
   yaitu urutan queryset di (1).
3. Menambah index komposit (atau sekadar pertumbuhan data yang menggeser
   statistik Postgres) mengubah rencana eksekusi, jadi mengubah urutan itu.

Akibatnya jumlah "Cocok" bisa berbeda antar-run untuk data yang PERSIS SAMA.

Reproduksi di bawah: satu pemain, empat baris nominal sama tanggal sama.
P1 (panel tanpa deklarasi kanal) boleh melamar uang NXPAY maupun RPAY; P2
(panel ber-`bank_title` "NXPAY DEPOSIT QR") hanya boleh melamar NXPAY. Urutan
`[P1, P2]` menghasilkan cocok=1, urutan `[P2, P1]` menghasilkan cocok=2.

Catatan penting soal yang TIDAK diuji di sini: tes ini menuntut KESAMAAN hasil
antar urutan, bukan nilai tertentu. Membuat repro selalu berakhir cocok=2 berarti
mengganti assignment greedy dengan maximum matching — itu mengubah SIAPA yang
boleh berpasangan (aturan anchor), bukan sekadar pemecah seri.
"""
from datetime import datetime
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from reconciliation.engine import PanelBankMatcher
from reconciliation.models import MatchResult, MatchRun, ToleranceProfile
from sources.models import SourceType, Upload
from transactions.models import Transaction


class DeterminismeUrutanTests(TestCase):
    def setUp(self):
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.gw = SourceType.objects.get_or_create(
            key="gateway", defaults={"name": "Gateway", "is_money_source": True}
        )[0]
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1, "fuzzy_threshold": 85}
        )[0]
        self.up = Upload.objects.create(source_type=self.panel)
        self.upg = Upload.objects.create(source_type=self.gw)
        self.dt = datetime(2026, 8, 12, 21, 15)

    # --- pembangun fixture ---------------------------------------------------
    def _panel_row(self, rh, bank_title="", username="andi", amount=25000):
        return Transaction.objects.create(
            upload=self.up, source_type=self.panel, jenis="depo",
            amount=Decimal(amount), money_delta=Decimal(amount),
            username=username, bank_title=bank_title,
            occurred_at=self.dt, row_hash=rh,
        )

    def _gw_row(self, rh, description, username="andi", amount=25000):
        return Transaction.objects.create(
            upload=self.upg, source_type=self.gw, jenis="depo",
            amount=Decimal(amount), money_delta=Decimal(amount),
            username=username, description=description,
            occurred_at=self.dt, row_hash=rh,
        )

    def _run(self):
        return MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol
        )

    @staticmethod
    def _ringkas(hasil):
        """Ringkasan hasil yang harus stabil: jumlah cocok + himpunan pasangan."""
        cocok = [r for r in hasil if r.bucket == MatchResult.Bucket.COCOK]
        return len(cocok), {(r.left.id, r.right.id) for r in cocok}

    # --- lapis 2: kunci sort pass 1 harus TOTAL ------------------------------
    def test_urutan_baris_tidak_mengubah_hasil(self):
        p1 = self._panel_row("p1")                        # tanpa kanal → bebas
        p2 = self._panel_row("p2", "NXPAY DEPOSIT QR")    # terkunci ke NXPAY
        b_nx = self._gw_row("g1", "NXPAY 8812345")
        b_rp = self._gw_row("g2", "RPay 619180666745")
        right = [b_nx, b_rp]

        maju = self._ringkas(PanelBankMatcher().match(self._run(), [p1, p2], right))
        mundur = self._ringkas(PanelBankMatcher().match(self._run(), [p2, p1], right))
        self.assertEqual(maju, mundur, f"urutan sisi kiri mengubah hasil: {maju} vs {mundur}")

    def test_urutan_sisi_uang_tidak_mengubah_hasil(self):
        # Satu baris panel bebas kanal, dua baris uang yang sama-sama layak
        # (skor identitas 100, nominal & tanggal identik) → seri murni pass 1.
        p1 = self._panel_row("p1")
        b_nx = self._gw_row("g1", "NXPAY 8812345")
        b_rp = self._gw_row("g2", "RPay 619180666745")

        maju = self._ringkas(PanelBankMatcher().match(self._run(), [p1], [b_nx, b_rp]))
        mundur = self._ringkas(PanelBankMatcher().match(self._run(), [p1], [b_rp, b_nx]))
        self.assertEqual(maju, mundur, f"urutan sisi uang mengubah hasil: {maju} vs {mundur}")

    # --- lapis 1: queryset `sides()` wajib diurutkan eksplisit ---------------
    def test_sides_selalu_mengurutkan_queryset(self):
        # SQLite biasanya MEMANG mengembalikan urutan rowid, jadi memeriksa isi
        # list tak membuktikan apa pun. Yang membuktikan: SQL-nya sendiri harus
        # membawa ORDER BY, supaya planner (Postgres, dengan index apa pun) tidak
        # lagi berhak memilih urutan.
        self._panel_row("p1")
        self._gw_row("g1", "NXPAY 8812345")
        with CaptureQueriesContext(connection) as ctx:
            PanelBankMatcher().sides(None, None, None)
        sql_tx = [q["sql"] for q in ctx.captured_queries if "transactions_transaction" in q["sql"]]
        self.assertTrue(sql_tx, "tak ada query transaksi yang tertangkap")
        for sql in sql_tx:
            self.assertIn("ORDER BY", sql.upper(), f"queryset sides() tanpa ORDER BY: {sql}")
