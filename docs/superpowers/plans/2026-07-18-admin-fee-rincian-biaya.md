# Admin Fee + Rincian Biaya Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Baris fee bank (BRI ATMSTRPRM/BFST/BRIVA, Mandiri "Biaya…") tertandai `jenis="admin"` saat ingest, dan halaman "Rincian Biaya" menampilkan rekap biaya admin per kanal — termasuk baris legacy yang belum bertanda (klasifikasi query-time).

**Architecture:** Modul aturan murni `sources/parsers/fee_rules.py` dipakai dua arah: parser (data baru) dan `web/biaya.py` (laporan, retroaktif). Tanpa migrasi, tanpa perubahan engine. Spec: `docs/superpowers/specs/2026-07-18-admin-fee-rincian-biaya-design.md`.

**Tech Stack:** Django 5.2 `TestCase`/`SimpleTestCase`, pola modul agregasi `web/hutang.py`.

## Global Constraints

- Venv checkout utama: `/Users/macads/Truth-of-auditor/.venv/bin/python`.
- UI/komentar bahasa Indonesia; tanpa emoji/glyph; warna via var token.
- TANPA migrasi; engine TIDAK diubah; `is_bca_fee`/`is_briva_fee`/merge SWITCHING yang ada TIDAK dihapus.
- Aturan fee HANYA yang di spec — pola numerik BRI 6.500 SENGAJA di luar lingkup.
- `collectstatic --noinput` bila manifest error; stage hanya file yang diubah (JANGAN `git add -A`); JANGAN push/deploy (controller).

---

### Task 1: `fee_rules.py` + penandaan di parser BRI & Mandiri

**Files:**
- Create: `sources/parsers/fee_rules.py`
- Modify: `sources/parsers/banks.py` (BRIParser jenis; MandiriParser jenis; import)
- Test: `sources/tests_fee_rules.py` (baru)

**Interfaces:**
- Produces: `is_admin_fee(bank: str, description, amount) -> bool` — `bank` kunci parser lower ("bri"/"mandiri"/"bca"/lainnya); `amount` = Decimal/angka NON-NEGATIF (abs), pemanggil yang memastikan baris keluar. Dipakai Task 2.

- [ ] **Step 1: Tulis failing tests**

Buat `sources/tests_fee_rules.py`:

```python
"""Aturan fee admin bank — nominal tetap + pola deskripsi per bank (bukti prod 18-07)."""
from decimal import Decimal

from django.test import SimpleTestCase

from sources.parsers.fee_rules import is_admin_fee


class AturanFeeTests(SimpleTestCase):
    def test_bri_atmstrprm_6500(self):
        self.assertTrue(is_admin_fee("bri", "ATMSTRPRM 0888123", Decimal("6500")))
        self.assertFalse(is_admin_fee("bri", "ATMSTRPRM 0888123", Decimal("650000")))

    def test_bri_bfst_2500(self):
        self.assertTrue(is_admin_fee("bri", "BFST2061125016 NBMB:...", Decimal("2500")))
        self.assertFalse(is_admin_fee("bri", "BFST2061125016 NBMB:...", Decimal("250000")))

    def test_bri_briva_1000(self):
        self.assertTrue(is_admin_fee("bri", "BRIVA301350882008 NBMB F R N", Decimal("1000")))
        self.assertFalse(is_admin_fee("bri", "BRIVA301350882008 NBMB", Decimal("100000")))

    def test_mandiri_biaya_semua_nominal(self):
        self.assertTrue(is_admin_fee("mandiri", "Biaya transfer BI Fast", Decimal("2500")))
        self.assertTrue(is_admin_fee("mandiri", "Biaya transaksi", Decimal("1000")))
        self.assertTrue(is_admin_fee("mandiri", "biaya transfer", Decimal("6500")))
        self.assertFalse(is_admin_fee("mandiri", "Transfer ke BANK MANDIRI ANDI", Decimal("2500")))

    def test_bca_delegasi_biaya_txn(self):
        self.assertTrue(is_admin_fee("bca", "BI-FAST DB BIAYA TXN 123", Decimal("2500")))
        self.assertFalse(is_admin_fee("bca", "TRSF E-BANKING DB 1707 ANDI", Decimal("2500")))

    def test_bank_lain_dan_desc_kosong_false(self):
        self.assertFalse(is_admin_fee("bni", "BY TRX", Decimal("1000")))  # BNI punya jalur sendiri
        self.assertFalse(is_admin_fee("bri", "", Decimal("2500")))
        self.assertFalse(is_admin_fee("bri", None, Decimal("2500")))
```

