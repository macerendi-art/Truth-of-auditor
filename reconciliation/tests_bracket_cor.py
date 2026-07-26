"""Panel↔Bracket untuk panel TANPA Ticket Number (Vigor / TM Gaming, mis. COR).

Panel Vigor/TMG tidak mengekspor Ticket Number sama sekali, jadi join lewat
ticket mustahil. Matcher punya DUA MODE (dipilih otomatis dari data):

* mode "ticket"   — Nexus: join Ticket Number (perilaku lama, tak berubah),
* mode "username" — panel tanpa ticket: anchor identitas UTAMA = username
  PERSIS; nominal + arah + tanggal hanya PENDUKUNG (blocking).

Catatan sejarah: modul ini dulu MEMATOK perilaku "panel tanpa ticket dilewati"
(`test_panel_tanpa_ticket_tak_emit_no_bracket`,
`test_run_batch_skip_panel_bracket_bila_tak_ada_ticket`). Spesifikasi itu
sengaja DIGANTI di Gelombang 10 — kedua tes ditulis ulang di bawah agar
memaku perilaku BARU, bukan dihapus diam-diam.
"""
from datetime import date, datetime
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from reconciliation.engine import run_batch, run_batches_auto, run_match
from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

D = Decimal


def _st(key):
    return SourceType.objects.get_or_create(key=key, defaults={"name": key.title()})[0]


class _Base(TestCase):
    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1})[0]
        self.toko = Toko.objects.get(key="g25")
        self.panel, self.bracket = _st("panel"), _st("bracket")
        self.bank = _st("bank")
        self.up_p = Upload.objects.create(source_type=self.panel, toko=self.toko,
                                          original_name="QRIS_deposit.xlsx")
        self.up_b = Upload.objects.create(source_type=self.bracket, toko=self.toko,
                                          original_name="Finance Report.xlsx")
        self.up_k = Upload.objects.create(source_type=self.bank, toko=self.toko,
                                          original_name="MUTASI BCA.csv")
        self._n = 0

    def tx(self, st, up, amount, dt, *, ticket="", username="", jenis="depo",
           posted=None):
        """Baris kanonik. Tanda money_delta mengikuti konvensi domain:
        DP uang masuk (+), WD uang keluar (−) — sama di panel maupun FR."""
        self._n += 1
        amt = D(amount)
        md = amt if jenis == "depo" else -amt
        if jenis not in ("depo", "wd"):
            md = amt
        return Transaction.objects.create(
            upload=up, source_type=st, toko=self.toko, jenis=jenis,
            amount=amt, money_delta=md, occurred_at=dt, posted_date=posted,
            ticket_no=ticket, username=username, row_hash=f"h{self._n}")

    def _run(self):
        return run_match(MatchRun.Relation.PANEL_BRACKET, self.tol, toko=self.toko)


