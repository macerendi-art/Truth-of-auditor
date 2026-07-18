# Koreksi Sel FR + Hutang/Piutang Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auditor bisa mengoreksi angka sel tabel Control Bracket (popup kecil + tanda segitiga merah, asli utuh, total & selisih ikut koreksi, tercatat di Log Audit) dan melihat daftar hutang/piutang di halaman terpisah; header FR mengikuti acuan klien.

**Architecture:** Model overlay `FRKoreksi` (app `web`, migrasi web 0001) ditumpangkan saat agregasi `web/breakdown.py` — data `Transaction` tidak pernah diubah. UI edit via HTMX (pola aksi review yang ada): klik sel → popup form → POST → render ulang partial tabel kontrol server-side. Halaman hutang/piutang = modul agregasi murni `web/hutang.py` + view read-only, pola `breakdown.py`.

**Tech Stack:** Django 5.2 (`TestCase`), HTMX (self-host, sudah dimuat `app_base.html`), template tag `raw_get` (`web_extras`), `core.audit.catat`.

**Spec:** `docs/superpowers/specs/2026-07-18-fr-koreksi-hutang-piutang-design.md`

## Global Constraints

- Virtualenv di checkout utama: `/Users/macads/Truth-of-auditor/.venv/bin/python` (worktree tanpa `.venv`); jalankan dari root worktree.
- Semua UI/komentar/docstring bahasa Indonesia; TANPA emoji/glyph-teks sebagai ikon; warna via var token (`var(--bad)`, JANGAN hardcode hex).
- Data `Transaction` TIDAK PERNAH diubah oleh fitur ini — koreksi hanya overlay.
- Semua role login boleh mengedit; scoping toko via `_active_toko` (pola view lain).
- Baris TOTAL & kolom Selisih Kontrol tidak bisa diedit (selalu hasil hitungan).
- `sum()` Decimal selalu dengan start `NOL` (jangan int 0 campur Decimal di template).
- Migrasi baru: `web/migrations/0001_initial.py` — WAJIB ikut ter-commit.
- Test render template butuh manifest staticfiles: bila error `Missing staticfiles manifest entry`, jalankan `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py collectstatic --noinput` sekali.
- Commit per task; push `origin/main` HANYA di task terakhir (`git fetch origin && git push origin HEAD:main`, fast-forward). JANGAN deploy (railway) — menunggu konfirmasi user.
- Django 5.2 meng-cache template loader meski DEBUG — restart server preview setelah edit template sebelum menyimpulkan gagal.

---

### Task 1: Model `FRKoreksi` + migrasi web 0001

**Files:**
- Modify: `web/models.py` (saat ini hanya stub 3 baris)
- Create: `web/migrations/0001_initial.py` (via makemigrations)
- Test: `web/tests_fr_koreksi.py` (file baru)

**Interfaces:**
- Produces: `web.models.FRKoreksi` dengan field `toko, tanggal, account, kolom, nilai, alasan, catatan, dibuat_oleh, created_at, updated_at`; konstanta pilihan `FRKoreksi.ALASAN_KOREKSI`; unique constraint `(toko, tanggal, account, kolom)` bernama `uniq_fr_koreksi_sel`. Task 2–3 bergantung pada nama-nama ini persis.

- [ ] **Step 1: Tulis failing test**

Buat `web/tests_fr_koreksi.py`:

```python
"""Koreksi sel FR (paket A): model overlay + agregasi + view popup."""
from datetime import date
from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase

from sources.models import Toko

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
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_fr_koreksi -v 2`
Expected: FAIL `ImportError: cannot import name 'FRKoreksi'`

- [ ] **Step 3: Implementasi model**

Ganti seluruh isi `web/models.py`:

```python
"""Model layer web: koreksi tampilan sel FR (overlay — data asli tak tersentuh)."""
from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class FRKoreksi(TimeStampedModel):
    """Koreksi satu sel tabel Control Bracket (FR) — timpa TAMPILAN saja.

    Nilai asli hasil agregasi `web.breakdown` TIDAK diubah; koreksi
    ditumpangkan saat render (dan total/selisih dihitung ulang darinya).
    Kunci sel = (toko, tanggal, account, kolom): `account` = label mentah
    `raw["Bank"]`, `kolom` = slug kategori atau `saldo_awal`/`saldo_akhir`.
    Edit ulang memperbarui baris yang sama — riwayat nilai ada di AuditLog.
    """

    ALASAN_KOREKSI = [
        ("cutoff_mutation", "Cutoff Mutation"),
        ("mistake_cs", "Mistake CS"),
        ("biaya_admin_bank", "Biaya Admin Bank"),
        ("biaya_admin_qris", "Biaya Admin QRIS"),
        ("dana_pending", "Dana Pending"),
        ("cm_pindah_dana", "Sesama CM (Pindah Dana)"),
        ("cm_naik_tampung", "Sesama CM (Naik Tampung)"),
        ("cm_turun_tampung", "Sesama CM (Turun Tampung)"),
        ("bank_title_beda", "Bank Title Tidak Sesuai"),
        ("lainnya", "Lainnya"),
    ]

    toko = models.ForeignKey(
        "sources.Toko", on_delete=models.CASCADE, related_name="fr_koreksi")
    tanggal = models.DateField()
    account = models.CharField(max_length=255)
    kolom = models.CharField(max_length=64)
    nilai = models.DecimalField(max_digits=18, decimal_places=2)
    alasan = models.CharField(max_length=32, choices=ALASAN_KOREKSI, blank=True)
    catatan = models.TextField(blank=True)
    dibuat_oleh = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="fr_koreksi")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["toko", "tanggal", "account", "kolom"],
                name="uniq_fr_koreksi_sel"),
        ]

    def __str__(self):
        return f"{self.tanggal} {self.account} [{self.kolom}] = {self.nilai}"
```

