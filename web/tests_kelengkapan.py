"""Kartu Kelengkapan Data membedakan "belum diupload" dari "sudah terpakai".

Lahir dari salah tafsir nyata (W25, 6 Agustus 2026): baris Gateway tampil
abu-abu bertulis "opsional", pemakai menyimpulkan file UNOPAY-nya tidak
terbaca — padahal 9.586 barisnya sudah dikonsumsi Batch #27. Dua keadaan yang
artinya berlawanan tampil identik.
"""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.kelengkapan import status_sumber


class _Basis(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "aud", "a@a.co", "pw12345", role="supervisor"
        )
        self.toko = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get(name="Default")

    def _st(self, key):
        return SourceType.objects.get_or_create(key=key, defaults={"name": key})[0]

    def _baris(self, key, jenis, n, tgl=date(2026, 8, 6), batch=None):
        st = self._st(key)
        up = Upload.objects.create(
            source_type=st, toko=self.toko, original_name=f"{key}.xlsx",
            status=Upload.PARSED,
        )
        for i in range(n):
            Transaction.objects.create(
                upload=up, source_type=st, toko=self.toko,
                occurred_at=datetime.combine(tgl, datetime.min.time()),
                posted_date=tgl, jenis=jenis, amount=Decimal("1000"),
                credit_delta=Decimal("0"), money_delta=Decimal("1000"),
                fee=Decimal("0"), bonus=Decimal("0"),
                consumed_by_batch=batch, row_hash=f"{key}-{jenis}-{i}-{tgl}",
            )
        return up

    def _batch(self, tgl=date(2026, 8, 6)):
        return ReconBatch.objects.create(toko=self.toko, recon_date=tgl, tolerance=self.tol)


class StatusSumberTest(_Basis):
    def test_belum_diupload_nol_semua(self):
        s = status_sumber(self.toko)["gateway"]
        self.assertEqual((s["aktif"], s["terpakai"], s["batch_no"]), (0, 0, None))

    def test_baris_aktif_terhitung(self):
        self._baris("gateway", "depo", 12)
        s = status_sumber(self.toko)["gateway"]
        self.assertEqual((s["aktif"], s["terpakai"]), (12, 0))

    def test_sudah_terpakai_menyebut_batch_dan_jumlahnya(self):
        """Kasus W25: aktif 0 tapi ribuan baris sudah masuk sebuah batch."""
        b = self._batch()
        self._baris("gateway", "depo", 9156, batch=b)
        self._baris("gateway", "wd", 430, batch=b)
        s = status_sumber(self.toko)["gateway"]
        self.assertEqual(s["aktif"], 0)
        self.assertEqual(s["terpakai"], 9586)
        self.assertEqual(s["batch_no"], 1)
        self.assertEqual(s["batch_tanggal"], date(2026, 8, 6))

    def test_nomor_batch_ikut_urutan_per_toko(self):
        self._batch(date(2026, 8, 4))
        self._batch(date(2026, 8, 5))
        b3 = self._batch(date(2026, 8, 6))
        self._baris("bank", "depo", 5, batch=b3)
        self.assertEqual(status_sumber(self.toko)["bank"]["batch_no"], 3)

    def test_batch_terakhir_yang_disebut(self):
        b1, b2 = self._batch(date(2026, 8, 5)), self._batch(date(2026, 8, 6))
        self._baris("bank", "depo", 3, tgl=date(2026, 8, 5), batch=b1)
        self._baris("bank", "depo", 4, tgl=date(2026, 8, 6), batch=b2)
        s = status_sumber(self.toko)["bank"]
        self.assertEqual((s["terpakai"], s["batch_no"]), (7, 2))

    def test_panel_dp_dan_wd_dipisah(self):
        self._baris("panel", "depo", 7)
        self._baris("panel", "wd", 3)
        s = status_sumber(self.toko)
        self.assertEqual(s["panel_dp"]["aktif"], 7)
        self.assertEqual(s["panel_wd"]["aktif"], 3)

    def test_rentang_tanggal_dihormati(self):
        self._baris("bank", "depo", 5, tgl=date(2026, 8, 1))
        self._baris("bank", "depo", 9, tgl=date(2026, 8, 6))
        s = status_sumber(self.toko, date(2026, 8, 6), date(2026, 8, 6))
        self.assertEqual(s["bank"]["aktif"], 9)

    def test_toko_lain_tidak_bocor(self):
        lain = Toko.objects.exclude(pk=self.toko.pk).first()
        st = self._st("gateway")
        up = Upload.objects.create(source_type=st, toko=lain, status=Upload.PARSED)
        Transaction.objects.create(
            upload=up, source_type=st, toko=lain,
            occurred_at=datetime(2026, 8, 6), posted_date=date(2026, 8, 6),
            jenis="depo", amount=Decimal("1"), credit_delta=Decimal("0"),
            money_delta=Decimal("1"), fee=Decimal("0"), bonus=Decimal("0"),
            row_hash="lain-1",
        )
        self.assertEqual(status_sumber(self.toko)["gateway"]["aktif"], 0)

    def test_query_konstan_berapa_pun_sumbernya(self):
        b = self._batch()
        for key in ("panel", "bracket", "bank", "gateway"):
            self._baris(key, "depo", 3, batch=b)
            self._baris(key, "wd", 2)
        with CaptureQueriesContext(connection) as ctx:
            status_sumber(self.toko)
        self.assertEqual(len(ctx.captured_queries), 3, "harus tetap 3 query")


class HalamanRekonsiliasiTest(_Basis):
    def setUp(self):
        super().setUp()
        self.client.login(username="aud", password="pw12345")
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})

    def test_sumber_terpakai_disebut_bukan_sekadar_opsional(self):
        b = self._batch()
        self._baris("gateway", "depo", 9586, batch=b)
        self._baris("panel", "depo", 5)          # supaya halaman punya isi wajar

        r = self.client.get(reverse("reconcile"))

        self.assertContains(r, "terpakai")
        self.assertContains(r, "Batch #1")
        self.assertContains(r, "9.586")

    def test_sumber_belum_diupload_tetap_berbunyi_lama(self):
        self._baris("panel", "depo", 5)

        r = self.client.get(reverse("reconcile"))

        self.assertContains(r, "opsional")
        self.assertNotContains(r, "Batch #1")

    def test_hitungan_siap_tidak_berubah(self):
        """Kontrak lama: cincin 'n/5' tetap menghitung sumber AKTIF saja —
        baris yang sudah terpakai tidak boleh membuatnya terlihat siap."""
        b = self._batch()
        self._baris("gateway", "depo", 100, batch=b)
        self._baris("panel", "depo", 5)

        r = self.client.get(reverse("reconcile"))

        self.assertEqual(r.context["comp_ready"], 1)
        self.assertFalse(r.context["completeness"]["gateway"])