class PanelBracketModeUsernameTests(_Base):
    """Mode username end-to-end lewat run_match."""

    def test_username_nominal_sama_jadi_cocok(self):
        p = self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                    username="budi88")
        b = self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10, 5),
                    username="budi88")
        run = self._run()
        self.assertEqual(run.summary["mode"], "username")
        res = MatchResult.objects.get(run=run)
        self.assertEqual(res.left_id, p.id)
        self.assertEqual(res.right_id, b.id)
        self.assertEqual(res.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(res.reason_code, "username_amount")
        self.assertEqual(res.score, 100)
        self.assertEqual(run.summary["cocok"], 1)
        self.assertEqual(run.summary["tidak_cocok"], 0)

    def test_username_beda_tak_dipasangkan(self):
        """Nominal + tanggal saja TIDAK PERNAH cukup — aturan anchor."""
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                username="budi88")
        self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10),
                username="siti99")
        run = self._run()
        self.assertEqual(run.summary["cocok"], 0)
        self.assertEqual(run.summary["tidak_cocok"], 2)  # no_bracket + no_panel

    def test_nominal_beda_tak_dipasangkan(self):
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                username="budi88")
        self.tx(self.bracket, self.up_b, "90000", datetime(2026, 7, 1, 10),
                username="budi88")
        run = self._run()
        self.assertEqual(run.summary["cocok"], 0)
        self.assertEqual(run.summary["tidak_cocok"], 2)

    def test_arah_dp_tak_kawin_dgn_wd(self):
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                username="budi88", jenis="depo")
        self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10),
                username="budi88", jenis="wd")
        run = self._run()
        self.assertEqual(run.summary["cocok"], 0)
        self.assertEqual(run.summary["tidak_cocok"], 2)

    def test_wd_juga_dipasangkan(self):
        p = self.tx(self.panel, self.up_p, "200000", datetime(2026, 7, 1, 10),
                    username="rina7", jenis="wd")
        b = self.tx(self.bracket, self.up_b, "200000", datetime(2026, 7, 1, 10, 3),
                    username="rina7", jenis="wd")
        run = self._run()
        res = MatchResult.objects.get(run=run)
        self.assertEqual((res.left_id, res.right_id), (p.id, b.id))
        self.assertEqual(res.bucket, MatchResult.Bucket.COCOK)

    def test_username_case_dan_spasi_dinormalisasi(self):
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                username=" Budi88 ")
        self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10),
                username="budi88")
        run = self._run()
        self.assertEqual(run.summary["cocok"], 1)

    def test_duplikat_kunci_diselesaikan_tanggal_terdekat(self):
        """Dua baris panel dengan (username, nominal) IDENTIK di hari berbeda,
        satu baris FR: yang menang = hari terdekat, bukan yang lebih dulu
        diiterasi (assignment GLOBAL, bukan greedy urut kiri)."""
        jauh = self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                       username="budi88")
        dekat = self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 2, 10),
                        username="budi88")
        b = self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 2, 11),
                    username="budi88")
        run = self._run()
        cocok = MatchResult.objects.get(run=run, bucket=MatchResult.Bucket.COCOK)
        self.assertEqual((cocok.left_id, cocok.right_id), (dekat.id, b.id))
        sisa = MatchResult.objects.get(run=run, bucket=MatchResult.Bucket.TIDAK)
        self.assertEqual(sisa.left_id, jauh.id)
        self.assertEqual(sisa.reason_code, "no_bracket")

    def test_panel_tanpa_ticket_kini_emit_no_bracket(self):
        """TULIS ULANG `test_panel_tanpa_ticket_tak_emit_no_bracket`.

        Lama: baris panel tanpa ticket sengaja TIDAK menghasilkan apa pun.
        Baru: selama sisi Bracket ada isinya, baris panel tanpa pasangan
        WAJIB menghasilkan no_bracket — kalau tidak, transaksi bisa hilang
        senyap dari rekonsiliasi."""
        p = self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                    username="budi88")
        self.tx(self.bracket, self.up_b, "50000", datetime(2026, 7, 1, 10),
                username="siti99")
        self._run()
        res = MatchResult.objects.get(left=p)
        self.assertEqual(res.bucket, MatchResult.Bucket.TIDAK)
        self.assertEqual(res.reason_code, "no_bracket")
        self.assertIn("username", res.reason_detail.lower())

    def test_tanpa_baris_bracket_tetap_mode_ticket(self):
        """Sisi Bracket kosong → tak ada yang bisa di-join: mode ticket
        (perilaku lama dipertahankan, baris panel tanpa ticket sunyi)."""
        p = self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                    username="budi88")
        run = self._run()
        self.assertEqual(run.summary["mode"], "ticket")
        self.assertFalse(MatchResult.objects.filter(left=p).exists())

    def test_panel_tanpa_username_jadi_no_bracket(self):
        p = self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                    username="")
        b = self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10),
                    username="budi88")
        run = self._run()
        rp = MatchResult.objects.get(left=p)
        self.assertEqual(rp.reason_code, "no_bracket")
        self.assertIn("tanpa username", rp.reason_detail.lower())
        rb = MatchResult.objects.get(right=b)
        self.assertIsNone(rb.left_id)
        self.assertEqual(rb.reason_code, "no_panel")
        self.assertEqual(run.summary["cocok"], 0)

    def test_bracket_sisa_depo_wd_jadi_no_panel(self):
        b = self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10),
                    username="andi", jenis="wd")
        self.tx(self.panel, self.up_p, "70000", datetime(2026, 7, 1, 10),
                username="budi88")
        self._run()
        res = MatchResult.objects.get(right=b)
        self.assertIsNone(res.left_id)
        self.assertEqual(res.bucket, MatchResult.Bucket.TIDAK)
        self.assertEqual(res.reason_code, "no_panel")

    def test_baris_fr_non_dp_wd_tanpa_hasil(self):
        """Bonus / beban admin / kategori lain di FR bukan transaksi panel —
        tidak boleh melahirkan no_panel palsu maupun mencuri pasangan."""
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                username="budi88")
        bonus = self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10),
                        username="budi88", jenis="bonus")
        admin = self.tx(self.bracket, self.up_b, "1000", datetime(2026, 7, 1, 10),
                        username="budi88", jenis="admin")
        lain = self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10),
                       username="budi88", jenis="lainnya")
        run = self._run()
        for t in (bonus, admin, lain):
            self.assertFalse(MatchResult.objects.filter(right=t).exists())
        self.assertEqual(run.summary["cocok"], 0)
        self.assertEqual(run.summary["tidak_cocok"], 1)  # hanya no_bracket panel

    def test_summary_right_hitung_baris_relevan_mode(self):
        """`right` yang dilaporkan = baris FR yang RELEVAN dengan mode (DP/WD),
        bukan panjang mentah sisi kanan — penyebut peringatan overlap ikut ini."""
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                username="budi88")
        self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10),
                username="budi88")
        for i in range(3):
            self.tx(self.bracket, self.up_b, f"{5000 + i}", datetime(2026, 7, 1, 10),
                    username="budi88", jenis="bonus")
        run = self._run()
        self.assertEqual(run.summary["left"], 1)
        self.assertEqual(run.summary["right"], 1)
        self.assertEqual(run.summary["cocok"], 1)


