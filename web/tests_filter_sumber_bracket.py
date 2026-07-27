"""Chip "Filter bank/sumber" tab **Tidak Ada di Panel** untuk relasi
Panel↔Bracket (panel Vigor/TM Gaming yang dicocokkan lewat username).

Keluhan end user (27 Juli 2026): chip-nya cuma menampilkan satu pilihan
"Bracket" — nama SourceType — bukan bank/akun FR-nya, jadi filternya tak
berguna. Sisi kanan relasi ini memang baris FR/Bracket, dan label upload untuk
baris FR selalu generik ("Bracket"); akun sebenarnya ada di `raw["Bank"]`
("BANK BCA | HENDI | WITHDRAW") — sumber yang sama dengan halaman /bracket/.

Relasi ke bank/gateway (panel_bank, bracket_bank) TIDAK boleh berubah: di sana
label upload memang bank aslinya (BRI/BCA/Mandiri/NXPay).
"""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()

AKUN_BCA = "BANK BCA | HENDI | WITHDRAW"
AKUN_BRI = "BANK BRI | MARGANI | DEPOSIT"
AKUN_QRIS = "QRIS FLYER | DEPOSIT / WITHDRAW"


class _Base(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.toko = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.panel = SourceType.objects.get(key="panel")
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"}
        )[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up_fr = Upload.objects.create(
            source_type=self.bracket, toko=self.toko, original_name="FR COR 26-07.xlsx"
        )
        self.batch = ReconBatch.objects.create(
            toko=self.toko, tolerance=self.tol, recon_date=datetime(2026, 7, 26).date()
        )
        self.run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BRACKET, tolerance=self.tol, batch=self.batch
        )
        self._n = 0

    def fr(self, akun, jenis="depo", amount="15000", upload=None):
        self._n += 1
        return Transaction.objects.create(
            upload=upload or self.up_fr, source_type=self.bracket, toko=self.toko,
            jenis=jenis, amount=Decimal(amount), money_delta=Decimal(amount),
            occurred_at=datetime(2026, 7, 26, 10, 0), posted_date=self.batch.recon_date,
            row_hash=f"fr{self._n}", raw={"Bank": akun, "Kategori": "Deposit"},
        )

    def orphan(self, right):
        return MatchResult.objects.create(
            run=self.run, bucket=MatchResult.Bucket.TIDAK,
            left=None, right=right, reason_code="no_panel",
        )

    def get(self, **q):
        url = reverse("run_detail", args=[self.run.pk]) + "?bucket=tidak_ada_panel"
        for k, v in q.items():
            url += f"&{k}={v}"
        return self.client.get(url)


class ChipAkunFRTests(_Base):
    def setUp(self):
        super().setUp()
        for akun, n in ((AKUN_BCA, 3), (AKUN_BRI, 2), (AKUN_QRIS, 1)):
            for _ in range(n):
                self.orphan(self.fr(akun))

    def test_chip_memakai_akun_fr_bukan_kata_bracket(self):
        chips = self.get().context["btitles"]
        codes = {c["code"]: c["n"] for c in chips}
        self.assertNotIn("Bracket", codes, f"chip masih generik: {codes}")
        self.assertEqual(codes.get(AKUN_BCA), 3)
        self.assertEqual(codes.get(AKUN_BRI), 2)
        self.assertEqual(codes.get(AKUN_QRIS), 1)

    def test_label_chip_terbaca_manusia(self):
        by_code = {c["code"]: c.get("label") for c in self.get().context["btitles"]}
        # pipa mentah tak enak dibaca di chip; nama akun dipisah seperti /bracket/
        self.assertEqual(by_code[AKUN_BCA], "BANK BCA — HENDI · WITHDRAW")
        self.assertEqual(by_code[AKUN_QRIS], "QRIS FLYER · DEPOSIT / WITHDRAW")

    def test_filter_akun_menyaring_baris(self):
        r = self.get(btitle=AKUN_BRI.replace(" ", "%20").replace("|", "%7C"))
        rows = list(r.context["page"])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(x.right.raw["Bank"] == AKUN_BRI for x in rows))
        self.assertEqual(r.context["totals"]["n"], 2)

    def test_chip_muncul_di_halaman(self):
        r = self.get()
        self.assertContains(r, "Filter bank/sumber")
        self.assertContains(r, "BANK BCA — HENDI · WITHDRAW")

    def test_baris_fr_tanpa_kolom_bank_tetap_terwakili(self):
        # baris FR cacat (tanpa kolom Bank) tak boleh hilang diam-diam dari chip
        self._n += 1
        tx = Transaction.objects.create(
            upload=self.up_fr, source_type=self.bracket, toko=self.toko, jenis="depo",
            amount=Decimal("9000"), occurred_at=datetime(2026, 7, 26, 11, 0),
            row_hash="frx", raw={"Kategori": "Deposit"},
        )
        self.orphan(tx)
        codes = {c["code"]: c["n"] for c in self.get().context["btitles"]}
        self.assertEqual(codes.get("(Tanpa Akun)"), 1)
        rows = list(self.get(btitle="(Tanpa%20Akun)").context["page"])
        self.assertEqual([x.right_id for x in rows], [tx.id])


class RelasiUangTakBerubahTests(_Base):
    """Relasi ke bank/gateway tetap memakai label upload (BRI/BCA/NXPay/…)."""

    def setUp(self):
        super().setUp()
        self.run_bank = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=self.batch
        )
        up_bank = Upload.objects.create(
            source_type=self.bank, toko=self.toko, original_name="mutasi bri juli.csv",
            provider="BRI",
        )
        for i in range(2):
            tx = Transaction.objects.create(
                upload=up_bank, source_type=self.bank, toko=self.toko, jenis="depo",
                amount=Decimal("25000"), occurred_at=datetime(2026, 7, 26, 9, 0),
                row_hash=f"bk{i}", raw={"Bank": "TIDAK DIPAKAI UNTUK SISI UANG"},
            )
            MatchResult.objects.create(
                run=self.run_bank, bucket=MatchResult.Bucket.TIDAK,
                left=None, right=tx, reason_code="no_panel",
            )

    def test_label_bank_dari_upload_tetap(self):
        url = reverse("run_detail", args=[self.run_bank.pk]) + "?bucket=tidak_ada_panel"
        codes = {c["code"]: c["n"] for c in self.client.get(url).context["btitles"]}
        self.assertEqual(codes, {"BRI": 2})


class AntreanTinjauTests(_Base):
    """Halaman /tinjau/ memakai jalur chip yang sama — jangan sampai cuma satu
    halaman yang diperbaiki."""

    def setUp(self):
        super().setUp()
        self.orphan(self.fr(AKUN_BCA))
        self.orphan(self.fr(AKUN_BCA))
        self.orphan(self.fr(AKUN_BRI))
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})

    def test_chip_akun_fr_di_antrean(self):
        r = self.client.get(reverse("review_queue") + "?bucket=tidak_ada_panel")
        codes = {c["code"]: c["n"] for c in r.context["btitles"]}
        self.assertNotIn("Bracket", codes)
        self.assertEqual(codes.get(AKUN_BCA), 2)
        self.assertEqual(codes.get(AKUN_BRI), 1)

    def test_filter_akun_menyaring_di_antrean(self):
        r = self.client.get(
            reverse("review_queue")
            + "?bucket=tidak_ada_panel&btitle=" + AKUN_BRI.replace(" ", "%20").replace("|", "%7C")
        )
        self.assertEqual(len(list(r.context["page"])), 1)
