"""Bukti wiring drag-select (I2) — seleksi persegi ala Excel di tabel angka.

Modul JS (`web/static/web/js/range-select.js`) sulit di-unit-test tanpa runner
browser, jadi verifikasi interaksi penuh (drag persegi + salin TSV) dilakukan
reviewer manusia. Tes ini hanya membuktikan *wiring*-nya benar:

1. Skrip `range-select.js` termuat global (via app_base.html) di halaman tabel.
2. Tabel angka besar diberi opt-in `class="selectable"` sehingga modul mengikat.
"""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

TGL = date(2026, 6, 28)


class DragSelectWiredTests(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.bank = SourceType.objects.get_or_create(
            key="bank", defaults={"name": "Bank"})[0]
        User = get_user_model()
        User.objects.create_user("aud", "a@a.co", "pw12345", role="supervisor")
        self.client.login(username="aud", password="pw12345")
        self.client.post(reverse("set_toko"), {"toko_id": self.toko.id})

    def _mutasi(self):
        up = Upload.objects.create(
            source_type=self.bank, toko=self.toko, provider="BCA", owner_name="HENDI")
        Transaction.objects.create(
            upload=up, source_type=self.bank, toko=self.toko, jenis="depo",
            amount=Decimal("500000"), money_delta=Decimal("500000"),
            balance_after=Decimal("500000"),
            occurred_at=datetime(TGL.year, TGL.month, TGL.day, 9, 0),
            row_hash="ds1",
        )

    def test_skrip_range_select_termuat(self):
        """Modul JS dimuat global lewat app_base.html di halaman tabel."""
        r = self.client.get(reverse("rekening_breakdown"), {"date": "2026-06-28"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("range-select.js", r.content.decode())

    def test_tabel_diberi_kelas_selectable(self):
        """Tabel angka besar ber-opt-in class="selectable" agar modul mengikat."""
        self._mutasi()
        r = self.client.get(reverse("rekening_breakdown"), {"date": "2026-06-28"})
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        # tabelnya benar-benar ter-render (ada datanya) …
        self.assertIn("BCA a/n HENDI", html)
        # … dan tabel itu ber-kelas selectable.
        self.assertIn('class="selectable"', html)