class PanelBracketJendelaTanggalTests(_Base):
    """Jendela tanggal SIMETRIS: posting FR dan approval panel bisa saling
    mendahului (backdated / lewat tengah malam)."""

    def _pair(self, hari_bracket):
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 2, 10),
                username="budi88")
        self.tx(self.bracket, self.up_b, "85000",
                datetime(2026, 7, hari_bracket, 10), username="budi88")
        return self._run()

    def test_bracket_h_minus_1_masih_cocok(self):
        self.assertEqual(self._pair(1).summary["cocok"], 1)

    def test_bracket_h_plus_1_masih_cocok(self):
        self.assertEqual(self._pair(3).summary["cocok"], 1)

    def test_bracket_di_luar_jendela_tak_cocok(self):
        run = self._pair(4)
        self.assertEqual(run.summary["cocok"], 0)
        self.assertEqual(run.summary["tidak_cocok"], 2)

    def test_posted_date_dipakai_lebih_dulu(self):
        """Baris FR 'Backdated': Transaction Date 22/07 23:59 tapi Tanggal
        (posted_date) 23/07 — panel-nya approved 22/07. Selisih 1 hari,
        masih dalam jendela."""
        self.tx(self.panel, self.up_p, "150000", datetime(2026, 7, 22, 23, 59),
                username="tutupboto", posted=date(2026, 7, 22))
        self.tx(self.bracket, self.up_b, "150000", datetime(2026, 7, 22, 23, 59),
                username="tutupboto", posted=date(2026, 7, 23))
        self.assertEqual(self._run().summary["cocok"], 1)


class PanelBracketModeTicketRegresiTests(_Base):
    """Regresi Nexus: selama panel punya ticket, hasilnya IDENTIK perilaku lama —
    baris FR tanpa ticket (bonus, beban admin, dst) tetap tak terlihat."""

    def test_campuran_ticketed_dan_tanpa_ticket(self):
        p1 = self.tx(self.panel, self.up_p, "50000", datetime(2026, 7, 1, 10),
                     ticket="D111111", username="budi88")
        p2 = self.tx(self.panel, self.up_p, "60000", datetime(2026, 7, 1, 11),
                     ticket="D222222", username="siti99")
        b1 = self.tx(self.bracket, self.up_b, "50000", datetime(2026, 7, 1, 10, 5),
                     ticket="D111111", username="budi88")
        bonus = self.tx(self.bracket, self.up_b, "60000", datetime(2026, 7, 1, 11, 5),
                        username="siti99", jenis="bonus")
        sisa = self.tx(self.bracket, self.up_b, "60000", datetime(2026, 7, 1, 11, 6),
                       username="siti99")   # DP tanpa ticket — tak terlihat mode ticket
        run = self._run()
        self.assertEqual(run.summary["mode"], "ticket")
        self.assertEqual(run.summary["right"], 1)   # hanya baris ber-ticket
        self.assertEqual(run.summary["cocok"], 1)
        self.assertEqual(run.summary["perlu_tinjau"], 0)
        self.assertEqual(run.summary["tidak_cocok"], 1)
        cocok = MatchResult.objects.get(run=run, bucket=MatchResult.Bucket.COCOK)
        self.assertEqual((cocok.left_id, cocok.right_id), (p1.id, b1.id))
        self.assertEqual(cocok.reason_code, "ticket+amount")
        tidak = MatchResult.objects.get(run=run, bucket=MatchResult.Bucket.TIDAK)
        self.assertEqual(tidak.left_id, p2.id)
        self.assertEqual(tidak.reason_code, "no_bracket")
        for t in (bonus, sisa):
            self.assertFalse(MatchResult.objects.filter(right=t).exists())

    def test_panel_tanpa_ticket_sunyi_saat_mode_ticket(self):
        """Panel campuran (ada yang ber-ticket, ada yang tidak): baris tanpa
        ticket TIDAK menghasilkan apa pun — persis perilaku lama."""
        self.tx(self.panel, self.up_p, "50000", datetime(2026, 7, 1, 10),
                ticket="D111111", username="budi88")
        polos = self.tx(self.panel, self.up_p, "70000", datetime(2026, 7, 1, 12),
                        username="andi")
        self.tx(self.bracket, self.up_b, "50000", datetime(2026, 7, 1, 10, 5),
                ticket="D111111", username="budi88")
        self.tx(self.bracket, self.up_b, "70000", datetime(2026, 7, 1, 12, 5),
                username="andi")
        run = self._run()
        self.assertEqual(run.summary["mode"], "ticket")
        self.assertFalse(MatchResult.objects.filter(left=polos).exists())
        self.assertEqual(run.summary["cocok"], 1)
        self.assertEqual(run.summary["tidak_cocok"], 0)

    def test_selisih_nominal_tetap_perlu_tinjau(self):
        self.tx(self.panel, self.up_p, "50000", datetime(2026, 7, 1, 10),
                ticket="D111111", username="budi88")
        self.tx(self.bracket, self.up_b, "40000", datetime(2026, 7, 1, 10, 5),
                ticket="D111111", username="budi88")
        run = self._run()
        self.assertEqual(run.summary["perlu_tinjau"], 1)
        self.assertEqual(
            MatchResult.objects.get(run=run).reason_code, "amount_mismatch")


