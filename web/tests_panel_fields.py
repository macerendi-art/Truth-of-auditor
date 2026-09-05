from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.templatetags.web_extras import raw_get


class RawGetFilterTests(TestCase):
    """Unit test filter `raw_get` — akses dict raw dgn key ber-spasi."""

    def test_none_dict_returns_empty_string(self):
        self.assertEqual(raw_get(None, "X"), "")

    def test_key_with_space_found(self):
        self.assertEqual(raw_get({"A B": "c"}, "A B"), "c")

    def test_missing_key_returns_empty_string(self):
        self.assertEqual(raw_get({"A B": "c"}, "Tidak Ada"), "")


class PanelFieldsRunDetailTests(TestCase):
    """Player Bank / Bank Title / Handler harus tampil di sisi Panel (kiri) — kini kolom sendiri."""

    def setUp(self):
        User = get_user_model()
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

    def _tx(self, st, raw, **kw):
        return Transaction.objects.create(
            upload=self.up, source_type=st, toko=self.lbs, jenis="depo",
            amount=Decimal("50000"), money_delta=Decimal("50000"),
            occurred_at=datetime(2026, 6, 27, 10, 0), raw=raw, **kw,
        )

    def test_panel_fields_shown_when_present(self):
        left = self._tx(
            self.panel,
            raw={
                "Player Bank": "DANA|fajar Pratama |083822153879",
                "Bank Title": "BCA|HENDI|7126201591",
                "Handler": "Mozart K25",
            },
            row_hash="pf1",
        )
        right = self._tx(self.bank, raw={}, row_hash="pf2")
        MatchResult.objects.create(
            run=self.run, bucket=MatchResult.Bucket.COCOK, left=left, right=right,
        )
        resp = self.client.get(reverse("run_detail", args=[self.run.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, ">Player Bank</th>")
        self.assertContains(resp, "DANA|fajar Pratama |083822153879")
        self.assertContains(resp, ">Bank Title</th>")
        self.assertContains(resp, "BCA|HENDI|7126201591")
        self.assertContains(resp, ">Handler</th>")
        self.assertContains(resp, "Mozart K25")

    def test_no_panel_fields_values_when_raw_empty(self):
        left = self._tx(self.panel, raw={}, row_hash="pf3")
        right = self._tx(self.bank, raw={}, row_hash="pf4")
        MatchResult.objects.create(
            run=self.run, bucket=MatchResult.Bucket.COCOK, left=left, right=right,
        )
        resp = self.client.get(reverse("run_detail", args=[self.run.pk]))
        self.assertEqual(resp.status_code, 200)
        # Raw kosong → sel kolom panel berisi "—" (tidak error, tidak bocor nilai).
        self.assertContains(resp, "—")

    def test_right_only_row_no_left_does_not_error(self):
        right = self._tx(self.bank, raw={}, row_hash="pf5")
        MatchResult.objects.create(
            run=self.run, bucket=MatchResult.Bucket.TIDAK, left=None, right=right,
        )
        resp = self.client.get(reverse("run_detail", args=[self.run.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_qris_elite_ticket_tampil_di_sisi_mutasi(self):
        """Panel↔Mutasi · Tak ada di panel: ticket gateway ELITE dari mutasi (kanan).

        Screenshot commander: posisi "—" di bawah Rekening a/n ELITE harus
        menampilkan kode TICKET file (D…) — diambil dari right.ticket_no.
        """
        gw = SourceType.objects.get_or_create(key="gateway", defaults={"name": "Gateway"})[0]
        up_gw = Upload.objects.create(
            source_type=gw, toko=self.lbs, original_name="04-09 DP QRIS ELITE.csv",
            owner_name="ELITE",
        )
        right = Transaction.objects.create(
            upload=up_gw, source_type=gw, toko=self.lbs, jenis="depo",
            amount=Decimal("25000"), money_delta=Decimal("25000"),
            occurred_at=datetime(2026, 9, 4, 23, 59),
            ticket_no="D2370410", username="kaizen01",
            description="QRIS ELITE KAIZEN DIGITECH LNC",
            counterparty="", raw={}, row_hash="elite-tix-1",
        )
        MatchResult.objects.create(
            run=self.run, bucket=MatchResult.Bucket.TIDAK,
            left=None, right=right,
            reason_code="no_panel",
            reason_detail="Ticket gateway tak dikenal panel",
        )
        # Tab "Tidak Ada di Panel" = TIDAK + left null → hide_left
        resp = self.client.get(
            reverse("run_detail", args=[self.run.pk]),
            {"bucket": "tidak_ada_panel"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "D2370410")
        self.assertContains(resp, "kaizen01")
        self.assertContains(resp, 'title="Ticket dari mutasi/gateway"')
        self.assertContains(resp, "QRIS ELITE KAIZEN DIGITECH LNC")


class ResultRowTemplateRenderTests(TestCase):
    """Render langsung _result_row.html via Template — pastikan tag {% load %} & filter jalan."""

    TEMPLATE = "{% load humanize %}{% load web_extras %}{% include \"web/_result_row.html\" %}"

    def _render(self, r, **extra):
        ctx = {"r": r}
        ctx.update(extra)
        return Template(self.TEMPLATE).render(Context(ctx))

    def test_partial_labels_when_only_handler_present(self):
        class FakeLeft:
            ticket_no = "D1"
            counterparty = ""
            username = "budi"
            occurred_at = None
            amount = Decimal("1000")
            raw = {"Handler": "Bot.qrisflyer"}

        class FakeRow:
            pk = 1
            bucket = "cocok"
            left = FakeLeft()
            right = None
            reason_code = ""
            reason_detail = ""
            score = 0

            def get_bucket_display(self):
                return "Cocok"

        html = self._render(FakeRow())
        self.assertIn("Bot.qrisflyer", html)  # Handler tampil di kolomnya
        self.assertIn("budi", html)  # username di kolom User ID
        self.assertNotIn("Handler:", html)  # label lama (satu sel) sudah tidak ada

    def test_right_ticket_qris_elite_mengganti_strip(self):
        """Sisi mutasi: ticket_no mono + username; "—" hilang bila ticket ada."""

        class FakeSrc:
            key = "gateway"
            name = "Gateway"

        class FakeUpload:
            owner_name = "ELITE"
            original_name = "elite.csv"

        class FakeRight:
            source_type = FakeSrc()
            upload = FakeUpload()
            ticket_no = "D2370410"
            username = "soju29"
            counterparty = ""
            player_name = ""
            description = "QRIS ELITE THERYX"
            jenis = "depo"
            occurred_at = None
            balance_after = None
            amount = Decimal("9700")
            money_delta = Decimal("9700")
            raw = {}
            source_label_full = "QRIS a/n ELITE"

        class FakeRow:
            pk = 99
            bucket = "unmatched_money"
            left = None
            right = FakeRight()
            reason_code = "no_panel"
            reason_detail = "Ticket gateway tak dikenal panel"
            score = 0
            alasan_manual = ""
            catatan_manual = ""

            def get_bucket_display(self):
                return "Tidak Cocok"

        html = self._render(FakeRow(), hide_left=True)
        self.assertIn("D2370410", html)
        self.assertIn("soju29", html)
        self.assertIn('title="Ticket dari mutasi/gateway"', html)
        self.assertIn("QRIS a/n ELITE", html)
        # Jangan tampil "—" palsu di slot nama bila ticket sudah ada
        # (boleh "—" di sel kiri kosong — hide_left=True menekan kiri).
        self.assertNotIn(">——<", html.replace(" ", ""))
