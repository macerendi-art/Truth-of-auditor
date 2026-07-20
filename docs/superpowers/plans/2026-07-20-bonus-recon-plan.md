# Paket E — Rekonsiliasi Bonus + Bulk Marking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rekonsiliasi bonus panel↔bracket (parser + halaman query-time) dan bulk marking di Area Pengecekan.

**Architecture:** Dua SourceType baru (`panel_bonus`, `bracket_bonus`) mengisolasi jalur bonus dari pipeline harian; dua parser di `sources/parsers/bonus.py`; mesin cocok query-time `web/bonus.py` + halaman `/bonus/`; view `bulk_review_queue` mengisi form kosong di `review_queue.html`.

**Tech Stack:** Django 5.2, openpyxl, pola parser/report yang sudah ada.

## Global Constraints

- Bahasa UI & komentar: Indonesia. Ikuti idiom modul tetangga (`hutang.py`, `biaya.py`, parser existing).
- `Amt.` panel dalam RIBUAN → ×`SCALE=Decimal(1000)`. `Nominal` bracket RUPIAH PENUH → TANPA ×1000.
- **K-BLD = "Lucky Draw"** (mapping klien, terkonfirmasi data).
- Baris bonus: `jenis="bonus"`, `money_delta=Decimal("0")`, `ticket_no=""` — TIDAK boleh masuk completeness/matcher/consume (terjamin oleh key SourceType baru; jangan sentuh `reconciliation/engine.py`).
- Kategori kanonik disimpan di `raw["Kategori"]` (kunci sama dengan pola breakdown/hutang).
- Kunci cocok: `(username.strip().lower(), int(abs(amount)), posted_date)`.
- Jangan menyentuh perilaku `bulk_review` / `review` yang ada; view baru terpisah.
- venv: `/Users/macads/Truth-of-auditor/.venv/bin/python` (worktree tak punya venv sendiri). Jalankan test dari root worktree.
- Commit per task, JANGAN `git add -A` — add file spesifik saja. JANGAN commit `.claude/settings.local.json`, `db.sqlite3`, `staticfiles.json`.

---

### Task E1: SourceType bonus + migrasi seed

**Files:**
- Modify: `sources/models.py` (KIND_CHOICES)
- Create: `sources/migrations/0010_seed_bonus_sourcetypes.py`
- Test: `sources/tests_bonus_seed.py` (baru)

**Interfaces:**
- Produces: SourceType rows `panel_bonus` ("Panel Bonus"), `bracket_bonus` ("Bracket Bonus"), keduanya `is_money_source=False` — dipakai E2 (`parser.source_key`) dan E3 (filter query).

- [ ] **Step 1: Failing test**

```python
"""Seed SourceType bonus + jaminan isolasi dari completeness."""
from django.test import TestCase

from reconciliation.engine import check_completeness
from sources.models import SourceType, Toko


class SeedBonusSourceTypeTests(TestCase):
    def test_seed_ada(self):
        pb = SourceType.objects.get(key="panel_bonus")
        bb = SourceType.objects.get(key="bracket_bonus")
        self.assertEqual(pb.name, "Panel Bonus")
        self.assertEqual(bb.name, "Bracket Bonus")
        self.assertFalse(pb.is_money_source)
        self.assertFalse(bb.is_money_source)

    def test_completeness_tak_terpengaruh(self):
        """Baris bonus TIDAK membuat panel/bracket dianggap 'ada'."""
        from datetime import date
        from decimal import Decimal
        from transactions.models import Transaction
        toko = Toko.objects.first()
        Transaction.objects.create(
            source_type=SourceType.objects.get(key="panel_bonus"),
            toko=toko, jenis="bonus", amount=Decimal("25000"),
            credit_delta=Decimal("-25000"), money_delta=Decimal("0"),
            posted_date=date(2026, 7, 15), username="x", row_hash="seedtest1",
        )
        comp = check_completeness(toko)
        self.assertFalse(comp["panel"])
        self.assertFalse(comp["bracket"])
```

- [ ] **Step 2: Run** `python manage.py test sources.tests_bonus_seed -v 1` → FAIL (`SourceType matching query does not exist`).

- [ ] **Step 3: Implement.** `sources/models.py` — tambah ke kelas `SourceType` setelah baris `PANEL, BRACKET, ...`:

```python
    PANEL_BONUS, BRACKET_BONUS = "panel_bonus", "bracket_bonus"
```