class PanelBracketGerbangBatchTests(_Base):
    """Gerbang run_batch: relasi jalan selama ada Panel dalam rentang + Bracket."""

    def test_run_batch_cor_menjalankan_panel_bracket(self):
        """TULIS ULANG `test_run_batch_skip_panel_bracket_bila_tak_ada_ticket`.

        Lama: panel tanpa ticket → relasi DILEWATI ("Dilewati (data tidak ada)").
        Baru: relasi JALAN dalam mode username."""
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                username="budi88")
        self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10, 5),
                username="budi88")
        batch = run_batch(self.toko, self.tol, date_from=date(2026, 7, 1),
                          date_to=date(2026, 7, 1), recon_date=date(2026, 7, 1))
        rels = [r.relation for r in batch.runs.all()]
        self.assertIn(MatchRun.Relation.PANEL_BRACKET, rels)
        self.assertNotIn(MatchRun.Relation.PANEL_BRACKET.value,
                         batch.summary["skipped"])
        run = batch.runs.get(relation=MatchRun.Relation.PANEL_BRACKET)
        self.assertEqual(run.summary["mode"], "username")
        self.assertEqual(run.summary["cocok"], 1)
        self.assertEqual(run.summary["tidak_cocok"], 0)

    def test_skip_bila_bracket_absen(self):
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                username="budi88")
        self.tx(self.bank, self.up_k, "85000", datetime(2026, 7, 1, 11))
        batch = run_batch(self.toko, self.tol, date_from=date(2026, 7, 1),
                          date_to=date(2026, 7, 1), recon_date=date(2026, 7, 1))
        self.assertIn(MatchRun.Relation.PANEL_BRACKET.value,
                      batch.summary["skipped"])
        detail = batch.summary["skipped_detail"]["panel_bracket"]
        self.assertIn("Bracket", detail)

    def test_skip_bila_panel_kosong_dalam_rentang(self):
        self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10),
                username="budi88")
        self.tx(self.bank, self.up_k, "85000", datetime(2026, 7, 1, 11))
        batch = run_batch(self.toko, self.tol, date_from=date(2026, 7, 1),
                          date_to=date(2026, 7, 1), recon_date=date(2026, 7, 1))
        self.assertIn(MatchRun.Relation.PANEL_BRACKET.value,
                      batch.summary["skipped"])
        detail = batch.summary["skipped_detail"]["panel_bracket"]
        self.assertIn("Panel", detail)
        # Baris panel bisa ADA tapi semuanya carried (dikecualikan gerbang) —
        # kalimatnya tidak boleh menuduh filenya kosong.
        self.assertIn("menunggu settlement", detail)

    def test_skip_bila_bracket_tak_diikutkan(self):
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                username="budi88")
        self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10, 5),
                username="budi88")
        self.tx(self.bank, self.up_k, "85000", datetime(2026, 7, 1, 11))
        batch = run_batch(self.toko, self.tol, date_from=date(2026, 7, 1),
                          date_to=date(2026, 7, 1), recon_date=date(2026, 7, 1),
                          include={"bracket": False})
        self.assertIn(MatchRun.Relation.PANEL_BRACKET.value,
                      batch.summary["skipped"])
        self.assertIn("tidak diikutkan",
                      batch.summary["skipped_detail"]["panel_bracket"])

    def test_carried_tak_ikut_mode_username(self):
        """Baris kredit carry-over (menunggu settlement) tetap DIKECUALIKAN dari
        Panel↔Bracket di mode username — kesempatan pairing bracket-nya sudah
        lewat di batch asalnya; kalau ikut, batch baru menulis no_bracket dobel."""
        p27 = self.tx(self.panel, self.up_p, "50000", datetime(2026, 6, 27, 9),
                      username="budi88")
        run_batch(self.toko, self.tol, recon_date=date(2026, 6, 27))
        p27.refresh_from_db()
        self.assertIsNone(p27.consumed_by_batch)   # menunggu settlement
        # Hari 28 gaya COR: panel tanpa ticket + FR + mutasi bank.
        self.tx(self.panel, self.up_p, "60000", datetime(2026, 6, 28, 9),
                username="andi")
        self.tx(self.bracket, self.up_b, "60000", datetime(2026, 6, 28, 9, 5),
                username="andi")
        self.tx(self.bank, self.up_k, "60000", datetime(2026, 6, 28, 10))
        b28 = run_batch(self.toko, self.tol, recon_date=date(2026, 6, 28))
        pb = b28.runs.get(relation=MatchRun.Relation.PANEL_BRACKET)
        self.assertEqual(pb.summary["mode"], "username")
        self.assertFalse(MatchResult.objects.filter(run=pb, left=p27).exists())
        self.assertEqual(pb.summary["left"], 1)   # hanya baris hari 28
        self.assertEqual(pb.summary["cocok"], 1)

    def test_fr_backdated_cocok_di_run_harian_berscope(self):
        """Baris FR 'Backdated' lewat run HARIAN yang berscope tanggal.

        Tanggal (posted) = 2/7 tapi Transaction Date = 1/7 23:59 — persis baris
        FR yang dientri lewat tengah malam. Scope run mengikuti run_batches_auto
        (`date_from=lo … date_to=D`), jadi baris itu ikut terjaring, dan
        pencocokan yang mengutamakan posted_date menaruhnya di hari 2/7 —
        bukan menyeretnya ke baris panel hari 1/7."""
        # Hari 1/7 punya panel sendiri (username lain) supaya ada dua hari nyata.
        self.tx(self.panel, self.up_p, "50000", datetime(2026, 7, 1, 9),
                username="andi")
        self.tx(self.bracket, self.up_b, "50000", datetime(2026, 7, 1, 9, 5),
                username="andi", posted=date(2026, 7, 1))
        run_batch(self.toko, self.tol, date_from=date(2026, 7, 1),
                  date_to=date(2026, 7, 1), recon_date=date(2026, 7, 1))
        p = self.tx(self.panel, self.up_p, "150000", datetime(2026, 7, 2, 10),
                    username="tutupboto")
        b = self.tx(self.bracket, self.up_b, "150000", datetime(2026, 7, 1, 23, 59),
                    username="tutupboto", posted=date(2026, 7, 2))
        batch = run_batch(self.toko, self.tol, date_from=date(2026, 7, 1),
                          date_to=date(2026, 7, 2), recon_date=date(2026, 7, 2))
        pb = batch.runs.get(relation=MatchRun.Relation.PANEL_BRACKET)
        self.assertEqual(pb.summary["mode"], "username")
        self.assertEqual(pb.summary["cocok"], 1)
        self.assertEqual(pb.summary["tidak_cocok"], 0)
        res = MatchResult.objects.get(run=pb)
        self.assertEqual((res.left_id, res.right_id), (p.id, b.id))
        self.assertEqual(res.reason_code, "username_amount")


