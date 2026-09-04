"""Nomor batch tampil = posisi urut per-toko (bukan pk global). Lihat tests_reconcile.py untuk pola."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()
_seq_bd = iter(range(1, 100000))


class BatchNumberTests(TestCase):
    def setUp(self):
        User.objects.create_user("adm", password="pw123456", role="admin")
        self.client.login(username="adm", password="pw123456")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.lbs = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def test_dua_batch_bernomor_1_dan_2(self):
        ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, ">#1</a>")
        self.assertContains(r, ">#2</a>")

    def test_hapus_semua_lalu_batch_baru_mulai_dari_1_lagi(self):
        b1 = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        b2 = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        b1.delete()
        b2.delete()
        ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, ">#1</a>")
        self.assertNotContains(r, ">#3</a>")  # bukan pk global (batch ke-3 yang pernah dibuat)

    def test_batch_detail_h1_pakai_nomor_urut(self):
        b1 = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        r = self.client.get(reverse("batch_detail", args=[b1.pk]))
        self.assertContains(r, "Batch #1")

    def test_lebih_dari_20_batch_nomor_slice_tetap_posisi_asli(self):
        # Riwayat menampilkan 20 terbaru: #25..#6 (bukan restart #20..#1).
        for _ in range(25):
            ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, ">#25</a>")
        self.assertContains(r, ">#6</a>")
        self.assertNotContains(r, ">#5</a>")  # di luar slice 20

    def test_scoping_per_toko_toko_lain_sudah_5_batch(self):
        lain = Toko.objects.exclude(key="lbs").first()
        for _ in range(5):
            ReconBatch.objects.create(toko=lain, tolerance=self.tol)
        ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol)
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, ">#1</a>")


class BatchDetailHomeNoPerformaTests(TestCase):
    """D3 (2026-09-04): /batch/<pk>/ perlu 226 query di produksi pada satu
    batch dgn banyak settlement terlambat ("resolved_here"). Penyebab: view
    lama menghitung `r.home_no` (nomor urut BATCH ASAL tiap baris) lewat
    `ReconBatch.objects.filter(toko=..., id__lte=...).count()` DI DALAM
    LOOP — satu COUNT query per baris resolved_here, plus satu lagi utk
    `batch_no` milik halaman itu sendiri.

    Perbaikan pakai konvensi yg SUDAH ada di dashboard (web/views.py
    ~baris 827, komentar "bisect_right(terurut, x) === COUNT(id <= x)"):
    ambil SATU daftar terurut id batch milik toko, lalu `bisect.bisect_right`
    utk batch_no maupun tiap r.home_no — O(1) query total, O(log n) per
    lookup di memori."""

    def setUp(self):
        User.objects.create_user("adm3", password="pw123456", role="admin")
        self.client.login(username="adm3", password="pw123456")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.lbs = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.panel = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        self.bank = SourceType.objects.get_or_create(key="bank", defaults={"name": "Bank"})[0]
        self.up = Upload.objects.create(source_type=self.panel, toko=self.lbs)

    def _resolved_row(self, home_batch, resolving_batch):
        """Satu MatchResult 'late_settlement': lahir di home_batch, disettle
        di resolving_batch — bentuk persis yg dibaca resolved_here."""
        run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=self.tol, batch=home_batch,
        )
        n = next(_seq_bd)
        left = Transaction.objects.create(
            upload=self.up, source_type=self.panel, toko=self.lbs, jenis="depo",
            amount=Decimal("10000"), money_delta=Decimal("-10000"),
            occurred_at=datetime(2026, 5, 1, 10, 0), row_hash=f"bd-l-{n}",
        )
        right = Transaction.objects.create(
            upload=self.up, source_type=self.bank, toko=self.lbs, jenis="depo",
            amount=Decimal("10000"), money_delta=Decimal("10000"),
            occurred_at=datetime(2026, 5, 2, 10, 0), row_hash=f"bd-r-{n}",
        )
        return MatchResult.objects.create(
            run=run, bucket="cocok", left=left, right=right,
            reason_code="late_settlement", resolved_by_batch=resolving_batch,
        )

    def _buat_skenario(self, n_resolved, tgl_awal):
        """resolving batch + n_resolved MatchResult yg masing2 punya home
        batch SENDIRI. Home batch bertanggal MUNDUR dari tgl_awal (bukan
        rentang tetap) supaya dua panggilan _buat_skenario dgn tgl_awal
        beda tak pernah nabrak unique constraint (toko, recon_date)."""
        resolving = ReconBatch.objects.create(
            toko=self.lbs, tolerance=self.tol, recon_date=tgl_awal
        )
        for i in range(n_resolved):
            home = ReconBatch.objects.create(
                toko=self.lbs, tolerance=self.tol,
                recon_date=tgl_awal - timedelta(days=n_resolved - i),
            )
            self._resolved_row(home, resolving)
        return resolving

    def test_jumlah_query_terkunci_dan_konstan_terhadap_banyak_resolved_here(self):
        kecil = self._buat_skenario(2, date(2026, 6, 1))
        # Request pemanasan: request PERTAMA sebuah sesi memodifikasi lalu
        # menyimpannya (SAVEPOINT + UPDATE django_session + RELEASE = 3 query)
        # -- bootstrap sesi, bukan biaya view ini, dan sejak v1.25.0 mencabut
        # SESSION_SAVE_EVERY_REQUEST ia hanya muncul sekali. Tanpa pemanasan,
        # angka di bawah bergantung pada apakah tes lain sudah menyentuh sesi
        # ini lebih dulu -- itulah sebab tes ini gagal HANYA di suite penuh
        # pada 04-09-2026 (13 != 16). Kami mengukur keadaan MANTAP.
        self.client.get(f"/batch/{kecil.pk}/")
        # 13 query (user tes ber-role admin -> IPAllowlistMiddleware dorman,
        # tak menambah query): session (1), auth user (1), ReconBatch via
        # get_object_or_404 (1), Toko (1), SEMUA id batch toko utk bisect —
        # dipakai batch_no DAN setiap r.home_no (1, INI yg menggantikan 1+N
        # query COUNT per-baris lama), resolved_here (1), settled_elsewhere
        # (1), per_bank money_rows (1), riwayat AuditLog (1), Toko lagi via
        # context processor (1), COUNT MatchResult badge sidebar (1),
        # ToleranceProfile lewat batch.tolerance di template (1), runs (1).
        # Dikunci supaya query baru di jalur ini terlihat eksplisit, BUKAN
        # diam-diam N+1 lagi.
        with self.assertNumQueries(13):
            r1 = self.client.get(reverse("batch_detail", args=[kecil.id]))
        self.assertEqual(r1.status_code, 200)

        besar = self._buat_skenario(25, date(2026, 7, 1))
        with CaptureQueriesContext(connection) as ctx_besar:
            r2 = self.client.get(reverse("batch_detail", args=[besar.id]))
        self.assertEqual(r2.status_code, 200)
        # Kode lama: N=2 -> ~19 query, N=25 -> ~42 query (naik ~1/baris).
        # Kode baru: flat 13 berapa pun n_resolved — bukti langsung anti-N+1
        # (sesi sudah dipersist request pemanasan di atas, jadi angka ini murni
        # biaya view).
        self.assertEqual(len(ctx_besar.captured_queries), 13)

    def test_nomor_batch_asal_benar_walau_bercampur_batch_lain(self):
        # Batch LAIN (tak terhubung resolve apa pun) ikut membentuk populasi
        # nomor urut, supaya bisect diuji thd id yg tak rapi berurutan.
        ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol, recon_date=date(2026, 4, 1))  # #1
        home = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol, recon_date=date(2026, 4, 2))  # #2
        ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol, recon_date=date(2026, 4, 3))  # #3
        resolving = ReconBatch.objects.create(toko=self.lbs, tolerance=self.tol, recon_date=date(2026, 4, 4))  # #4
        self._resolved_row(home, resolving)

        r = self.client.get(reverse("batch_detail", args=[resolving.id]))
        self.assertContains(r, "Batch #4")   # halaman yg sedang dilihat
        self.assertContains(r, ">#2</a>")    # link "Batch asal" -> home (nomor urut #2)

    def test_keluaran_sama_dgn_banyak_resolved_here(self):
        """Isi kartu 'Settlement tertunda' (jumlah baris + tombol 'tampilkan
        semua') tak berubah oleh perbaikan — hanya CARA r.home_no dihitung
        yg berubah, bukan nilainya."""
        besar = self._buat_skenario(15, date(2026, 8, 1))
        r = self.client.get(reverse("batch_detail", args=[besar.id]))
        html = r.content.decode()
        self.assertContains(r, "Settlement tertunda")
        self.assertContains(r, "Tampilkan semua (15)")
        # resolving batch dibuat LEBIH DULU (nomor #1); 15 home batch-nya
        # dibuat sesudah (nomor #2..#16, urutan pembuatan = urutan id).
        for no in range(2, 17):
            self.assertIn(f">#{no}</a>", html)
