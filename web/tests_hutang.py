"""Hutang/Piutang: agregasi murni web.hutang + view /hutang-piutang/."""
import re
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import AuditLog
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.hutang import hutang_piutang
from web.models import HutangManual

TGL = date(2026, 7, 1)
User = get_user_model()


class _HutangData(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"})[0]
        self.up = Upload.objects.create(source_type=self.bracket, toko=self.toko)
        self._n = 0

    def fr(self, kategori, total, tanggal=TGL, member="BUDI", jam="10:00"):
        self._n += 1
        return Transaction.objects.create(
            upload=self.up, source_type=self.bracket, toko=self.toko,
            jenis="lainnya", amount=abs(Decimal(total)), money_delta=Decimal(total),
            posted_date=tanggal, occurred_at=datetime(2026, 7, 1, 10, 0),
            row_hash=f"hp{self._n}",
            raw={"Bank": "BANK BCA | SUSI | DEPOSIT", "Kategori": kategori,
                 "Jam": jam, "Member": member},
        )


class AgregasiHutangTests(_HutangData):
    def test_hanya_kategori_hutang_piutang(self):
        self.fr("Hutang", "-500000")
        self.fr("PIUTANG", "250000")           # varian kapital ikut
        self.fr("Deposit", "100000")            # bukan hutang/piutang → keluar
        data = hutang_piutang(self.toko)
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["total_hutang"], Decimal("-500000"))
        self.assertEqual(data["total_piutang"], Decimal("250000"))
        self.assertEqual(data["netto"], Decimal("-250000"))
        kategori = {r["kategori"] for r in data["rows"]}
        self.assertEqual(kategori, {"hutang", "piutang"})

    def test_filter_rentang_tanggal(self):
        self.fr("Hutang", "-100", tanggal=date(2026, 6, 1))
        self.fr("Hutang", "-200", tanggal=TGL)
        data = hutang_piutang(self.toko, dari=date(2026, 6, 15))
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["rows"][0]["nominal"], Decimal("-200"))

    def test_baris_bawa_member_dan_akun(self):
        self.fr("Piutang", "75000", member="SITI")
        (r,) = hutang_piutang(self.toko)["rows"]
        self.assertEqual(r["member"], "SITI")
        self.assertEqual(r["account"], "BANK BCA | SUSI | DEPOSIT")
        self.assertEqual(r["tanggal"], TGL)

    def test_urutan_terbaru_dulu_dan_tahan_tanggal_none(self):
        self.fr("Hutang", "-100", tanggal=date(2026, 6, 20), jam="09:00")
        self.fr("Piutang", "300", tanggal=TGL, jam="08:00")
        self.fr("Hutang", "-200", tanggal=TGL, jam="11:00")
        # baris tanggal gagal-parse (posted_date=None) tidak boleh membuat sort crash
        t = self.fr("Hutang", "-50", tanggal=TGL, jam="07:00")
        t.posted_date = None
        t.save(update_fields=["posted_date"])
        data = hutang_piutang(self.toko)
        nominal = [r["nominal"] for r in data["rows"]]
        self.assertEqual(nominal, [Decimal("-200"), Decimal("300"), Decimal("-100"), Decimal("-50")])