Tambahkan juga test parser di file yang sama:

```python
import csv
import os
import tempfile

from sources.parsers.banks import BRIParser


def _bri_csv(rows):
    fd, p = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["NOREK", "SEQ", "TGL_TRAN", "DESK_TRAN",
                    "MUTASI_DEBET", "MUTASI_KREDIT", "SALDO_AKHIR_MUTASI"])
        w.writerows(rows)
    return p


class BRIFeeParserTests(SimpleTestCase):
    def _parse(self, rows):
        p = _bri_csv(rows)
        try:
            return BRIParser().parse(p)
        finally:
            os.remove(p)

    def test_atmstrprm_dan_bfst_jadi_admin(self):
        out = self._parse([
            ["123", "1", "2026-07-17 10:00:00", "ATMSTRPRM 0888555", "6500", "0", "100000"],
            ["123", "2", "2026-07-17 10:01:00", "BFST2061125016 NBMB:X", "2500", "0", "97500"],
            ["123", "3", "2026-07-17 10:02:00", "NBMB SENDER TO RECEIVER ESB", "0", "50000", "147500"],
        ])
        self.assertEqual([r["jenis"] for r in out], ["admin", "admin", "depo"])
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources.tests_fee_rules -v 2`
Expected: FAIL `ModuleNotFoundError: sources.parsers.fee_rules`

- [ ] **Step 3: Implementasi**

Buat `sources/parsers/fee_rules.py`:

```python
"""Aturan baris fee admin bank — nominal tetap + pola deskripsi per bank.

Tarif dari matriks klien: e-wallet 1.000 · BI Fast 2.500 · transfer
realtime/online 6.500. Bukti kalibrasi prod 18-07-2026 (8.937 baris legacy):
BRI `ATMSTRPRM…`@6500, `BFST…`@2500 (transfer BI-Fast min 10rb → 2.500 pasti
fee), `BRIVA…`@1000 (fee kembar); Mandiri teks eksplisit "Biaya …".
Dipakai DUA arah: parser saat ingest (data baru) dan laporan Rincian Biaya
saat baca (baris legacy yang terlanjur tanpa tanda). Pola numerik BRI 6.500
yang ambigu SENGAJA tidak ditandai (tunggu kalibrasi lanjutan).
"""
from decimal import Decimal

_F1000 = Decimal("1000")
_F2500 = Decimal("2500")
_F6500 = Decimal("6500")


def is_admin_fee(bank, description, amount):
    """True bila baris KELUAR ini biaya admin menurut pola bank tsb.

    `bank` = kunci parser lower ("bri"/"mandiri"/"bca"/…); `amount` nilai
    non-negatif (abs) — pemanggil memastikan arah keluar (money_delta < 0).
    """
    d = str(description or "").strip().upper()
    if not d:
        return False
    try:
        amt = Decimal(str(amount))
    except Exception:  # noqa: BLE001 — nilai aneh dianggap bukan fee
        return False
    if bank == "mandiri":
        return d.startswith("BIAYA")
    if bank == "bri":
        return (
            (d.startswith("ATMSTRPRM") and amt == _F6500)
            or (d.startswith("BFST") and amt == _F2500)
            or (d.startswith("BRIVA") and amt == _F1000)
        )
    if bank == "bca":
        return "BIAYA TXN" in d
    return False
```

