"""Matcher v2 (multi-pass) + B1 carry uang + B2 uang tanpa pasangan.

Skenario di sini mereplikasi temuan audit trial OKE25 27–29 Juni:
salah-sanding lintas-rekening, pencurian kandidat, ticket gateway, fee, H-1,
uang lintas-hari terkunci, dan klasifikasi uang tak berpasangan A–D.
"""
from datetime import datetime
from decimal import Decimal

from django.test import TestCase

from reconciliation.engine import run_batch, run_match
from reconciliation.models import MatchResult, MatchRun, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

D = Decimal


def _st(key):
    return SourceType.objects.get_or_create(key=key, defaults={"name": key.title()})[0]


class _Base(TestCase):
    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.toko = Toko.objects.get(key="lbs")
        self.panel, self.bank, self.gw = _st("panel"), _st("bank"), _st("gateway")
        self.up_panel = Upload.objects.create(
            source_type=self.panel, toko=self.toko, original_name="HISTORI DP PANEL.xlsx"
        )
        self.up_hendi = Upload.objects.create(
            source_type=self.bank, toko=self.toko, original_name="27_WD_BCA_HENDI.csv"
        )
        self.up_nijun = Upload.objects.create(
            source_type=self.bank, toko=self.toko, original_name="27_WD_BCA_NIJUN.csv"
        )
        self.up_qr = Upload.objects.create(
            source_type=self.gw, toko=self.toko, original_name="MUTASI DP QR FLYER.xlsx"
        )
        self._n = 0

    def tx(self, st, up, jenis, amount, md, dt, *, ticket="", user="", cp="", raw=None):
        self._n += 1
        return Transaction.objects.create(
            upload=up, source_type=st, toko=self.toko, jenis=jenis,
            amount=D(amount), money_delta=D(md), occurred_at=dt,
            ticket_no=ticket, username=user, counterparty=cp, raw=raw or {},
            row_hash=f"h{self._n}",
        )

    def match(self):
        return run_match(
            MatchRun.Relation.PANEL_BANK, self.tol, toko=self.toko
        )


class Pass0TicketGatewayTests(_Base):
    def test_ticket_join_menang_atas_nama(self):
        # Gateway ber-ticket harus dipasangkan via ticket — bukan direbut fuzzy
        # oleh baris panel lain yang namanya lebih mirip (temuan: 834 salah sanding).
        p1 = self.tx(self.panel, self.up_panel, "depo", "50000", "50000",
                     datetime(2026, 6, 27, 10), ticket="D111", user="budi88", cp="BUDI SANTOSO")
        p2 = self.tx(self.panel, self.up_panel, "depo", "50000", "50000",
                     datetime(2026, 6, 27, 11), ticket="D222", user="anton1", cp="ANTON WIJAYA")
        g1 = self.tx(self.gw, self.up_qr, "depo", "50000", "50000",
                     datetime(2026, 6, 27, 10, 5), ticket="D222", user="budi88", cp="QRIS")
        run = self.match()
        r2 = MatchResult.objects.get(left=p2)
        self.assertEqual(r2.right_id, g1.id)
        self.assertEqual(r2.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r2.reason_code, "ticket")
        r1 = MatchResult.objects.get(left=p1)
        self.assertIsNone(r1.right_id)  # tak boleh menyambar gateway ticket orang

    def test_ticket_sama_nominal_beda_jadi_tinjau(self):
        p = self.tx(self.panel, self.up_panel, "depo", "50000", "50000",
                    datetime(2026, 6, 27, 10), ticket="D333", user="cici", cp="CICI P")
        g = self.tx(self.gw, self.up_qr, "depo", "51000", "51000",
                    datetime(2026, 6, 27, 10), ticket="D333", user="cici", cp="QRIS")
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.right_id, g.id)
        self.assertEqual(r.bucket, MatchResult.Bucket.TINJAU)
        self.assertEqual(r.reason_code, "ticket_amount")

    def test_gateway_ticket_asing_tidak_dipasangkan_fuzzy(self):
        p = self.tx(self.panel, self.up_panel, "depo", "50000", "50000",
                    datetime(2026, 6, 27, 10), ticket="D444", user="dodi", cp="DODI K")
        self.tx(self.gw, self.up_qr, "depo", "50000", "50000",
                datetime(2026, 6, 27, 10), ticket="D999", user="dodi", cp="QRIS")
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertIsNone(r.right_id)
        self.assertEqual(r.reason_code, "no_money")


