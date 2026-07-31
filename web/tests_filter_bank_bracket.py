"""Chip "(Tanpa Bank)" pada tab berpasangan (Perlu Ditinjau / Tidak Cocok).

Keluhan end user: run **Panel ↔ Bracket** untuk toko ber-panel Vigor/TM Gaming
(mis. COR/Gacor25) tak punya filter bank sama sekali di kedua tab itu. Sebabnya
baris panel QRIS memang TANPA kolom bank, sedangkan builder chip lama membuang
nilai kosong (`__gt=""`) — daftar opsi jadi kosong dan template menyembunyikan
SELURUH bar filter.

Nilai kosong kini dikelompokkan ke sentinel "(Tanpa Bank)": fold-nya tetap
muncul dan baris tanpa bank jadi kelompok yang bisa disaring. Sentinel selalu
di urutan terakhir, dan hanya baris ber-sisi-kiri yang dihitung — bank pemain
adalah konsep sisi panel.
"""
import re
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()

SENTINEL = "(Tanpa Bank)"
AKUN_FR = "BANK BCA | HENDI | WITHDRAW"


class _Base(TestCase):
    def setUp(self):
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.toko = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.panel = SourceType.objects.get_or_create(
            key="panel", defaults={"name": "Panel"}
        )[0]
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"}
        )[0]
        self.up_panel = Upload.objects.create(source_type=self.panel, toko=self.toko)
        self.up_fr = Upload.objects.create(
            source_type=self.bracket, toko=self.toko, original_name="FR COR 30-07.xlsx"
        )
        self.batch = ReconBatch.objects.create(
            toko=self.toko, tolerance=self.tol,
            recon_date=datetime(2026, 7, 30).date(),
        )
        self.run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BRACKET, tolerance=self.tol, batch=self.batch
        )
        self._n = 0

    def _tx(self, st, upload, **kw):
        self._n += 1
        d = dict(
            upload=upload, source_type=st, toko=self.toko, jenis="depo",
            amount=Decimal("15000"), occurred_at=datetime(2026, 7, 30, 10, 0),
            posted_date=self.batch.recon_date, raw={},
        )
        d.update(kw)
        return Transaction.objects.create(row_hash=f"t{self._n}", **d)

    def panel_row(self, player_bank="", bank_title="", **kw):
        """Baris panel. Default TANPA kolom bank — persis ekspor COR QRIS DP."""
        return self._tx(
            self.panel, self.up_panel, player_bank=player_bank,
            bank_title=bank_title, username=f"player{self._n}", **kw
        )

    def fr_row(self, akun=AKUN_FR, **kw):
        return self._tx(
            self.bracket, self.up_fr, money_delta=Decimal("15000"),
            raw={"Bank": akun, "Kategori": "Deposit"}, **kw
        )

    def hasil(self, bucket, left=None, right=None, reason=""):
        return MatchResult.objects.create(
            run=self.run, bucket=bucket, left=left, right=right, reason_code=reason
        )

    def get(self, **q):
        url = reverse("run_detail", args=[self.run.pk])
        if q:
            url += "?" + urlencode(q)
        return self.client.get(url)


class FoldTetapMunculTests(_Base):
    """Run QRIS-berat: semua baris panel tanpa bank → bar filter tak boleh lenyap."""

    def setUp(self):
        super().setUp()
        for _ in range(3):
            self.hasil(MatchResult.Bucket.TIDAK, self.panel_row(), None, "no_bracket")

    def test_kedua_fold_terender_dengan_chip_sentinel(self):
        r = self.get(bucket="tidak_cocok")
        self.assertContains(r, "Filter bank pemain")
        self.assertContains(r, "Filter bank title")
        self.assertContains(r, SENTINEL)

    def test_chip_sentinel_menghitung_seluruh_baris_kosong(self):
        c = self.get(bucket="tidak_cocok").context
        self.assertEqual(c["banks"], [{"code": SENTINEL, "n": 3}])
        self.assertEqual(c["btitles"], [{"code": SENTINEL, "n": 3}])


