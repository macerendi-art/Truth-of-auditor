"""Filter channel/sumber bertingkat di halaman detail run.

Latar: tabel hasil rekonsiliasi sudah punya filter bucket (Semua/Cocok/Perlu
Ditinjau/Tidak Cocok) lewat tab. User minta filter KEDUA — per *channel/sumber*
— yang diterapkan SETELAH filter bucket. Channel diambil dari sisi kiri (Panel):
`Transaction.raw["Player Bank"]` berformat `"<channel>|<nama>|<nomor>"`,
mis. `"DANA|Eko Siswahyudi|082148737773"`. Segmen pertama (DANA/OVO/BCA/…) itu
"sumber" yang difilter.

Tes ini menjaga:
1. `?channel=DANA` hanya kembalikan baris DANA (BCA tersaring).
2. Filter channel bergabung dengan filter bucket (keduanya berlaku).
3. Baris chip channel muncul (dengan hitungan) saat ada ≥2 channel; hilang saat 1.
4. href chip mempertahankan bucket; href tab bucket mempertahankan channel.
5. Baris `left=None` (uang yatim) tak bikin crash & tersaring saat channel aktif.
6. Channel tak dikenal → hasil kosong, halaman tetap 200.
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


class RunChannelFilterTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get(name="Default")
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

        self.adm = User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

        # Satu batch + satu run panel_bank untuk menampung hasil.
        self.batch = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        self.run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=self.batch
        )

        # Panel tx per channel (segmen pertama Player Bank).
        self.dana_cocok = self._panel("D-DANA-1", "DANA|Eko Siswahyudi|082148737773")
        self.dana_tinjau = self._panel("D-DANA-2", "DANA|Budi Santoso|081200000000")
        self.bca_cocok = self._panel("D-BCA-1", "BCA|Siti Aminah|1234567890")

        # Hasil: dua cocok (DANA + BCA), satu perlu tinjau (DANA), satu yatim (left=None).
        self._result(self.dana_cocok, MatchResult.Bucket.COCOK)
        self._result(self.dana_tinjau, MatchResult.Bucket.TINJAU)
        self._result(self.bca_cocok, MatchResult.Bucket.COCOK)
        # Uang yatim: right ada, left None → tak punya channel, tersaring saat filter aktif.
        self.orphan_right = Transaction.objects.create(
            upload=self.up, source_type=self.bank, toko=self.lbs, jenis="depo",
            amount=Decimal("50000"), money_delta=Decimal("50000"),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash="orphan-r",
            counterparty="ORANG TAK DIKENAL",
        )
        MatchResult.objects.create(
            run=self.run, bucket=MatchResult.Bucket.TIDAK,
            left=None, right=self.orphan_right, reason_code="no_panel",
        )

    def _panel(self, ticket, player_bank):
        return Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=self.lbs, jenis="depo",
            amount=Decimal("50000"), money_delta=Decimal("50000"), ticket_no=ticket,
            occurred_at=datetime(2026, 6, 27, 10, 0),
            row_hash=f"h-{ticket}", raw={"Player Bank": player_bank},
        )

    def _result(self, left, bucket):
        return MatchResult.objects.create(
            run=self.run, bucket=bucket, left=left, right=None,
            reason_code="test", score=100,
        )

    def _url(self, **params):
        base = reverse("run_detail", args=[self.run.pk])
        if not params:
            return base
        from urllib.parse import urlencode
        return f"{base}?{urlencode(params)}"

    # ── 1. Filter channel menyaring baris ──────────────────────────────────
    def test_channel_dana_hanya_baris_dana(self):
        r = self.client.get(self._url(channel="DANA"))
        self.assertEqual(r.status_code, 200)
        # Tiket DANA muncul, tiket BCA tidak.
        self.assertContains(r, "D-DANA-1")
        self.assertContains(r, "D-DANA-2")
        self.assertNotContains(r, "D-BCA-1")

    def test_channel_bca_hanya_baris_bca(self):
        r = self.client.get(self._url(channel="BCA"))
        self.assertContains(r, "D-BCA-1")
        self.assertNotContains(r, "D-DANA-1")

    # ── 2. Filter channel + bucket bergabung ───────────────────────────────
    def test_channel_dan_bucket_bergabung(self):
        # bucket=cocok & channel=DANA → hanya DANA yang cocok (tinjau DANA tersaring).
        r = self.client.get(self._url(bucket="cocok", channel="DANA"))
        self.assertContains(r, "D-DANA-1")   # DANA cocok
        self.assertNotContains(r, "D-DANA-2")  # DANA tinjau tersaring oleh bucket
        self.assertNotContains(r, "D-BCA-1")   # BCA tersaring oleh channel

    # ── 3. Chip channel muncul dgn hitungan saat ≥2 channel ────────────────
    def test_chip_channel_muncul_dengan_hitungan(self):
        r = self.client.get(self._url())
        html = r.content.decode()
        # Dua channel berbeda (DANA, BCA) → baris chip harus ada.
        self.assertContains(r, "Semua channel")
        self.assertContains(r, "DANA")
        self.assertContains(r, "BCA")
        # Hitungan: DANA muncul 2 kali, BCA 1 kali (dari qs ter-bucket, di sini semua).
        self.assertIn("(2)", html)
        self.assertIn("(1)", html)

    def test_chip_channel_hilang_saat_satu_channel(self):
        # Bucket yg hanya berisi 1 channel (BCA cocok saja tak cukup; buat run bersih).
        run2 = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=self.batch
        )
        solo = self._panel("D-SOLO", "OVO|Solo Player|0811")
        MatchResult.objects.create(
            run=run2, bucket=MatchResult.Bucket.COCOK, left=solo, right=None, reason_code="test",
        )
        r = self.client.get(reverse("run_detail", args=[run2.pk]))
        # Hanya satu channel (OVO) → baris chip channel tidak dirender.
        self.assertNotContains(r, "Semua channel")

    # ── 4. href chip menjaga bucket; href tab bucket menjaga channel ───────
    def test_chip_href_menjaga_bucket(self):
        r = self.client.get(self._url(bucket="cocok"))
        html = r.content.decode()
        # Chip channel harus membawa bucket=cocok di href-nya. `&` literal di
        # sumber template tak di-autoescape jadi &amp; (hanya output variabel yg di-escape).
        self.assertIn("bucket=cocok&channel=DANA", html)

    def test_tab_bucket_href_menjaga_channel(self):
        r = self.client.get(self._url(channel="DANA"))
        html = r.content.decode()
        # Tab bucket (mis. Cocok) harus membawa channel=DANA.
        self.assertIn("bucket=cocok&channel=DANA", html)

    # ── 5. Baris left=None tersaring saat channel aktif, tak crash ─────────
    def test_orphan_tersaring_saat_channel_aktif(self):
        r = self.client.get(self._url(channel="DANA"))
        self.assertEqual(r.status_code, 200)
        # Yatim (counterparty ORANG TAK DIKENAL) tak muncul saat filter channel aktif.
        self.assertNotContains(r, "ORANG TAK DIKENAL")

    def test_orphan_muncul_tanpa_filter(self):
        # Tanpa filter channel, baris yatim tetap tampil (tak ikut disaring).
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "ORANG TAK DIKENAL")

    # ── 6. Channel tak dikenal → kosong tapi 200 ───────────────────────────
    def test_channel_tak_dikenal_kosong_200(self):
        r = self.client.get(self._url(channel="ZZZ"))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "D-DANA-1")
        self.assertNotContains(r, "D-BCA-1")

    def test_channel_case_insensitive(self):
        # channel lowercase harus tetap cocok (dinormalisasi + istartswith).
        r = self.client.get(self._url(channel="dana"))
        self.assertContains(r, "D-DANA-1")
        self.assertNotContains(r, "D-BCA-1")