Lalu: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py makemigrations web`
Expected: `web/migrations/0001_initial.py` dibuat (model FRKoreksi + constraint).

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_fr_koreksi -v 2`
Expected: PASS (3 test)

- [ ] **Step 5: Commit**

```bash
git add web/models.py web/migrations/0001_initial.py web/tests_fr_koreksi.py
git commit -m "feat(fr): model FRKoreksi — overlay koreksi sel Control Bracket (web 0001)"
```

---

### Task 2: Overlay koreksi di `web/breakdown.py` + urutan header acuan

**Files:**
- Modify: `web/breakdown.py` (KATEGORI_KANONIK, `bracket_breakdown`, fungsi baru `_apply_koreksi`)
- Test: `web/tests_fr_koreksi.py` (tambah class)

**Interfaces:**
- Consumes: `web.models.FRKoreksi` (Task 1).
- Produces: `bracket_breakdown(toko, tanggal, dengan_koreksi=True)` — parameter baru; tiap dict akun punya kunci `"koreksi"` (dict `kolom_key → {"asli","nilai","alasan","catatan","oleh","waktu"}`, `{}` bila tak ada); nilai sel/mutasi/deposit/withdraw/net/selisih/TOTAL memakai nilai koreksi. Task 3 memanggil dengan `dengan_koreksi=False` untuk nilai asli.

- [ ] **Step 1: Tulis failing tests**

Tambahkan di `web/tests_fr_koreksi.py` (impor tambahan di atas file: `from datetime import datetime`, `from sources.models import SourceType, Upload`, `from transactions.models import Transaction`, `from web.breakdown import bracket_breakdown, KATEGORI_KANONIK`):

```python
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
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_fr_koreksi -v 2`
Expected: FAIL — `koreksi` KeyError / urutan header salah / `dengan_koreksi` unexpected argument.

- [ ] **Step 3: Implementasi**

Di `web/breakdown.py`:

(a) **Urutan header** — dalam `KATEGORI_KANONIK`, tukar posisi dua entri sehingga blok beban berbunyi (urutan acuan spreadsheet kuning klien):

```python
    ("beban admin bank", "Beban Admin Bank"),
    ("beban admin qris", "Beban Admin QRIS"),
    ("biaya transaksi", "Biaya Transaksi"),
    ("beban other expense", "Beban Other Expense"),
    ("beban mistake cs", "Beban Mistake CS"),
```

(b) **Signature + kunci koreksi default** — ubah `def bracket_breakdown(toko, tanggal):` menjadi `def bracket_breakdown(toko, tanggal, dengan_koreksi=True):` dan di dict `accounts.append({...})` tambahkan kunci `"koreksi": {}`.

(c) **Overlay** — tepat SETELAH loop `for account, items in per_akun.items():` selesai (sebelum `accounts.sort(...)`), sisipkan:

```python
    if dengan_koreksi:
        _apply_koreksi(toko, tanggal, accounts, slugs_muncul)
```

dan tambahkan fungsi baru (letakkan setelah `_pecah_akun`):

```python
def _apply_koreksi(toko, tanggal, accounts, slugs_muncul):
    """Timpa nilai sel dengan `FRKoreksi` lalu hitung ulang turunannya.

    Data mentah tak disentuh — hanya dict tampilan. Mutasi = Σ kategori
    (setara Σ delta mentah karena tiap baris FR masuk tepat satu kategori),
    jadi setelah sel kategori diganti, mutasi/deposit/withdraw/net/selisih
    dihitung ulang dari nilai terkoreksi. Koreksi pada akun yang tak hadir
    pada tanggal itu diabaikan (sel tampilan tidak ada).
    """
    from web.models import FRKoreksi  # impor lokal: hindari siklus saat startup

    per_acc = {}
    for k in FRKoreksi.objects.filter(
        toko=toko, tanggal=tanggal
    ).select_related("dibuat_oleh"):
        per_acc.setdefault(k.account, []).append(k)
    if not per_acc:
        return
    for acc in accounts:
        daftar = per_acc.get(acc["account"])
        if not daftar:
            continue
        info = {}
        for k in daftar:
            if k.kolom in ("saldo_awal", "saldo_akhir"):
                asli = acc[k.kolom]
                acc[k.kolom] = k.nilai
            else:
                asli = acc["kategori"].get(k.kolom)
                acc["kategori"][k.kolom] = k.nilai
                slugs_muncul.add(k.kolom)
            info[k.kolom] = {
                "asli": asli, "nilai": k.nilai,
                "alasan": k.get_alasan_display() if k.alasan else "",
                "catatan": k.catatan,
                "oleh": getattr(k.dibuat_oleh, "username", "") or "",
                "waktu": k.updated_at,
            }
        acc["koreksi"] = info
        acc["mutasi"] = sum(acc["kategori"].values(), NOL)
        acc["deposit"] = acc["kategori"].get("deposit", NOL)
        acc["withdraw"] = abs(acc["kategori"].get("withdrawal", NOL))
        acc["net"] = acc["deposit"] - acc["withdraw"]
        acc["selisih"] = None
        if acc["saldo_awal"] is not None and acc["saldo_akhir"] is not None:
            acc["selisih"] = acc["saldo_akhir"] - (acc["saldo_awal"] + acc["mutasi"])
```

