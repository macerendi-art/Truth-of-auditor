"""Gate settle gateway (K1): QR UNPAID/FAILED = uang BELUM masuk.

Parser QRFlyer/NXPay menelan SEMUA baris (status hanya tersimpan di raw), jadi
tanpa gate ini QR UNPAID ber-tiket sah dipasangkan COCOK oleh pass 0 — uang
yang tak pernah masuk dihitung masuk dan selisih riil TERSEMBUNYI. Aturan:

- hanya baris SETTLE yang boleh jadi pasangan (pass 0/0b) & kandidat fuzzy;
- tiket/reference ADA tapi tak ada yang settle -> terminal `gateway_unpaid`
  (tidak_cocok, BUKAN no_money: uang belum masuk itu FAKTA, jangan carried
  menunggu settlement);
- baris belum settle keluar dari gross uang & kategori uang tanpa pasangan 'e'.

Fail-open: status kosong / tak dikenal dianggap settle (QHoki/RPay/COR sudah
menyaring saat parse; jangan merusak parser yang tak menaruh kolom status).
"""
from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase

from reconciliation.engine import (
    pending_settlement_count,
    run_batch,
    run_batches_auto,
    run_match,
)
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
        self.up_qr = Upload.objects.create(
            source_type=self.gw, toko=self.toko, original_name="MUTASI DP QR FLYER.xlsx"
        )
        self.up_bank = Upload.objects.create(
            source_type=self.bank, toko=self.toko, original_name="27_DP_BCA_HENDI.csv"
        )
        self._n = 0

    def tx(self, st, up, jenis, amount, md, dt, *, ticket="", user="", cp="", ref="", raw=None):
        self._n += 1
        return Transaction.objects.create(
            upload=up, source_type=st, toko=self.toko, jenis=jenis,
            amount=D(amount), money_delta=D(md), occurred_at=dt,
            ticket_no=ticket, username=user, counterparty=cp, reference=ref,
            raw=raw or {}, row_hash=f"h{self._n}",
        )

    def match(self):
        return run_match(MatchRun.Relation.PANEL_BANK, self.tol, toko=self.toko)


class GatewayUnpaidGateTests(_Base):
    def test_unpaid_ticket_join_jadi_gateway_unpaid(self):
        # Tiket ADA di gateway tapi belum settle -> uang belum masuk. TERMINAL
        # tidak_cocok (bukan cocok, bukan no_money yang menunggu settlement).
        p = self.tx(self.panel, self.up_panel, "depo", "50000", "50000",
                    datetime(2026, 6, 27, 10), ticket="D555", user="budi", cp="BUDI")
        self.tx(self.gw, self.up_qr, "depo", "50000", "50000",
                datetime(2026, 6, 27, 10, 5), ticket="D555",
                raw={"Payment Status": "UNPAID"})
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.TIDAK)
        self.assertEqual(r.reason_code, "gateway_unpaid")
        self.assertIsNone(r.right_id)

    def test_settled_ticket_join_tetap_cocok(self):
        p = self.tx(self.panel, self.up_panel, "depo", "50000", "50000",
                    datetime(2026, 6, 27, 10), ticket="D556", user="cici", cp="CICI")
        g = self.tx(self.gw, self.up_qr, "depo", "50000", "50000",
                    datetime(2026, 6, 27, 10, 5), ticket="D556",
                    raw={"Payment Status": "Settled"})
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.reason_code, "ticket")
        self.assertEqual(r.right_id, g.id)

    def test_status_tak_dikenal_fail_open(self):
        # Status di luar kamus (mis. parser lain / kolom beda makna) -> anggap
        # settle: JANGAN merusak join yang hari ini sudah benar.
        p = self.tx(self.panel, self.up_panel, "depo", "75000", "75000",
                    datetime(2026, 6, 27, 10), ticket="D557", user="didi", cp="DIDI")
        g = self.tx(self.gw, self.up_qr, "depo", "75000", "75000",
                    datetime(2026, 6, 27, 10, 5), ticket="D557",
                    raw={"Status": "Approved"})
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.right_id, g.id)

    def test_unpaid_reference_join_juga_digate(self):
        p = self.tx(self.panel, self.up_panel, "depo", "60000", "60000",
                    datetime(2026, 6, 27, 10), user="eka", cp="EKA",
                    ref="F260627206100206205")
        self.tx(self.gw, self.up_qr, "depo", "60000", "60000",
                datetime(2026, 6, 27, 10, 5), ref="F260627206100206205",
                raw={"Payment Status": "FAILED"})
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.TIDAK)
        self.assertEqual(r.reason_code, "gateway_unpaid")

    def test_unpaid_tak_jadi_kandidat_fuzzy(self):
        # Baris gateway belum settle TANPA tiket/reference (pola RPay: kunci di
        # username/nama) tak boleh menyeberang ke pool fuzzy nominal+nama —
        # uangnya belum ada.
        p = self.tx(self.panel, self.up_panel, "depo", "80000", "80000",
                    datetime(2026, 6, 27, 10), ticket="D558", user="fafa",
                    cp="FAJAR SIDIK")
        self.tx(self.gw, self.up_qr, "depo", "80000", "80000",
                datetime(2026, 6, 27, 11), cp="FAJAR SIDIK",
                raw={"Payment Status": "UNPAID"})
        self.match()
        r = MatchResult.objects.get(left=p)
        self.assertIsNone(r.right_id)
        self.assertEqual(r.reason_code, "no_money")