class Pass1GlobalAssignTests(_Base):
    def test_kandidat_tidak_dicuri_baris_lemah(self):
        # P-lemah datang lebih dulu; P-kuat namanya persis. v2: P-kuat menang.
        p_weak = self.tx(self.panel, self.up_panel, "wd", "100000", "-100000",
                         datetime(2026, 6, 27, 9), ticket="W1", cp="ORANG LAIN")
        p_strong = self.tx(self.panel, self.up_panel, "wd", "100000", "-100000",
                           datetime(2026, 6, 27, 10), ticket="W2", cp="SITI AMINAH")
        m = self.tx(self.bank, self.up_hendi, "wd", "100000", "-100000",
                    datetime(2026, 6, 27, 12), cp="SITI AMINAH")
        self.match()
        self.assertEqual(MatchResult.objects.get(left=p_strong).right_id, m.id)
        self.assertEqual(MatchResult.objects.get(left=p_strong).bucket, MatchResult.Bucket.COCOK)
        self.assertIsNone(MatchResult.objects.get(left=p_weak).right_id)

    def test_route_prioritas_rekening_benar(self):
        # Dua kandidat nominal sama; panel menunjuk rekening HENDI via Bank Title.
        p = self.tx(self.panel, self.up_panel, "wd", "75000", "-75000",
                    datetime(2026, 6, 27, 9), ticket="W3", cp="JOKO S",
                    raw={"Bank Title": "BCA|HENDI|712620"})
        m_wrong = self.tx(self.bank, self.up_nijun, "wd", "75000", "-75000",
                          datetime(2026, 6, 27, 10), cp="SESEORANG")
        m_right = self.tx(self.bank, self.up_hendi, "wd", "75000", "-75000",
                          datetime(2026, 6, 27, 11), cp="ORANG BEDA")
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.right_id, m_right.id)
        self.assertEqual(r.bucket, MatchResult.Bucket.TINJAU)


class PhoneIdentityTests(_Base):
    def test_va_ewallet_nomor_hp_jadi_cocok(self):
        # Mutasi FTFVA/DANA tanpa nama pengirim tapi membawa nomor HP tujuan —
        # sama dengan raw['Player Bank'] panel → identitas kuat, cocok.
        p = self.tx(self.panel, self.up_panel, "wd", "126000", "-126000",
                    datetime(2026, 6, 27, 10), ticket="W7", cp="ANGGER PRAJA",
                    raw={"Player Bank": "DANA|Angger Praja |083174114447"})
        m = self.tx(self.bank, self.up_hendi, "wd", "126000", "-126000",
                    datetime(2026, 6, 27, 11), cp="",
                    raw={"line": "2706/FTFVA/WS9527172345/DANA - - 083174114447 126,000.00 DB",
                         "cont": "TRSF E-BANKING DB"})
        decoy = self.tx(self.bank, self.up_hendi, "wd", "126000", "-126000",
                        datetime(2026, 6, 27, 9), cp="",
                        raw={"line": "2706/FTFVA/WS9500000001/DANA - - 081234567890 126,000.00 DB"})
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.right_id, m.id)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.score, 100)

    def test_saldo_tidak_dianggap_nomor(self):
        # Deret digit saldo/nominal tidak boleh jadi "nomor HP".
        p = self.tx(self.panel, self.up_panel, "wd", "50000", "-50000",
                    datetime(2026, 6, 27, 10), ticket="W8", cp="TANPA HP",
                    raw={"Player Bank": "BCA|Tanpa Hp|12345678"})
        self.tx(self.bank, self.up_hendi, "wd", "50000", "-50000",
                datetime(2026, 6, 27, 11), cp="",
                raw={"Saldo": "12345678.00"})
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertNotEqual(r.bucket, MatchResult.Bucket.COCOK)


class Pass3NearMissTests(_Base):
    def test_fee_kecil_identitas_kuat_jadi_tinjau(self):
        p = self.tx(self.panel, self.up_panel, "wd", "50000", "-50000",
                    datetime(2026, 6, 27, 9), ticket="W4", cp="GUDEL NGULET")
        m = self.tx(self.bank, self.up_hendi, "wd", "52000", "-52000",
                    datetime(2026, 6, 27, 10), cp="GUDEL NGULET")
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.right_id, m.id)
        self.assertEqual(r.bucket, MatchResult.Bucket.TINJAU)
        self.assertEqual(r.reason_code, "amount_fee")

    def test_uang_h_minus_1_identitas_kuat_jadi_tinjau(self):
        p = self.tx(self.panel, self.up_panel, "depo", "80000", "80000",
                    datetime(2026, 6, 27, 9), ticket="D5", cp="RATna sari")
        m = self.tx(self.bank, self.up_hendi, "depo", "80000", "80000",
                    datetime(2026, 6, 26, 23), cp="RATNA SARI")
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.right_id, m.id)
        self.assertEqual(r.reason_code, "date_before")

    def test_fee_tanpa_identitas_tetap_no_money(self):
        p = self.tx(self.panel, self.up_panel, "wd", "50000", "-50000",
                    datetime(2026, 6, 27, 9), ticket="W6", cp="AAA BBB")
        self.tx(self.bank, self.up_hendi, "wd", "52000", "-52000",
                datetime(2026, 6, 27, 10), cp="ZZZ YYY")
        self.match()
        self.assertEqual(MatchResult.objects.get(left=p).reason_code, "no_money")