Baris TOTAL tidak perlu diubah — loop total yang ada sudah menjumlah nilai per-akun (yang kini terkoreksi).

- [ ] **Step 4: Jalankan test modul + regresi breakdown lama**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_fr_koreksi web.tests_breakdown -v 1`
Expected: semua PASS (perilaku lama utuh — `test_tanpa_koreksi_perilaku_lama_persis` + 16 test lama).

- [ ] **Step 5: Commit**

```bash
git add web/breakdown.py web/tests_fr_koreksi.py
git commit -m "feat(fr): overlay FRKoreksi di bracket_breakdown + urutan header acuan klien"
```

---

### Task 3: View popup koreksi + partial tabel + tanda sel

**Files:**
- Modify: `web/views.py` (2 view baru + helper `_fr_asli`), `web/urls.py`
- Create: `web/templates/web/_fr_control_table.html`, `web/templates/web/_fr_koreksi_form.html`
- Modify: `web/templates/web/breakdown_bracket.html`
- Test: `web/tests_fr_koreksi.py` (tambah class view)

**Interfaces:**
- Consumes: `bracket_breakdown(toko, tanggal, dengan_koreksi=...)` (Task 2), `FRKoreksi` (Task 1), `core.audit.catat(user, aksi, objek, toko=None, **detail)`.
- Produces: URL name `fr_koreksi_form` (GET) dan `fr_koreksi_simpan` (POST); partial `#fr-control` yang dirender ulang; popup container `#koreksiPop`.

- [ ] **Step 1: Tulis failing tests**

Tambahkan di `web/tests_fr_koreksi.py` (impor tambahan: `from django.urls import reverse`, `from django.contrib.auth import get_user_model`, `from core.models import AuditLog`):

```python
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
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_fr_koreksi.KoreksiViewTests -v 2`
Expected: FAIL `NoReverseMatch: 'fr_koreksi_simpan'`

- [ ] **Step 3: Implementasi view + URL**

`web/urls.py` — tambah dua path setelah baris `bracket/`:

```python
    path("bracket/koreksi/", views.fr_koreksi_form, name="fr_koreksi_form"),
    path("bracket/koreksi/simpan/", views.fr_koreksi_simpan, name="fr_koreksi_simpan"),
```

`web/views.py` — tambahkan setelah view `bracket_breakdown` (impor yang mungkin belum ada di file: `from django.http import HttpResponseBadRequest`, `from django.template.loader import render_to_string`, `from decimal import Decimal, InvalidOperation`, `from web.models import FRKoreksi`, `from web.breakdown import KATEGORI_KANONIK`, `from core.audit import catat`):

