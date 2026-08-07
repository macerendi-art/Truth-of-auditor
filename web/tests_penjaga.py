"""Penjaga kesalahan upload — tiga pemeriksaan pasca-ingest.

Kasus nyata yang melahirkannya (Agustus 2026, produksi):

* SLO — file bernama ``01-08-2026 PANEL QRIS DP SLO.xlsx`` isinya data 30/06–01/07.
  Baris 1 Juli itu jadi tanggal panel terawal, rentang panel melar sebulan, dan
  seluruh mutasi Juli mendadak diprotes gerbang panel-penutup.
* W25 — file ``06-08-2026 W25 DP QRIS UNOPAY.xlsx`` berisi 9.156 baris milik
  merchant lain (volume harian normal 615–714). Tak satu pun kode transaksinya
  dikenal panel W25 → 9.618 baris "uang tanpa panel" dalam satu batch.

Keduanya lolos tanpa sepatah peringatan pun. Yang diuji di sini: keduanya
sekarang berbunyi, dan hari-hari normal TIDAK berbunyi.
"""
import shutil
import tempfile
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from django.urls import reverse

from sources import services
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.penjaga import (
    periksa_irisan_kunci,
    periksa_tanggal_isi,
    periksa_upload,
    periksa_volume,
    tanggal_dari_nama,
)


class TanggalDariNamaTest(TestCase):
    """Pola nama file yang benar-benar dipakai klien (disurvei dari 600 upload
    produksi: 56% dd-mm-yyyy, 22% dd-mm, 22% tanpa tanggal)."""

    def test_pola_lengkap_dengan_pemisah_apa_pun(self):
        for nama, harap in [
            ("06-08-2026 W25 DP QRIS UNOPAY.xlsx", (6, 8, 2026)),
            ("06_08_2026 W25 WD BCA YUSNIDAR.CSV", (6, 8, 2026)),
            ("01-08-2026 PANEL QRIS DP SLO.xlsx", (1, 8, 2026)),
        ]:
            self.assertEqual(tanggal_dari_nama(nama), harap, nama)

    def test_pola_pendek_tanpa_tahun(self):
        self.assertEqual(
            tanggal_dari_nama("HISTORI DP PANEL SLO ALL BANK 31-07.xlsx"), (31, 7, None)
        )

    def test_nama_tanpa_tanggal_menghasilkan_none(self):
        for nama in ["FR BREKET.xlsx", "mutasi bank.csv", "W25 LAYER BRI YUDI.csv"]:
            self.assertIsNone(tanggal_dari_nama(nama), nama)

    def test_tanggal_mustahil_diabaikan(self):
        """32-13 bukan tanggal — jangan dipaksakan jadi tanggal."""
        self.assertIsNone(tanggal_dari_nama("laporan 32-13-2026.xlsx"))

    def test_dua_tanggal_berbeda_dianggap_ambigu(self):
        """Rentang di nama file (mis. '01-07 sd 31-07') tak boleh ditebak — diam."""
        self.assertIsNone(tanggal_dari_nama("MUTASI 01-07 sd 31-07.xlsx"))

    def test_tanggal_sama_disebut_dua_kali_tetap_terbaca(self):
        self.assertEqual(tanggal_dari_nama("06-08-2026 W25 06-08-2026.xlsx"), (6, 8, 2026))


