"""Dashboard: kalender 14 hari — nomor batch & jumlah query.

Dua hal dikunci di sini, dan yang KEDUA jauh lebih penting daripada yang pertama:

1. Jumlah query dashboard tidak boleh tumbuh terhadap jumlah BATCH. Hari ini
   `web/views.py` menghitung nomor batch tiap sel kalender dengan satu COUNT
   terpisah (`ReconBatch.objects.filter(toko=active, id__lte=b.id).count()`)
   di dalam loop 14 hari — sampai 14 query hanya untuk 14 angka kecil.

2. Nomor itu WAJIB tetap menghitung SEMUA batch toko, termasuk yang
   `recon_date`-nya NULL. Godaan alami saat membereskan (1) adalah menghitung
   posisi dari daftar `batches` yang sudah ada di memori — tapi daftar itu
   tersaring `recon_date__isnull=False`, jadi nomornya akan bergeser diam-diam
   begitu toko punya satu saja batch tanpa tanggal. Nomor batch yang bergeser
   di aplikasi audit adalah kerusakan mahal: laporan lama, tangkapan layar, dan
   percakapan operator menyebut "Batch #27". Konvensi yang sama (posisi menaik
   menurut id atas SELURUH batch toko) dipakai `web/kelengkapan.py`.

Semua tanggal di berkas ini RELATIF terhadap `date.today()`: kalender ber-anchor
`max(batch terakhir, hari ini)`, jadi tanggal mati membuat tesnya kedaluwarsa
sendiri (pernah terjadi 27 Juli 2026 — lihat `tests_dashboard_g2.py`).
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import Toko

User = get_user_model()


class _Base(TestCase):
    def setUp(self):
        User.objects.create_user("adm", "a@a.co", "pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")
        self.toko = Toko.objects.get(key="lbs")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})
        self.today = date.today()

    def batch(self, d):
        """Batch bertanggal. `d=None` = batch tanpa recon_date (nyata: run yang
        dibuat sebelum rekonsiliasi harian, atau run manual lintas periode)."""
        return ReconBatch.objects.create(
            toko=self.toko, tolerance=self.tol, recon_date=d,
            summary={"dp": {"selisih": 0}, "wd": {"selisih": 0}},
        )

    def get(self, **params):
        r = self.client.get(reverse("dashboard"), params)
        self.assertEqual(r.status_code, 200)
        return r

    def nomor_lama(self, b):
        """Perhitungan nomor batch versi lama — acuan kebenaran tes ini."""
        return ReconBatch.objects.filter(toko=self.toko, id__lte=b.id).count()


class KalenderQueryTests(_Base):
    def test_query_kalender_tidak_tumbuh_dengan_jumlah_batch(self):
        # 2 batch di dalam jendela 14 hari...
        self.batch(self.today)
        self.batch(self.today - timedelta(days=1))

        self.client.get(reverse("dashboard"))  # pemanasan (cache ContentType dkk.)
        with CaptureQueriesContext(connection) as before:
            self.get()

        # ...lalu 10 batch lagi, SEMUANYA di dalam jendela yang sama (today-2
        # s/d today-11 — jendelanya today-13..today). Tak ada sumber, upload,
        # atau transaksi baru: satu-satunya yang bertambah adalah jumlah batch.
        for i in range(2, 12):
            self.batch(self.today - timedelta(days=i))

        with CaptureQueriesContext(connection) as after:
            self.get()

        self.assertEqual(
            len(before), len(after),
            f"query tumbuh {len(before)}→{len(after)} saat batch bertambah "
            f"(N+1 nomor batch di loop kalender)")


class NomorBatchTests(_Base):
    def test_nomor_batch_menghitung_batch_tanpa_tanggal(self):
        """Tes paling penting di berkas ini — HIJAU sebelum DAN sesudah optimasi.

        Batch tanpa `recon_date` tak pernah muncul di kalender, tapi ia tetap
        memakan satu nomor urut. Kalau nomor dihitung dari daftar `batches`
        (yang tersaring `recon_date__isnull=False`), b2/b3 di bawah akan
        bernomor 2/3, bukan 3/4.
        """
        b1 = self.batch(self.today - timedelta(days=2))
        self.batch(None)               # id di antara — TIDAK bertanggal
        b2 = self.batch(self.today - timedelta(days=1))
        b3 = self.batch(self.today)

        kal = self.get().context["kal"]
        per_tanggal = {s["d"]: s for s in kal if s["batch"]}

        # (a) setiap sel kalender identik dengan perhitungan lama, satu per satu.
        self.assertEqual(len(per_tanggal), 3)
        for b in (b1, b2, b3):
            with self.subTest(batch=b.pk):
                self.assertEqual(
                    per_tanggal[b.recon_date]["no"], self.nomor_lama(b))

        # (b) angkanya dieja eksplisit — kalau `nomor_lama` ikut rusak, (a) bisa
        # lulus semu. Batch tanpa tanggal menempati nomor 2, jadi b2 = 3.
        self.assertEqual(per_tanggal[b1.recon_date]["no"], 1)
        self.assertEqual(per_tanggal[b2.recon_date]["no"], 3)
        self.assertEqual(per_tanggal[b3.recon_date]["no"], 4)

        # (c) sel tanpa batch tetap None (bukan 0) — template membedakannya.
        self.assertTrue(all(s["no"] is None for s in kal if not s["batch"]))

    def test_total_batch_tetap_menghitung_semua(self):
        """`last_no` (satu-satunya jalan keluar `total_b` ke template) ikut
        menghitung batch tanpa tanggal — populasi yang sama dengan nomor sel."""
        self.batch(self.today - timedelta(days=1))
        self.batch(None)
        terakhir = self.batch(self.today)

        r = self.get()
        self.assertEqual(r.context["last"], terakhir)
        self.assertEqual(r.context["last_no"], 3)
        self.assertEqual(r.context["last_no"], self.nomor_lama(terakhir))