class GatewayUnpaidBatchTests(_Base):
    def _run(self):
        return run_batch(
            self.toko, self.tol,
            date_from=date(2026, 6, 27), date_to=date(2026, 6, 27),
            recon_date=date(2026, 6, 27),
        )

    def test_unpaid_keluar_dari_gross_dan_kategori_e(self):
        p = self.tx(self.panel, self.up_panel, "depo", "50000", "50000",
                    datetime(2026, 6, 27, 10), ticket="D560", user="gina", cp="GINA")
        self.tx(self.gw, self.up_qr, "depo", "50000", "50000",
                datetime(2026, 6, 27, 10, 5), ticket="D560",
                raw={"Payment Status": "UNPAID"})
        g_paid = self.tx(self.gw, self.up_qr, "depo", "30000", "30000",
                         datetime(2026, 6, 27, 11), ticket="D561",
                         raw={"Payment Status": "PAID"})
        batch = self._run()
        # Gross DP hanya uang yang benar-benar masuk (baris PAID).
        self.assertEqual(batch.summary["dp"]["money_gross"], 30000.0)
        # Uang tanpa pasangan: PAID tanpa panel = 'b' (tiket asing);
        # UNPAID = 'e' (belum settle) TANPA hasil no_panel (bukan uang masuk).
        stats = batch.summary["unmatched_money"]
        self.assertEqual(stats["e"]["n"], 1)
        self.assertEqual(stats["b"]["n"], 1)
        run = batch.runs.get(relation=MatchRun.Relation.PANEL_BANK)
        no_panel = MatchResult.objects.filter(run=run, reason_code="no_panel")
        self.assertEqual(no_panel.count(), 1)  # hanya g_paid, bukan yang UNPAID
        self.assertEqual(no_panel.first().right_id, g_paid.id)
        # gateway_unpaid TERMINAL: baris panel dikonsumsi, tidak carried.
        p.refresh_from_db()
        self.assertEqual(p.consumed_by_batch_id, batch.id)
        self.assertEqual(pending_settlement_count(self.toko), 0)

    def test_verify_anchor_abaikan_unpaid(self):
        # Tanggal yang HANYA berisi QR belum settle bukan pelanggaran jangkar —
        # tak ada uang nyata yang butuh panel penutup.
        self.tx(self.panel, self.up_panel, "depo", "50000", "50000",
                datetime(2026, 6, 27, 10), ticket="D562", user="hani", cp="HANI")
        self.tx(self.gw, self.up_qr, "depo", "20000", "20000",
                datetime(2026, 6, 25, 9), ticket="D500",
                raw={"Payment Status": "EXPIRED"})
        res = run_batches_auto(self.toko, self.tol)
        self.assertTrue(res["ok"], res["violations"])