dan tambah dua entri di `KIND_CHOICES`:

```python
        (PANEL_BONUS, "Panel Bonus"),
        (BRACKET_BONUS, "Bracket Bonus"),
```

`sources/migrations/0010_seed_bonus_sourcetypes.py`:

```python
from django.db import migrations, models


def seed(apps, schema_editor):
    SourceType = apps.get_model("sources", "SourceType")
    SourceType.objects.get_or_create(
        key="panel_bonus", defaults={"name": "Panel Bonus", "is_money_source": False})
    SourceType.objects.get_or_create(
        key="bracket_bonus", defaults={"name": "Bracket Bonus", "is_money_source": False})


def unseed(apps, schema_editor):
    apps.get_model("sources", "SourceType").objects.filter(
        key__in=["panel_bonus", "bracket_bonus"]).delete()


class Migration(migrations.Migration):
    dependencies = [("sources", "0009_upload_duplicate_transactions")]
    operations = [
        migrations.AlterField(
            model_name="sourcetype", name="key",
            field=models.CharField(choices=[
                ("panel", "Panel"), ("bracket", "Bracket"), ("bank", "Bank"),
                ("gateway", "Gateway"), ("panel_bonus", "Panel Bonus"),
                ("bracket_bonus", "Bracket Bonus"),
            ], max_length=20, unique=True),
        ),
        migrations.RunPython(seed, unseed),
    ]
```

Cek dulu field `key` asli di `sources/migrations/0001_initial.py` — samakan atribut lain persis (max_length/unique). Jalankan `python manage.py makemigrations --check --dry-run` untuk memastikan tidak ada migrasi tersisa.

- [ ] **Step 4: Run test** → PASS. Jalankan juga `python manage.py test sources reconciliation -v 1` → PASS.
- [ ] **Step 5: Commit** `feat(bonus): SourceType panel_bonus/bracket_bonus + seed (migrasi 0010) — jalur bonus terisolasi dari completeness`

---

### Task E2: Parser bonus (panel + bracket) + registrasi + deteksi

**Files:**
- Create: `sources/parsers/bonus.py`
- Modify: `sources/services.py` (import + 2 entri PARSERS), `sources/detect.py` (2 signature)
- Test: `sources/tests_bonus_parsers.py` (baru), tambah kasus di `sources/tests_detect.py`

**Interfaces:**
- Consumes: SourceType keys dari E1; helper `base.py` (`read_xlsx_rows`, `parse_decimal`, `parse_dt`, `row_hash`, `BaseParser`).
- Produces: parser key `panel_bonus` & `bracket_bonus`; baris `Transaction` dengan `raw["Kategori"]` kanonik — dipakai E3.

- [ ] **Step 1: Cek `parse_dt`** dengan string nyata `"15-Jul-2026 00:00:09.927"` dan `"2026-07-15 23:46:22"` (shell/print). Bila format pertama gagal, tambahkan format `"%d-%b-%Y %H:%M:%S.%f"` dan `"%d-%b-%Y %H:%M:%S"` secara ADITIF ke daftar format `parse_dt` di `sources/parsers/base.py` (suite lama menjaga regresi).

- [ ] **Step 2: Failing tests** — `sources/tests_bonus_parsers.py`. Fixture xlsx sintetis dibuat via openpyxl (ikuti pola test parser existing, mis. `sources/tests_parsers.py`). Kasus wajib:

```python
"""Parser bonus: panel Credit Balance & bracket Credit/Non-Credit Bonus."""
# Panel: buat sheet dgn baris judul + header baris-2 persis:
# No. | Brand | Date & Time | Description | Remarks | Payment Type | Payment Details | Amt. | Current Credit Balance
# Baris data:
#  Deposit M77Aaa (skip), Withdraw M77Bbb (skip), Opening Balance (skip),
#  'Offset M77ccc Lucky Draw Agent: ...' Amt 50 (skip),
#  'Lucky Draw Agent: Gold Ticket - Event X M77Ccc' Amt -50 -> kategori "Lucky Draw", username "Ccc", amount 50000
#  'Redemption Coupon: CREDIT 15.000 - x:1 M77Ddd' Amt -15 -> "Redemption Coupon", "Ddd", 15000
#  'Promotion Claim: BONUS NEW MEMBER 30% SLOT - [D123] - M77Eee' Amt -15 -> "Promotion Claim", "Eee"
#  'Adjustment: M77Fff' Remarks 'K-BCR3' Amt -5 -> kategori "Adjustment", username "Fff"
# Assert: jumlah baris = 4; jenis="bonus"; money_delta==0; ticket_no=="";
#   credit_delta negatif; posted_date dari Date & Time; raw["Kategori"] benar;
#   row_hash stabil (parse dua kali -> hash sama).
# Bracket: header baris-1 varian LENGKAP (dgn Category) dan varian TANPA Category:
#  Deleted=Yes -> skip; 'K-BLD\nPlayer: Ggg' -> kategori "Lucky Draw", username "Ggg";
#  Category='BONUS LOYALTY MURAH (BL1)' + Description '...\nPlayer: hhh' -> kategori verbatim, username "hhh";
#  Nominal 25000 -> amount 25000 (TANPA ×1000), credit_delta -25000.
```

