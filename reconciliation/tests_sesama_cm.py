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

    def test_bracket_bank_owner_fr_plus_lawan_cm(self):
        """Mutasi di rekening FR (owner file) ke CM lain — cocok walau norek FR tak di desc."""
        dt = datetime(2026, 8, 22, 1, 0)
        up_moh = Upload.objects.create(
            source_type=self.bank, toko=self.toko, original_name="bca_moh.csv",
            owner_name="MOH ZUNAEDY AWAN",
        )
        Upload.objects.create(
            source_type=self.bank, toko=self.toko, original_name="bca_yuli.csv",
            owner_name="YULIYANTI PRATIWI",
        )
        fr = self._fr_cm(
            "BANK BCA | MOH ZUNAEDY AWAN | DEPOSIT", "BCA 3880950656",
            "-1050000", dt, desc="MUL NAIK TAMPUNG WEBSITE",
        )
        money = self._tx(
            self.bank, up_moh, jenis="wd", amount="1050000", money="-1050000",
            dt=dt, counterparty="YULIYANTI PRATIWI",
            description="TRSF E-BANKING DB YULIYANTI PRATIWI",
        )
        clear_cm_cache()
        run = run_match(MatchRun.Relation.BRACKET_BANK, self.tol, toko=self.toko,
                        date_from=dt.date(), date_to=dt.date())
        r_ok = MatchResult.objects.get(run=run, left=fr)
        self.assertEqual(r_ok.bucket, "cocok")
        self.assertEqual(r_ok.right_id, money.id)
        self.assertIn(r_ok.reason_code, (
            "owner_fr+counterparty_cm", "amount+name_cm",
        ))

    def test_identity_tidak_pakai_nama_sendiri_di_desc_owner(self):
        """Nama FR di deskripsi statement sendiri saja ≠ identitas (hindari false match)."""
        from reconciliation.engine import _sesama_cm_identity
        from types import SimpleNamespace
        fr = SimpleNamespace(raw={
            "Bank": "BANK BRI | KIKI SUASANTO | TAMPUNG",
            "No. Rek Bank Member": "BRI 119101022152500",
        })
        bank = SimpleNamespace(
            counterparty="ANWAR",
            description="NBMB Kikisuasanto TO ANWAR",
            upload=SimpleNamespace(owner_name="KIKI SUASANTO"),
        )
        sc, reason = _sesama_cm_identity(
            fr, bank, cm_names=("KIKI SUASANTO", "NASRUL"), cm_reks=("119101022152500",),
        )
        self.assertEqual(sc, 0.0)
        self.assertEqual(reason, "")

    def test_identity_typo_yuliayanti_vs_yuliyanti(self):
        """FR YULIAYANTI ≈ owner YULIYANTI — typo ejaan FR."""
        from reconciliation.engine import _sesama_cm_identity
        from types import SimpleNamespace
        from web.sesama_cm import cm_names_match
        self.assertTrue(cm_names_match("YULIAYANTI PRATIWI", "YULIYANTI PRATIWI"))
        fr = SimpleNamespace(raw={
            "Bank": "BANK BCA | YULIAYANTI PRATIWI | TAMPUNG LAYER 1",
            "No. Rek Bank Member": "BCA 8447072062",
        })
        bank = SimpleNamespace(
            counterparty="MOH ZUNAEDY AWAN",
            description="TRSF E-BANKING CR MOH ZUNAEDY AWAN",
            upload=SimpleNamespace(owner_name="YULIYANTI PRATIWI"),
        )
        sc, reason = _sesama_cm_identity(
            fr, bank,
            cm_names=("YULIAYANTI PRATIWI", "YULIYANTI PRATIWI", "MOH ZUNAEDY AWAN"),
            cm_reks=("8447072062", "3880950656"),
        )
        self.assertGreaterEqual(sc, 90)
        self.assertEqual(reason, "owner_fr+counterparty_cm")

    def test_serva_dp_member_bukan_sesama_cm(self):
        """DP member ke rekening SERVA (owner=SERVA) bukan Sesama CM."""
        from web.sesama_cm import tandai_sesama_cm, clear_cm_cache
        clear_cm_cache()
        # seed FR CM SERVA
        self._fr_cm(
            "BANK BRI | SERVA MUHAMAD SEBASTIAN | DEPOSIT", "BRI 058801037387506",
            "100000", datetime(2026, 8, 22, 10, 0),
        )
        up = Upload.objects.create(
            source_type=self.bank, toko=self.toko, original_name="bri_serva.csv",
            owner_name="SERVA",
        )
        t = self._tx(
            self.bank, up, jenis="depo", amount="110000", money="110000",
            dt=datetime(2026, 8, 22, 11, 0),
            counterparty="ABD MULUK LD P",
            description="NBMB ABD MULUK LD P TO SERVA MUHAMAD SEB",
        )
        clear_cm_cache()
        tandai_sesama_cm([t], self.toko.id)
        self.assertFalse(t.is_sesama_cm)

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
        self.assertIn("fr_bank", rels)
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

    def test_a_kredit_opaque_owner_cm_cocok_fr_masuk(self):
        """A: kredit masuk rekening CM (owner≈FR, cp kosong, desc ESB) ↔ FR masuk."""
        dt = datetime(2026, 8, 22, 8, 44)
        fr = self._fr_cm(
            "BANK BRI | KIKI SUASANTO | TAMPUNG LAYER 2", "BRI 119101022152500",
            "23787096", dt, desc="PINDAH DANA FYLER + BIAYA TRANSFER",
        )
        money = self._tx(
            self.bank, self.up_k, jenis="depo", amount="23787096", money="23787096",
            dt=dt, counterparty="",
            description="1787363038aA8P7PC WS_OB ESB:APFT:000TP00F:000372912238",
            raw={"NOREK": "119101022152500", "MUTASI_KREDIT": "23787096.00", "GLSIGN": "Cr"},
        )
        clear_cm_cache()
        run = run_match(
            MatchRun.Relation.BRACKET_BANK, self.tol, toko=self.toko,
            date_from=dt.date(), date_to=dt.date(),
        )
        r_ok = MatchResult.objects.get(run=run, left=fr)
        self.assertEqual(r_ok.bucket, "cocok")
        self.assertEqual(r_ok.right_id, money.id)
        self.assertIn(r_ok.reason_code, ("amount+rek", "owner_fr+kredit_masuk"))

    def test_a_kredit_settlement_pt_sahabat_owner_cm(self):
        """OKE ROMEQR: kredit PT SAHABAT di rekening MARIO ↔ FR masuk Sesama CM."""
        dt = datetime(2026, 8, 30, 12, 0)
        up_m = Upload.objects.create(
            source_type=self.bank, toko=self.toko, original_name="bca_mario.csv",
            owner_name="MARIO KARO-KARO",
        )
        fr = self._fr_cm(
            "BANK BCA | MARIO KAROKARO | TAMPUNG LAYER 1", "BCA 5798108942",
            "30000000", dt, desc="PINDAH DANA ROMEQR",
        )
        money = self._tx(
            self.bank, up_m, jenis="depo", amount="30000000", money="30000000",
            dt=dt, counterparty="PT SAHABAT KIRIM D",
            description="BI-FAST CR TRANSFER   DR 490 PT SAHABAT KIRIM D",
        )
        clear_cm_cache()
        run = run_match(
            MatchRun.Relation.BRACKET_BANK, self.tol, toko=self.toko,
            date_from=dt.date(), date_to=dt.date(),
        )
        r_ok = MatchResult.objects.get(run=run, left=fr)
        self.assertEqual(r_ok.bucket, "cocok")
        self.assertEqual(r_ok.right_id, money.id)
        self.assertEqual(r_ok.reason_code, "owner_fr+kredit_masuk")

    def test_compact_name_mario_karo_karo_di_counterparty(self):
        """FR MARIO KAROKARO ↔ mutasi cp MARIO KARO KARO (spasi) di rekening LUSIYATI."""
        dt = datetime(2026, 8, 30, 13, 0)
        up_l = Upload.objects.create(
            source_type=self.bank, toko=self.toko, original_name="bca_lus.csv",
            owner_name="LUSIYATI",
        )
        # seed LUSIYATI as CM too
        self._fr_cm(
            "BANK BCA | LUSIYATI | WITHDRAW", "BCA 0202419231",
            "1000", datetime(2026, 8, 20, 10, 0),
        )
        fr = self._fr_cm(
            "BANK BCA | MARIO KAROKARO | TAMPUNG LAYER 1", "BCA 5798108942",
            "-15000000", dt, desc="TURUN TAMPUNG OPS",
        )
        # money: WD from Mario? Actually FR is -15jt on Mario side meaning money leaves Mario
        # Better: FR +15jt LUSIYATI receiving from Mario with cp MARIO KARO KARO
        fr_in = self._fr_cm(
            "BANK BCA | LUSIYATI | WITHDRAW", "BCA 0202419231",
            "15000000", dt, desc="TURUN TAMPUNG OPS",
        )
        money = self._tx(
            self.bank, up_l, jenis="depo", amount="15000000", money="15000000",
            dt=dt, counterparty="MARIO KARO KARO",
            description="BI-FAST CR TRANSFER   DR 009 MARIO KARO KARO",
        )
        clear_cm_cache()
        run = run_match(
            MatchRun.Relation.BRACKET_BANK, self.tol, toko=self.toko,
            date_from=dt.date(), date_to=dt.date(),
        )
        r_ok = MatchResult.objects.get(run=run, left=fr_in)
        self.assertEqual(r_ok.bucket, "cocok")
        self.assertEqual(r_ok.right_id, money.id)

    def test_a_outbound_tidak_cocok_hanya_karena_raw_norek_sendiri(self):
        """A aman: FR keluar + WD member amount sama TIDAK cocok hanya karena NOREK rekening sendiri."""
        dt = datetime(2026, 8, 22, 9, 0)
        fr = self._fr_cm(
            "BANK BRI | KIKI SUASANTO | TAMPUNG", "BRI 119101022152500",
            "-5000000", dt,
        )
        # WD member di rekening Kiki — raw NOREK = rekening sendiri, lawan bukan CM
        money = self._tx(
            self.bank, self.up_k, jenis="wd", amount="5000000", money="-5000000",
            dt=dt, counterparty="ANWAR PEMAIN",
            description="NBMB Kikisuasanto TO ANWAR PEMAIN",
            raw={"NOREK": "119101022152500"},
        )
        clear_cm_cache()
        run = run_match(
            MatchRun.Relation.BRACKET_BANK, self.tol, toko=self.toko,
            date_from=dt.date(), date_to=dt.date(),
        )
        r = MatchResult.objects.get(run=run, left=fr)
        self.assertEqual(r.bucket, "tidak_cocok")
        self.assertEqual(r.reason_code, "no_money")
        # money boleh no_fr atau tidak masuk right — yang penting tidak dipasangkan ke FR ini
        self.assertFalse(
            MatchResult.objects.filter(run=run, left=fr, right=money, bucket="cocok").exists()
        )

    def test_b_flyer_tampung_cocok_fr_keluar_channel(self):
        """B: FR keluar channel QRIS FLYER ↔ mutasi QRFLYER TAMPUNG (norek tujuan CM)."""
        gw = SourceType.objects.get_or_create(key="gateway", defaults={"name": "Gateway"})[0]
        up_g = Upload.objects.create(
            source_type=gw, toko=self.toko, original_name="flyer_tampung.csv",
            owner_name="MUL ZMGZCRT",
        )
        dt = datetime(2026, 8, 22, 8, 44, 1)
        fr = self._fr_cm(
            "QRIS FLYER | DEPOSIT / WITHDRAW", "QRIS 000000556677",
            "-23787096", dt, desc="PINDAH DANA FYLER + BIAYA TRANSFER",
        )
        # seed norek tujuan sebagai CM (FR masuk terpisah — identitas norek)
        self._fr_cm(
            "BANK BRI | KIKI SUASANTO | TAMPUNG LAYER 2", "BRI 119101022152500",
            "1000", datetime(2026, 8, 20, 10, 0),
        )
        money = self._tx(
            gw, up_g, jenis="wd", amount="23787096", money="-23787096",
            dt=dt, counterparty="KIKISUASANTO",
            description="QRFLYER TAMPUNG BRI 119101022152500 KIKISUASANTO",
        )
        clear_cm_cache()
        run = run_match(
            MatchRun.Relation.BRACKET_BANK, self.tol, toko=self.toko,
            date_from=dt.date(), date_to=dt.date(),
        )
        r_ok = MatchResult.objects.get(run=run, left=fr)
        self.assertEqual(r_ok.bucket, "cocok")
        self.assertEqual(r_ok.right_id, money.id)
        self.assertEqual(r_ok.reason_code, "amount+channel_tampung")

    def test_c_typo_kilo_tanpa_sinyal_ab_tolak(self):
        """C: typo KILO≈KIKI saja tanpa sinyal A/B → score 0 (bukan primary)."""
        from types import SimpleNamespace

        from reconciliation.engine import _sesama_cm_identity

        fr = SimpleNamespace(raw={
            "Bank": "BANK BRI | NASRUL | DEPOSIT",
            "No. Rek Bank Member": "BRI 1550016356993",
        })
        bank = SimpleNamespace(
            counterparty="KILOSUASANTO",
            description="TRSF KE KILOSUASANTO",
            money_delta=Decimal("-100000"),
            upload=SimpleNamespace(owner_name="NASRUL"),
            raw={},
        )
        sc, reason = _sesama_cm_identity(
            fr, bank,
            cm_names=("KIKI SUASANTO", "NASRUL"),
            cm_reks=("1550016356993", "119101022152500"),
        )
        self.assertEqual(sc, 0.0)
        self.assertEqual(reason, "")

    def test_c_typo_kilo_dengan_sinyal_b_channel(self):
        """C: typo KILO≈KIKI diizinkan bila ada sinyal channel tampung (B)."""
        from types import SimpleNamespace

        from reconciliation.engine import _sesama_cm_identity

        fr = SimpleNamespace(raw={
            "Bank": "QRIS FLYER | DEPOSIT / WITHDRAW",
            "No. Rek Bank Member": "QRIS 000000556677",
        })
        bank = SimpleNamespace(
            counterparty="KILOSUASANTO",
            description="QRFLYER TAMPUNG BRI 119101022152500 KILOSUASANTO",
            money_delta=Decimal("-23787096"),
            upload=SimpleNamespace(owner_name="MUL ZMGZCRT"),
            raw={"Beneficiary Account": "119101022152500"},
        )
        sc, reason = _sesama_cm_identity(
            fr, bank,
            cm_names=("KIKI SUASANTO", "NASRUL"),
            cm_reks=("000000556677", "119101022152500"),
        )
        self.assertGreaterEqual(sc, 90)
        self.assertIn(reason, ("amount+channel_tampung", "amount+name_cm"))

    def test_abc_pasangan_pindah_flyer_ke_kiki(self):
        """E2E MUL-like: FR keluar Flyer + FR masuk Kiki ↔ tampung WD + kredit BRI."""
        gw = SourceType.objects.get_or_create(key="gateway", defaults={"name": "Gateway"})[0]
        up_g = Upload.objects.create(
            source_type=gw, toko=self.toko, original_name="MUTASI TAMPUNG QR FLYER.csv",
            owner_name="MUL ZMGZCRT",
        )
        dt = datetime(2026, 8, 22, 8, 44)
        fr_out = self._fr_cm(
            "QRIS FLYER | DEPOSIT / WITHDRAW", "QRIS 000000556677",
            "-23787096", dt, desc="PINDAH DANA FYLER + BIAYA TRANSFER",
        )
        fr_in = self._fr_cm(
            "BANK BRI | KIKI SUASANTO | TAMPUNG LAYER 2", "BRI 119101022152500",
            "23787096", dt, desc="PINDAH DANA FYLER + BIAYA TRANSFER",
        )
        flyer = self._tx(
            gw, up_g, jenis="wd", amount="23787096", money="-23787096",
            dt=dt, counterparty="KILOSUASANTO",
            description="QRFLYER TAMPUNG BRI 119101022152500 KILOSUASANTO",
        )
        bri = self._tx(
            self.bank, self.up_k, jenis="depo", amount="23787096", money="23787096",
            dt=dt, counterparty="",
            description="1787363038aA8P7PC WS_OB ESB:APFT:000TP00F:000372912238",
            raw={"NOREK": "119101022152500", "GLSIGN": "Cr"},
        )
        clear_cm_cache()
        run = run_match(
            MatchRun.Relation.BRACKET_BANK, self.tol, toko=self.toko,
            date_from=dt.date(), date_to=dt.date(),
        )
        r_out = MatchResult.objects.get(run=run, left=fr_out)
        r_in = MatchResult.objects.get(run=run, left=fr_in)
        self.assertEqual(r_out.bucket, "cocok")
        self.assertEqual(r_out.right_id, flyer.id)
        self.assertEqual(r_in.bucket, "cocok")
        self.assertEqual(r_in.right_id, bri.id)

    def test_cutoff_uang_h1_cocok_seperti_panel_bank(self):
        """Cutoff mutasi: FR jam malam D, uang D+1 → cocok (date_ok terarah window 1)."""
        fr_dt = datetime(2026, 8, 22, 23, 30)
        money_dt = datetime(2026, 8, 23, 0, 15)
        fr = self._fr_cm(
            "BANK BRI | KIKI SUASANTO | TAMPUNG", "BRI 119101022152500",
            "3000000", fr_dt,
        )
        money = self._tx(
            self.bank, self.up_k, jenis="depo", amount="3000000", money="3000000",
            dt=money_dt, counterparty="",
            description="ESB:APFT:cutoff",
            raw={"NOREK": "119101022152500", "GLSIGN": "Cr"},
        )
        clear_cm_cache()
        run = run_match(
            MatchRun.Relation.BRACKET_BANK, self.tol, toko=self.toko,
            date_from=fr_dt.date(), date_to=money_dt.date(),
        )
        r = MatchResult.objects.get(run=run, left=fr)
        self.assertEqual(r.bucket, "cocok")
        self.assertEqual(r.right_id, money.id)

    def test_uang_mendahului_fr_tidak_cocok(self):
        """Uang D-1 vs FR D tidak dipasangkan — sama panel↔bank (bukan abs hari)."""
        fr_dt = datetime(2026, 8, 22, 10, 0)
        money_dt = datetime(2026, 8, 21, 22, 0)
        fr = self._fr_cm(
            "BANK BRI | KIKI SUASANTO | TAMPUNG", "BRI 119101022152500",
            "4000000", fr_dt,
        )
        money = self._tx(
            self.bank, self.up_k, jenis="depo", amount="4000000", money="4000000",
            dt=money_dt, counterparty="",
            description="ESB:APFT:before",
            raw={"NOREK": "119101022152500"},
        )
        clear_cm_cache()
        run = run_match(
            MatchRun.Relation.BRACKET_BANK, self.tol, toko=self.toko,
            date_from=money_dt.date(), date_to=fr_dt.date(),
        )
        r = MatchResult.objects.get(run=run, left=fr)
        self.assertEqual(r.bucket, "tidak_cocok")
        self.assertEqual(r.reason_code, "no_money")
        self.assertFalse(
            MatchResult.objects.filter(run=run, left=fr, right=money, bucket="cocok").exists()
        )

    def test_late_settlement_sesama_cm_flip_batch_asal(self):
        """FR Sesama no_money D menunggu; uang D+1 → flip late_settlement di batch asal."""
        d22 = datetime(2026, 8, 22, 23, 45)
        d23 = datetime(2026, 8, 23, 1, 0)
        # minimal panel+bank agar run_batch panel_bank juga jalan
        self._tx(self.panel, self.up_p, jenis="depo", amount="100000", money="100000",
                 dt=d22, ticket="D22x", username="p", counterparty="PLAYER X")
        self._tx(self.bank, self.up_n, jenis="depo", amount="100000", money="100000",
                 dt=d22, counterparty="PLAYER X", description="TRSF PLAYER X")
        fr = self._fr_cm(
            "BANK BRI | KIKI SUASANTO | TAMPUNG", "BRI 119101022152500",
            "5500000", d22,
        )
        clear_cm_cache()
        b22 = run_batch(
            self.toko, self.tol, date_from=d22.date(), date_to=d22.date(),
            recon_date=d22.date(),
        )
        r22 = MatchResult.objects.get(
            run__batch=b22, run__relation="bracket_bank", left=fr,
        )
        self.assertEqual(r22.bucket, "tidak_cocok")
        self.assertEqual(r22.reason_code, "no_money")
        self.assertIsNone(fr.consumed_by_batch_id)  # menunggu settlement

        # hari berikutnya: panel + money member + uang Sesama CM
        self._tx(self.panel, self.up_p, jenis="depo", amount="110000", money="110000",
                 dt=d23, ticket="D23x", username="q", counterparty="PLAYER Y")
        self._tx(self.bank, self.up_n, jenis="depo", amount="110000", money="110000",
                 dt=d23, counterparty="PLAYER Y", description="TRSF PLAYER Y")
        money = self._tx(
            self.bank, self.up_k, jenis="depo", amount="5500000", money="5500000",
            dt=d23, counterparty="",
            description="ESB:APFT:late",
            raw={"NOREK": "119101022152500"},
        )
        clear_cm_cache()
        b23 = run_batch(
            self.toko, self.tol, date_from=d22.date(), date_to=d23.date(),
            recon_date=d23.date(),
        )
        r22.refresh_from_db()
        fr.refresh_from_db()
        self.assertEqual(r22.bucket, "cocok")
        self.assertEqual(r22.reason_code, "late_settlement")
        self.assertEqual(r22.right_id, money.id)
        self.assertEqual(r22.resolved_by_batch_id, b23.id)
        self.assertEqual(fr.consumed_by_batch_id, b22.id)