class PeriksaTanggalIsiTest(TestCase):
    def test_kasus_slo_berbunyi(self):
        """Nama 01-08-2026, isi 30/06–01/07 → melenceng sebulan."""
        h = periksa_tanggal_isi(
            "01-08-2026 PANEL QRIS DP SLO.xlsx", date(2026, 6, 30), date(2026, 7, 1)
        )
        self.assertIsNotNone(h)
        self.assertEqual(h["tanggal_nama"], date(2026, 8, 1))
        self.assertEqual(h["isi_dari"], date(2026, 6, 30))
        self.assertEqual(h["isi_sampai"], date(2026, 7, 1))
        self.assertGreater(h["selisih_hari"], 25)

    def test_hari_normal_diam(self):
        self.assertIsNone(
            periksa_tanggal_isi(
                "06-08-2026 W25 DP QRIS UNOPAY.xlsx", date(2026, 8, 6), date(2026, 8, 6)
            )
        )

    def test_baris_larut_malam_hari_sebelumnya_diam(self):
        """Panel 01/07 lazim memuat request 30/06 malam yang di-approve 01/07.
        Itu normal — toleransi 1 hari menutupinya."""
        self.assertIsNone(
            periksa_tanggal_isi(
                "01-07-2026 PANEL SLO.xlsx", date(2026, 6, 30), date(2026, 7, 1)
            )
        )

    def test_ekspor_kumulatif_berakhir_di_tanggal_nama_diam(self):
        """Tarikan bank kumulatif 01–06/08 bernama 06-08-2026 itu sah."""
        self.assertIsNone(
            periksa_tanggal_isi(
                "06-08-2026 MUTASI BCA.csv", date(2026, 8, 1), date(2026, 8, 6)
            )
        )

    def test_tanpa_tahun_memakai_tahun_isi_terdekat(self):
        """'31-07' + isi Juli 2026 → 31/07/2026, wajar. Tak boleh salah tuduh
        gara-gara tahun tidak tertulis di nama file."""
        self.assertIsNone(
            periksa_tanggal_isi(
                "HISTORI DP PANEL SLO 31-07.xlsx", date(2026, 7, 31), date(2026, 7, 31)
            )
        )

    def test_pergantian_tahun_tidak_salah_tuduh(self):
        """Nama '01-01' dengan isi 31/12/2025–01/01/2026: kandidat tahun diambil
        dari kedua ujung isi, jadi 01/01/2026 yang menang — bukan 01/01/2025."""
        self.assertIsNone(
            periksa_tanggal_isi(
                "01-01 MUTASI.xlsx", date(2025, 12, 31), date(2026, 1, 1)
            )
        )

    def test_nama_tanpa_tanggal_diam(self):
        self.assertIsNone(
            periksa_tanggal_isi("FR BREKET.xlsx", date(2026, 8, 6), date(2026, 8, 6))
        )

    def test_isi_kosong_diam(self):
        self.assertIsNone(periksa_tanggal_isi("06-08-2026 X.xlsx", None, None))


class PeriksaVolumeTest(TestCase):
    def test_kasus_w25_berbunyi(self):
        """9.156 baris vs kebiasaan ±700."""
        h = periksa_volume(9156, [615, 697, 678, 714, 700, 690])
        self.assertIsNotNone(h)
        self.assertEqual(h["baris"], 9156)
        self.assertEqual(h["biasanya"], 693.5)
        self.assertEqual(h["arah"], "atas")

    def test_jauh_di_bawah_kebiasaan_juga_berbunyi(self):
        """File 'DP' yang isinya cuma 30 baris padahal biasanya 700 —
        persis kasus tertukar DP/WD di W25 tanggal 01/08."""
        h = periksa_volume(30, [615, 697, 678, 714, 700, 690])
        self.assertIsNotNone(h)
        self.assertEqual(h["arah"], "bawah")

    def test_hari_normal_diam(self):
        self.assertIsNone(periksa_volume(705, [615, 697, 678, 714, 700, 690]))

    def test_riwayat_terlalu_pendek_diam(self):
        """Toko/sumber baru belum punya kebiasaan — jangan menuduh."""
        self.assertIsNone(periksa_volume(9156, [615, 697]))

    def test_kebiasaan_terlalu_kecil_diam(self):
        """Sumber bervolume kecil (WD QRIS ±25 baris) berayun wajar 3–4 kali
        lipat; ambang rasio di sana cuma menghasilkan bising."""
        self.assertIsNone(periksa_volume(40, [5, 8, 3, 12, 6, 9]))

    def test_file_kosong_diam(self):
        """0 baris punya jalurnya sendiri (parse gagal / duplikat penuh)."""
        self.assertIsNone(periksa_volume(0, [615, 697, 678, 714, 700, 690]))


class PeriksaIrisanKunciTest(TestCase):
    def test_kasus_w25_berbunyi(self):
        h = periksa_irisan_kunci({f"uuid-{i}" for i in range(9156)}, {"lain-1", "lain-2"})
        self.assertIsNotNone(h)
        self.assertEqual(h["cocok"], 0)
        self.assertEqual(h["total"], 9156)

    def test_hari_normal_diam(self):
        kunci = {f"uuid-{i}" for i in range(700)}
        self.assertIsNone(periksa_irisan_kunci(kunci, kunci))

    def test_irisan_sebagian_besar_diam(self):
        """Gateway lazim memuat sedikit transaksi yang panelnya belum diupload."""
        file_ = {f"uuid-{i}" for i in range(700)}
        panel = {f"uuid-{i}" for i in range(650)}
        self.assertIsNone(periksa_irisan_kunci(file_, panel))

    def test_panel_belum_diupload_diam(self):
        """Tanpa panel pembanding tak ada yang bisa disimpulkan."""
        self.assertIsNone(periksa_irisan_kunci({f"u{i}" for i in range(900)}, set()))

    def test_file_tanpa_kunci_diam(self):
        """RafflesPay sengaja tak membawa reference — bukan kesalahan."""
        self.assertIsNone(periksa_irisan_kunci(set(), {"a", "b", "c"}))

    def test_file_terlalu_kecil_diam(self):
        """Beberapa baris tanpa irisan itu kebetulan biasa, bukan pola."""
        self.assertIsNone(periksa_irisan_kunci({"a", "b", "c"}, {"x", "y"}))