**Catatan implementasi:** cabang `"bca"` menulis langsung pola `"BIAYA TXN" in d`
— substring yang sama dengan regex `BCA_FEE_RE` di `banks.py`; duplikasi satu
substring literal di modul aturan murni lebih baik daripada import silang
banks.py→fee_rules.py→banks.py yang melingkar.

Di `sources/parsers/banks.py`:
- tambah import: `from .fee_rules import is_admin_fee`
- `BRIParser` — ganti baris jenis menjadi:

```python
                "jenis": "admin"
                if (money < 0 and (is_briva_fee(desc, money)
                                   or is_admin_fee("bri", desc, abs(money))))
                else _jenis_from_money(money),
```

- `MandiriParser` — ganti baris `"jenis": _jenis_from_money(money),` menjadi:

```python
                "jenis": "admin"
                if (money < 0 and is_admin_fee("mandiri", ket, abs(money)))
                else _jenis_from_money(money),
```

(Cek nama variabel keterangan di MandiriParser — `ket` — sesuaikan bila beda.)

- [ ] **Step 4: Jalankan test, pastikan lulus + regresi bank**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources.tests_fee_rules sources.tests_bri_fee sources.tests_mandiri sources.tests_bank_fields -v 1`
Expected: semua PASS.

- [ ] **Step 5: Commit**

```bash
git add sources/parsers/fee_rules.py sources/parsers/banks.py sources/tests_fee_rules.py
git commit -m "feat(fee): aturan admin-fee BRI/Mandiri (ATMSTRPRM/BFST/BRIVA/Biaya) + tanda di parser"
```

---

### Task 2: Laporan "Rincian Biaya" (`/biaya-admin/`)

**Files:**
- Create: `web/biaya.py`, `web/templates/web/biaya_admin.html`
- Modify: `web/views.py`, `web/urls.py`, `web/templates/web/app_base.html` (menu)
- Test: `web/tests_biaya.py` (baru)

**Interfaces:**
- Consumes: `sources.parsers.fee_rules.is_admin_fee`, `transactions.models.provider_from_filename`.
- Produces: `web.biaya.rincian_biaya(toko, dari=None, sampai=None)`; URL name `rincian_biaya`.

- [ ] **Step 1: Tulis failing tests**

Buat `web/tests_biaya.py`:

```python
"""Rincian Biaya admin: agregasi web.biaya + view /biaya-admin/."""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.biaya import rincian_biaya

TGL = date(2026, 7, 17)