```python
_FR_KOLOM_SALDO = {"saldo_awal": "Saldo Awal", "saldo_akhir": "Saldo Akhir"}


def _fr_label_kolom(kolom):
    if kolom in _FR_KOLOM_SALDO:
        return _FR_KOLOM_SALDO[kolom]
    return dict(KATEGORI_KANONIK).get(kolom, kolom.title())


def _fr_asli(toko, tanggal, account, kolom):
    """Nilai agregasi MENTAH satu sel (tanpa koreksi) — utk tampilan & audit."""
    data = hitung_bracket_breakdown(toko, tanggal, dengan_koreksi=False)
    for acc in data["accounts"]:
        if acc["account"] == account:
            if kolom in _FR_KOLOM_SALDO:
                return acc[kolom]
            return acc["kategori"].get(kolom)
    return None


def _fr_params(request, src):
    tanggal = _parse_date(src.get("date", ""))
    account = (src.get("account") or "").strip()[:255]
    kolom = (src.get("kolom") or "").strip().lower()[:64]
    if not tanggal or not account or not kolom:
        return None
    return tanggal, account, kolom


@login_required
def fr_koreksi_form(request):
    """Popup kecil koreksi satu sel Control Bracket (GET, HTMX)."""
    active = _active_toko(request)
    params = _fr_params(request, request.GET)
    if active is None or params is None:
        return HttpResponseBadRequest("parameter kurang")
    tanggal, account, kolom = params
    koreksi = FRKoreksi.objects.filter(
        toko=active, tanggal=tanggal, account=account, kolom=kolom).first()
    return render(request, "web/_fr_koreksi_form.html", {
        "tanggal": tanggal, "account": account, "kolom": kolom,
        "label": _fr_label_kolom(kolom),
        "asli": _fr_asli(active, tanggal, account, kolom),
        "koreksi": koreksi, "pilihan_alasan": FRKoreksi.ALASAN_KOREKSI,
    })


@login_required
def fr_koreksi_simpan(request):
    """Simpan/hapus koreksi sel FR lalu render ulang tabel kontrol (POST, HTMX)."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST saja")
    active = _active_toko(request)
    params = _fr_params(request, request.POST)
    if active is None or params is None:
        return HttpResponseBadRequest("parameter kurang")
    tanggal, account, kolom = params
    asli = _fr_asli(active, tanggal, account, kolom)

    if request.POST.get("hapus"):
        FRKoreksi.objects.filter(
            toko=active, tanggal=tanggal, account=account, kolom=kolom).delete()
        catat(request.user, "fr_koreksi_hapus", f"{account} [{kolom}]", toko=active,
              tanggal=str(tanggal), account=account, kolom=kolom,
              nilai_asli=str(asli) if asli is not None else "")
    else:
        mentah = (request.POST.get("nilai") or "").strip().replace(" ", "")
        try:
            # input polos tanpa pemisah ribuan; koma desimal diterima
            nilai = Decimal(mentah.replace(".", "").replace(",", "."))
        except InvalidOperation:
            return HttpResponseBadRequest("nilai tidak valid")
        alasan = request.POST.get("alasan") or ""
        if alasan and alasan not in dict(FRKoreksi.ALASAN_KOREKSI):
            return HttpResponseBadRequest("alasan tidak dikenal")
        FRKoreksi.objects.update_or_create(
            toko=active, tanggal=tanggal, account=account, kolom=kolom,
            defaults={"nilai": nilai, "alasan": alasan,
                      "catatan": (request.POST.get("catatan") or "").strip(),
                      "dibuat_oleh": request.user})
        catat(request.user, "fr_koreksi", f"{account} [{kolom}]", toko=active,
              tanggal=str(tanggal), account=account, kolom=kolom,
              nilai_asli=str(asli) if asli is not None else "",
              nilai_baru=str(nilai), alasan=alasan)

    data = hitung_bracket_breakdown(active, tanggal)
    html = render_to_string("web/_fr_control_table.html",
                            {"data": data, "tanggal": tanggal}, request=request)
    html += '<div id="koreksiPop" hx-swap-oob="innerHTML"></div>'
    return HttpResponse(html)
```

Catatan implementasi: `_parse_date`, `_active_toko`, `hitung_bracket_breakdown`, `HttpResponse`, `render` sudah ada/terimpor di `web/views.py` — pakai yang ada, jangan duplikasi.

- [ ] **Step 4: Partial tabel kontrol + form + wiring template**

**(a)** Buat `web/templates/web/_fr_control_table.html` — pindahan kartu "Control Bracket Transaction" dari `breakdown_bracket.html` (baris `<div class="card pad0 reveal">` terakhir s/d penutupnya) dengan id + sel klikabel. Isi lengkap:

```html
{% load humanize %}
{% load web_extras %}
<div class="card pad0 reveal" id="fr-control">
  <div style="padding:16px 18px 4px">
    <h2 style="margin:0;font-size:15px">Control Bracket Transaction <span class="faint" style="font-weight:500">(Harian)</span></h2>
    <p class="faint" style="margin:4px 0 10px;font-size:12px">Breakdown per kategori FR, mutasi bertanda. <b>Selisih Kontrol</b> = Saldo Akhir − (Saldo Awal + Total Mutasi) — idealnya 0. Klik sel angka untuk mengoreksi; sel bertanda merah punya koreksi (nilai asli tetap tersimpan).</p>
  </div>
  <div class="table-wrap" style="border:none">
  <table>
    <thead><tr>
      <th style="width:44px" class="num">No</th><th>FR Account</th>
      <th class="num">Saldo Awal</th>
      {% for slug, label in data.kolom %}<th class="num">{{ label }}</th>{% endfor %}
      <th class="num">Total Mutasi</th><th class="num">Saldo Akhir</th>
      <th class="num" title="Saldo Akhir − (Saldo Awal + Total Mutasi)">Selisih Kontrol</th>
    </tr></thead>
    <tbody>
    {% for a in data.accounts %}
    <tr>
      <td class="num mono faint">{{ forloop.counter }}</td>
      <td style="font-size:12.5px;white-space:nowrap"><b>{{ a.name }}</b>{% if a.role %} <span class="badge" style="font-size:10px">{{ a.role }}</span>{% endif %}</td>
      {% with kk=a.koreksi|raw_get:"saldo_awal" %}
      <td class="num mono cell-edit{% if kk %} koreksi{% endif %}"
          hx-get="{% url 'fr_koreksi_form' %}?date={{ tanggal|date:'Y-m-d' }}&account={{ a.account|urlencode }}&kolom=saldo_awal"
          hx-target="#koreksiPop" hx-swap="innerHTML"
          {% if kk %}title="asli {% if kk.asli is None %}—{% else %}{{ kk.asli|floatformat:0|intcomma }}{% endif %} → {{ kk.nilai|floatformat:0|intcomma }}{% if kk.alasan %} · {{ kk.alasan }}{% endif %}"{% endif %}
          >{% if a.saldo_awal is not None %}{{ a.saldo_awal|floatformat:0|intcomma }}{% else %}<span class="faint">—</span>{% endif %}</td>
      {% endwith %}
      {% for slug, label in data.kolom %}{% with v=a.kategori|raw_get:slug kk=a.koreksi|raw_get:slug %}
      <td class="num mono cell-edit{% if kk %} koreksi{% endif %}"
          hx-get="{% url 'fr_koreksi_form' %}?date={{ tanggal|date:'Y-m-d' }}&account={{ a.account|urlencode }}&kolom={{ slug|urlencode }}"
          hx-target="#koreksiPop" hx-swap="innerHTML"
          {% if kk %}title="asli {% if kk.asli is None %}—{% else %}{{ kk.asli|floatformat:0|intcomma }}{% endif %} → {{ kk.nilai|floatformat:0|intcomma }}{% if kk.alasan %} · {{ kk.alasan }}{% endif %}"{% endif %}
          >{% if v == "" %}<span class="faint">·</span>{% else %}<span {% if v < 0 %}style="color:var(--bad)"{% endif %}>{{ v|floatformat:0|intcomma }}</span>{% endif %}</td>
      {% endwith %}{% endfor %}
      <td class="num mono" style="font-weight:600">{{ a.mutasi|floatformat:0|intcomma }}</td>
      {% with kk=a.koreksi|raw_get:"saldo_akhir" %}
      <td class="num mono cell-edit{% if kk %} koreksi{% endif %}"
          hx-get="{% url 'fr_koreksi_form' %}?date={{ tanggal|date:'Y-m-d' }}&account={{ a.account|urlencode }}&kolom=saldo_akhir"
          hx-target="#koreksiPop" hx-swap="innerHTML"
          {% if kk %}title="asli {% if kk.asli is None %}—{% else %}{{ kk.asli|floatformat:0|intcomma }}{% endif %} → {{ kk.nilai|floatformat:0|intcomma }}{% if kk.alasan %} · {{ kk.alasan }}{% endif %}"{% endif %}
          >{% if a.saldo_akhir is not None %}{{ a.saldo_akhir|floatformat:0|intcomma }}{% else %}<span class="faint">—</span>{% endif %}</td>
      {% endwith %}
      <td class="num">{% if a.selisih is None %}<span class="faint">—</span>{% elif a.selisih == 0 %}<span class="badge ok">0</span>{% else %}<span class="badge bad mono">{{ a.selisih|floatformat:0|intcomma }}</span>{% endif %}</td>
    </tr>
    {% endfor %}
    </tbody>
    <tfoot><tr style="font-weight:700">
      <td></td><td>TOTAL</td>
      <td class="num mono">{% if data.total.saldo_awal is not None %}{{ data.total.saldo_awal|floatformat:0|intcomma }}{% else %}<span class="faint">—</span>{% endif %}</td>
      {% for slug, label in data.kolom %}{% with v=data.total.kategori|raw_get:slug %}
      <td class="num mono">{% if v == "" %}<span class="faint">·</span>{% else %}{{ v|floatformat:0|intcomma }}{% endif %}</td>
      {% endwith %}{% endfor %}
      <td class="num mono">{{ data.total.mutasi|floatformat:0|intcomma }}</td>
      <td class="num mono">{% if data.total.saldo_akhir is not None %}{{ data.total.saldo_akhir|floatformat:0|intcomma }}{% else %}<span class="faint">—</span>{% endif %}</td>
      <td class="num">{% if data.total.selisih is None %}<span class="faint">—</span>{% elif data.total.selisih == 0 %}<span class="badge ok">0</span>{% else %}<span class="badge bad mono">{{ data.total.selisih|floatformat:0|intcomma }}</span>{% endif %}</td>
    </tr></tfoot>
  </table>
  </div>
</div>
```

**(b)** Buat `web/templates/web/_fr_koreksi_form.html`:

```html
{% load humanize %}
<div class="card pop-mini">
  <h3 style="margin:0 0 2px;font-size:14px">Koreksi {{ label }}</h3>
  <p class="faint" style="margin:0 0 10px;font-size:12px">
    {{ account }} · {{ tanggal|date:"d M Y" }}<br>
    Nilai asli: <b class="mono">{% if asli is None %}—{% else %}{{ asli|floatformat:0|intcomma }}{% endif %}</b>
    {% if koreksi %} · koreksi aktif oleh <b>{{ koreksi.dibuat_oleh.username|default:"—" }}</b>{% endif %}
  </p>
  <form hx-post="{% url 'fr_koreksi_simpan' %}" hx-target="#fr-control" hx-swap="outerHTML">
    {% csrf_token %}
    <input type="hidden" name="date" value="{{ tanggal|date:'Y-m-d' }}">
    <input type="hidden" name="account" value="{{ account }}">
    <input type="hidden" name="kolom" value="{{ kolom }}">
    <div class="field"><label>Nilai baru</label>
      <input name="nilai" required autocomplete="off" placeholder="tanpa titik ribuan, minus boleh"
             value="{% if koreksi %}{{ koreksi.nilai|floatformat:0 }}{% endif %}"></div>
    <div class="field"><label>Alasan</label>
      <select name="alasan">
        <option value="">— pilih alasan —</option>
        {% for kode, nama in pilihan_alasan %}
        <option value="{{ kode }}" {% if koreksi and koreksi.alasan == kode %}selected{% endif %}>{{ nama }}</option>
        {% endfor %}
      </select></div>
    <div class="field"><label>Catatan</label>
      <textarea name="catatan" rows="2">{% if koreksi %}{{ koreksi.catatan }}{% endif %}</textarea></div>
    <div class="row" style="justify-content:flex-end;gap:8px;margin-top:6px">
      {% if koreksi %}<button class="btn danger" name="hapus" value="1">Kembalikan nilai asli</button>{% endif %}
      <button type="button" class="btn" onclick="document.getElementById('koreksiPop').innerHTML=''">Batal</button>
      <button class="btn primary" type="submit">Simpan</button>
    </div>
  </form>
</div>
```

**(c)** Di `web/templates/web/breakdown_bracket.html`: ganti seluruh kartu "Control Bracket Transaction" (dari `<div class="card pad0 reveal">` kedua s/d `</div>` penutupnya, tepat sebelum `{% endif %}`) dengan:

```html
{% include "web/_fr_control_table.html" %}
```

lalu tepat sebelum `{% endblock %}` tambahkan container popup + CSS halaman:

```html
<div id="koreksiPop"></div>
<style>
  .cell-edit{cursor:pointer;position:relative}
  .cell-edit:hover{box-shadow:inset 0 0 0 1px var(--brand, #2563eb)}
  td.koreksi::after{content:"";position:absolute;top:2px;right:2px;
    border-left:6px solid transparent;border-top:6px solid var(--bad)}
  #koreksiPop:not(:empty){position:fixed;inset:0;z-index:80;
    background:rgba(8,10,17,.45);display:flex;align-items:center;justify-content:center}
  .pop-mini{width:min(380px,92vw);box-shadow:0 12px 40px rgba(0,0,0,.25)}
</style>
```

(Nilai `var(--brand, #2563eb)` hanya fallback; bila token `--brand` tak ada di design system, pakai token aksen yang ada di `app_base.html` — cek dan sesuaikan, jangan tambah warna hardcode baru.)

- [ ] **Step 5: Jalankan test, pastikan lulus**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_fr_koreksi -v 1`
Expected: PASS (16 test). Bila `Missing staticfiles manifest entry` → jalankan collectstatic (Global Constraints) lalu ulangi.

- [ ] **Step 6: Commit**

```bash
git add web/views.py web/urls.py web/templates/web/_fr_control_table.html \
        web/templates/web/_fr_koreksi_form.html web/templates/web/breakdown_bracket.html \
        web/tests_fr_koreksi.py
git commit -m "feat(fr): popup koreksi sel HTMX + tanda segitiga merah + refresh tabel kontrol"
```

---

### Task 4: Halaman Hutang/Piutang

**Files:**
- Create: `web/hutang.py`, `web/templates/web/hutang_piutang.html`
- Modify: `web/views.py`, `web/urls.py`, `web/templates/web/app_base.html` (menu sidebar)
- Test: `web/tests_hutang.py` (file baru)

**Interfaces:**
- Consumes: `web.breakdown._slug_kategori`.
- Produces: `web.hutang.hutang_piutang(toko, dari=None, sampai=None)` → `{"rows": [...], "total_hutang", "total_piutang", "netto", "count"}`; URL name `hutang_piutang`.

- [ ] **Step 1: Tulis failing tests**

Buat `web/tests_hutang.py`:

```python
"""Hutang/Piutang: agregasi murni web.hutang + view /hutang-piutang/."""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.hutang import hutang_piutang

TGL = date(2026, 7, 1)


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
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_hutang -v 2`
Expected: FAIL `ModuleNotFoundError: No module named 'web.hutang'`

- [ ] **Step 3: Implementasi**

Buat `web/hutang.py`:

```python
"""Hutang/Piutang — daftar baris FR berkategori hutang/piutang, query-time.

Pola sama `web/breakdown.py`: baca `Transaction.raw` bracket tanpa migrasi,
berlaku retroaktif untuk data lama. Read-only murni.
"""
from decimal import Decimal

from django.db.models.fields.json import KeyTextTransform

from transactions.models import Transaction
from web.breakdown import _slug_kategori

NOL = Decimal("0")