class B1CarryMoneyTests(_Base):
    def _seed_pair_27(self):
        p = self.tx(self.panel, self.up_panel, "depo", "10000", "10000",
                    datetime(2026, 6, 27, 8), ticket="D10", cp="PASANGAN OK")
        self.tx(self.bank, self.up_hendi, "depo", "10000", "10000",
                datetime(2026, 6, 27, 9), cp="PASANGAN OK")
        return p

    def test_uang_lintas_hari_tak_dikonsumsi_dan_match_besok(self):
        # Replikasi 8 korban: uang tgl 28 terbawa file yang diupload tgl 27.
        self._seed_pair_27()
        m28 = self.tx(self.bank, self.up_hendi, "wd", "295000", "-295000",
                      datetime(2026, 6, 28, 1), cp="WAWAN HERNAWAN")
        b27 = run_batch(self.toko, self.tol, recon_date=datetime(2026, 6, 27).date())
        m28.refresh_from_db()
        self.assertIsNone(m28.consumed_by_batch_id)  # tetap aktif
        p28 = self.tx(self.panel, self.up_panel, "wd", "295000", "-295000",
                      datetime(2026, 6, 28, 0, 30), ticket="W28", cp="WAWAN HERNAWAN")
        b28 = run_batch(self.toko, self.tol, recon_date=datetime(2026, 6, 28).date())
        r = MatchResult.objects.get(left=p28)
        self.assertEqual(r.right_id, m28.id)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        m28.refresh_from_db()
        self.assertEqual(m28.consumed_by_batch_id, b28.id)

    def test_uang_lintas_hari_yang_berpasangan_tetap_dikonsumsi(self):
        p27 = self.tx(self.panel, self.up_panel, "depo", "60000", "60000",
                      datetime(2026, 6, 27, 8), ticket="D11", cp="LINTAS HARI")
        m28 = self.tx(self.bank, self.up_hendi, "depo", "60000", "60000",
                      datetime(2026, 6, 28, 1), cp="LINTAS HARI")
        b27 = run_batch(self.toko, self.tol, recon_date=datetime(2026, 6, 27).date())
        m28.refresh_from_db()
        self.assertEqual(m28.consumed_by_batch_id, b27.id)


class B2UnmatchedMoneyTests(_Base):
    def test_klasifikasi_dan_hasil_no_panel(self):
        self.tx(self.panel, self.up_panel, "depo", "10000", "10000",
                datetime(2026, 6, 27, 8), ticket="D20", cp="PASANGAN OK")
        self.tx(self.bank, self.up_hendi, "depo", "10000", "10000",
                datetime(2026, 6, 27, 9), cp="PASANGAN OK")
        a = self.tx(self.bank, self.up_hendi, "depo", "11000", "11000",
                    datetime(2026, 6, 20, 9), cp="HISTORI LAMA")
        b = self.tx(self.gw, self.up_qr, "depo", "12000", "12000",
                    datetime(2026, 6, 27, 9), ticket="D777", user="asing", cp="QRIS")
        c = self.tx(self.bank, self.up_hendi, "depo", "13000", "13000",
                    datetime(2026, 6, 27, 9), cp="NIJUN")
        d = self.tx(self.bank, self.up_hendi, "wd", "14000", "-14000",
                    datetime(2026, 6, 27, 9), cp="TANPA PENJELASAN")
        batch = run_batch(self.toko, self.tol, recon_date=datetime(2026, 6, 27).date())
        um = batch.summary["unmatched_money"]
        self.assertEqual((um["a"]["n"], um["b"]["n"], um["c"]["n"], um["d"]["n"]),
                         (1, 1, 1, 1))
        self.assertEqual(um["d"]["wd"], 14000.0)
        self.assertFalse(MatchResult.objects.filter(right=a).exists())
        self.assertFalse(MatchResult.objects.filter(right=c).exists())
        rb = MatchResult.objects.get(right=b)
        rd = MatchResult.objects.get(right=d)
        for r in (rb, rd):
            self.assertIsNone(r.left_id)
            self.assertEqual(r.bucket, MatchResult.Bucket.TIDAK)
            self.assertEqual(r.reason_code, "no_panel")
        # semua terkonsumsi ke batch ini (tanggal <= recon_date)
        for t in (a, b, c, d):
            t.refresh_from_db()
            self.assertEqual(t.consumed_by_batch_id, batch.id)

    def test_run_tanpa_recon_date_tanpa_b2(self):
        self.tx(self.panel, self.up_panel, "depo", "10000", "10000",
                datetime(2026, 6, 27, 8), ticket="D21", cp="X Y")
        self.tx(self.bank, self.up_hendi, "wd", "15000", "-15000",
                datetime(2026, 6, 27, 9), cp="APAPUN")
        batch = run_batch(self.toko, self.tol)
        self.assertNotIn("unmatched_money", batch.summary)
        self.assertFalse(MatchResult.objects.filter(reason_code="no_panel",
                                                    run__relation=MatchRun.Relation.PANEL_BANK).exists())