class _BiayaData(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.bank = SourceType.objects.get_or_create(
            key="bank", defaults={"name": "Bank"})[0]
        self.up_bri = Upload.objects.create(
            source_type=self.bank, toko=self.toko,
            original_name="17_07_2026_WD_BRI_NASRUL.csv", owner_name="NASRUL")
        self._n = 0

    def tx(self, up, desc, amount, jenis="wd", tanggal=TGL):
        self._n += 1
        return Transaction.objects.create(
            upload=up, source_type=self.bank, toko=self.toko, jenis=jenis,
            amount=Decimal(amount), money_delta=-Decimal(amount),
            posted_date=tanggal, occurred_at=datetime(2026, 7, 17, 10, 0),
            description=desc, row_hash=f"by{self._n}")


class AgregasiBiayaTests(_BiayaData):
    def test_bertanda_admin_dan_legacy_rule_ikut(self):
        self.tx(self.up_bri, "BFST123 NBMB:X", "2500", jenis="admin")   # bertanda
        self.tx(self.up_bri, "ATMSTRPRM 0888", "6500", jenis="wd")     # legacy tanpa tanda
        self.tx(self.up_bri, "BRIVA30135082 NBMB", "1000", jenis="wd") # legacy
        self.tx(self.up_bri, "NBMB ANDI TO BUDI ESB", "500000", jenis="wd")  # transfer nyata
        data = rincian_biaya(self.toko, dari=TGL, sampai=TGL)
        self.assertEqual(data["ringkas"]["n"], 3)
        self.assertEqual(data["ringkas"]["total"], Decimal("10000"))
        kanal = data["ringkas"]["kanal"]
        self.assertEqual(kanal["BI Fast"]["total"], Decimal("2500"))
        self.assertEqual(kanal["Transfer online"]["total"], Decimal("6500"))
        self.assertEqual(kanal["E-wallet"]["total"], Decimal("1000"))

    def test_rentang_tanggal(self):
        self.tx(self.up_bri, "BFST1", "2500", jenis="admin", tanggal=date(2026, 7, 1))
        self.tx(self.up_bri, "BFST2", "2500", jenis="admin", tanggal=TGL)
        data = rincian_biaya(self.toko, dari=date(2026, 7, 10), sampai=TGL)
        self.assertEqual(data["ringkas"]["n"], 1)

    def test_baris_per_tanggal_sumber(self):
        self.tx(self.up_bri, "BFST1", "2500", jenis="admin")
        self.tx(self.up_bri, "BFST2", "2500", jenis="admin")
        data = rincian_biaya(self.toko, dari=TGL, sampai=TGL)
        (baris,) = data["rows"]
        self.assertEqual(baris["tanggal"], TGL)
        self.assertIn("BRI", baris["sumber"])
        self.assertEqual(baris["n"], 2)
        self.assertEqual(baris["total"], Decimal("5000"))


class BiayaViewTests(_BiayaData):
    def setUp(self):
        super().setUp()
        u = get_user_model().objects.create_user(
            username="aud_b", password="rahasia123", role="auditor")
        u.allowed_tokos.add(self.toko)
        self.client.force_login(u)
        s = self.client.session
        s["active_toko_id"] = self.toko.id
        s.save()

    def test_halaman_render(self):
        self.tx(self.up_bri, "BFST1", "2500", jenis="admin")
        r = self.client.get(reverse("rincian_biaya"),
                            {"dari": "2026-07-01", "sampai": "2026-07-31"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Rincian Biaya")
        self.assertContains(r, "2.500")

    def test_kosong_empty_state(self):
        r = self.client.get(reverse("rincian_biaya"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Belum ada")
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_biaya -v 2`
Expected: FAIL `ModuleNotFoundError: web.biaya`

- [ ] **Step 3: Implementasi**

Buat `web/biaya.py`:

```python
"""Rincian Biaya admin — rekap fee bank per kanal, query-time & retroaktif.

Baris fee = `jenis="admin"` TERSIMPAN (parser era baru) ATAU cocok aturan
`is_admin_fee` saat baca (baris legacy ter-ingest sebelum aturannya lahir —
dedup membuat re-upload tak menandai ulang, jadi laporan yang menutupnya).
Kanal dari tarif tetap klien: 1.000 e-wallet · 2.500 BI Fast · 6.500 online.
"""
from decimal import Decimal

from sources.parsers.fee_rules import is_admin_fee
from transactions.models import Transaction, provider_from_filename

NOL = Decimal("0")

_KANAL = {
    Decimal("1000"): "E-wallet",
    Decimal("2500"): "BI Fast",
    Decimal("6500"): "Transfer online",
}


def _kanal(amount):
    return _KANAL.get(amount, "Lainnya")


def rincian_biaya(toko, dari=None, sampai=None):
    qs = (
        Transaction.objects.filter(
            toko=toko, source_type__key="bank", money_delta__lt=0)
        .select_related("upload", "account", "source_type")
    )
    if dari:
        qs = qs.filter(posted_date__gte=dari)
    if sampai:
        qs = qs.filter(posted_date__lte=sampai)

    per = {}   # (tanggal, sumber) → {n, total, kanal:{}}
    ringkas = {"n": 0, "total": NOL, "kanal": {}}
    for t in qs.iterator():
        if t.jenis != "admin":
            bank = provider_from_filename(
                t.upload.original_name if t.upload_id else "").lower()
            if not is_admin_fee(bank, t.description, t.amount):
                continue
        kanal = _kanal(t.amount)
        kunci = (t.posted_date, t.source_label_full)
        slot = per.setdefault(kunci, {"n": 0, "total": NOL, "kanal": {}})
        slot["n"] += 1
        slot["total"] += t.amount
        k = slot["kanal"].setdefault(kanal, {"n": 0, "total": NOL})
        k["n"] += 1
        k["total"] += t.amount
        ringkas["n"] += 1
        ringkas["total"] += t.amount
        rk = ringkas["kanal"].setdefault(kanal, {"n": 0, "total": NOL})
        rk["n"] += 1
        rk["total"] += t.amount

    rows = [
        {"tanggal": tgl, "sumber": sumber, **slot}
        for (tgl, sumber), slot in per.items()
    ]
    # tanggal None aman (date.min), terbaru dulu — pelajaran sort hutang.py
    rows.sort(key=lambda r: (r["tanggal"] or date.min, r["sumber"]), reverse=True)
    return {"rows": rows, "ringkas": ringkas}
```

(Tambahkan `from datetime import date` di bagian import `web/biaya.py`.)

`web/views.py` — view baru (pola persis `hutang_piutang`; impor
`from web.biaya import rincian_biaya as hitung_rincian_biaya`):

```python
@login_required
def rincian_biaya(request):
    """Rekap biaya admin bank per kanal (E-wallet/BI Fast/Transfer online)."""
    active = _active_toko(request)
    if active is None:
        return render(request, "web/no_toko.html")
    sampai = _parse_date(request.GET.get("sampai", "")) or date_cls.today()
    dari = _parse_date(request.GET.get("dari", "")) or sampai - timedelta(days=30)
    data = hitung_rincian_biaya(active, dari=dari, sampai=sampai)
    page = Paginator(data["rows"], 40).get_page(request.GET.get("page"))
    return render(request, "web/biaya_admin.html", {
        "page": page, "data": data, "dari": dari, "sampai": sampai,
    })
```

`web/urls.py` — setelah `hutang-piutang/`:

```python
    path("biaya-admin/", views.rincian_biaya, name="rincian_biaya"),
```

Buat `web/templates/web/biaya_admin.html`:

```html
{% extends "web/app_base.html" %}
{% load humanize %}
{% load web_extras %}
{% block title %}Rincian Biaya · Truth of Auditor{% endblock %}
{% block crumb %}Transaksi · Rincian Biaya{% endblock %}
{% block content %}
<div class="page-head reveal">
  <div>
    <h1>Rincian Biaya</h1>
    <p>Biaya admin bank <b>{{ active_toko.name }}</b> per kanal — baris fee bertanda maupun legacy (dikenali pola), tarif tetap: E-wallet 1.000 · BI Fast 2.500 · Transfer online 6.500.</p>
  </div>
</div>

<div class="card reveal" style="margin-bottom:18px">
  <form method="get" class="row" style="align-items:flex-end">
    <div class="field"><label>Dari</label><input type="date" name="dari" value="{{ dari|date:'Y-m-d' }}"></div>
    <div class="field"><label>Sampai</label><input type="date" name="sampai" value="{{ sampai|date:'Y-m-d' }}"></div>
    <button class="btn primary" type="submit">Terapkan</button>
    <span class="spacer"></span>
    <span class="faint" style="font-size:12px">{{ data.ringkas.n|intcomma }} baris fee</span>
  </form>
</div>

<div class="grid cols-4 reveal" style="margin-bottom:18px">
  <div class="card stat"><div class="k">Total Biaya</div><div class="v mono">{{ data.ringkas.total|floatformat:0|intcomma }}</div></div>
  {% with k=data.ringkas.kanal %}
  <div class="card stat"><div class="k">E-wallet (1.000)</div><div class="v mono">{{ k|raw_get:"E-wallet"|raw_get:"total"|default:0|floatformat:0|intcomma }}</div></div>
  <div class="card stat"><div class="k">BI Fast (2.500)</div><div class="v mono">{{ k|raw_get:"BI Fast"|raw_get:"total"|default:0|floatformat:0|intcomma }}</div></div>
  <div class="card stat"><div class="k">Transfer online (6.500)</div><div class="v mono">{{ k|raw_get:"Transfer online"|raw_get:"total"|default:0|floatformat:0|intcomma }}</div></div>
  {% endwith %}
</div>

{% if not data.rows %}
<div class="card reveal"><div class="cell-empty" style="padding:34px 12px;text-align:center">
  Belum ada baris biaya pada rentang ini.
</div></div>
{% else %}
<div class="card pad0 reveal">
  <div class="table-wrap" style="border:none">
  <table>
    <thead><tr>
      <th>Tanggal</th><th>Sumber</th><th class="num">Baris</th>
      <th class="num">E-wallet</th><th class="num">BI Fast</th>
      <th class="num">Transfer online</th><th class="num">Lainnya</th><th class="num">Total</th>
    </tr></thead>
    <tbody>
    {% for r in page %}
    <tr>
      <td class="mono">{{ r.tanggal|date:"d/m/Y"|default:"—" }}</td>
      <td style="font-size:12.5px">{{ r.sumber }}</td>
      <td class="num mono">{{ r.n|intcomma }}</td>
      <td class="num mono">{{ r.kanal|raw_get:"E-wallet"|raw_get:"total"|default:""|floatformat:0|intcomma }}</td>
      <td class="num mono">{{ r.kanal|raw_get:"BI Fast"|raw_get:"total"|default:""|floatformat:0|intcomma }}</td>
      <td class="num mono">{{ r.kanal|raw_get:"Transfer online"|raw_get:"total"|default:""|floatformat:0|intcomma }}</td>
      <td class="num mono">{{ r.kanal|raw_get:"Lainnya"|raw_get:"total"|default:""|floatformat:0|intcomma }}</td>
      <td class="num mono" style="font-weight:600">{{ r.total|floatformat:0|intcomma }}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  </div>
  <div style="padding:10px 14px">{% pager page %}</div>
</div>
{% endif %}
{% endblock %}
```

**Catatan template:** cek dulu perilaku filter `raw_get` terhadap dict bertingkat
dan nilai kosong — bila `raw_get` mengembalikan `""` untuk kunci absen, rantai
`|raw_get:"total"` pada `""` bisa error; bila begitu, siapkan nilai kanal per
baris di `web/biaya.py` (flatten: `r["ewallet"], r["bifast"], r["online"],
r["lainnya"]` berisi Decimal/None) dan pakai itu di template — pilih pendekatan
yang LOLOS test render, konsistensi > kepatuhan literal ke contoh ini.

Menu sidebar `app_base.html`: setelah item "Rincian Rekening" tambahkan:

```html
  <a class="link {% if '/biaya-admin' in p %}active{% endif %}" href="{% url 'rincian_biaya' %}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>Rincian Biaya</a>
```

- [ ] **Step 4: Jalankan test + suite penuh**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_biaya sources.tests_fee_rules -v 1`
lalu `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test`
Expected: modul PASS; suite penuh PASS (≈810+).

- [ ] **Step 5: Docs + commit**

`CLAUDE.md`: (a) bagian fee ("Fee rows are tagged…") tambah kalimat: BRI
`ATMSTRPRM`@6500 / `BFST`@2500 / `BRIVA`@1000 dan Mandiri `Biaya…` kini
ditandai via `sources/parsers/fee_rules.is_admin_fee` (dipakai parser + laporan
Rincian Biaya query-time utk baris legacy). (b) daftar modul agregasi web:
tambah `web/biaya.py` (`/biaya-admin/`).

Spec `docs/superpowers/specs/2026-07-18-admin-fee-rincian-biaya-design.md`:
tambah bagian `## Hasil implementasi` (hasil test + jumlah baris legacy prod
yang kini tercakup laporan — angka 8.937 dari probe).

```bash
git add web/biaya.py web/views.py web/urls.py web/templates/web/biaya_admin.html \
        web/templates/web/app_base.html web/tests_biaya.py CLAUDE.md \
        docs/superpowers/specs/2026-07-18-admin-fee-rincian-biaya-design.md
git commit -m "feat(biaya): laporan Rincian Biaya per kanal — bertanda + legacy rule-based"
```