class OverlayHutangManualTests(_HutangData):
    """Override total bulanan via HutangManual — baris FR tetap auto."""

    def test_overlay_timpa_total_satu_bulan(self):
        self.fr("Hutang", "-500000")
        self.fr("Piutang", "250000")
        admin = User.objects.create_user(username="adm_hp", password="x", role="admin")
        HutangManual.objects.create(
            toko=self.toko, periode=date(2026, 7, 1), field="hutang",
            nilai=Decimal("-111000"), tanggal=date(2026, 7, 15),
            catatan="koreksi admin", dibuat_oleh=admin)
        HutangManual.objects.create(
            toko=self.toko, periode=date(2026, 7, 1), field="piutang",
            nilai=Decimal("222000"), tanggal=date(2026, 7, 15),
            catatan="koreksi admin", dibuat_oleh=admin)
        data = hutang_piutang(self.toko, dari=date(2026, 7, 1), sampai=date(2026, 7, 31))
        self.assertEqual(data["count"], 2)  # baris FR utuh
        self.assertEqual(data["total_hutang_auto"], Decimal("-500000"))
        self.assertEqual(data["total_piutang_auto"], Decimal("250000"))
        self.assertEqual(data["total_hutang"], Decimal("-111000"))
        self.assertEqual(data["total_piutang"], Decimal("222000"))
        self.assertEqual(data["netto"], Decimal("111000"))
        self.assertTrue(data["manual"]["aktif"])
        self.assertEqual(data["manual"]["hutang"]["catatan"], "koreksi admin")
        self.assertEqual(data["manual"]["hutang"]["oleh"], "adm_hp")

    def test_overlay_hanya_field_yang_ada(self):
        self.fr("Hutang", "-500000")
        self.fr("Piutang", "250000")
        HutangManual.objects.create(
            toko=self.toko, periode=date(2026, 7, 1), field="hutang",
            nilai=Decimal("0"), tanggal=date(2026, 7, 1))
        data = hutang_piutang(self.toko, dari=date(2026, 7, 1), sampai=date(2026, 7, 31))
        self.assertEqual(data["total_hutang"], Decimal("0"))
        self.assertEqual(data["total_piutang"], Decimal("250000"))  # auto

    def test_overlay_lintas_bulan_tetap_pakai_override(self):
        """Juli override + Agustus auto — filter Juli–Agustus tidak menghidupkan FR Juli."""
        self.fr("Piutang", "100014000", tanggal=date(2026, 7, 11))  # FR Juli (seperti SSN)
        self.fr("Piutang", "5000000", tanggal=date(2026, 8, 10))     # FR Agustus
        HutangManual.objects.create(
            toko=self.toko, periode=date(2026, 7, 1), field="piutang",
            nilai=Decimal("0"), tanggal=date(2026, 7, 15),
            catatan="nol-kan juli")
        data = hutang_piutang(
            self.toko, dari=date(2026, 7, 1), sampai=date(2026, 8, 22))
        self.assertTrue(data["manual"]["aktif"])
        self.assertEqual(data["total_piutang_auto"], Decimal("105014000"))
        # Juli diganti 0, Agustus tetap 5jt
        self.assertEqual(data["total_piutang"], Decimal("5000000"))
        self.assertEqual(data["total_hutang"], Decimal("0"))
        self.assertEqual(data["count"], 2)  # baris FR tetap tampil
        self.assertEqual(
            data["manual"]["bulan_override"], [date(2026, 7, 1)])

    def test_overlay_lintas_bulan_dua_override(self):
        self.fr("Hutang", "-100", tanggal=date(2026, 7, 1))
        self.fr("Hutang", "-200", tanggal=date(2026, 8, 1))
        HutangManual.objects.create(
            toko=self.toko, periode=date(2026, 7, 1), field="hutang",
            nilai=Decimal("10"), tanggal=date(2026, 7, 1))
        HutangManual.objects.create(
            toko=self.toko, periode=date(2026, 8, 1), field="hutang",
            nilai=Decimal("20"), tanggal=date(2026, 8, 1))
        data = hutang_piutang(
            self.toko, dari=date(2026, 7, 1), sampai=date(2026, 8, 31))
        self.assertEqual(data["total_hutang"], Decimal("30"))
        self.assertEqual(
            set(data["manual"]["bulan_override"]),
            {date(2026, 7, 1), date(2026, 8, 1)})