- [ ] **Step 3: Run** → FAIL (module tidak ada).

- [ ] **Step 4: Implement** `sources/parsers/bonus.py`:

```python
"""Parser bonus: panel Credit Balance & bracket Credit/Non-Credit Bonus (MUL/M77).

Panel `Credit Balance` = ledger kredit penuh; yang diambil HANYA baris bonus
(Redemption Coupon / Promotion Claim / Lucky Draw Agent / Adjustment). Baris
Deposit/Withdraw/Offset/Opening/Reject dilewati — DP/WD sudah diimpor parser
panel biasa, dan Offset = penyeimbang net-nol Lucky Draw (bukan bonusnya).
Bracket bonus: file `Credit Bonus` (ada kolom Category) dan `Non Credit Bonus`
(tanpa Category; kode di Description — K-BLD = Lucky Draw) — satu parser.

Amt panel dalam RIBUAN (×1000); Nominal bracket sudah rupiah penuh.
Bonus bukan uang: money_delta=0, tak pernah ikut matcher/completeness harian
(SourceType terpisah `panel_bonus`/`bracket_bonus`).
"""
import re
from decimal import Decimal

from .base import BaseParser, parse_decimal, parse_dt, read_xlsx_rows, row_hash

SCALE = Decimal(1000)  # 1 kredit panel = Rp1.000
NOL = Decimal("0")

# Awalan Description panel yang merupakan bonus -> kategori kanonik.
_PANEL_KATEGORI = [
    ("Redemption Coupon", "Redemption Coupon"),
    ("Promotion Claim", "Promotion Claim"),
    ("Lucky Draw Agent", "Lucky Draw"),
    ("Adjustment:", "Adjustment"),
]

# Kode Description bracket non-credit -> kategori kanonik (mapping klien).
KODE_BONUS = {"K-BLD": "Lucky Draw"}

_PLAYER_RE = re.compile(r"Player:\s*(.+)", re.IGNORECASE)


def _username_panel(desc, brand):
    """Token terakhir Description; buang prefix brand ('M77Maxx28' -> 'Maxx28')."""
    tokens = desc.split()
    if not tokens:
        return ""
    u = tokens[-1]
    if brand and u.lower().startswith(brand.lower()) and len(u) > len(brand):
        u = u[len(brand):]
    return u.strip()


class PanelBonusParser(BaseParser):
    source_key = "panel_bonus"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=2)
        out = []
        for r in rows:
            desc = str(r.get("Description", "") or "").strip()
            kategori = next(
                (k for pfx, k in _PANEL_KATEGORI if desc.startswith(pfx)), None)
            if kategori is None:
                continue  # Deposit/Withdraw/Offset/Opening/Reject dll.
            amt = parse_decimal(r.get("Amt.")) * SCALE
            occurred = parse_dt(r.get("Date & Time"))
            brand = str(r.get("Brand", "") or "").strip()
            raw = {k: ("" if v is None else str(v)) for k, v in r.items()}
            raw["Kategori"] = kategori
            row = {
                "source_type": "panel_bonus",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "bonus",
                "amount": abs(amt),
                "credit_delta": amt,  # negatif = kredit keluar ke player
                "money_delta": NOL,
                "fee": NOL,
                "bonus": abs(amt),
                "balance_after": None,
                "ticket_no": "",
                "username": _username_panel(desc, brand),
                "reference": "",
                "counterparty": "",
                "description": desc,
                "player_bank": "",
                "bank_title": "",
                "raw": raw,
            }
            row["row_hash"] = row_hash(
                "panel_bonus", [raw.get("Date & Time", ""), desc, row["amount"]])
            out.append(row)
        return out


class BracketBonusParser(BaseParser):
    source_key = "bracket_bonus"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=1)
        out = []
        for r in rows:
            if str(r.get("Deleted", "") or "").strip().lower() == "yes":
                continue
            desc = str(r.get("Description", "") or "").strip()
            tid = str(r.get("Transaction ID", "") or "").strip()
            if not desc and not tid:
                continue  # baris kosong/footer
            kategori = str(r.get("Category", "") or "").strip()
            if not kategori:
                kode = desc.split()[0] if desc.split() else ""
                kategori = KODE_BONUS.get(kode, kode or "Bonus")
            m = _PLAYER_RE.search(desc)
            nominal = abs(parse_decimal(r.get("Nominal")))  # rupiah penuh
            occurred = parse_dt(r.get("Date"))
            raw = {k: ("" if v is None else str(v)) for k, v in r.items()}
            raw["Kategori"] = kategori
            row = {
                "source_type": "bracket_bonus",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "bonus",
                "amount": nominal,
                "credit_delta": -nominal,
                "money_delta": NOL,
                "fee": NOL,
                "bonus": nominal,
                "balance_after": None,
                "ticket_no": "",
                "username": (m.group(1).strip() if m else ""),
                "reference": "",
                "counterparty": "",
                "description": desc,
                "player_bank": "",
                "bank_title": "",
                "raw": raw,
            }
            row["row_hash"] = row_hash(
                "bracket_bonus", [tid, raw.get("Date", ""), desc, row["amount"]])
            out.append(row)
        return out
```