class CampuranTests(_Base):
    """Sebagian berbank, sebagian kosong: chip nyata dulu, sentinel TERAKHIR.

    Sentinel sengaja dibuat lebih banyak (3) daripada chip nyata (2) supaya
    posisi terakhirnya terbukti aturan, bukan efek samping urutan `-n`.
    """

    def setUp(self):
        super().setUp()
        for _ in range(2):
            row = self.panel_row(player_bank="BCA", bank_title="BCA VIRTUAL")
            self.hasil(MatchResult.Bucket.TIDAK, row, None, "no_bracket")
        for _ in range(3):
            self.hasil(MatchResult.Bucket.TIDAK, self.panel_row(), None, "no_bracket")

    def test_chip_nyata_duluan_sentinel_terakhir(self):
        c = self.get(bucket="tidak_cocok").context
        self.assertEqual(c["banks"], [{"code": "BCA", "n": 2}, {"code": SENTINEL, "n": 3}])
        self.assertEqual(
            c["btitles"], [{"code": "BCA VIRTUAL", "n": 2}, {"code": SENTINEL, "n": 3}]
        )

    def test_filter_bank_sentinel_hanya_baris_kosong(self):
        c = self.get(bucket="tidak_cocok", bank=SENTINEL).context
        rows = list(c["page"])
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r.left.player_bank == "" for r in rows))
        self.assertEqual(c["totals"]["n"], 3)

    def test_filter_btitle_sentinel_hanya_baris_kosong(self):
        c = self.get(bucket="tidak_cocok", btitle=SENTINEL).context
        rows = list(c["page"])
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r.left.bank_title == "" for r in rows))
        self.assertEqual(c["totals"]["n"], 3)

    def test_filter_bank_nyata_tetap_jalan(self):
        rows = list(self.get(bucket="tidak_cocok", bank="BCA").context["page"])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.left.player_bank == "BCA" for r in rows))


class PerluTinjauTests(_Base):
    """Tab Perlu Ditinjau (hasil berpasangan) juga harus dapat fold filternya."""

    def setUp(self):
        super().setUp()
        for _ in range(2):
            self.hasil(
                MatchResult.Bucket.TINJAU, self.panel_row(), self.fr_row(), "manual_override"
            )

    def test_fold_terender_di_perlu_tinjau(self):
        r = self.get(bucket="perlu_tinjau")
        self.assertContains(r, "Filter bank pemain")
        self.assertContains(r, SENTINEL)
        self.assertEqual(r.context["banks"], [{"code": SENTINEL, "n": 2}])


class AntreanTinjauTests(_Base):
    """/tinjau/ memakai jalur chip yang sama — jangan cuma satu halaman diperbaiki."""

    def setUp(self):
        super().setUp()
        for _ in range(2):
            self.hasil(MatchResult.Bucket.TIDAK, self.panel_row(), None, "no_bracket")
        row = self.panel_row(player_bank="BCA")
        self.hasil(MatchResult.Bucket.TIDAK, row, None, "no_bracket")
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})

    def antrean(self, **q):
        return self.client.get(reverse("review_queue") + "?" + urlencode(q))

    def test_chip_sentinel_di_antrean(self):
        c = self.antrean(bucket="tidak_cocok").context
        self.assertEqual(c["banks"], [{"code": "BCA", "n": 1}, {"code": SENTINEL, "n": 2}])

    def test_filter_sentinel_round_trip_di_antrean(self):
        c = self.antrean(bucket="tidak_cocok", bank=SENTINEL).context
        rows = list(c["page"])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.left.player_bank == "" for r in rows))


class TautanUrutTests(_Base):
    """Bug lama: mengurutkan kolom membuang filter bank yang sedang aktif."""

    def setUp(self):
        super().setUp()
        row = self.panel_row(player_bank="BCA", bank_title="QRIS")
        self.hasil(MatchResult.Bucket.TIDAK, row, None, "no_bracket")

    def test_tautan_urut_membawa_filter_bank_aktif(self):
        html = self.get(bucket="tidak_cocok", bank="BCA", btitle="QRIS").content.decode()
        hrefs = re.findall(r'<a class="th-sort" href="([^"]+)"', html)
        self.assertEqual(len(hrefs), 2, f"tautan sort tak lengkap: {hrefs}")
        for href in hrefs:
            self.assertIn("bank=BCA", href)
            self.assertIn("btitle=QRIS", href)


