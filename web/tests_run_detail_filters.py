"""run_detail: pisah bucket (tidak_cocok vs tidak ada di panel), filter bank/
bank title, ringkasan total terfilter, label amount per relasi."""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


class _Base(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)
        self.batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        self.run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=self.batch
        )

    def _tx(self, st, rh, **kw):
        d = dict(
            upload=self.up, source_type=st, toko=self.lbs, jenis="depo",
            amount=Decimal("50000"), occurred_at=datetime(2026, 6, 27, 10, 0), raw={},
        )
        d.update(kw)
        return Transaction.objects.create(row_hash=rh, **d)

    def _res(self, bucket, left=None, right=None, reason=""):
        return MatchResult.objects.create(
            run=self.run, bucket=bucket, left=left, right=right, reason_code=reason
        )

    def _get(self, **q):
        url = reverse("run_detail", args=[self.run.pk])
        if q:
            url += "?" + "&".join(f"{k}={v}" for k, v in q.items())
        return self.client.get(url)


class BucketSplitTests(_Base):
    def setUp(self):
        super().setUp()
        cl = self._tx(self.panel, "c1", amount=Decimal("50000"), ticket_no="D1")
        cr = self._tx(self.bank, "c2", amount=Decimal("50000"))
        self._res("cocok", cl, cr, "ticket")
        nm = self._tx(self.panel, "n1", amount=Decimal("30000"), ticket_no="D2")
        self._res("tidak_cocok", nm, None, "no_money")           # ada kredit
        orphan = self._tx(self.bank, "o1", amount=Decimal("70000"))
        self._res("tidak_cocok", None, orphan, "no_panel")       # orphan uang

    def test_kartu_split_counts(self):
        c = self._get().context
        self.assertEqual(c["n_tidak_cocok"], 1)
        self.assertEqual(c["n_tidak_ada_panel"], 1)

    def test_tab_tidak_ada_panel_hanya_orphan(self):
        rows = list(self._get(bucket="tidak_ada_panel").context["page"])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].left_id)

    def test_tab_tidak_cocok_hanya_ada_kredit(self):
        rows = list(self._get(bucket="tidak_cocok").context["page"])
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0].left_id)

    def test_orphan_label_relasi(self):
        self.assertEqual(self._get().context["orphan_label"], "Tidak Ada di Panel")


class BankFilterTests(_Base):
    def setUp(self):
        super().setUp()
        for i, code in enumerate(["DANA", "DANA", "BCA"]):
            left = self._tx(self.panel, f"b{i}", amount=Decimal("10000"),
                            player_bank=code, bank_title="QRIS", ticket_no=f"D{i}")
            right = self._tx(self.bank, f"r{i}", amount=Decimal("10000"))
            self._res("cocok", left, right, "ticket")

    def test_bank_chips_terhitung(self):
        codes = {b["code"]: b["n"] for b in self._get().context["banks"]}
        self.assertEqual(codes.get("DANA"), 2)
        self.assertEqual(codes.get("BCA"), 1)

    def test_filter_bank_menyaring(self):
        rows = list(self._get(bank="DANA").context["page"])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.left.player_bank == "DANA" for r in rows))

    def test_bank_title_chips_dan_filter(self):
        titles = {b["code"]: b["n"] for b in self._get().context["btitles"]}
        self.assertEqual(titles.get("QRIS"), 3)
        self.assertEqual(len(list(self._get(btitle="QRIS").context["page"])), 3)


class TotalsTests(_Base):
    def setUp(self):
        super().setUp()
        for i, (amt, code) in enumerate([(10000, "DANA"), (20000, "DANA"), (5000, "BCA")]):
            left = self._tx(self.panel, f"t{i}", amount=Decimal(amt), player_bank=code, ticket_no=f"D{i}")
            right = self._tx(self.bank, f"tr{i}", amount=Decimal(amt))
            self._res("cocok", left, right, "ticket")

    def test_total_semua(self):
        t = self._get().context["totals"]
        self.assertEqual(t["n"], 3)
        self.assertEqual(t["kredit"], Decimal("35000"))
        self.assertEqual(t["saldo"], Decimal("35000"))

    def test_total_ikut_filter_bank(self):
        t = self._get(bank="DANA").context["totals"]
        self.assertEqual(t["n"], 2)
        self.assertEqual(t["kredit"], Decimal("30000"))


class AmountLabelTests(_Base):
    def test_panel_bank_labels(self):
        c = self._get().context
        self.assertEqual(c["left_amt_label"], "Kredit/Koin")
        self.assertEqual(c["right_amt_label"], "Saldo Bank")
