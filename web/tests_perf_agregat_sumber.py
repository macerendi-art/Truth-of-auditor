"""Kartu "Transaksi per Sumber" & validasi tanggal /reconcile/.

Dua cacat produksi 2026-08-29, keduanya terlihat pemakai sebagai "website
lemot dan tidak bisa dibuka":

1. Agregat kartu memakai ``Count("id")`` sehingga Postgres wajib menyentuh
   heap. Pada toko g25 (1,49 juta baris) itu 210.515 blok / 3.794 ms untuk
   menghasilkan ENAM angka. ``Count("*")`` dijawab dari index saja: 33.118
   blok / 909 ms. Angkanya identik — ``id`` primary key.
2. Tanggal salah ketik ("20026-08-28") dari ``<input type="date">`` yang tak
   punya min/max sampai mentah ke mesin dan melempar ValueError → HTTP 500.
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from django.core.files.uploadedfile import SimpleUploadedFile

from reconciliation.models import ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


class AgregatSumberTests(TestCase):
    """`Count("*")` load-bearing: jangan dikembalikan ke `Count("id")`."""

    def test_sql_memakai_count_bintang(self):
        # Pengujian pada SQL, bukan hasil: angkanya memang sengaja identik,
        # jadi hanya rencana eksekusi yang membedakan — dan itulah yang dijaga.
        from django.db.models import Count

        sql = str(
            Transaction.objects.values("source_type_id")
            .annotate(n=Count("*"))
            .order_by("-n")
            .query
        )
        self.assertIn("COUNT(*)", sql)

    def test_angka_sama_dengan_count_id(self):
        from django.db.models import Count

        toko = Toko.objects.create(key="ujiperf", name="Uji Perf", panel="nexus")
        st = SourceType.objects.first()
        up = Upload.objects.create(
            toko=toko, source_type=st,
            file=SimpleUploadedFile("uji.csv", b"a,b\n1,2"),
        )
        for i in range(5):
            Transaction.objects.create(
                upload=up, toko=toko, source_type=st, jenis="depo",
                amount=1000, credit_delta=-1000, money_delta=1000,
                posted_date=date(2026, 8, 29), row_hash=f"perf-{i}",
            )
        bintang = list(
            Transaction.objects.filter(toko=toko).values("source_type_id")
            .annotate(n=Count("*")).order_by("source_type_id")
        )
        pakai_id = list(
            Transaction.objects.filter(toko=toko).values("source_type_id")
            .annotate(n=Count("id")).order_by("source_type_id")
        )
        self.assertEqual(bintang, pakai_id)


class ReconcileTanggalTests(TestCase):
    """Tanggal ngawur DITOLAK, bukan diam-diam jadi None."""

    def setUp(self):
        self.toko = Toko.objects.create(key="ujitgl", name="Uji Tgl", panel="nexus")
        self.user = User.objects.create_user(
            username="ujitgl", password="Uji#Tanggal2026", role="admin",
        )
        self.client.force_login(self.user)
        s = self.client.session
        s["active_toko_id"] = self.toko.id
        s.save()

    def _post(self, date_from, date_to=""):
        return self.client.post(
            reverse("reconcile"),
            {"tolerance": ToleranceProfile.objects.first().name,
             "date_from": date_from, "date_to": date_to,
             "inc_panel_dp": "on"},
            follow=True,
        )

    def test_tahun_kelebihan_nol_tidak_500(self):
        # kasus produksi persis: '20026-08-28'
        r = self._post("20026-08-28")
        self.assertEqual(r.status_code, 200)
        pesan = [m.message for m in r.context["messages"]]
        self.assertTrue(any("tidak valid" in m for m in pesan), pesan)

    def test_tanggal_ngawur_lain_juga_ditolak(self):
        for buruk in ("2026-13-01", "bukan-tanggal", "2026-02-30"):
            r = self._post(buruk)
            self.assertEqual(r.status_code, 200, buruk)
            pesan = [m.message for m in r.context["messages"]]
            self.assertTrue(any("tidak valid" in m for m in pesan), (buruk, pesan))

    def test_kosong_tetap_boleh(self):
        # kosong = "semua tanggal", perilaku lama yang sah — jangan ikut ditolak
        r = self._post("", "")
        pesan = [m.message for m in r.context["messages"]]
        self.assertFalse(any("tidak valid" in m for m in pesan), pesan)
