"""Pass 0c — join persis nomor rekening gateway (UNO QRIS WD).

UNO membawa `AccountNumber` (rekening tujuan pemain) di raw gateway; panel COR
menyimpan nomor yang sama di segmen ke-3 `raw['Player Bank']` (sudah diekstrak
`_panel_phone`). UUID reference (pass 0b) sudah menutup ~100% kasus — pass 0c
ini jaring robustness untuk baris fee-shifted / late-settled yang lolos dari
reference join. Anchor: AccountNumber adalah kunci PEMAIN (bukan kunci
transaksi) — hanya nominal PERSIS yang dipasangkan; selisih jatuh ke pass 1/2.
"""
from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase

from reconciliation.engine import _norm_acct_digits, _panel_phone, run_batch, run_match
from reconciliation.models import MatchResult, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

D = Decimal


class NormAcctDigitsTests(TestCase):
    """Unit murni (tanpa DB) — helper harus menghasilkan kunci yang SAMA dari
    format panel (_panel_phone, segmen Player Bank) dan format gateway
    (AccountNumber mentah), termasuk varian awalan 0 vs 62."""

    def test_gateway_dan_panel_hasil_sama_untuk_nomor_sama(self):
        panel_key = _panel_phone_from_segment("082250625228")
        self.assertEqual(_norm_acct_digits("082250625228"), panel_key)

    def test_varian_62_setara_dengan_varian_0(self):
        self.assertEqual(_norm_acct_digits("62822505252281"),
                          _norm_acct_digits("0822505252281"))

    def test_kurang_dari_6_digit_tidak_diindeks(self):
        self.assertEqual(_norm_acct_digits("12345"), "")

    def test_kosong_tidak_diindeks(self):
        self.assertEqual(_norm_acct_digits(""), "")
        self.assertEqual(_norm_acct_digits(None), "")


def _panel_phone_from_segment(acct):
    """Bangun objek panel minimal & pakai _panel_phone asli — hindari duplikasi
    logika normalisasi di tes."""
    from types import SimpleNamespace
    return _panel_phone(SimpleNamespace(raw={"Player Bank": f"BANKX|Nama|{acct}"}))