`sources/services.py` — import `from .parsers.bonus import BracketBonusParser, PanelBonusParser` dan tambah ke `PARSERS`:

```python
    "panel_bonus": PanelBonusParser,
    "bracket_bonus": BracketBonusParser,
```

`sources/detect.py` — setelah blok `rpay_wd_xlsx`:

```python
        if _has(t, "date & time") and _has(t, "payment details") and _has(t, "current credit balance"):
            add("panel_bonus", 0.95)  # Panel Credit Balance (ledger kredit; bonus)
        if _has(t, "transaction id") and _has(t, "nominal") and _has(t, "deleted") and _has(t, "created by"):
            add("bracket_bonus", 0.95)  # Bracket Credit/Non-Credit Bonus
```

Tambah kasus di `sources/tests_detect.py`: ketiga layout terdeteksi benar 0.95; layout FR bracket & panel lama TIDAK ikut mendeteksi bonus (regresi).

- [ ] **Step 5: Run** `python manage.py test sources -v 1` → PASS.
- [ ] **Step 6: Commit** `feat(bonus): parser panel_bonus + bracket_bonus (K-BLD=Lucky Draw) + deteksi 0.95`

---

### Task E3: web/bonus.py + halaman /bonus/ + menu

**Files:**
- Create: `web/bonus.py`, `web/templates/web/bonus_recon.html`, `web/tests_bonus.py`
- Modify: `web/views.py` (view `bonus_recon`), `web/urls.py`, `web/templates/web/app_base.html` (menu)

**Interfaces:**
- Consumes: SourceType keys E1, `raw["Kategori"]` E2.
- Produces: `rekonsiliasi_bonus(toko, dari=None, sampai=None)` → `{"cocok": [...], "panel_only": [...], "bracket_only": [...], "ringkas": {...}}`; URL name `bonus_recon` path `bonus/`.

- [ ] **Step 1: Failing tests** `web/tests_bonus.py` (pola `web/tests_biaya.py`): buat Transaction panel_bonus/bracket_bonus langsung via ORM. Kasus:
  - pasangan (username sama beda kapital, nominal sama, tanggal sama) → cocok 1.
  - panel tanpa pasangan → panel_only; bracket tanpa pasangan → bracket_only.
  - dua baris identik panel vs satu bracket → 1 cocok + 1 panel_only (greedy 1:1).
  - rentang tanggal memfilter; per-kategori ringkas benar.
  - view GET `/bonus/` render 200 + judul; empty state; menu link muncul.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** `web/bonus.py`:

```python
"""Rekonsiliasi Bonus panel↔bracket — query-time, tanpa menyentuh run_batch.

Baris bonus tak punya ticket/uang — kunci cocok: username (lowercase) +
nominal bulat + tanggal. Pairing 1:1 greedy per kunci; sisa jadi
panel_only / bracket_only. Pola retroaktif seperti hutang.py/biaya.py.
"""
from collections import defaultdict, deque
from datetime import date
from decimal import Decimal

from transactions.models import Transaction

NOL = Decimal("0")


def _baris(t):
    return {
        "id": t.id,
        "tanggal": t.posted_date,
        "username": t.username,
        "kategori": (t.raw or {}).get("Kategori", "") or "Bonus",
        "nominal": t.amount,
        "deskripsi": t.description,
    }


def _kunci(t):
    return ((t.username or "").strip().lower(), int(abs(t.amount or 0)), t.posted_date)


def rekonsiliasi_bonus(toko, dari=None, sampai=None):
    def ambil(key):
        qs = Transaction.objects.filter(
            toko=toko, source_type__key=key, is_duplicate=False)
        if dari:
            qs = qs.filter(posted_date__gte=dari)
        if sampai:
            qs = qs.filter(posted_date__lte=sampai)
        return list(qs.order_by("posted_date", "id"))

    panel, bracket = ambil("panel_bonus"), ambil("bracket_bonus")

    sisa = defaultdict(deque)
    for b in bracket:
        sisa[_kunci(b)].append(b)

    cocok, panel_only = [], []
    for p in panel:
        antre = sisa.get(_kunci(p))
        if antre:
            cocok.append({"panel": _baris(p), "bracket": _baris(antre.popleft())})
        else:
            panel_only.append(_baris(p))
    bracket_only = [_baris(b) for antre in sisa.values() for b in antre]
    bracket_only.sort(key=lambda r: (r["tanggal"] or date.min, r["id"]))

    def _tot(rows):
        return sum((r["nominal"] for r in rows), NOL)

    per_kat = {}

    def _kat(k):
        return per_kat.setdefault(k, {"cocok": 0, "panel_only": 0, "bracket_only": 0})

    for c in cocok:
        _kat(c["panel"]["kategori"])["cocok"] += 1
    for r in panel_only:
        _kat(r["kategori"])["panel_only"] += 1
    for r in bracket_only:
        _kat(r["kategori"])["bracket_only"] += 1

    ringkas = {
        "cocok": {"n": len(cocok), "total": sum((c["panel"]["nominal"] for c in cocok), NOL)},
        "panel_only": {"n": len(panel_only), "total": _tot(panel_only)},
        "bracket_only": {"n": len(bracket_only), "total": _tot(bracket_only)},
        "kategori": dict(sorted(per_kat.items())),
    }
    return {"cocok": cocok, "panel_only": panel_only,
            "bracket_only": bracket_only, "ringkas": ringkas}
```

View `bonus_recon` di `web/views.py` — CERMINKAN pola view `rincian_biaya` (login_required, toko aktif, `dari`/`sampai` GET default 30 hari, Paginator 40). Tab via GET `tab` ∈ `panel` (default) | `bracket` | `cocok`; paginasi pada list tab aktif. Template `bonus_recon.html` cermin `biaya_admin.html`: crumb `Rekonsiliasi · Bonus`, 3 kartu stat (Cocok hijau, Hanya Panel merah, Hanya Bracket biru; n + total Rp), tabel per-kategori kecil, tab, tabel utama (Tanggal | Username | Kategori | Nominal | Deskripsi; tab cocok menampilkan deskripsi kedua sisi), empty state, pager.

`web/urls.py` setelah `biaya-admin`:

```python
    path("bonus/", views.bonus_recon, name="bonus_recon"),
```

Menu `app_base.html` setelah baris Area Pengecekan (grup Rekonsiliasi):

```html
    <a class="link sub {% if '/bonus' in p %}active{% endif %}" href="{% url 'bonus_recon' %}">Rekonsiliasi Bonus</a>
```

dan tambahkan `'/bonus' in p` ke kondisi open grup Rekonsiliasi (cek pola kondisi grup yang ada, ikuti persis).

- [ ] **Step 4: Run** `python manage.py test web.tests_bonus -v 1` → PASS.
- [ ] **Step 5: Commit** `feat(bonus): rekonsiliasi bonus query-time + halaman /bonus/ + menu`

---

### Task E4: Bulk marking Area Pengecekan

**Files:**
- Modify: `web/views.py` (view `bulk_review_queue`), `web/urls.py`, `web/templates/web/review_queue.html`, (bila perlu) `web/templates/web/_result_row.html`
- Test: `web/tests_bulk_queue.py` (baru)