class PanelBracketAggregateTests(_Base):
    """Cross-check AGREGAT Panel vs Bracket (`_panel_bracket_total_warning`) —
    tetap hidup berdampingan dengan hasil per-baris mode username."""

    def test_warning_muncul_saat_total_beda(self):
        self.tx(self.panel, self.up_p, "100000", datetime(2026, 7, 1, 10),
                username="budi88")
        self.tx(self.bracket, self.up_b, "150000", datetime(2026, 7, 1, 10),
                username="budi88")   # beda 50% dari panel
        batch = run_batch(self.toko, self.tol, date_from=date(2026, 7, 1),
                          date_to=date(2026, 7, 1), recon_date=date(2026, 7, 1))
        joined = " ".join(batch.summary.get("warnings", []))
        self.assertIn("Panel↔Bracket DP total beda", joined)

    def test_tak_ada_warning_saat_total_sama(self):
        self.tx(self.panel, self.up_p, "100000", datetime(2026, 7, 1, 10),
                username="budi88")
        self.tx(self.bracket, self.up_b, "100000", datetime(2026, 7, 1, 10),
                username="budi88")
        batch = run_batch(self.toko, self.tol, date_from=date(2026, 7, 1),
                          date_to=date(2026, 7, 1), recon_date=date(2026, 7, 1))
        joined = " ".join(batch.summary.get("warnings", []))
        self.assertNotIn("Panel↔Bracket", joined)


