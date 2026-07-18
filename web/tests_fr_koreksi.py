"""Koreksi sel FR (paket A): model overlay + agregasi + view popup."""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog
from sources.models import Toko, SourceType, Upload
from transactions.models import Transaction
from web.breakdown import bracket_breakdown, KATEGORI_KANONIK

TGL = date(2026, 7, 1)


class FRKoreksiModelTests(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")

    def _buat(self, **over):
        from web.models import FRKoreksi
        base = dict(toko=self.toko, tanggal=TGL,
                    account="BANK BCA | SUSILAWATI | DEPOSIT",
                    kolom="deposit", nilai=Decimal("123000"),
                    alasan="mistake_cs", catatan="salah input CS")
        base.update(over)
        return FRKoreksi.objects.create(**base)

    def test_buat_dan_str(self):
        k = self._buat()
        self.assertIn("BANK BCA", str(k))
        self.assertIn("deposit", str(k))
        self.assertEqual(k.get_alasan_display(), "Mistake CS")

    def test_satu_koreksi_per_sel(self):
        self._buat()
        with self.assertRaises(IntegrityError):
            self._buat(nilai=Decimal("999"))

    def test_sel_beda_boleh(self):
        self._buat()
        self._buat(kolom="saldo_awal")
        self._buat(tanggal=date(2026, 7, 2))
        from web.models import FRKoreksi
        self.assertEqual(FRKoreksi.objects.count(), 3)


class _BracketKoreksiData(TestCase):
    """Fixture bracket + helper baris FR (pola web/tests_breakdown.py)."""

    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.bracket = SourceType.objects.get_or_create(
            key="bracket", defaults={"name": "Bracket"})[0]
        self.up = Upload.objects.create(source_type=self.bracket, toko=self.toko)
        self._n = 0

    def fr(self, bank, kategori, total, saldo, jam="10:00"):
        self._n += 1
        return Transaction.objects.create(
            upload=self.up, source_type=self.bracket, toko=self.toko,
            jenis="lainnya", amount=abs(Decimal(total)), money_delta=Decimal(total),
            balance_after=None if saldo is None else Decimal(saldo),
            posted_date=TGL, occurred_at=datetime(2026, 7, 1, 10, 0),
            row_hash=f"frk{self._n}",
            raw={"Bank": bank, "Kategori": kategori, "Jam": jam},
        )

    def koreksi(self, kolom, nilai, account="BANK BCA | SUSI | DEPOSIT", **over):
        from web.models import FRKoreksi
        base = dict(toko=self.toko, tanggal=TGL, account=account,
                    kolom=kolom, nilai=Decimal(nilai), alasan="mistake_cs")
        base.update(over)
        return FRKoreksi.objects.create(**base)


class OverlayKoreksiTests(_BracketKoreksiData):
    AKUN = "BANK BCA | SUSI | DEPOSIT"

    def _dasar(self):
        # saldo awal 1.000.000 → depo +500rb (saldo 1.500.000) → beban −4.972
        self.fr(self.AKUN, "Deposit", "500000", "1500000", jam="09:00")
        self.fr(self.AKUN, "BEBAN ADMIN QRIS", "-4972", "1495028", jam="10:30")

    def test_tanpa_koreksi_perilaku_lama_persis(self):
        self._dasar()
        data = bracket_breakdown(self.toko, TGL)
        (acc,) = data["accounts"]
        self.assertEqual(acc["koreksi"], {})
        self.assertEqual(acc["mutasi"], Decimal("495028"))
        self.assertEqual(acc["selisih"], Decimal("0"))

    def test_koreksi_sel_kategori_mengubah_mutasi_selisih_total(self):
        self._dasar()
        self.koreksi("deposit", "450000", catatan="salah input")
        data = bracket_breakdown(self.toko, TGL)
        (acc,) = data["accounts"]
        self.assertEqual(acc["kategori"]["deposit"], Decimal("450000"))
        self.assertEqual(acc["mutasi"], Decimal("445028"))       # 450000 − 4972
        self.assertEqual(acc["selisih"], Decimal("50000"))       # akhir − (awal+mutasi)
        self.assertEqual(data["total"]["kategori"]["deposit"], Decimal("450000"))
        self.assertEqual(data["total"]["mutasi"], Decimal("445028"))
        info = acc["koreksi"]["deposit"]
        self.assertEqual(info["asli"], Decimal("500000"))
        self.assertEqual(info["nilai"], Decimal("450000"))
        self.assertEqual(info["alasan"], "Mistake CS")
        self.assertEqual(info["catatan"], "salah input")

    def test_koreksi_saldo_awal(self):
        self._dasar()
        self.koreksi("saldo_awal", "900000")
        data = bracket_breakdown(self.toko, TGL)
        (acc,) = data["accounts"]
        self.assertEqual(acc["saldo_awal"], Decimal("900000"))
        self.assertEqual(acc["selisih"], Decimal("100000"))
        self.assertEqual(acc["koreksi"]["saldo_awal"]["asli"], Decimal("1000000"))

    def test_koreksi_kategori_belum_muncul_menambah_kolom(self):
        self._dasar()
        self.koreksi("beban mistake cs", "-25000")
        data = bracket_breakdown(self.toko, TGL)
        (acc,) = data["accounts"]
        self.assertEqual(acc["kategori"]["beban mistake cs"], Decimal("-25000"))
        self.assertIn("beban mistake cs", [s for s, _ in data["kolom"]])
        self.assertIsNone(acc["koreksi"]["beban mistake cs"]["asli"])

    def test_dengan_koreksi_false_nilai_asli(self):
        self._dasar()
        self.koreksi("deposit", "450000")
        data = bracket_breakdown(self.toko, TGL, dengan_koreksi=False)
        (acc,) = data["accounts"]
        self.assertEqual(acc["kategori"]["deposit"], Decimal("500000"))
        self.assertEqual(acc["koreksi"], {})

    def test_koreksi_akun_tak_hadir_diabaikan(self):
        self._dasar()
        self.koreksi("deposit", "1", account="BANK LAIN | X | DEPOSIT")
        data = bracket_breakdown(self.toko, TGL)
        (acc,) = data["accounts"]
        self.assertEqual(acc["kategori"]["deposit"], Decimal("500000"))


class UrutanHeaderTests(TestCase):
    def test_acuan_kuning_other_expense_sebelum_mistake_cs(self):
        slugs = [s for s, _ in KATEGORI_KANONIK]
        i_biaya = slugs.index("biaya transaksi")
        i_other = slugs.index("beban other expense")
        i_cs = slugs.index("beban mistake cs")
        self.assertLess(i_biaya, i_other)
        self.assertLess(i_other, i_cs)


class KoreksiViewTests(_BracketKoreksiData):
    AKUN = "BANK BCA | SUSI | DEPOSIT"

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username="auditor1", password="rahasia123", role="auditor")
        self.user.allowed_tokos.add(self.toko)
        self.client.force_login(self.user)
        s = self.client.session
        s["active_toko_id"] = self.toko.id
        s.save()
        self.fr(self.AKUN, "Deposit", "500000", "1500000", jam="09:00")

    def _post(self, **over):
        base = dict(date="2026-07-01", account=self.AKUN, kolom="deposit",
                    nilai="450000", alasan="mistake_cs", catatan="uji")
        base.update(over)
        return self.client.post(reverse("fr_koreksi_simpan"), base)

    def test_form_get_berisi_nilai_asli(self):
        r = self.client.get(reverse("fr_koreksi_form"), {
            "date": "2026-07-01", "account": self.AKUN, "kolom": "deposit"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "500.000")       # nilai asli (locale id: titik ribuan)
        self.assertContains(r, "Mistake CS")    # opsi alasan

    def test_simpan_membuat_koreksi_dan_audit(self):
        r = self._post()
        self.assertEqual(r.status_code, 200)
        from web.models import FRKoreksi
        k = FRKoreksi.objects.get()
        self.assertEqual(k.nilai, Decimal("450000"))
        self.assertEqual(k.dibuat_oleh, self.user)
        log = AuditLog.objects.filter(aksi="fr_koreksi").latest("id")
        self.assertEqual(log.detail["kolom"], "deposit")
        self.assertEqual(log.detail["nilai_baru"], "450000")
        self.assertIn("fr-control", r.content.decode())   # tabel dirender ulang
        self.assertIn("450.000", r.content.decode())      # nilai koreksi tampil

    def test_simpan_ulang_memperbarui_baris_sama(self):
        self._post()
        self._post(nilai="475000")
        from web.models import FRKoreksi
        self.assertEqual(FRKoreksi.objects.count(), 1)
        self.assertEqual(FRKoreksi.objects.get().nilai, Decimal("475000"))

    def test_hapus_mengembalikan_nilai_asli(self):
        self._post()
        r = self._post(hapus="1")
        from web.models import FRKoreksi
        self.assertEqual(FRKoreksi.objects.count(), 0)
        self.assertTrue(AuditLog.objects.filter(aksi="fr_koreksi_hapus").exists())
        self.assertIn("500.000", r.content.decode())

    def test_nilai_tak_valid_ditolak(self):
        r = self._post(nilai="abc")
        self.assertEqual(r.status_code, 400)
        from web.models import FRKoreksi
        self.assertEqual(FRKoreksi.objects.count(), 0)

    def test_wajib_login(self):
        self.client.logout()
        r = self._post()
        self.assertEqual(r.status_code, 302)