class PeriksaUploadTest(TestCase):
    """Orkestrator: mengambil datanya sendiri dari DB lalu mengarang pesannya."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "aud", "a@a.co", "pw12345", role="supervisor"
        )
        self.toko = Toko.objects.get(key="lbs")
        self.gw = SourceType.objects.get_or_create(
            key="gateway", defaults={"name": "Gateway"}
        )[0]
        self.panel = SourceType.objects.get_or_create(
            key="panel", defaults={"name": "Panel"}
        )[0]

    def _upload(self, st, nama, flow="dp", n_baris=0):
        return Upload.objects.create(
            source_type=st, toko=self.toko, flow=flow, original_name=nama,
            status=Upload.PARSED, rows_parsed=n_baris, uploaded_by=self.user,
        )

    def _baris(self, up, st, tgl, ref="", n=1, jenis="depo"):
        for i in range(n):
            Transaction.objects.create(
                upload=up, source_type=st, toko=self.toko,
                occurred_at=datetime.combine(tgl, datetime.min.time()),
                posted_date=tgl, jenis=jenis, amount=Decimal("50000"),
                credit_delta=Decimal("0"), money_delta=Decimal("50000"),
                fee=Decimal("0"), bonus=Decimal("0"),
                reference=(f"{ref}{i}" if ref else ""),
                row_hash=f"{up.pk}-{ref}-{i}-{jenis}",
            )

    def test_gateway_tanpa_irisan_panel_berbunyi(self):
        pu = self._upload(self.panel, "06-08-2026 PANEL.xlsx")
        self._baris(pu, self.panel, date(2026, 8, 6), ref="panel-uuid-", n=30)
        gu = self._upload(self.gw, "06-08-2026 GATEWAY.xlsx", n_baris=30)
        self._baris(gu, self.gw, date(2026, 8, 6), ref="asing-uuid-", n=30)
        pesan = periksa_upload(gu)
        self.assertTrue(any("tidak dikenal panel" in p for p in pesan), pesan)

    def test_gateway_beririsan_diam(self):
        pu = self._upload(self.panel, "06-08-2026 PANEL.xlsx")
        self._baris(pu, self.panel, date(2026, 8, 6), ref="uuid-", n=30)
        gu = self._upload(self.gw, "06-08-2026 GATEWAY.xlsx", n_baris=30)
        self._baris(gu, self.gw, date(2026, 8, 6), ref="uuid-", n=30)
        self.assertEqual(periksa_upload(gu), [])

    def test_tanggal_nama_melenceng_berbunyi(self):
        up = self._upload(self.panel, "01-08-2026 PANEL SLO.xlsx", n_baris=5)
        self._baris(up, self.panel, date(2026, 7, 1), n=5)
        pesan = periksa_upload(up)
        self.assertTrue(any("nama file" in p for p in pesan), pesan)

    def test_upload_kosong_tidak_meledak(self):
        up = self._upload(self.gw, "06-08-2026 GATEWAY.xlsx")
        self.assertEqual(periksa_upload(up), [])

    def test_panel_pembanding_diambil_lintas_status_konsumsi(self):
        """Panel hari itu lazim SUDAH dikonsumsi batch sebelumnya; kalau hanya
        baris aktif yang dilihat, penjaga jadi buta tepat pada kasus tersibuk."""
        from reconciliation.models import ReconBatch, ToleranceProfile

        batch = ReconBatch.objects.create(
            toko=self.toko, recon_date=date(2026, 8, 6),
            tolerance=ToleranceProfile.objects.get(name="Default"),
        )
        pu = self._upload(self.panel, "06-08-2026 PANEL.xlsx")
        self._baris(pu, self.panel, date(2026, 8, 6), ref="uuid-", n=30)
        Transaction.objects.filter(upload=pu).update(consumed_by_batch=batch)
        gu = self._upload(self.gw, "06-08-2026 GATEWAY.xlsx", n_baris=30)
        self._baris(gu, self.gw, date(2026, 8, 6), ref="uuid-", n=30)
        self.assertEqual(periksa_upload(gu), [])


def _parser_palsu(sumber, tgl, ref_awalan, n):
    """Parser tiruan: `n` baris bersumber `sumber`, semuanya bertanggal `tgl`."""

    class _P:
        source_key = sumber

        def parse(self, path, flow=""):
            return [{
                "occurred_at": datetime.combine(tgl, datetime.min.time()).replace(hour=1 + i % 20),
                "posted_date": tgl, "jenis": "depo", "amount": Decimal("50000"),
                "credit_delta": Decimal("0"), "money_delta": Decimal("50000"),
                "fee": Decimal("0"), "bonus": Decimal("0"), "balance_after": None,
                "ticket_no": "", "username": "", "reference": f"{ref_awalan}{i}",
                "counterparty": "", "description": "", "raw": {},
                "row_hash": f"penjaga-{sumber}-{ref_awalan}-{i}",
            } for i in range(n)]

    return _P


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="toa-test-penjaga-"))
class PenjagaDiHalamanUploadTest(TestCase):
    """Penjaga terpasang di jalur commit upload dan tampil sebagai peringatan —
    bukan penghalang: `n file diproses` harus tetap berbunyi sukses."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._overridden_settings["MEDIA_ROOT"], ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        get_user_model().objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.toko = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})

    def _unggah(self, nama, parser):
        staged = default_storage.save(f"staging/{nama}", ContentFile(b"isi"))
        with patch.dict(services.PARSERS, {"_pj": parser}, clear=False):
            return self.client.post(reverse("upload"), {
                "action": "commit", "staged": [staged],
                "parser_key": ["_pj"], "flow": ["dp"], "orig_name": [nama],
            }, follow=True)

    def _pesan(self, r):
        return " ".join(str(m) for m in r.context["messages"])

    def test_tanggal_isi_melenceng_dari_nama_file_diperingatkan(self):
        r = self._unggah(
            "01-08-2026 PANEL QRIS DP SLO.xlsx",
            _parser_palsu("panel", date(2026, 7, 1), "uuid-", 20),
        )
        pesan = self._pesan(r)
        self.assertIn("tanggal di nama file", pesan)
        self.assertIn("01/08/2026", pesan)
        self.assertIn("1 file diproses, 0 gagal.", pesan)  # tetap masuk, tidak diblokir

    def test_gateway_tanpa_irisan_panel_diperingatkan(self):
        self._unggah("06-08-2026 PANEL W25.xlsx",
                     _parser_palsu("panel", date(2026, 8, 6), "panel-", 30))
        r = self._unggah("06-08-2026 W25 DP QRIS UNOPAY.xlsx",
                         _parser_palsu("gateway", date(2026, 8, 6), "asing-", 30))
        pesan = self._pesan(r)
        self.assertIn("tidak dikenal panel", pesan)
        self.assertIn("1 file diproses, 0 gagal.", pesan)
        # ...dan benar-benar TERCETAK sebagai peringatan, bukan sekadar ada di
        # `messages`: nada visualnya yang membedakannya dari galat.
        self.assertContains(r, 'class="msg warning"')

    def test_file_wajar_tanpa_peringatan(self):
        self._unggah("06-08-2026 PANEL W25.xlsx",
                     _parser_palsu("panel", date(2026, 8, 6), "uuid-", 30))
        r = self._unggah("06-08-2026 W25 DP QRIS UNOPAY.xlsx",
                         _parser_palsu("gateway", date(2026, 8, 6), "uuid-", 30))
        pesan = self._pesan(r)
        self.assertNotIn("tidak dikenal panel", pesan)
        self.assertNotIn("tanggal di nama file", pesan)
        self.assertNotIn("kebiasaan sumber ini", pesan)

    def test_penjaga_gagal_tidak_dilaporkan_sebagai_upload_gagal(self):
        """Bug di penjaga tak boleh mengubah upload yang SUKSES jadi 'gagal'.

        Penting karena pemanggilnya berada di dalam blok `try` handler commit:
        galat apa pun di sana akan terhitung `n_err`. `periksa_upload` menelan
        galatnya sendiri justru supaya itu tak pernah terjadi."""
        with patch("web.penjaga._periksa", side_effect=RuntimeError("boom")):
            # assertLogs sekaligus menahan traceback-nya keluar ke output tes.
            with self.assertLogs("web.penjaga", level="ERROR") as log:
                r = self._unggah("06-08-2026 Y.xlsx",
                                 _parser_palsu("bank", date(2026, 8, 6), "c-", 5))

        self.assertIn("Penjaga upload gagal", log.output[0])  # tetap tercatat, tidak hilang
        self.assertIn("1 file diproses, 0 gagal.", self._pesan(r))
        self.assertEqual(Upload.objects.filter(original_name="06-08-2026 Y.xlsx").count(), 1)