class TautanArusTests(_Base):
    """Bug sekelas tautan urut: tab Deposit/Withdraw membuang filter yang aktif.

    Chip bank/alasan justru fitur utama rilis ini, jadi jalur "pilih chip lalu
    klik Deposit" adalah jalur yang paling sering ditempuh — filternya tak boleh
    hilang diam-diam. Pola pembawa param sama dgn `web/templates/web/review_queue.html`.
    """

    def setUp(self):
        super().setUp()
        row = self.panel_row(player_bank="BCA", bank_title="QRIS")
        self.hasil(MatchResult.Bucket.TIDAK, row, None, "no_bracket")
        self.hasil(MatchResult.Bucket.TIDAK, self.panel_row(), None, "no_bracket")

    def seg_hrefs(self, **q):
        html = self.get(**q).content.decode()
        blok = re.search(
            r'<div class="seg"[^>]*aria-label="Pilah arus[^"]*">(.*?)</div>', html, re.S
        )
        self.assertIsNotNone(blok, "blok segmented control arus tak ditemukan")
        return re.findall(r'href="([^"]+)"', blok.group(1))

    def test_tautan_arus_membawa_filter_aktif(self):
        hrefs = self.seg_hrefs(
            bucket="tidak_cocok", bank="BCA", btitle="QRIS", reason="no_bracket"
        )
        self.assertEqual(len(hrefs), 3, f"tautan arus tak lengkap: {hrefs}")
        for href in hrefs:
            self.assertIn("bank=BCA", href)
            self.assertIn("btitle=QRIS", href)
            self.assertIn("reason=no_bracket", href)

    def test_tautan_arus_meng_urlencode_sentinel(self):
        # "(Tanpa Bank)" wajib ter-escape; mentah-mentah "(" ")" & spasi merusak
        # querystring dan chip-nya tak pernah kembali terpilih.
        hrefs = self.seg_hrefs(bucket="tidak_cocok", bank=SENTINEL)
        for href in hrefs:
            self.assertIn("bank=%28Tanpa%20Bank%29", href)

    def test_tab_bucket_sengaja_mereset_filter(self):
        """Kebalikannya DISENGAJA: chip dihitung per-bucket, jadi pindah bucket
        harus melepas filter (chip bank bucket lain bisa tak ada sama sekali)."""
        html = self.get(bucket="tidak_cocok", bank="BCA").content.decode()
        blok = re.search(r'<div class="tabs" style="margin-bottom:0">(.*?)</div>', html, re.S)
        for href in re.findall(r'href="([^"]+)"', blok.group(1)):
            self.assertNotIn("bank=", href)


class OrphanTakBerubahTests(_Base):
    """Regresi: tab 'Tidak Ada di Panel' tetap pakai chip akun FR (`_chips_sumber_uang`)."""

    def setUp(self):
        super().setUp()
        for _ in range(2):
            self.hasil(MatchResult.Bucket.TIDAK, self.panel_row(), None, "no_bracket")
        self.hasil(MatchResult.Bucket.TIDAK, None, self.fr_row(), "no_panel")

    def test_tab_orphan_tetap_chip_akun_fr(self):
        c = self.get(bucket="tidak_ada_panel").context
        self.assertEqual([b["code"] for b in c["btitles"]], [AKUN_FR])
        self.assertEqual(c["banks"], [])

    def test_baris_orphan_tak_ikut_dihitung_sentinel(self):
        # tab "Semua" memuat orphan juga; bank pemain konsep sisi panel → 2, bukan 3.
        c = self.get().context
        self.assertEqual(c["banks"], [{"code": SENTINEL, "n": 2}])
        self.assertEqual(c["btitles"], [{"code": SENTINEL, "n": 2}])
