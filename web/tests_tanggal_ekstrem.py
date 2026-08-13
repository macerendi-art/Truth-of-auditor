"""Ujung kalender: tak satu halaman pun boleh mati di `date.min`/`date.max`.

Bukan tes akademis. Setiap bar filter di aplikasi ini memakai
`<input type="date">` TANPA atribut `max`/`min`, dan spinner tahun bawaan
browser bisa sampai 9999 (dan turun sampai 0001). `web/views.py::_parse_date`
memakai `date.fromisoformat`, yang menerima kedua ujung itu sebagai tanggal
sah. Jadi tanggal ekstrem sampai ke kode aplikasi lewat jalur pemakaian
BIASA — bukan lewat URL rakitan.

Begitu sampai di sana, tiap `tanggal ± timedelta` melempar `OverflowError`
di PYTHON, sebelum query dibentuk. Akibatnya bukan tabel kosong (yang benar
dan tak apa-apa) melainkan HTTP 500 untuk SELURUH halaman — di dashboard
bahkan seluruh dashboard, gara-gara loop kalender 14 hari.

Yang dikunci di sini cuma satu hal: **halaman tetap merender**. Isinya boleh
kosong; tak ada satu pun angka pada tanggal waras yang boleh berubah karena
penjaga ini (dijaga tes-tes lain yang sudah ada).
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import Toko

User = get_user_model()

AWAL = "0001-01-05"   # < 14 hari dari date.min → loop kalender dashboard meluap
AKHIR = "9999-12-31"  # date.max → `+ 1 hari` / `+ span` meluap


class _Base(TestCase):
    def setUp(self):
        User.objects.create_user("adm", "a@a.co", "pw12345", role="admin")
        self.client.login(username="adm", password="pw12345")
        self.toko = Toko.objects.get(key="lbs")
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})

    def cek(self, nama, **params):
        r = self.client.get(reverse(nama), params)
        self.assertEqual(
            r.status_code, 200,
            f"{nama} mati (HTTP {r.status_code}) untuk {params}")
        return r


class UjungKalenderTests(_Base):
    def test_dashboard_tanggal_paling_awal(self):
        """Kalender dashboard mundur 13 hari dari `anchor`; di mode filter
        `anchor = ?sampai`. Pada 0001-01-05 pengurangan itu meluap dan yang
        mati bukan kartunya — seluruh dashboard."""
        self.cek("dashboard", dari=AWAL, sampai=AWAL)

    def test_dashboard_tanggal_paling_akhir(self):
        self.cek("dashboard", dari=AKHIR, sampai=AKHIR)

    def test_dashboard_semua_toko_tanggal_paling_awal(self):
        """Mode "Semua Toko" punya loop kalendernya sendiri (kode terpisah)."""
        self.client.post(reverse("set_toko"), {"toko_id": "all"})
        self.cek("dashboard", dari=AWAL, sampai=AWAL)

    def test_dashboard_next_date_dari_batch_ekstrem(self):
        """`next_date = batch terakhir + 1 hari`. `recon_date` datang dari
        tanggal baris panel yang di-ingest, bukan dari form — satu tanggal
        rusak di file sumber cukup untuk mematikan dashboard SELAMANYA,
        tanpa satu pun parameter URL."""
        tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1})[0]
        ReconBatch.objects.create(
            toko=self.toko, tolerance=tol, recon_date=date(9999, 12, 31),
            summary={"dp": {"selisih": 0}, "wd": {"selisih": 0}},
        )
        self.cek("dashboard")

    def test_bracket_breakdown_tanggal_paling_akhir(self):
        """Tautan prev/next menggeser seluruh lebar jendela (`span`), jadi
        `sampai + span` meluap di ujung atas."""
        self.cek("bracket_breakdown", sampai=AKHIR)

    def test_bracket_breakdown_tanggal_paling_awal(self):
        self.cek("bracket_breakdown", dari="0001-01-01", sampai="0001-01-01")

    def test_bracket_detail_tanggal_paling_akhir(self):
        self.cek("bracket_detail", sampai=AKHIR)

    def test_rentang_default_30_hari_di_ujung_awal(self):
        """`dari` kosong = `sampai − 30 hari`. Pada 0001-01-05 itu meluap;
        tiga halaman memakai pola yang sama."""
        for nama in ("hutang_piutang", "rincian_biaya", "bonus_recon"):
            with self.subTest(halaman=nama):
                self.cek(nama, sampai=AWAL)

    def test_tanggal_waras_tetap_apa_adanya(self):
        """Penjaga ujung kalender TIDAK boleh menyentuh rentang normal:
        prev/next tetap bergeser selebar jendela seperti sebelumnya."""
        r = self.cek("bracket_breakdown", dari="2026-07-01", sampai="2026-07-10")
        self.assertEqual(r.context["prev_dari"], date(2026, 6, 21))
        self.assertEqual(r.context["prev_sampai"], date(2026, 6, 30))
        self.assertEqual(r.context["next_dari"], date(2026, 7, 11))
        self.assertEqual(r.context["next_sampai"], date(2026, 7, 20))


class SettlementUjungKalenderTests(TestCase):
    """`/settlement/` menghitung `batas = tanggal kredit + window toleransi`.

    Tak ada parameter tanggal di halaman ini — `d` datang dari `occurred_at`
    hasil ingest. Jadi jalurnya bukan URL melainkan DATA: satu tanggal rusak
    di file sumber (tahun 9999 dari kolom tanggal yang salah baca) cukup untuk
    membuat penjumlahan itu meluap dan mematikan halaman. Fungsinya diuji
    langsung karena membangun baris carry-over lengkap butuh satu batch penuh.
    """

    def test_batas_menempel_di_ujung_bukan_meledak(self):
        from web.settlement import _batas_settlement
        self.assertEqual(_batas_settlement(date(2026, 7, 20), 3), date(2026, 7, 23))
        self.assertEqual(_batas_settlement(date(9999, 12, 31), 1), date(9999, 12, 31))
        self.assertEqual(_batas_settlement(date(1, 1, 1), -5), date(1, 1, 1))