class HutangViewTests(_HutangData):
    def setUp(self):
        super().setUp()
        user = get_user_model().objects.create_user(
            username="auditor2", password="rahasia123", role="auditor")
        user.allowed_tokos.add(self.toko)
        self.client.force_login(user)
        s = self.client.session
        s["active_toko_id"] = self.toko.id
        s.save()

    def test_halaman_render_dengan_ringkasan(self):
        self.fr("Hutang", "-500000")
        r = self.client.get(reverse("hutang_piutang"),
                            {"dari": "2026-06-01", "sampai": "2026-07-31"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Hutang/Piutang")
        self.assertContains(r, "500.000")

    def test_kosong_tampil_empty_state(self):
        r = self.client.get(reverse("hutang_piutang"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Belum ada")

    def test_auditor_tidak_lihat_form_manual(self):
        r = self.client.get(reverse("hutang_piutang"),
                            {"dari": "2026-07-01", "sampai": "2026-07-31"})
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Override total bulanan")
        self.assertFalse(r.context["boleh_edit_manual"])


class HutangManualAdminViewTests(_HutangData):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(
            username="admin_hp", password="rahasia123", role="admin")
        self.auditor = User.objects.create_user(
            username="aud_hp", password="rahasia123", role="auditor")
        self.auditor.allowed_tokos.add(self.toko)
        self.client.force_login(self.admin)
        s = self.client.session
        s["active_toko_id"] = self.toko.id
        s.save()

    def test_admin_lihat_form_manual(self):
        r = self.client.get(reverse("hutang_piutang"),
                            {"dari": "2026-07-01", "sampai": "2026-07-31"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Override total bulanan")
        self.assertTrue(r.context["boleh_edit_manual"])

    def test_simpan_override_dan_audit(self):
        self.fr("Hutang", "-500000")
        r = self.client.post(reverse("hutang_manual_simpan"), {
            "bulan": "2026-07",
            "tanggal": "2026-07-20",
            "nilai_hutang": "-1000000",
            "nilai_piutang": "2000000",
            "catatan": "pinjaman antar toko",
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(HutangManual.objects.filter(toko=self.toko).count(), 2)
        h = HutangManual.objects.get(toko=self.toko, field="hutang")
        self.assertEqual(h.nilai, Decimal("-1000000"))
        self.assertEqual(h.tanggal, date(2026, 7, 20))
        self.assertEqual(h.catatan, "pinjaman antar toko")
        self.assertTrue(AuditLog.objects.filter(aksi="hutang_manual").exists())
        log = AuditLog.objects.filter(aksi="hutang_manual", detail__field="hutang").latest("id")
        self.assertEqual(log.detail["nilai_baru"], "-1000000")
        self.assertEqual(log.detail["catatan"], "pinjaman antar toko")

        # Halaman satu bulan menampilkan total override + badge
        page = self.client.get(reverse("hutang_piutang"),
                               {"dari": "2026-07-01", "sampai": "2026-07-31"})
        self.assertContains(page, "Manual")
        self.assertEqual(page.context["data"]["total_hutang"], Decimal("-1000000"))
        self.assertEqual(page.context["data"]["total_piutang"], Decimal("2000000"))

    def test_hapus_override_dan_audit(self):
        HutangManual.objects.create(
            toko=self.toko, periode=date(2026, 7, 1), field="hutang",
            nilai=Decimal("1"), tanggal=date(2026, 7, 1), dibuat_oleh=self.admin)
        r = self.client.post(reverse("hutang_manual_simpan"), {
            "bulan": "2026-07", "hapus": "1",
        })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(HutangManual.objects.filter(toko=self.toko).exists())
        self.assertTrue(AuditLog.objects.filter(aksi="hutang_manual_hapus").exists())

    def test_auditor_ditolak_post(self):
        self.client.force_login(self.auditor)
        s = self.client.session
        s["active_toko_id"] = self.toko.id
        s.save()
        r = self.client.post(reverse("hutang_manual_simpan"), {
            "bulan": "2026-07",
            "tanggal": "2026-07-01",
            "nilai_hutang": "100",
        })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(HutangManual.objects.exists())


class PerfHutangQueryTests(TestCase):
    """D2 (2026-09-04): perbaikan performa mode Semua Toko — lihat CLAUDE.md
    "Performa (v1.23.0)". Dua invarian yang WAJIB dijaga tes, bukan cuma
    diyakini benar oleh mata:

    1. Jumlah query **konstan** terhadap jumlah toko (preseden: dua tes N+1
       dashboard mode Semua Toko).
    2. Baris "berat" (Bank/Member/Username/Expense) hanya diambil untuk baris
       yang BENAR-BENAR dibaca (satu halaman `Paginator`), bukan seluruh
       baris yang cocok kategori hutang/piutang.
    """

    def setUp(self):
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"})[0]
        self._n = 0

    def _fr(self, toko, up, kategori, total, tanggal, jam="10:00"):
        self._n += 1
        return Transaction.objects.create(
            upload=up, source_type=self.bracket, toko=toko,
            jenis="lainnya", amount=abs(Decimal(total)), money_delta=Decimal(total),
            posted_date=tanggal,
            occurred_at=datetime(tanggal.year, tanggal.month, tanggal.day, 10, 0),
            row_hash=f"perf{self._n}",
            raw={"Bank": "BANK BCA | X | DEPOSIT", "Kategori": kategori,
                 "Jam": jam, "Member": "BUDI"},
        )

    def _seed(self, prefix, n_toko, n_baris_per_toko):
        tokos = []
        for i in range(n_toko):
            t = Toko.objects.create(key=f"{prefix}{i}", name=f"{prefix}{i}".upper(),
                                     panel="nexus")
            up = Upload.objects.create(source_type=self.bracket, toko=t)
            for j in range(n_baris_per_toko):
                self._fr(t, up, "Hutang" if j % 2 == 0 else "Piutang",
                         "-1000" if j % 2 == 0 else "1000", TGL)
            tokos.append(t)
        return tokos

    def _pakai_seperti_view(self, data):
        """Yang dibaca view/template dari `data`: bool (empty-state), count
        (label baris), dan satu halaman lewat `Paginator` (40/hal)."""
        bool(data["rows"])
        _ = data["count"]
        _ = data["rows"][0:40]

    def test_query_konstan_terhadap_jumlah_toko(self):
        tokos = self._seed("qh", n_toko=3, n_baris_per_toko=5)
        with CaptureQueriesContext(connection) as before:
            data = hutang_piutang(tokos, dari=TGL, sampai=TGL)
            self._pakai_seperti_view(data)

        tokos = tokos + self._seed("qh2_", n_toko=12, n_baris_per_toko=5)
        with CaptureQueriesContext(connection) as after:
            data = hutang_piutang(tokos, dari=TGL, sampai=TGL)
            self._pakai_seperti_view(data)

        self.assertEqual(
            len(before.captured_queries), len(after.captured_queries),
            f"query tumbuh {len(before.captured_queries)}→"
            f"{len(after.captured_queries)} saat toko bertambah (N+1)")
        # Dua query: satu scan kategori sempit (fase 1) + satu ambil kolom
        # berat utk halaman yang dibaca (fase 2, di-PK `id__in`).
        self.assertEqual(len(before.captured_queries), 2)

    def test_slice_kecil_tak_menyeret_seluruh_baris_cocok(self):
        tokos = self._seed("lebar", n_toko=1, n_baris_per_toko=50)
        data = hutang_piutang(tokos[0], dari=TGL, sampai=TGL)
        self.assertEqual(data["count"], 50)

        with CaptureQueriesContext(connection) as ctx:
            halaman = data["rows"][0:5]
        self.assertEqual(len(halaman), 5)
        # Persis SATU query tambahan (fase 2), dan lebarnya cuma 5 id —
        # bukan 50. Ini yang membuat kartu "N baris" tak perlu menyeret
        # Bank/Member/Username/Expense utk baris yang tak pernah ditampilkan.
        self.assertEqual(len(ctx.captured_queries), 1)
        sql = ctx.captured_queries[0]["sql"]
        in_clause = re.search(r'"id" IN \(([^)]*)\)', sql).group(1)
        self.assertEqual(len(in_clause.split(",")), 5)

    def test_indeks_negatif_dan_iterasi_penuh_tetap_konsisten(self):
        tokos = self._seed("neg", n_toko=1, n_baris_per_toko=4)
        data = hutang_piutang(tokos[0], dari=TGL, sampai=TGL)
        semua = list(data["rows"])
        self.assertEqual(len(semua), 4)
        self.assertEqual(data["rows"][-1], semua[-1])
        self.assertEqual(data["rows"][0], semua[0])
