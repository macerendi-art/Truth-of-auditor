"""Rincian Biaya admin: agregasi web.biaya + view /biaya-admin/."""
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

import transactions.models as tx_models
import web.biaya as biaya_mod
from sources.models import Account, SourceType, Toko, Upload
from transactions.models import Transaction
from web.biaya import rincian_biaya

TGL = date(2026, 7, 17)


class _BiayaData(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.bank = SourceType.objects.get_or_create(
            key="bank", defaults={"name": "Bank"})[0]
        self.up_bri = Upload.objects.create(
            source_type=self.bank, toko=self.toko,
            original_name="17_07_2026_WD_BRI_NASRUL.csv", owner_name="NASRUL")
        self._n = 0

    def tx(self, up, desc, amount, jenis="wd", tanggal=TGL, account=None):
        self._n += 1
        return Transaction.objects.create(
            upload=up, source_type=self.bank, toko=self.toko, jenis=jenis,
            amount=Decimal(amount), money_delta=-Decimal(amount),
            posted_date=tanggal, occurred_at=datetime(2026, 7, 17, 10, 0),
            description=desc, row_hash=f"by{self._n}", account=account)


class AgregasiBiayaTests(_BiayaData):
    def test_bertanda_admin_dan_legacy_rule_ikut(self):
        self.tx(self.up_bri, "BFST123 NBMB:X", "2500", jenis="admin")   # bertanda
        self.tx(self.up_bri, "ATMSTRPRM 0888", "6500", jenis="wd")     # legacy tanpa tanda
        self.tx(self.up_bri, "BRIVA30135082 NBMB", "1000", jenis="wd") # legacy
        self.tx(self.up_bri, "NBMB ANDI TO BUDI ESB", "500000", jenis="wd")  # transfer nyata
        data = rincian_biaya(self.toko, dari=TGL, sampai=TGL)
        self.assertEqual(data["ringkas"]["n"], 3)
        self.assertEqual(data["ringkas"]["total"], Decimal("10000"))
        kanal = data["ringkas"]["kanal"]
        self.assertEqual(kanal["BI Fast"]["total"], Decimal("2500"))
        self.assertEqual(kanal["Transfer online"]["total"], Decimal("6500"))
        self.assertEqual(kanal["E-wallet"]["total"], Decimal("1000"))

    def test_rentang_tanggal(self):
        self.tx(self.up_bri, "BFST1", "2500", jenis="admin", tanggal=date(2026, 7, 1))
        self.tx(self.up_bri, "BFST2", "2500", jenis="admin", tanggal=TGL)
        data = rincian_biaya(self.toko, dari=date(2026, 7, 10), sampai=TGL)
        self.assertEqual(data["ringkas"]["n"], 1)

    def test_baris_per_tanggal_sumber(self):
        self.tx(self.up_bri, "BFST1", "2500", jenis="admin")
        self.tx(self.up_bri, "BFST2", "2500", jenis="admin")
        data = rincian_biaya(self.toko, dari=TGL, sampai=TGL)
        (baris,) = data["rows"]
        self.assertEqual(baris["tanggal"], TGL)
        self.assertIn("BRI", baris["sumber"])
        self.assertEqual(baris["n"], 2)
        self.assertEqual(baris["total"], Decimal("5000"))


class LabelMemoTests(_BiayaData):
    """Memoisasi label sumber: kecepatan BOLEH berubah, labelnya TIDAK.

    `source_label_full` murni terhadap (source_type, account, upload) — memo
    per-pemanggilan menghemat ribuan evaluasi regex. Dua tes pertama menjaga
    KEBENARAN label (harus hijau sebelum & sesudah memo), tes ketiga menjaga
    memonya benar-benar bekerja.
    """

    def setUp(self):
        super().setUp()
        self.up_bca = Upload.objects.create(
            source_type=self.bank, toko=self.toko,
            original_name="17_07_2026_WD_BCA_HENDI.csv", owner_name="HENDI")
        self.acc_bca = Account.objects.create(
            kind="bank", provider="BCA", name="BCA HENDI", toko=self.toko)

    def test_label_tetap_beda_untuk_upload_berbeda(self):
        self.tx(self.up_bri, "BFST1", "2500", jenis="admin")
        self.tx(self.up_bri, "BFST2", "2500", jenis="admin")
        self.tx(self.up_bca, "BIAYA TXN 1", "2500", jenis="admin")
        data = rincian_biaya(self.toko, dari=TGL, sampai=TGL)
        sumber = {r["sumber"]: r["n"] for r in data["rows"]}
        self.assertEqual(sumber, {"BRI a/n NASRUL": 2, "BCA a/n HENDI": 1})

    def test_label_beda_untuk_rekening_berbeda_di_upload_sama(self):
        """Kunci memo TIDAK boleh cuma upload — `account.provider` menang.

        Dua baris satu upload tapi beda rekening = beda label. Kalau memo
        dikunci upload saja, biaya bank tercatat di rekening yang salah.
        """
        self.tx(self.up_bri, "BFST1", "2500", jenis="admin")
        self.tx(self.up_bri, "BFST2", "2500", jenis="admin", account=self.acc_bca)
        data = rincian_biaya(self.toko, dari=TGL, sampai=TGL)
        sumber = {r["sumber"]: r["n"] for r in data["rows"]}
        # owner sama (dari upload), provider beda (dari account) → label beda
        self.assertEqual(sumber, {"BRI a/n NASRUL": 1, "BCA a/n NASRUL": 1})

    def test_label_tidak_dihitung_ulang_per_baris(self):
        # 3 kombinasi (source_type, account, upload), 10 baris lolos filter fee
        for i in range(3):                                    # kombinasi 1
            self.tx(self.up_bri, f"BFST{i}", "2500", jenis="admin")
        for i in range(2):                                    # kombinasi 1 (legacy)
            self.tx(self.up_bri, f"ATMSTRPRM {i}", "6500", jenis="wd")
        for i in range(3):                                    # kombinasi 2
            self.tx(self.up_bca, f"BIAYA TXN {i}", "2500", jenis="wd")
        for i in range(2):                                    # kombinasi 3
            self.tx(self.up_bri, f"BFSTX{i}", "2500", jenis="admin",
                    account=self.acc_bca)
        # baris transfer nyata: ikut jalur provider_from_filename lalu dibuang
        self.tx(self.up_bri, "NBMB ANDI TO BUDI", "500000", jenis="wd")

        asli_label = tx_models.specific_source_label
        asli_provider = biaya_mod.provider_from_filename
        with patch("transactions.models.specific_source_label",
                   wraps=asli_label) as m_label, \
             patch("web.biaya.provider_from_filename",
                   wraps=asli_provider) as m_prov:
            data = rincian_biaya(self.toko, dari=TGL, sampai=TGL)

        self.assertEqual(data["ringkas"]["n"], 10)
        # label dievaluasi per KOMBINASI (3), bukan per baris (10)
        self.assertEqual(m_label.call_count, 3)
        # nama file dibaca per UPLOAD non-admin (2), bukan per baris (6)
        self.assertEqual(m_prov.call_count, 2)


class BiayaViewTests(_BiayaData):
    def setUp(self):
        super().setUp()
        u = get_user_model().objects.create_user(
            username="aud_b", password="rahasia123", role="auditor")
        u.allowed_tokos.add(self.toko)
        self.client.force_login(u)
        s = self.client.session
        s["active_toko_id"] = self.toko.id
        s.save()

    def test_halaman_render(self):
        self.tx(self.up_bri, "BFST1", "2500", jenis="admin")
        r = self.client.get(reverse("rincian_biaya"),
                            {"dari": "2026-07-01", "sampai": "2026-07-31"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Rincian Biaya")
        self.assertContains(r, "2.500")

    def test_kosong_empty_state(self):
        r = self.client.get(reverse("rincian_biaya"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Belum ada")
