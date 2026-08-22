"""Hutang/Piutang: agregasi murni web.hutang + view /hutang-piutang/."""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
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

    def test_overlay_tidak_aktif_lintas_bulan(self):
        self.fr("Hutang", "-500000")
        HutangManual.objects.create(
            toko=self.toko, periode=date(2026, 7, 1), field="hutang",
            nilai=Decimal("1"), tanggal=date(2026, 7, 1))
        data = hutang_piutang(self.toko, dari=date(2026, 6, 1), sampai=date(2026, 7, 31))
        self.assertFalse(data["manual"]["aktif"])
        self.assertEqual(data["total_hutang"], Decimal("-500000"))


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