class PanelBracketModeRasioTests(_Base):
    """Mode dipilih dari RASIO baris panel ber-ticket, BUKAN dari ada/tidaknya
    satu baris ber-ticket.

    Kenapa penting: satu file salah unggah (ekspor bergaya Nexus masuk ke toko
    COR) menyisipkan segelintir baris ber-ticket. Dengan aturan 'ada satu ticket
    → mode ticket', seluruh hari jadi SENYAP — sisi kanan menyusut ke 0 baris
    ber-ticket, tak ada pasangan, tak ada peringatan, dan tak seorang pun tahu
    rekonsiliasi hari itu tidak pernah benar-benar jalan."""

    def _panel_bracket_pair(self, username, amount, hari=1):
        self.tx(self.panel, self.up_p, amount, datetime(2026, 7, hari, 10),
                username=username)
        self.tx(self.bracket, self.up_b, amount, datetime(2026, 7, hari, 10, 5),
                username=username)

    def test_satu_ticket_nyasar_tak_memaksa_mode_ticket(self):
        nyasar = self.tx(self.panel, self.up_p, "10000", datetime(2026, 7, 1, 9),
                         ticket="D999999", username="nyasar")
        for i, u in enumerate(("budi88", "siti99", "andi")):
            self._panel_bracket_pair(u, f"{50000 + i}")
        run = self._run()
        self.assertEqual(run.summary["mode"], "username")
        self.assertEqual(run.summary["cocok"], 3)
        # Baris nyasar tetap DINILAI (punya username) — tak boleh hilang senyap.
        self.assertEqual(MatchResult.objects.get(left=nyasar).reason_code, "no_bracket")

    def test_baris_minoritas_ber_ticket_tetap_dipasangkan_lewat_username(self):
        """Di mode username baris panel yang KEBETULAN ber-ticket tidak dikucilkan:
        anchornya username, ticket cuma ikut menumpang."""
        p = self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 9),
                    ticket="D999999", username="budi88")
        b = self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 9, 5),
                    username="budi88")
        for i, u in enumerate(("siti99", "andi", "rina7")):
            self._panel_bracket_pair(u, f"{50000 + i}")
        run = self._run()
        self.assertEqual(run.summary["mode"], "username")
        res = MatchResult.objects.get(left=p)
        self.assertEqual(res.right_id, b.id)
        self.assertEqual(res.bucket, MatchResult.Bucket.COCOK)

    def test_mayoritas_ber_ticket_tetap_mode_ticket(self):
        """3 dari 4 baris panel ber-ticket = populasi Nexus asli → mode ticket."""
        for i in range(3):
            self.tx(self.panel, self.up_p, "50000", datetime(2026, 7, 1, 10),
                    ticket=f"D10000{i}", username="budi88")
            self.tx(self.bracket, self.up_b, "50000", datetime(2026, 7, 1, 10, 5),
                    ticket=f"D10000{i}", username="budi88")
        self.tx(self.panel, self.up_p, "50000", datetime(2026, 7, 1, 11),
                username="andi")
        run = self._run()
        self.assertEqual(run.summary["mode"], "ticket")
        self.assertEqual(run.summary["cocok"], 3)

    def test_tepat_separuh_ber_ticket_mode_ticket(self):
        """Ambang 50% INKLUSIF — seri dimenangkan mode ticket (perilaku lama)."""
        self.tx(self.panel, self.up_p, "50000", datetime(2026, 7, 1, 10),
                ticket="D111111", username="budi88")
        self.tx(self.panel, self.up_p, "70000", datetime(2026, 7, 1, 12),
                username="andi")
        self.tx(self.bracket, self.up_b, "50000", datetime(2026, 7, 1, 10, 5),
                ticket="D111111", username="budi88")
        self.assertEqual(self._run().summary["mode"], "ticket")