**Interfaces:**
- Consumes: `MatchResult`, `ReviewAction`, `refresh_batch_summary`, `catat`, `tokos_for` — semuanya sudah diimpor di `web/views.py`.

- [ ] **Step 1: Failing tests** `web/tests_bulk_queue.py`:
  - POST `mark_matched` 2 result dari 2 run/batch BERBEDA → kedua bucket jadi `cocok`, `reason_code="manual_override"`, 2 `ReviewAction`, `refresh_batch_summary` efeknya terlihat (summary run berubah), redirect ke `next`.
  - result milik toko yang BUKAN milik user (auditor dgn allowed_tokos terbatas) → tidak berubah.
  - `action` tak dikenal → 400.
  - GET → 405.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** — `web/views.py` (letakkan setelah `bulk_review`):

```python
@login_required
@require_POST
def bulk_review_queue(request):
    """Setujui / tandai-tinjau massal LINTAS-run dari Area Pengecekan.
    Mutasi per baris identik bulk_review; ringkasan tiap batch tersentuh
    disegarkan sekali."""
    action = request.POST.get("action", "")
    buckets = {"mark_matched": MatchResult.Bucket.COCOK,
               "mark_review": MatchResult.Bucket.TINJAU}
    if action not in buckets:
        return HttpResponseBadRequest("Aksi tidak dikenal.")
    ids = [i for i in request.POST.getlist("result_ids") if i.isdigit()]
    rows = list(MatchResult.objects.filter(
        id__in=ids, run__batch__toko__in=tokos_for(request.user)
    ).select_related("run__batch"))
    batches = {}
    for r in rows:
        r.bucket = buckets[action]
        r.reason_code = "manual_override"
        r.save(update_fields=["bucket", "reason_code"])
        ReviewAction.objects.create(
            result=r, action=action, reason="bulk", reviewer=request.user)
        if r.run.batch_id:
            batches[r.run.batch_id] = r.run.batch
    if rows:
        catat(request.user, "review_massal", f"{len(rows)} hasil (Area Pengecekan)",
              toko=rows[0].run.batch.toko if rows[0].run.batch else None,
              n=len(rows), action=action)
        for b in batches.values():  # kartu run & batch jangan basi
            refresh_batch_summary(b)
    messages.success(request, f"{len(rows)} hasil diperbarui.")
    nxt = request.POST.get("next") or reverse("review_queue")
    if not url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        nxt = reverse("review_queue")
    return redirect(nxt)
```

`web/urls.py` setelah `tinjau/`:

```python
    path("tinjau/bulk-review/", views.bulk_review_queue, name="bulk_review_queue"),
```

`review_queue.html` — ganti `<form id="bulk-form">{% csrf_token %}</form>` dengan bar aksi cermin `run_detail.html` (form method post action `{% url 'bulk_review_queue' %}`, hidden `next={{ request.get_full_path }}`, checkbox `#checkAll` "pilih semua di halaman ini", tombol `Setujui terpilih`/`Tinjau terpilih` dengan `confirm()`, SVG sama persis run_detail). PENTING: baris tabel berada DI LUAR elemen form di halaman ini — pastikan checkbox `result_ids` di `_result_row.html` punya atribut `form="bulk-form"` (cek dulu; jika belum ada, tambahkan — aman untuk run_detail karena id form-nya sama). Cek juga handler JS `#checkAll` (cari di app_base.html / run_detail.html); jika page-local, sertakan skrip kecil yang sama di review_queue.html.

- [ ] **Step 4: Run** `python manage.py test web.tests_bulk_queue web.tests_views -v 1` (modul test view yang relevan; cek nama file test existing) → PASS.
- [ ] **Step 5: Commit** `feat(tinjau): bulk Setujui/Tinjau terpilih di Area Pengecekan (lintas-run)`

---

### Task E5: Suite penuh + kalibrasi data nyata + docs (dikendalikan controller)

- [ ] Kalibrasi scratch-DB dengan 3 file sampel (path stabil di scratchpad session). Ekspektasi: panel_bonus 606 baris (474 Promotion + 122 Redemption + 6 Lucky Draw + 4 Adjustment); bracket_bonus 134 (128+6); rekonsiliasi tanggal 2026-07-15: Lucky Draw cocok 6/6, bracket_only Lucky Draw 0.
- [ ] `python manage.py test` penuh → PASS (≥814 + test baru).
- [ ] Tulis bagian "Hasil implementasi" di spec + update ledger + commit + push origin/main.