class AccountJoinTests(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1, "fuzzy_threshold": 85})[0]
        self.panel = SourceType.objects.get_or_create(
            key="panel", defaults={"name": "Panel"})[0]
        self.gw = SourceType.objects.get_or_create(
            key="gateway", defaults={"name": "Gateway"})[0]
        self.up_p = Upload.objects.create(source_type=self.panel, toko=self.toko)
        self.up_g = Upload.objects.create(source_type=self.gw, toko=self.toko)
        self._n = 0

    def _rh(self):
        self._n += 1
        return f"h{self._n}"

    def panel_wd(self, amount, name, acct, dt, *, username="", ticket="", ref=""):
        return Transaction.objects.create(
            upload=self.up_p, source_type=self.panel, toko=self.toko, jenis="wd",
            amount=D(abs(amount)), money_delta=D(-abs(amount)),
            counterparty=name, username=username, occurred_at=dt,
            ticket_no=ticket, reference=ref, row_hash=self._rh(),
            raw={"Player Bank": f"UNO|{name}|{acct}"},
        )

    def gw_wd(self, amount, acct, dt, *, username="", ticket="", ref=""):
        return Transaction.objects.create(
            upload=self.up_g, source_type=self.gw, toko=self.toko, jenis="wd",
            amount=D(abs(amount)), money_delta=D(-abs(amount)),
            username=username, occurred_at=dt,
            ticket_no=ticket, reference=ref, row_hash=self._rh(),
            raw={"AccountNumber": acct},
        )

    # 1. pairing dasar ------------------------------------------------------
    def test_pairing_dasar_via_account(self):
        p = self.panel_wd(500000, "Budi", "082250625228",
                          datetime(2026, 7, 20, 10, 0))
        g = self.gw_wd(500000, "082250625228", datetime(2026, 7, 20, 10, 5))
        run = run_match("panel_bank", self.tol)
        r = MatchResult.objects.get(run=run, left=p)
        self.assertEqual(r.right, g)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.reason_code, "account")
        self.assertEqual(r.score, 100)

    # 2. pemain sama, dua WD nominal beda ke rekening sama ------------------
    def test_pemain_sama_dua_wd_masing_masing_ke_nominal_persis(self):
        acct = "082250625228"
        p1 = self.panel_wd(500000, "Budi", acct, datetime(2026, 7, 20, 9, 0))
        p2 = self.panel_wd(750000, "Budi", acct, datetime(2026, 7, 20, 15, 0))
        g1 = self.gw_wd(500000, acct, datetime(2026, 7, 20, 9, 5))
        g2 = self.gw_wd(750000, acct, datetime(2026, 7, 20, 15, 5))
        run = run_match("panel_bank", self.tol)
        r1 = MatchResult.objects.get(run=run, left=p1)
        r2 = MatchResult.objects.get(run=run, left=p2)
        self.assertEqual(r1.right, g1)
        self.assertEqual(r1.reason_code, "account")
        self.assertEqual(r2.right, g2)
        self.assertEqual(r2.reason_code, "account")

    # 3. normalisasi 0/62 -----------------------------------------------------
    def test_normalisasi_62_vs_0_tetap_cocok(self):
        p = self.panel_wd(300000, "Sari", "0822505252281",
                          datetime(2026, 7, 20, 11, 0))
        g = self.gw_wd(300000, "62822505252281", datetime(2026, 7, 20, 11, 5))
        run = run_match("panel_bank", self.tol)
        r = MatchResult.objects.get(run=run, left=p)
        self.assertEqual(r.right, g)
        self.assertEqual(r.reason_code, "account")

    # 4. pass 0b menang duluan ------------------------------------------------
    def test_pass_0b_reference_menang_atas_account(self):
        acct = "082250625228"
        p = self.panel_wd(400000, "Dedi", acct, datetime(2026, 7, 20, 12, 0),
                          ref="uuid-dedi-1")
        g = self.gw_wd(400000, acct, datetime(2026, 7, 20, 12, 5),
                       ref="uuid-dedi-1")
        run = run_match("panel_bank", self.tol)
        r = MatchResult.objects.get(run=run, left=p)
        self.assertEqual(r.right, g)
        self.assertEqual(r.reason_code, "reference")  # BUKAN "account"

    # 5. klausa blocked: akun asing tak boleh dicuri fuzzy --------------------
    def test_akun_gateway_asing_tidak_dipasangkan_fuzzy(self):
        """Diuji pada level run_batch: bukan cuma "tidak dipasangkan", tapi baris
        uangnya harus MUNCUL sebagai uang tanpa jejak panel (no_panel, kategori
        'd') supaya selisih batch selalu punya baris penjelas."""
        # p: identitas kuat (username persis) + rekening SENDIRI dikenal panel.
        p = self.panel_wd(200000, "Eko", "082250625228",
                          datetime(2026, 7, 20, 8, 0), username="eko99")
        # g: nominal & tanggal SAMA + username SAMA (tanpa klausa blocked ini
        # akan menang di pass 1 skor 100) tapi AccountNumber TAK dikenal panel.
        g = self.gw_wd(200000, "099999999999", datetime(2026, 7, 20, 8, 0),
                       username="eko99")
        batch = run_batch(self.toko, self.tol, recon_date=date(2026, 7, 20))
        r = MatchResult.objects.get(run__batch=batch, left=p)
        self.assertIsNone(r.right)
        self.assertEqual(r.bucket, MatchResult.Bucket.TIDAK)
        self.assertEqual(r.reason_code, "no_money")
        # g tak pernah jadi pasangan siapa pun — tampil sebagai no_panel.
        rg = MatchResult.objects.get(run__batch=batch, right=g)
        self.assertIsNone(rg.left)
        self.assertEqual(rg.reason_code, "no_panel")
        self.assertEqual(batch.summary["unmatched_money"]["d"]["n"], 1)

    # 5b. guard panel_accts kosong: jangan blokir seluruh gateway ber-rekening -
    def test_panel_tanpa_rekening_gateway_berrekening_tidak_diblokir(self):
        """Sisi kredit tanpa satu pun rekening dikenal (mis. run bracket↔bank,
        atau panel tanpa segmen Player Bank): klausa blocked account TIDAK boleh
        aktif — kalau aktif, SEMUA baris gateway ber-AccountNumber lenyap dari
        kandidat fuzzy (jurang match-rate senyap)."""
        p = self.panel_wd(200000, "Eko", "", datetime(2026, 7, 20, 8, 0),
                          username="eko99")
        g = self.gw_wd(200000, "099999999999", datetime(2026, 7, 20, 8, 0),
                       username="eko99")
        run = run_match("panel_bank", self.tol)
        r = MatchResult.objects.get(run=run, left=p)
        self.assertEqual(r.right, g)  # tetap terjangkau pass 1
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.reason_code, "amount+date+name")

    # 5c. assignment global urut delta (bukan urutan iterasi panel) -----------
    def test_assignment_global_pilih_delta_terkecil_bukan_baris_pertama(self):
        """Pemain & nominal sama pada dua hari (19 & 20) tapi HANYA satu baris
        gateway tanggal 20: pasangan account harus jatuh ke panel tanggal 20
        (delta 0), bukan ke panel tanggal 19 yang kebetulan lebih dulu dalam
        urutan iterasi — di alur harian baris 19 itu carried, dan pasangan
        salah-hari akan memicu flip late_settlement palsu ke batch 19 Juli."""
        acct = "082250625228"
        p19 = self.panel_wd(500000, "Budi", acct, datetime(2026, 7, 19, 9, 0))
        p20 = self.panel_wd(500000, "Budi", acct, datetime(2026, 7, 20, 9, 0))
        g20 = self.gw_wd(500000, acct, datetime(2026, 7, 20, 9, 5))
        run = run_match("panel_bank", self.tol)
        r20 = MatchResult.objects.get(run=run, left=p20)
        self.assertEqual(r20.right, g20)
        self.assertEqual(r20.reason_code, "account")
        r19 = MatchResult.objects.get(run=run, left=p19)
        self.assertIsNone(r19.right)
        self.assertNotEqual(r19.reason_code, "account")

    # 5d. jendela tanggal terarah --------------------------------------------
    def test_uang_sebelum_tanggal_panel_tidak_dipasangkan_account(self):
        """Uang tak boleh mendahului kredit: H-1 pun hanya boleh lewat pass 2
        (perlu_tinjau), tidak pernah jadi 'account' cocok."""
        acct = "082250625228"
        p = self.panel_wd(500000, "Budi", acct, datetime(2026, 7, 20, 9, 0))
        self.gw_wd(500000, acct, datetime(2026, 7, 18, 9, 0))
        run = run_match("panel_bank", self.tol)
        r = MatchResult.objects.get(run=run, left=p)
        self.assertIsNone(r.right)
        self.assertNotEqual(r.reason_code, "account")

    def test_selisih_hari_di_luar_window_tidak_dipasangkan_account(self):
        acct = "082250625228"
        p = self.panel_wd(500000, "Budi", acct, datetime(2026, 7, 20, 9, 0))
        self.gw_wd(500000, acct, datetime(2026, 7, 22, 9, 0))  # delta 2 > window 1
        run = run_match("panel_bank", self.tol)
        r = MatchResult.objects.get(run=run, left=p)
        self.assertIsNone(r.right)
        self.assertNotEqual(r.reason_code, "account")

    # 5e. baris tanpa tanggal ---------------------------------------------------
    def test_panel_tanpa_tanggal_tidak_dipasangkan_account(self):
        """Tanpa occurred_at jendela tak bisa dihitung — jangan pasangkan
        berdasarkan nominal semata."""
        acct = "082250625228"
        p = self.panel_wd(500000, "Budi", acct, None)
        self.gw_wd(500000, acct, datetime(2026, 7, 20, 9, 0))
        run = run_match("panel_bank", self.tol)
        r = MatchResult.objects.get(run=run, left=p)
        self.assertIsNone(r.right)
        self.assertNotEqual(r.reason_code, "account")

    def test_gateway_tanpa_tanggal_tidak_dipasangkan_account(self):
        acct = "082250625228"
        p = self.panel_wd(500000, "Budi", acct, datetime(2026, 7, 20, 9, 0))
        self.gw_wd(500000, acct, None)
        run = run_match("panel_bank", self.tol)
        r = MatchResult.objects.get(run=run, left=p)
        self.assertIsNone(r.right)
        self.assertNotEqual(r.reason_code, "account")

    # 6. sub-6-digit tidak diindeks -------------------------------------------
    def test_akun_kurang_dari_6_digit_tidak_terindeks(self):
        p = self.panel_wd(150000, "Fani", "12345",
                          datetime(2026, 7, 20, 13, 0))
        g = self.gw_wd(150000, "12345", datetime(2026, 7, 20, 13, 5))
        run = run_match("panel_bank", self.tol)
        r = MatchResult.objects.get(run=run, left=p)
        self.assertIsNone(r.right)
        self.assertNotEqual(r.reason_code, "account")

    # 7. zero-diff Nexus: tanpa AccountNumber sama sekali → perilaku lama utuh -
    def test_tanpa_accountnumber_perilaku_lama_utuh(self):
        """Skenario pencocokan berbasis nomor HP (pola DANA VA, sumber BANK —
        di luar jangkauan pass 0c/blocked yang cuma menyentuh gateway) harus
        menghasilkan bucket identik dengan sebelum perubahan ini."""
        bank = SourceType.objects.get_or_create(
            key="bank", defaults={"name": "Bank"})[0]
        up_b = Upload.objects.create(source_type=bank)
        p = Transaction.objects.create(
            upload=self.up_p, source_type=self.panel, jenis="wd",
            amount=D(126000), money_delta=D(-126000),
            counterparty="Angger Praja", occurred_at=datetime(2026, 7, 20, 10, 0),
            row_hash=self._rh(), raw={"Player Bank": "DANA|Angger Praja|082264436674"},
        )
        b = Transaction.objects.create(
            upload=up_b, source_type=bank, jenis="wd",
            amount=D(126000), money_delta=D(-126000),
            counterparty="", occurred_at=datetime(2026, 7, 20, 11, 0),
            row_hash=self._rh(),
            raw={"Keterangan": "TRSF E-BANKING DB 0107/FTFVA/WS9501139010/DANA - - 82264436674"},
        )
        run = run_match("panel_bank", self.tol)
        r = MatchResult.objects.get(run=run, left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.right, b)
        self.assertEqual(r.score, 100)
        self.assertEqual(r.reason_code, "amount+date+name")  # bukan "account"

    def test_gateway_tanpa_accountnumber_key_tetap_jalan_seperti_biasa(self):
        """Baris gateway tanpa key 'AccountNumber' sama sekali di raw (mis.
        RPay/NXPay lama) — tak boleh ikut terindeks/blocked oleh klausa baru;
        join username biasa (pass 1) tetap berfungsi seperti sebelumnya."""
        p = Transaction.objects.create(
            upload=self.up_p, source_type=self.panel, jenis="wd",
            amount=D(90000), money_delta=D(-90000),
            counterparty="Gita", username="gita01",
            occurred_at=datetime(2026, 7, 20, 9, 0),
            row_hash=self._rh(), raw={"Player Bank": "RPAY|Gita|081111111111"},
        )
        g = Transaction.objects.create(
            upload=self.up_g, source_type=self.gw, jenis="wd",
            amount=D(90000), money_delta=D(-90000),
            username="gita01", occurred_at=datetime(2026, 7, 20, 9, 5),
            row_hash=self._rh(), raw={"Customer Username": "gita01"},
        )
        run = run_match("panel_bank", self.tol)
        r = MatchResult.objects.get(run=run, left=p)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.right, g)
        self.assertEqual(r.reason_code, "amount+date+name")
