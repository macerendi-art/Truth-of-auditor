"""Dashboard: kartu "Transaksi per Sumber" (`by_source` + `tx_total`).

Jaring pengaman yang ditulis SEBELUM bentuk query-nya diubah, dan tetap
berlaku sesudahnya. Dulu kedua nilai ini dua query terpisah — agregat
ber-JOIN ke `sources_sourcetype` plus `tx.count()` — yang di produksi jadi
Parallel Seq Scan 6,1 juta baris (5,3 GB) untuk satu diagram batang.
Sekarang satu agregat yang dikelompokkan di `source_type_id`, dengan
`tx_total` diturunkan dari hasil yang sama.

Angkanya TETAP hitungan baris `Transaction` yang nyata. Agregat dari
pembukuan `Upload.rows_parsed` sempat dipertimbangkan — di data produksi
keduanya cocok 126/126 — lalu DITOLAK: kecocokan itu membuktikan jalur
divergensinya belum pernah dijalankan, bukan bahwa jalurnya aman (menghapus
transaksi lewat Django admin tak pernah memperbarui `rows_parsed`). Untuk
aplikasi audit, ±0,15 dtk tidak sepadan dengan angka yang bisa basi.

Helper `buat_tx` di bawah tetap memelihara `rows_parsed` seperti ingest
sungguhan — bukan lagi karena dibutuhkan agregatnya, melainkan supaya
fixture-nya tetap setia pada keadaan produksi.

Kontrak yang dikunci:
- bentuk dict `by_source` persis (`source_type__name`/`source_type__key`/`n`),
  urut menurun berdasar `n`;
- `tx_total == sum(n)` — penyebut `{% widthratio %}` di template;
- baris toko lain tak ikut;
- toko kosong → `by_source == []` dan `tx_total == 0` (empty state);
- filter tanggal `?dari=&sampai=` sengaja TIDAK menyentuh kartu ini;
- jumlah query tidak tumbuh terhadap jumlah baris.
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

User = get_user_model()

D1 = date(2026, 7, 20)
D2 = date(2026, 7, 23)


class _Base(TestCase):
    def setUp(self):
        User.objects.create_user("adm", "a@a.co", "pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")
        self.toko = Toko.objects.get(key="lbs")
        self.lain = Toko.objects.get(key="slo")
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1}
        )[0]
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})
        self.panel = SourceType.objects.get(key="panel")
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"}
        )[0]
        self.bank = SourceType.objects.get_or_create(
            key="bank", defaults={"name": "Bank", "is_money_source": True}
        )[0]
        self._n = 0
        self._uploads = {}

    # --- fixture: SATU-SATUNYA cara membuat Transaction di berkas ini -------
    def upload_untuk(self, source_type, toko=None):
        """Upload per (toko, source_type) — persis seperti produksi, di mana
        satu Upload hanya pernah memuat satu source_type milik satu toko."""
        toko = toko or self.toko
        kunci = (toko.id, source_type.id)
        if kunci not in self._uploads:
            self._uploads[kunci] = Upload.objects.create(
                source_type=source_type, toko=toko, rows_parsed=0
            )
        return self._uploads[kunci]

    def buat_tx(self, source_type, upload=None, toko=None, **kwargs):
        """Membuat satu Transaction LALU menaikkan `upload.rows_parsed`.

        JANGAN sederhanakan menjadi `Transaction.objects.create(...)` biasa.
        Helper ini meniru invarian jalur ingest produksi
        (`sources/services.py`, di dalam satu `atomic()`):

            Transaction.objects.bulk_create(objs, ...)
            up.rows_parsed = len(objs)
            up.save(update_fields=["rows_parsed", "rows_duplicate"])

        yaitu: `rows_parsed` = jumlah Transaction yang benar-benar dibuat lewat
        upload itu, dan Upload-nya membawa source_type + toko yang SAMA dengan
        transaksinya. Di produksi keduanya terbukti identik (126 dari 126
        kombinasi toko×sumber cocok persis, 6.088.060 vs 6.088.060). Kalau
        fixture melanggar invarian ini, tes di berkas ini akan MERAH begitu
        sumber angkanya pindah ke agregat `Upload.rows_parsed` — padahal kode
        produksinya benar. Itulah satu-satunya kegagalan yang berkas ini ada
        untuk mencegahnya.
        """
        toko = toko or self.toko
        up = upload or self.upload_untuk(source_type, toko)
        assert up.source_type_id == source_type.id and up.toko_id == toko.id, (
            "Upload harus se-source_type dan se-toko dengan transaksinya "
            "(lihat docstring buat_tx)"
        )
        self._n += 1
        kwargs.setdefault("jenis", "depo")
        kwargs.setdefault("amount", Decimal("100000"))
        kwargs.setdefault("occurred_at", datetime(2026, 7, 20, 10, 0))
        tx = Transaction.objects.create(
            upload=up, source_type=source_type, toko=toko,
            row_hash=f"h{self._n}", **kwargs,
        )
        up.rows_parsed += 1
        up.save(update_fields=["rows_parsed"])
        return tx

    def batch(self, d, toko=None):
        return ReconBatch.objects.create(
            toko=toko or self.toko, tolerance=self.tol, recon_date=d,
            summary={"dp": {"selisih": 0}, "wd": {"selisih": 0}},
        )

    def get(self, **params):
        r = self.client.get(reverse("dashboard"), params)
        self.assertEqual(r.status_code, 200)
        return r


class BySourceTests(_Base):
    def test_by_source_menghitung_semua_baris_toko(self):
        for _ in range(3):
            self.buat_tx(self.panel)
        for _ in range(2):
            self.buat_tx(self.bracket, jenis="lainnya")
        self.buat_tx(self.bank, jenis="depo")
        r = self.get()
        # Bentuk dict-nya ikut dipatok: template membaca `s.source_type__key`,
        # `s.source_type__name` dan `s.n` apa adanya, jadi rename kunci =
        # kartu kosong tanpa error. Urutan menurun (`order_by("-n")`).
        self.assertEqual(r.context["by_source"], [
            {"source_type__name": self.panel.name,
             "source_type__key": "panel", "n": 3},
            {"source_type__name": self.bracket.name,
             "source_type__key": "bracket", "n": 2},
            {"source_type__name": self.bank.name,
             "source_type__key": "bank", "n": 1},
        ])
        self.assertEqual(r.context["tx_total"], 6)

    def test_tx_total_sama_dengan_jumlah_by_source(self):
        """Invarian penyebut `{% widthratio s.n tx_total 100 %}`.

        Panjang bar tiap sumber = n/tx_total. Kalau kedua angka datang dari
        sumber yang berbeda dan pecah (mis. tx_total dari agregat Upload
        sementara by_source masih sensus Transaction, atau sebaliknya), tak
        ada error yang muncul — bar-nya cuma jadi bohong: total >  jumlah n
        membuat semua bar terlihat pendek, total < jumlah n membuat bar
        melewati 100% dan meluber dari wadahnya. Karena itu keduanya WAJIB
        dihitung dari populasi yang sama.
        """
        for _ in range(4):
            self.buat_tx(self.panel)
        for _ in range(7):
            self.buat_tx(self.bracket, jenis="lainnya")
        self.buat_tx(self.bank)
        r = self.get()
        self.assertEqual(
            r.context["tx_total"], sum(s["n"] for s in r.context["by_source"])
        )
        self.assertEqual(r.context["tx_total"], 12)

    def test_baris_toko_lain_tak_ikut(self):
        self.buat_tx(self.panel)
        self.buat_tx(self.bracket, jenis="lainnya")
        for _ in range(5):
            self.buat_tx(self.panel, toko=self.lain)
        self.buat_tx(self.bank, toko=self.lain)
        r = self.get()
        self.assertEqual(r.context["tx_total"], 2)
        self.assertEqual(
            {s["source_type__key"]: s["n"] for s in r.context["by_source"]},
            {"panel": 1, "bracket": 1},
        )

    def test_kartu_kosong_saat_toko_tanpa_data(self):
        # (a) belum ada upload sama sekali. tx_total HARUS int 0 — agregat
        # Sum() mengembalikan None untuk himpunan kosong, dan header akan
        # merender "None baris".
        r = self.get()
        self.assertEqual(r.context["by_source"], [])
        self.assertEqual(r.context["tx_total"], 0)
        self.assertContains(r, "Belum ada data.")

        # (b) ada upload TAPI nol baris (nyata di produksi: file QRFlyer shape-2
        # ter-upload "sukses" tanpa satu pun baris). Upload telanjang ini bukan
        # sampah tes — ia menjaga agar agregat berbasis Upload tidak memunculkan
        # grup n=0 yang mematikan empty state.
        Upload.objects.create(source_type=self.panel, toko=self.toko, rows_parsed=0)
        r = self.get()
        self.assertEqual(r.context["by_source"], [])
        self.assertEqual(r.context["tx_total"], 0)
        self.assertContains(r, "Belum ada data.")

    def test_mode_filter_tanggal_tak_mengubah_angka(self):
        """Kartu ini sengaja "seumur hidup" — TIDAK ikut filter tanggal.

        `by_source`/`tx_total` dihitung sebelum percabangan `mode_filter` di
        `dashboard()` dan tak pernah disaring ulang: kartu ini menjawab "berapa
        banyak data yang dimiliki toko ini", bukan "berapa di jendela ini".
        Itu perilaku yang DISENGAJA dan dikunci di sini, bukan bug yang
        kebetulan tertangkap — kalau suatu hari kartu ini memang harus ikut
        jendela, tes ini yang harus diubah lebih dulu, sadar-sadar.
        """
        b1, b2 = self.batch(D1), self.batch(D2)
        for _ in range(3):
            self.buat_tx(self.panel, posted_date=D1,
                         occurred_at=datetime(2026, 7, 20, 10, 0),
                         consumed_by_batch=b1)
        self.buat_tx(self.panel, posted_date=D2,
                     occurred_at=datetime(2026, 7, 23, 10, 0),
                     consumed_by_batch=b2)
        self.buat_tx(self.bracket, jenis="lainnya", posted_date=D1,
                     occurred_at=datetime(2026, 7, 20, 11, 0))

        polos = self.get()
        # jendela sempit: HANYA D1 (baris D2 di luar jendela)
        saring = self.get(dari=D1.isoformat(), sampai=D1.isoformat())

        # filternya memang menyala dan memang mengubah kartu lain — tanpa cek
        # ini, tes bisa lulus semu (mis. nama parameter salah ketik).
        self.assertTrue(saring.context["mode_filter"])
        self.assertNotEqual(polos.context["panel_sum"], saring.context["panel_sum"])

        # ...tapi kartu Transaksi per Sumber tetap utuh.
        self.assertEqual(polos.context["tx_total"], saring.context["tx_total"])
        self.assertEqual(polos.context["by_source"], saring.context["by_source"])
        self.assertEqual(saring.context["tx_total"], 5)


class UrutanSeriTests(_Base):
    """Urutan batang saat dua sumber punya jumlah baris SAMA.

    Tanpa pemecah seri eksplisit, urutannya milik rencana eksekusi database:
    `order_by("-n")` saja tak mengatakan apa pun tentang baris ber-`n` sama.
    Dulu pengelompokan `(name, key)` kebetulan mengeluarkannya urut nama;
    setelah pindah ke `source_type_id` ia kebetulan urut id — dan di Postgres
    "kebetulan" itu bahkan tak dijamin sama antar-eksekusi. Nilai `n` dan
    `tx_total` tak pernah berbeda; yang bergoyang cuma urutannya, yang untuk
    aplikasi audit tetap mengganggu (halaman yang sama, urutan lain).

    Fixture-nya sengaja dibuat agar urutan PEMBUATAN (=id) berlawanan dengan
    urutan NAMA: kalau tidak, tes ini akan sama-sama hijau untuk kedua
    perilaku dan tak membuktikan apa pun.
    """

    def test_urutan_stabil_saat_jumlah_seri(self):
        # id menaik: zeta → alfa → beta  (nama menaik: alfa → beta → zeta)
        zeta = SourceType.objects.create(key="z_zeta", name="Zeta")
        alfa = SourceType.objects.create(key="a_alfa", name="Alfa")
        beta = SourceType.objects.create(key="b_beta", name="Beta")
        self.assertLess(zeta.id, alfa.id)  # fixture memang melawan urutan nama
        self.assertLess(alfa.id, beta.id)
        for st in (zeta, alfa, beta):
            for _ in range(2):  # n SAMA persis untuk ketiganya → seri
                self.buat_tx(st, jenis="lainnya")
        # satu sumber ber-n lebih besar: memastikan kunci utama tetap `-n`
        for _ in range(5):
            self.buat_tx(self.panel)

        r = self.get()
        self.assertEqual(
            [s["source_type__key"] for s in r.context["by_source"]],
            ["panel", "a_alfa", "b_beta", "z_zeta"],
        )
        self.assertEqual([s["n"] for s in r.context["by_source"]], [5, 2, 2, 2])
        self.assertEqual(r.context["tx_total"], 11)


class SumberYatimTests(_Base):
    """Baris yang `source_type_id`-nya menunjuk `SourceType` yang tak ada.

    Lewat ORM ini mustahil (`source_type` FK non-null `PROTECT`); butuh
    kerusakan di tingkat DB — restore parsial, hapus manual lewat psql,
    migrasi yang gagal separuh. Justru karena begitu, kejanggalannya harus
    TERLIHAT, bukan mematikan halaman: menaikkan `_sumber[...]` jadi `KeyError`
    membuat SELURUH dashboard 500, bukan cuma kartunya — mode gagal terburuk
    yang mungkin dari sebuah diagram batang.

    Kode lama pun tidak benar (INNER JOIN membuang baris yatim dari
    `by_source` sementara `tx.count()` tetap menghitungnya, jadi bar-nya
    berbohong tanpa peringatan). Kontrak yang benar: baris yatim TETAP
    terhitung di `tx_total` DAN tampil dengan label pengganti.
    """

    def _yatimkan(self, tx):
        """Tunjuk `source_type_id` ke id yang tak ada — SQL mentah, karena
        `save()` akan ditolak FK. Aman di SQLite: Django membuat FK-nya
        DEFERRABLE INITIALLY DEFERRED dan `TestCase` tak pernah commit."""
        hantu = SourceType.objects.order_by("-id").first().id + 999
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE transactions_transaction SET source_type_id = %s WHERE id = %s",
                [hantu, tx.id],
            )
        # dikembalikan lagi di akhir tes: jangan sampai pemeriksaan constraint
        # saat teardown yang meledak, bukan kode yang sedang diuji.
        self.addCleanup(self._pulihkan, tx.id, tx.source_type_id)
        return hantu

    def _pulihkan(self, tx_id, source_type_id):
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE transactions_transaction SET source_type_id = %s WHERE id = %s",
                [source_type_id, tx_id],
            )

    def test_sumber_yatim_tidak_mematikan_dashboard(self):
        for _ in range(3):
            self.buat_tx(self.panel)
        rusak = self.buat_tx(self.bank)
        self._yatimkan(rusak)

        r = self.get()  # ← `self.get` sudah meng-assert 200
        # barisnya TIDAK boleh hilang diam-diam: tetap ikut penyebut bar
        self.assertEqual(r.context["tx_total"], 4)
        self.assertEqual(r.context["tx_total"],
                         sum(s["n"] for s in r.context["by_source"]))
        # ...dan kejanggalannya kelihatan di layar, bukan disembunyikan
        yatim = [s for s in r.context["by_source"] if s["source_type__key"] == "?"]
        self.assertEqual(len(yatim), 1)
        self.assertEqual(yatim[0]["n"], 1)
        self.assertEqual(yatim[0]["source_type__name"], "(sumber tak dikenal)")
        self.assertContains(r, "(sumber tak dikenal)")

    def test_bentuk_dict_tetap_sama_untuk_baris_yatim(self):
        """Label pengganti tetap harus memenuhi kontrak template (3 kunci,
        `n` int, dua sisanya str) — kalau tidak, kartunya merender kosong."""
        rusak = self.buat_tx(self.panel)
        self._yatimkan(rusak)
        r = self.get()
        for s in r.context["by_source"]:
            self.assertEqual(set(s), {"source_type__key", "source_type__name", "n"})
            self.assertIsInstance(s["n"], int)
            self.assertIsInstance(s["source_type__key"], str)
            self.assertIsInstance(s["source_type__name"], str)


class DashboardSumberQueryTests(_Base):
    """Jumlah query dashboard harus KONSTAN terhadap jumlah BARIS — itu justru
    alasan sensus `Transaction` diganti agregat `Upload`: bukan jumlah query-nya
    yang jadi masalah, melainkan biaya satu query sensus di tabel 5,3 GB."""

    def test_dashboard_satu_toko_query_tak_tumbuh(self):
        b = self.batch(D1)
        for _ in range(3):
            self.buat_tx(self.panel, posted_date=D1, consumed_by_batch=b)
        self.buat_tx(self.bracket, jenis="lainnya", posted_date=D1)
        self.buat_tx(self.bank, posted_date=D1)

        self.client.get(reverse("dashboard"))  # pemanasan (cache ContentType dkk.)
        with CaptureQueriesContext(connection) as before:
            self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

        # HANYA menambah TRANSAKSI, ke aliran (toko, sumber) yang SUDAH ada:
        # tak ada source_type baru, tak ada upload pertama, dan — penting —
        # TAK ADA ReconBatch baru. Jumlah query dashboard memang konstan
        # terhadap jumlah baris, tapi TUMBUH terhadap jumlah batch: ada N+1
        # kalender di `web/views.py` (`ReconBatch.objects.filter(
        # toko=active, id__lte=b.id).count()` di dalam loop 14 hari). Jadi
        # jangan "melengkapi" tes ini dengan batch tambahan — ia akan merah
        # karena N+1 yang lain, bukan karena regresi kartu ini. N+1 kalender
        # itu punya fase & tesnya sendiri.
        for _ in range(200):
            self.buat_tx(self.panel, posted_date=D1, consumed_by_batch=b)

        with CaptureQueriesContext(connection) as after:
            self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertEqual(
            len(before), len(after),
            f"query tumbuh {len(before)}→{len(after)} saat baris bertambah (N+1)")


class BentukKontrakTests(_Base):
    """Kontrak kartu ini dengan `web/templates/web/dashboard.html` (baris 191-205),
    ditulis saat bentuk query-nya diubah (grouping pindah ke `source_type_id`
    agar Postgres tak menyeret jutaan baris ke hash join `sources_sourcetype`).
    Template membaca kuncinya apa adanya — rename/tambah kunci = kartu diam-diam
    salah, bukan error."""

    def test_bentuk_dict_by_source_tetap_sama(self):
        self.buat_tx(self.panel)
        self.buat_tx(self.bracket, jenis="lainnya")
        r = self.get()
        self.assertTrue(r.context["by_source"])
        for s in r.context["by_source"]:
            with self.subTest(sumber=s):
                # PERSIS tiga kunci: tak kurang (template merender kosong) dan
                # tak lebih (kunci internal yang bocor jadi kontrak dadakan).
                self.assertEqual(
                    set(s), {"source_type__key", "source_type__name", "n"})
                self.assertIsInstance(s["n"], int)
                self.assertIsInstance(s["source_type__key"], str)
                self.assertIsInstance(s["source_type__name"], str)

    def test_sumber_tanpa_baris_tidak_muncul(self):
        """SourceType yang tak punya transaksi di toko ini tak boleh jadi entri
        n=0. Kartu ini menampilkan sumber yang DIPAKAI toko; entri nol akan
        merender bar kosong untuk tiap sumber yang pernah ada di seed —
        dan `{% widthratio 0 tx_total 100 %}` tak akan meneriakkannya."""
        self.buat_tx(self.panel)
        # `bank` & `bracket` ada di tabel referensi, tapi tak punya baris di
        # toko ini (bank punya baris di toko LAIN — jebakan grouping tanpa
        # filter toko).
        self.buat_tx(self.bank, toko=self.lain)
        r = self.get()
        self.assertEqual(
            [s["source_type__key"] for s in r.context["by_source"]], ["panel"])
        self.assertNotIn(0, [s["n"] for s in r.context["by_source"]])
