"""Settlement Tertunda — antrean kredit menunggu uang tiba (H+1)."""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.settlement import pending_settlement_rows


class _SettleData(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.toko)
        self._n = 0
        self._runs = {}

    def _home_run(self, d, window):
        """Batch+run untuk tanggal `d` (satu per tanggal — hormati unique constraint)."""
        if d not in self._runs:
            tol = self.tol
            if window != 1:
                tol = ToleranceProfile.objects.get_or_create(
                    name=f"W{window}", defaults={"date_window_days": window}
                )[0]
            home = ReconBatch.objects.create(toko=self.toko, tolerance=tol, recon_date=d)
            run = MatchRun.objects.create(
                relation=MatchRun.Relation.PANEL_BANK, tolerance=tol, batch=home
            )
            self._runs[d] = run
        return self._runs[d]

    def waiting(self, d, jenis="wd", ticket="W1", username="budi", amount="59000",
                window=1, player_bank="BCA"):
        """Buat 1 baris kredit no_money AKTIF di batch tanggal `d`."""
        self._n += 1
        run = self._home_run(d, window)
        tx = Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=self.toko, jenis=jenis,
            amount=Decimal(amount), money_delta=Decimal(amount) if jenis == "depo" else -Decimal(amount),
            ticket_no=ticket, username=username, player_bank=player_bank,
            occurred_at=datetime(d.year, d.month, d.day, 23, 30), row_hash=f"s{self._n}",
        )
        MatchResult.objects.create(
            run=run, bucket=MatchResult.Bucket.TIDAK, reason_code="no_money", left=tx,
        )
        return tx


class PendingRowsTests(_SettleData):
    def test_baris_menunggu_dengan_umur_dan_sisa(self):
        self.waiting(date(2026, 6, 28), ticket="W6166103", username="eddysusanto", amount="59000")
        rows = pending_settlement_rows(self.toko, reference=date(2026, 6, 29))
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["ticket"], "W6166103")
        self.assertEqual(r["username"], "eddysusanto")
        self.assertEqual(r["nominal"], Decimal("59000"))
        self.assertEqual(r["jenis"], "wd")
        self.assertEqual(r["umur"], 1)           # 29 − 28
        self.assertEqual(r["batas"], date(2026, 6, 29))  # d + window
        self.assertEqual(r["sisa"], 0)           # batas − reference
        self.assertIsNotNone(r["home_batch_id"])

    def test_window_lebih_lebar_menambah_sisa(self):
        self.waiting(date(2026, 6, 28), window=3)
        r = pending_settlement_rows(self.toko, reference=date(2026, 6, 29))[0]
        self.assertEqual(r["batas"], date(2026, 7, 1))  # 28 + 3 hari
        self.assertEqual(r["sisa"], 2)

    def test_urut_tertua_dulu(self):
        self.waiting(date(2026, 6, 28), ticket="W-baru")
        self.waiting(date(2026, 6, 26), ticket="W-lama")
        rows = pending_settlement_rows(self.toko, reference=date(2026, 6, 30))
        self.assertEqual([r["ticket"] for r in rows], ["W-lama", "W-baru"])

    def test_reference_default_ke_batch_terakhir(self):
        self.waiting(date(2026, 6, 28))
        rows = pending_settlement_rows(self.toko)  # tanpa reference
        # reference otomatis = recon_date terakhir (28) → umur 0
        self.assertEqual(rows[0]["umur"], 0)

    def test_baris_terkonsumsi_tak_muncul(self):
        tx = self.waiting(date(2026, 6, 28))
        # baris yang sudah settle (consumed) tidak lagi menunggu
        b = ReconBatch.objects.first()
        tx.consumed_by_batch = b
        tx.save()
        self.assertEqual(pending_settlement_rows(self.toko), [])


class SettlementViewTests(_SettleData):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})

    def test_butuh_login(self):
        self.client.logout()
        r = self.client.get(reverse("settlement_pending"))
        self.assertEqual(r.status_code, 302)

    def test_render_dan_filter_flow(self):
        self.waiting(date(2026, 6, 28), jenis="wd", ticket="W-satu", username="andi")
        self.waiting(date(2026, 6, 28), jenis="depo", ticket="D-dua", username="rina")
        r = self.client.get(reverse("settlement_pending"))
        html = r.content.decode()
        self.assertIn("Settlement Tertunda", html)
        self.assertIn("W-satu", html)
        self.assertIn("D-dua", html)
        r2 = self.client.get(reverse("settlement_pending"), {"flow": "wd"})
        html2 = r2.content.decode()
        self.assertIn("W-satu", html2)
        self.assertNotIn("D-dua", html2)

    def test_empty_state(self):
        r = self.client.get(reverse("settlement_pending"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("Tidak ada", r.content.decode())