class PanelBracketTicketKontradiksiTests(_Base):
    """Di mode username, ticket yang MEMBANTAH mengalahkan kunci pemain.

    Mode username hanya menjangkarkan username; ticket ikut menumpang. Tapi
    dalam rezim campuran (minoritas baris ber-ticket) bisa muncul pasangan yang
    KEDUA sisinya punya ticket dan tickets-nya BERBEDA — itu bukti keras dua
    transaksi berlainan. Aturan anchor: kunci transaksi yang membantah harus
    membatalkan pasangan, bukan dikalahkan kebetulan username+nominal sama.
    """

    def _isi_agar_mode_username(self, mulai=0):
        """3 pasang panel/FR tanpa ticket → rasio ber-ticket < 50% (mode username)."""
        for i, u in enumerate(("siti99", "andi", "rina7")):
            amt = f"{50000 + mulai + i}"
            self.tx(self.panel, self.up_p, amt, datetime(2026, 7, 1, 10),
                    username=u)
            self.tx(self.bracket, self.up_b, amt, datetime(2026, 7, 1, 10, 5),
                    username=u)

    def test_ticket_berbeda_membatalkan_pasangan_username(self):
        p = self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 9),
                    ticket="D999999", username="budi88")
        b = self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 9, 5),
                    ticket="D111111", username="budi88")
        self._isi_agar_mode_username()
        run = self._run()
        self.assertEqual(run.summary["mode"], "username")
        self.assertEqual(run.summary["cocok"], 3)   # hanya 3 pasang pengisi
        kiri = MatchResult.objects.get(left=p)
        self.assertIsNone(kiri.right_id)
        self.assertEqual(kiri.reason_code, "no_bracket")
        kanan = MatchResult.objects.get(right=b)
        self.assertIsNone(kanan.left_id)
        self.assertEqual(kanan.reason_code, "no_panel")

    def test_ticket_sama_tetap_dipasangkan(self):
        """Ticket identik = KONFIRMASI, bukan bantahan — pasangan tetap terbentuk."""
        p = self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 9),
                    ticket="D999999", username="budi88")
        b = self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 9, 5),
                    ticket="D999999", username="budi88")
        self._isi_agar_mode_username()
        run = self._run()
        self.assertEqual(run.summary["mode"], "username")
        res = MatchResult.objects.get(left=p)
        self.assertEqual(res.right_id, b.id)
        self.assertEqual(res.bucket, MatchResult.Bucket.COCOK)

    def test_ticket_hanya_di_sisi_bracket_tetap_dipasangkan(self):
        """Kasus COR normal (cermin dari sisi panel): satu sisi kosong = tak ada
        bantahan, jadi username tetap menjangkarkan pasangan."""
        p = self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 9),
                    username="budi88")
        b = self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 9, 5),
                    ticket="D999999", username="budi88")
        self._isi_agar_mode_username()
        self.assertEqual(self._run().summary["mode"], "username")
        res = MatchResult.objects.get(left=p)
        self.assertEqual(res.right_id, b.id)
        self.assertEqual(res.bucket, MatchResult.Bucket.COCOK)

    def test_ticket_membantah_tak_menghalangi_kandidat_lain(self):
        """Baris FR ber-ticket yang membantah tidak boleh 'memakan' baris panel:
        kandidat FR lain dengan username+nominal sama tetap boleh dipasangkan."""
        p = self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 9),
                    ticket="D999999", username="budi88")
        self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 9, 1),
                ticket="D111111", username="budi88")           # membantah
        sah = self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 9, 5),
                      username="budi88")                        # tanpa ticket → sah
        self._isi_agar_mode_username()
        self.assertEqual(self._run().summary["mode"], "username")
        res = MatchResult.objects.get(left=p)
        self.assertEqual(res.right_id, sah.id)
        self.assertEqual(res.bucket, MatchResult.Bucket.COCOK)


class PanelBracketPeringatanPopulasiTests(_Base):
    """Peringatan batch untuk populasi yang TIDAK ternilai relasi ini."""

    def _batch(self):
        return run_batch(self.toko, self.tol, date_from=date(2026, 7, 1),
                         date_to=date(2026, 7, 1), recon_date=date(2026, 7, 1))

    def _warnings(self):
        return " ".join(self._batch().summary.get("warnings", []))

    def test_peringatan_saat_ada_panel_tanpa_ticket_di_mode_ticket(self):
        for i in range(3):
            self.tx(self.panel, self.up_p, "50000", datetime(2026, 7, 1, 10),
                    ticket=f"D10000{i}", username="budi88")
            self.tx(self.bracket, self.up_b, "50000", datetime(2026, 7, 1, 10, 5),
                    ticket=f"D10000{i}", username="budi88")
        self.tx(self.panel, self.up_p, "50000", datetime(2026, 7, 1, 11),
                username="andi")   # tak dinilai sama sekali di mode ticket
        joined = self._warnings()
        self.assertIn("1 baris Panel tanpa ticket", joined)

    def test_tak_ada_peringatan_bila_semua_panel_ber_ticket(self):
        self.tx(self.panel, self.up_p, "50000", datetime(2026, 7, 1, 10),
                ticket="D111111", username="budi88")
        self.tx(self.bracket, self.up_b, "50000", datetime(2026, 7, 1, 10, 5),
                ticket="D111111", username="budi88")
        self.assertNotIn("tanpa ticket", self._warnings())

    def test_tak_ada_peringatan_ticket_di_mode_username(self):
        """Mode username menilai SEMUA baris panel — tak ada populasi terbuang."""
        self.tx(self.panel, self.up_p, "50000", datetime(2026, 7, 1, 10),
                username="budi88")
        self.tx(self.bracket, self.up_b, "50000", datetime(2026, 7, 1, 10, 5),
                username="budi88")
        self.assertNotIn("tanpa ticket", self._warnings())

    def test_peringatan_saat_fr_tak_punya_baris_dp_wd(self):
        """Hari RUSAK: file FR hanya berisi beban admin/kategori lain, jadi tak ada
        satu pun kandidat. Peringatan overlap lama mati total di kasus ini (syaratnya
        `right` > 0), padahal justru inilah hari yang perlu diteriakkan."""
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                username="budi88")
        self.tx(self.bracket, self.up_b, "1000", datetime(2026, 7, 1, 10),
                username="budi88", jenis="admin")
        self.tx(self.bracket, self.up_b, "5000", datetime(2026, 7, 1, 11),
                jenis="lainnya")
        joined = self._warnings()
        self.assertIn("Deposit/Withdraw", joined)
        self.assertIn("periksa file FR", joined)

    def test_tak_ada_peringatan_fr_kosong_bila_ada_kandidat(self):
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                username="budi88")
        self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10, 5),
                username="budi88")
        self.assertNotIn("periksa file FR", self._warnings())


