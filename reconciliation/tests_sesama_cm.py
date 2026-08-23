"""Sesama CM: exclude dari panel↔bank + relasi bracket_bank khusus FR Sesama CM."""
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from reconciliation.engine import run_batch, run_match
from reconciliation.models import MatchResult, MatchRun, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.sesama_cm import clear_cm_cache

User = get_user_model()
_seq = iter(range(1, 100000))


class SesamaCmReconTests(TestCase):
    def setUp(self):
        clear_cm_cache()
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.bracket = SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})[0]
        self.up_p = Upload.objects.create(source_type=self.panel, toko=self.toko, original_name="p.xlsx")
        self.up_n = Upload.objects.create(
            source_type=self.bank, toko=self.toko, original_name="bri_nasrul.csv",
            owner_name="NASRUL",
        )
        self.up_k = Upload.objects.create(
            source_type=self.bank, toko=self.toko, original_name="bri_kiki.csv",
            owner_name="KIKI SUASANTO",
        )
        self.up_fr = Upload.objects.create(source_type=self.bracket, toko=self.toko, original_name="fr.xlsx")
        clear_cm_cache()

    def _tx(self, st, up, *, jenis, amount, money, dt, ticket="", username="",
            counterparty="", description="", raw=None, posted=None):
        return Transaction.objects.create(
            upload=up, source_type=st, toko=self.toko, jenis=jenis,
            amount=Decimal(amount), money_delta=Decimal(money),
            occurred_at=dt, posted_date=posted or dt.date(),
            ticket_no=ticket, username=username,
            counterparty=counterparty, description=description,
            raw=raw or {}, row_hash=f"scm-{next(_seq)}",
        )

    def _fr_cm(self, bank, rek, money, dt, desc="PINDAH DANA"):
        return self._tx(
            self.bracket, self.up_fr, jenis="lainnya",
            amount=str(abs(Decimal(money))), money=money, dt=dt,
            description=desc,
            raw={
                "Kategori": "Sesama CM",
                "Bank": bank,
                "No. Rek Bank Member": rek,
                "Description": desc,
            },
        )

    def test_panel_bank_exclude_sesama_cm_money(self):
        """Mutasi pindah dana CM tidak jadi no_panel / tidak mencuri pair panel."""
        dt = datetime(2026, 8, 21, 10, 0)
        # panel DP member
        self._tx(self.panel, self.up_p, jenis="depo", amount="100000", money="100000",
                 dt=dt, ticket="D1", username="budi", counterparty="BUDI SANTOSO")
        # money member matching panel
        self._tx(self.bank, self.up_n, jenis="depo", amount="100000", money="100000",
                 dt=dt, counterparty="BUDI SANTOSO", description="TRSF BUDI SANTOSO")
        # sesama CM money (Kiki → Nasrul) — harus DIkeluarkan dari panel_bank
        self._fr_cm("BANK BRI | KIKI SUASANTO | TAMPUNG", "BRI 119101022152500",
                    "5000000", dt)
        cm_money = self._tx(
            self.bank, self.up_n, jenis="depo", amount="5000000", money="5000000",
            dt=dt, counterparty="Kikisuasanto",
            description="NBMB Kikisuasanto TO NASRUL 119101022152500",
        )
        clear_cm_cache()
        run = run_match(MatchRun.Relation.PANEL_BANK, self.tol, toko=self.toko,
                        date_from=dt.date(), date_to=dt.date())
        rights = {r.right_id for r in MatchResult.objects.filter(run=run) if r.right_id}
        self.assertNotIn(cm_money.id, rights)
        # panel member tetap cocok / tinjau (bukan no_money karena dicuri CM)
        r_panel = MatchResult.objects.get(run=run, left__ticket_no="D1")
        self.assertIn(r_panel.bucket, ("cocok", "perlu_tinjau"))
        self.assertNotEqual(r_panel.right_id, cm_money.id)

    def test_bracket_bank_sesama_cm_cocok_via_norek(self):
        dt = datetime(2026, 8, 21, 12, 0)
        fr = self._fr_cm(
            "BANK BCA | YULIYANTI PRATIWI | TAMPUNG", "BCA 8447072062",
            "-970000", dt,
        )
        money = self._tx(
            self.bank, self.up_n, jenis="wd", amount="970000", money="-970000",
            dt=dt, counterparty="YULI",
            description="Transfer BI Fast Ke BCA 8447072062",
        )
        # FR tanpa pasangan
        fr2 = self._fr_cm(
            "BANK BRI | KIKI SUASANTO | TAMPUNG", "BRI 119101022152500",
            "-5000000", dt,
        )
        clear_cm_cache()
        run = run_match(MatchRun.Relation.BRACKET_BANK, self.tol, toko=self.toko,
                        date_from=dt.date(), date_to=dt.date())
        self.assertEqual(run.summary.get("mode"), "sesama_cm")
        r_ok = MatchResult.objects.get(run=run, left=fr)
        self.assertEqual(r_ok.bucket, "cocok")
        self.assertEqual(r_ok.right_id, money.id)
        self.assertEqual(r_ok.reason_code, "amount+rek")
        r_miss = MatchResult.objects.get(run=run, left=fr2)
        self.assertEqual(r_miss.bucket, "tidak_cocok")
        self.assertEqual(r_miss.reason_code, "no_money")

    def test_run_batch_menjalankan_bracket_bank_sesama(self):
        dt = datetime(2026, 8, 21, 10, 0)
        # minimal kelengkapan: panel + bank + bracket
        self._tx(self.panel, self.up_p, jenis="depo", amount="100000", money="100000",
                 dt=dt, ticket="D9", username="x", counterparty="X PLAYER")
        self._tx(self.bank, self.up_n, jenis="depo", amount="100000", money="100000",
                 dt=dt, counterparty="X PLAYER", description="TRSF X PLAYER")
        self._fr_cm("BANK BRI | KIKI SUASANTO | T", "BRI 119101022152500",
                    "5000000", dt)
        self._tx(
            self.bank, self.up_n, jenis="depo", amount="5000000", money="5000000",
            dt=dt, counterparty="Kikisuasanto",
            description="Transfer dari KIKISUASANTO 119101022152500",
        )
        clear_cm_cache()
        batch = run_batch(
            self.toko, self.tol, date_from=dt.date(), date_to=dt.date(),
            recon_date=dt.date(),
        )
        rels = list(batch.runs.values_list("relation", flat=True))
        self.assertIn("bracket_bank", rels)
        self.assertIn("panel_bank", rels)
        bb = batch.runs.get(relation="bracket_bank")
        self.assertEqual(bb.summary.get("mode"), "sesama_cm")
        self.assertGreaterEqual(bb.summary.get("cocok", 0), 1)

    def test_batch_tanpa_bracket_sesama_cm_bukan_no_panel(self):
        """Bracket tidak dicentang: uang Sesama CM tidak jadi orphan no_panel."""
        dt = datetime(2026, 8, 22, 10, 0)
        self._tx(self.panel, self.up_p, jenis="depo", amount="100000", money="100000",
                 dt=dt, ticket="D22", username="x", counterparty="X PLAYER")
        self._tx(self.bank, self.up_n, jenis="depo", amount="100000", money="100000",
                 dt=dt, counterparty="X PLAYER", description="TRSF X PLAYER")
        # FR ada (identitas CM) tapi include bracket=False
        self._fr_cm("BANK BRI | KIKI SUASANTO | T", "BRI 119101022152500",
                    "5000000", dt)
        cm = self._tx(
            self.bank, self.up_n, jenis="depo", amount="5000000", money="5000000",
            dt=dt, counterparty="Kikisuasanto",
            description="Transfer dari KIKISUASANTO 119101022152500",
        )
        clear_cm_cache()
        include = {
            "panel_dp": True, "panel_wd": True, "bracket": False,
            "bank": True, "gateway": True,
        }
        batch = run_batch(
            self.toko, self.tol, date_from=dt.date(), date_to=dt.date(),
            recon_date=dt.date(), include=include,
        )
        self.assertIn("bracket_bank", batch.summary.get("skipped") or [])
        pb = batch.runs.get(relation="panel_bank")
        # CM money must not appear as no_panel
        self.assertFalse(
            MatchResult.objects.filter(run=pb, right=cm, reason_code="no_panel").exists()
        )
        um = (batch.summary or {}).get("unmatched_money") or {}
        self.assertGreaterEqual((um.get("c") or {}).get("n", 0), 1)