def hutang_piutang(toko, dari=None, sampai=None):
    """Baris bracket berkategori Hutang/Piutang + ringkasan total.

    Filter kategori didorong ke DB (iregex pada key JSON) supaya scan tetap
    ringan di volume produksi; slug final tetap lewat `_slug_kategori` agar
    normalisasi varian ejaan satu pintu.
    """
    qs = Transaction.objects.filter(toko=toko, source_type__key="bracket")
    if dari:
        qs = qs.filter(posted_date__gte=dari)
    if sampai:
        qs = qs.filter(posted_date__lte=sampai)
    qs = (
        qs.annotate(
            fr_bank=KeyTextTransform("Bank", "raw"),
            fr_kategori=KeyTextTransform("Kategori", "raw"),
            fr_jam=KeyTextTransform("Jam", "raw"),
            fr_member=KeyTextTransform("Member", "raw"),
            fr_username=KeyTextTransform("Username", "raw"),
            fr_expense=KeyTextTransform("Expense", "raw"),
        )
        .filter(fr_kategori__iregex=r"^\s*(hutang|piutang)\s*$")
        .values_list("id", "posted_date", "money_delta", "fr_bank",
                     "fr_kategori", "fr_jam", "fr_member", "fr_username",
                     "fr_expense")
    )
    rows, total_h, total_p = [], NOL, NOL
    for pk, tanggal, delta, bank, kategori, jam, member, username, expense in qs:
        slug = _slug_kategori(kategori)
        delta = delta or NOL
        rows.append({
            "id": pk, "tanggal": tanggal, "jam": str(jam or ""),
            "account": str(bank or "").strip() or "(Tanpa Akun)",
            "kategori": slug,
            "member": str(member or "").strip() or str(username or "").strip(),
            "keterangan": str(expense or "").strip(),
            "nominal": delta,
        })
        if slug == "hutang":
            total_h += delta
        else:
            total_p += delta
    rows.sort(key=lambda r: (r["tanggal"], r["jam"], r["id"]), reverse=True)
    return {"rows": rows, "total_hutang": total_h, "total_piutang": total_p,
            "netto": total_h + total_p, "count": len(rows)}
```

`web/views.py` — tambah view (impor `from web.hutang import hutang_piutang as hitung_hutang_piutang`, `from datetime import timedelta` bila belum):

```python
@login_required
def hutang_piutang(request):
    """Daftar hutang/piutang FR lintas tanggal (otomatis dari data bracket)."""
    active = _active_toko(request)
    if active is None:
        return render(request, "web/no_toko.html")
    sampai = _parse_date(request.GET.get("sampai", "")) or date_cls.today()
    dari = _parse_date(request.GET.get("dari", "")) or sampai - timedelta(days=30)
    data = hitung_hutang_piutang(active, dari=dari, sampai=sampai)
    page = Paginator(data["rows"], 40).get_page(request.GET.get("page"))
    return render(request, "web/hutang_piutang.html", {
        "page": page, "data": data, "dari": dari, "sampai": sampai,
    })
```

`web/urls.py` — setelah path `bracket/koreksi/simpan/`:

```python
    path("hutang-piutang/", views.hutang_piutang, name="hutang_piutang"),
```

Buat `web/templates/web/hutang_piutang.html`:

```html
{% extends "web/app_base.html" %}
{% load humanize %}
{% load web_extras %}
{% block title %}Hutang/Piutang · Truth of Auditor{% endblock %}
{% block crumb %}Transaksi · Hutang/Piutang{% endblock %}
{% block content %}
<div class="page-head reveal">
  <div>
    <h1>Hutang/Piutang</h1>
    <p>Baris FR berkategori Hutang &amp; Piutang untuk <b>{{ active_toko.name }}</b> — otomatis dari data bracket, lintas tanggal.</p>
  </div>
</div>

<div class="card reveal" style="margin-bottom:18px">
  <form method="get" class="row" style="align-items:flex-end">
    <div class="field"><label>Dari</label><input type="date" name="dari" value="{{ dari|date:'Y-m-d' }}"></div>
    <div class="field"><label>Sampai</label><input type="date" name="sampai" value="{{ sampai|date:'Y-m-d' }}"></div>
    <button class="btn primary" type="submit">Terapkan</button>
    <span class="spacer"></span>
    <span class="faint" style="font-size:12px">{{ data.count|intcomma }} baris</span>
  </form>
</div>

<div class="grid cols-3 reveal" style="margin-bottom:18px">
  <div class="card stat"><div class="k">Total Hutang</div><div class="v mono">{{ data.total_hutang|floatformat:0|intcomma }}</div></div>
  <div class="card stat"><div class="k">Total Piutang</div><div class="v mono">{{ data.total_piutang|floatformat:0|intcomma }}</div></div>
  <div class="card stat"><div class="k">Netto</div><div class="v mono">{{ data.netto|floatformat:0|intcomma }}</div></div>
</div>

{% if not data.rows %}
<div class="card reveal"><div class="cell-empty" style="padding:34px 12px;text-align:center">
  Belum ada baris hutang/piutang pada rentang ini.