class PanelBracketDetailAlasanTests(_Base):
    """Alasan sisi kiri & sisi kanan harus SIMETRIS: baris tanpa anchor diberi
    tahu bahwa ia tak punya anchor, bukan dituduh 'tak ada pasangannya'."""

    def test_bracket_tanpa_username_punya_alasan_sendiri(self):
        b = self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10),
                    username="")
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                username="budi88")
        self._run()
        res = MatchResult.objects.get(right=b)
        self.assertIsNone(res.left_id)
        self.assertEqual(res.reason_code, "no_panel")
        self.assertIn("tanpa username", res.reason_detail.lower())

    def test_bracket_ber_username_tetap_alasan_lama(self):
        b = self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10),
                    username="siti99")
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                username="budi88")
        self._run()
        res = MatchResult.objects.get(right=b)
        self.assertIn("Tidak ada baris Panel", res.reason_detail)


class PanelBracketModeDiUITests(_Base):
    """`summary["mode"]` harus terbaca pengguna, bukan hanya tersimpan."""

    def setUp(self):
        super().setUp()
        get_user_model().objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")

    def _batch_html(self):
        batch = run_batch(self.toko, self.tol, date_from=date(2026, 7, 1),
                          date_to=date(2026, 7, 1), recon_date=date(2026, 7, 1))
        return self.client.get(reverse("batch_detail", args=[batch.pk]))

    def test_mode_username_dijelaskan_di_tabel_relasi(self):
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                username="budi88")
        self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10, 5),
                username="budi88")
        self.assertContains(self._batch_html(), "join username+nominal")

    def test_mode_ticket_tanpa_catatan(self):
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10),
                ticket="D111111", username="budi88")
        self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10, 5),
                ticket="D111111", username="budi88")
        self.assertNotContains(self._batch_html(), "join username+nominal")


class PanelBracketPeringatanTotalCarriedTests(_Base):
    """Peringatan agregat "total beda" hanya boleh menilai baris SEGAR batch ini.

    Baris kredit yang menunggu settlement (carried) nilainya sudah tercatat di
    batch ASALnya — persis alasan `_aggregate_batch` mengecualikannya. Tanpa
    pengecualian yang sama, dua hari yang rekonsiliasinya SEMPURNA tetap
    meneriakkan "Panel↔Bracket DP total beda" di hari kedua: baris panel hari-1
    masih aktif (menunggu mutasi), sedangkan pasangan FR-nya sudah dikonsumsi.
    """

    def _pasangan(self, hari, amount, username):
        self.tx(self.panel, self.up_p, amount, datetime(2026, 7, hari, 10),
                username=username)
        self.tx(self.bracket, self.up_b, amount, datetime(2026, 7, hari, 10, 5),
                username=username)

    def _batch_tanggal(self, hasil, hari):
        return next(b for b in hasil["batches"] if b.recon_date == date(2026, 7, hari))

    def test_baris_carried_tak_memicu_peringatan_total(self):
        # Tanpa mutasi bank: baris panel hari-1 jadi no_money → carried ke hari-2.
        self._pasangan(1, "150000", "budi88")
        self._pasangan(2, "88000", "siti99")
        hasil = run_batches_auto(self.toko, self.tol)
        self.assertTrue(hasil["ok"], hasil.get("violations"))
        b2 = self._batch_tanggal(hasil, 2)
        joined = " ".join(b2.summary.get("warnings", []))
        self.assertNotIn("total beda", joined)

    def test_total_benar_benar_beda_tetap_diperingatkan(self):
        """Penjaga positif-benar: file FR yang memang kurang tetap diteriakkan."""
        self._pasangan(1, "150000", "budi88")
        self.tx(self.panel, self.up_p, "88000", datetime(2026, 7, 2, 10),
                username="siti99")
        self.tx(self.bracket, self.up_b, "20000", datetime(2026, 7, 2, 10, 5),
                username="siti99")
        hasil = run_batches_auto(self.toko, self.tol)
        self.assertTrue(hasil["ok"], hasil.get("violations"))
        joined = " ".join(self._batch_tanggal(hasil, 2).summary.get("warnings", []))
        self.assertIn("total beda", joined)