</div></div>
{% else %}
<div class="card pad0 reveal">
  <div class="table-wrap" style="border:none">
  <table>
    <thead><tr>
      <th>Tanggal</th><th>Jam</th><th>FR Account</th><th>Kategori</th>
      <th>Member</th><th>Keterangan</th><th class="num">Nominal</th>
    </tr></thead>
    <tbody>
    {% for r in page %}
    <tr>
      <td class="mono">{{ r.tanggal|date:"d/m/Y" }}</td>
      <td class="mono faint">{{ r.jam }}</td>
      <td style="font-size:12.5px">{{ r.account }}</td>
      <td>{% if r.kategori == "hutang" %}<span class="badge bad">Hutang</span>{% else %}<span class="badge ok">Piutang</span>{% endif %}</td>
      <td>{{ r.member|default:"—" }}</td>
      <td class="faint">{{ r.keterangan|default:"—" }}</td>
      <td class="num mono" {% if r.nominal < 0 %}style="color:var(--bad)"{% endif %}>{{ r.nominal|floatformat:0|intcomma }}</td>
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

Menu sidebar: di `web/templates/web/app_base.html` (±baris 428–435) grup FR/Bracket berbentuk `<details class="grp…">`. Tambahkan link baru tepat SETELAH baris `<a class="link sub ...>Breakdown FR/Bracket</a>`:

```html
    <a class="link sub {% if '/hutang-piutang' in p %}active{% endif %}" href="{% url 'hutang_piutang' %}">Hutang/Piutang</a>
```

dan perluas kondisi buka-grup pada tag `<details>` dari `{% if '/bracket' in p %}` (dipakai dua kali: kelas ` on` dan atribut ` open`) menjadi `{% if '/bracket' in p or '/hutang-piutang' in p %}` supaya grup terbuka saat halaman hutang/piutang aktif.

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_hutang -v 1`
Expected: PASS (5 test)

- [ ] **Step 5: Commit**

```bash
git add web/hutang.py web/views.py web/urls.py web/templates/web/hutang_piutang.html \
        web/templates/web/app_base.html web/tests_hutang.py
git commit -m "feat(fr): halaman Hutang/Piutang — daftar otomatis dari data bracket"
```

---

### Task 5: Suite penuh, verifikasi browser, docs, push

**Files:**
- Modify: `CLAUDE.md` (bagian "Read-only reporting views")
- Modify: `docs/superpowers/specs/2026-07-18-fr-koreksi-hutang-piutang-design.md` (bagian hasil verifikasi)

**Interfaces:**
- Consumes: semua task sebelumnya.

- [ ] **Step 1: Suite penuh + migrate dev DB**

```bash
/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test
```
Expected: semua lulus (≈768 + ~24 test baru). `collectstatic` dulu bila manifest error.

- [ ] **Step 2: Verifikasi browser (preview)**

Worktree tak punya `db.sqlite3` — salin dari checkout utama lalu migrate:

```bash
cp /Users/macads/Truth-of-auditor/db.sqlite3 ./db.sqlite3
/Users/macads/Truth-of-auditor/.venv/bin/python manage.py migrate
```

Start preview dev server (gunakan tooling preview harness, BUKAN Bash; port dari `.claude/launch.json`), login (`rnd` / `RnD-Audit#2026`), buka `/bracket/` tanggal yang ada datanya, lalu verifikasi:
1. Klik sel kategori → popup muncul berisi nilai asli + dropdown alasan.
2. Simpan nilai baru → tabel refresh, sel bertanda segitiga merah, Total Mutasi & Selisih Kontrol berubah konsisten, popup tertutup.
3. Klik lagi → popup menampilkan koreksi aktif; "Kembalikan nilai asli" memulihkan tampilan.
4. Buka `/kelola/log/` (login admin lokal bila perlu) — entri `fr_koreksi` tercatat.
5. Buka `/hutang-piutang/` — ringkasan + tabel/empty-state render benar.
6. Screenshot bukti popup + sel bertanda + halaman hutang/piutang.
Ingat: restart server preview setelah edit template (cached loader); animasi reveal bisa tampak beku di tab background (artefak headless — bukan bug).

- [ ] **Step 3: Docs**

`CLAUDE.md` bagian "Read-only reporting views": perbarui kalimat pembuka bahwa breakdown FR kini punya SATU tabel tulis (`web.models.FRKoreksi`, overlay koreksi sel — data `Transaction` tetap tak tersentuh; total/selisih dihitung ulang dari nilai koreksi; jejak di AuditLog `fr_koreksi`/`fr_koreksi_hapus`), dan tambahkan `web/hutang.py` (`/hutang-piutang/`) ke daftar modul agregasi. Singkat, ikuti gaya kalimat yang ada.

Spec: tambah bagian `## Hasil verifikasi` berisi hasil suite + verifikasi browser (apa yang dicek, hasilnya).

- [ ] **Step 4: Commit + push**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-07-18-fr-koreksi-hutang-piutang-design.md
git commit -m "docs(fr): catat overlay FRKoreksi + halaman hutang/piutang + hasil verifikasi"
git fetch origin && git push origin HEAD:main
```

Expected: fast-forward. JANGAN deploy — tunggu konfirmasi user (ada migrasi web 0001; start command prod menjalankan migrate otomatis saat deploy nanti).
