# Parser MUTASI WD QR UNO + RPay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dua parser gateway baru — (1) MUTASI WD QR UNO (sisi uang QRIS-withdrawal panel Vigor/TM Gaming, join UUID penuh terbukti 278/278 di data SLO) dan (2) RPay (gateway QRIS DP brand panel-Nexus/MUL, anchor username exact) — terdaftar, terdeteksi otomatis, teruji, dan terkalibrasi Fase-0.

**Architecture:** Mengikuti pola parser yang ada persis: subclass `BaseParser` yang mengembalikan list dict berfield `Transaction`, registrasi di dict `PARSERS` (`sources/services.py`), signature deteksi di `sources/detect.py`. UNO WD masuk `sources/parsers/cor.py` (keluarga platform TM Gaming/Vigor); RPay masuk `sources/parsers/gateways.py` (keluarga gateway Nexus, seperti NXPay).

**Tech Stack:** Django 5.2, openpyxl via `read_xlsx_rows` (styles-tolerant), csv stdlib, tes `django.test.SimpleTestCase` pola `sources/tests_cor.py`.

## Global Constraints

- Bahasa komentar/docstring/pesan: Indonesia; identifier Python: Inggris.
- Nominal kedua file sudah RUPIAH PENUH — JANGAN ×1000.
- Konvensi tanda: WD = `money_delta < 0`; DP = `money_delta > 0`; gateway `credit_delta = 0`.
- `USE_TZ = False` — datetime naif.
- **Keputusan anchor RPay (jangan diubah tanpa data baru):** `reference` DIKOSONGKAN, UUID hanya di `raw`. Alasan: aturan `blocked` di `reconciliation/engine.py` (±baris 361) mengasingkan gateway ber-`reference` yang tak dikenal panel dari seluruh pass identitas; belum terbukti panel Nexus menanam UUID RPay di Remarks. Matching RPay mengandalkan pass-1 username exact (`_identity` → skor 100).
- **Baris REFUND mutasi UNO WD dilewati** (payout gagal, uang kembali); baris SUCCESS non-UUID (transfer manual operator) TETAP diambil → tampil sebagai uang-tanpa-panel (`no_panel`).
- Jalankan tes dengan venv utama: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test ...` dari root worktree.
- Commit per task; push ke `origin/main` hanya di task terakhir (fetch+rebase dulu, fast-forward only).

---

### Task 1: Parser `CORQRISWDGatewayParser` (MUTASI WD QR UNO)

**Files:**
- Modify: `sources/parsers/cor.py` (tambah kelas di akhir file)
- Test: `sources/tests_uno_rpay.py` (file baru)

**Interfaces:**
- Consumes: `BaseParser`, `parse_decimal`, `parse_dt`, `read_xlsx_rows`, `row_hash` dari `sources/parsers/base.py` (sudah di-import di cor.py).
- Produces: kelas `CORQRISWDGatewayParser` dengan `source_key = "gateway"`, method `parse(path, flow="") -> list[dict]`; dipakai Task 2.

- [ ] **Step 1: Tulis tes yang gagal**

Buat `sources/tests_uno_rpay.py`:

```python
"""Parser gateway UNO WD (QRIS withdrawal Vigor/TMG) & RPay (QRIS DP Nexus/MUL)."""
import os, tempfile
from django.test import SimpleTestCase
from openpyxl import Workbook


def _xlsx(rows):
    wb = Workbook(); ws = wb.active
    for r in rows:
        ws.append(r)
    fd, path = tempfile.mkstemp(suffix=".xlsx"); os.close(fd)
    wb.save(path)
    return path


UNO_WD_HEADER = ["Merchant Name", "Order ID (Merchant)", "AccountNumber",
                 "RecipientName", "Grand Total", "Amount", "Fee", "Remark",
                 "TransactionTime", "Status"]


class UnoWDGatewayTests(SimpleTestCase):
    def _parse(self, rows):
        from sources.parsers.cor import CORQRISWDGatewayParser
        path = _xlsx([UNO_WD_HEADER] + rows)
        try:
            return CORQRISWDGatewayParser().parse(path)
        finally:
            os.remove(path)

    def test_wd_sukses_field_lengkap(self):
        rows = self._parse([
            ["Omega Vig66", "fd1a26d3-5dbe-411b-9f32-96e97184fe31", "081270553953",
             "081270553953", "800900", "800000", "900", "[via-api] ",
             "2026-07-03 23:54:40", "SUCCESS"],
        ])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["jenis"], "wd")
        self.assertEqual(str(r["amount"]), "800000")       # nett = angka panel
        self.assertEqual(str(r["money_delta"]), "-800000")
        self.assertEqual(str(r["credit_delta"]), "0")
        self.assertEqual(str(r["fee"]), "900")
        self.assertEqual(r["reference"], "fd1a26d3-5dbe-411b-9f32-96e97184fe31")
        self.assertEqual(r["counterparty"], "")            # recipient == account (telepon)
        self.assertEqual(r["occurred_at"].hour, 23)
        self.assertIn("081270553953", r["raw"]["AccountNumber"])

    def test_refund_dilewati(self):
        rows = self._parse([
            ["Omega Vig66", "6f2ebccd-9da1-47be-8986-36065e520fc2", "901829968671",
             "901829968671", "412110", "410610", "1500", "[via-api] ",
             "2026-07-03 23:11:52", "REFUND"],
        ])
        self.assertEqual(rows, [])

    def test_transfer_manual_non_uuid_tetap_diambil(self):
        rows = self._parse([
            ["Omega Vig66", "ee4c1d014ae6451891ad", "058801037091503",
             "MAULANA IQBAL AILA", "30001500", "30000000", "1500", "0",
             "2026-07-03 21:20:14", "SUCCESS"],
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["counterparty"], "MAULANA IQBAL AILA")

    def test_row_hash_stabil(self):
        baris = ["Omega Vig66", "fd1a26d3-5dbe-411b-9f32-96e97184fe31", "081270553953",
                 "081270553953", "800900", "800000", "900", "", "2026-07-03 23:54:40", "SUCCESS"]
        a = self._parse([baris])[0]["row_hash"]
        b = self._parse([baris])[0]["row_hash"]
        self.assertEqual(a, b)
```

- [ ] **Step 2: Jalankan tes, pastikan gagal**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources.tests_uno_rpay -v 2`
Expected: FAIL/ERROR `ImportError: cannot import name 'CORQRISWDGatewayParser'`

- [ ] **Step 3: Implementasi minimal**

Tambahkan di akhir `sources/parsers/cor.py`:

```python
class CORQRISWDGatewayParser(BaseParser):
    """Mutasi WD gateway QR UNO — sisi uang QRIS withdrawal keluarga panel
    TM Gaming/Vigor (SLO/COR/WN25).

    Kunci exact: `Order ID (Merchant)` (UUID penuh) == `Transaction ID` panel
    QRIS WD -> reference-join pass 0b. Baris REFUND dilewati (payout gagal,
    uang kembali). Baris SUCCESS ber-order non-UUID (transfer manual operator)
    tetap diambil supaya muncul sebagai uang-tanpa-panel.
    """

    source_key = "gateway"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=1)
        out = []
        for r in rows:
            order = str(r.get("Order ID (Merchant)", "") or "").strip()
            status = str(r.get("Status", "") or "").strip().lower()
            if not order or status != "success":
                continue
            amt = parse_decimal(r.get("Amount"))  # nett = angka yang dilihat panel
            occurred = parse_dt(r.get("TransactionTime"))
            acct = str(r.get("AccountNumber", "") or "").strip()
            recipient = str(r.get("RecipientName", "") or "").strip()
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "wd",
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": -amt,
                "fee": parse_decimal(r.get("Fee")),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": "",
                "username": "",
                "reference": order,
                "counterparty": "" if recipient == acct else recipient,
                "description": f"QRIS WD {r.get('Merchant Name', '')}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items()},
            }
            row["row_hash"] = row_hash("cor_qris_wd_gw", [order, amt, occurred])
            out.append(row)
        return out
```

- [ ] **Step 4: Jalankan tes, pastikan lolos**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources.tests_uno_rpay -v 2`
Expected: 4 tes PASS

- [ ] **Step 5: Commit**

```bash
git add sources/parsers/cor.py sources/tests_uno_rpay.py
git commit -m "feat(sources): parser mutasi WD QR UNO (QRIS withdrawal Vigor/TMG)"
```

---

### Task 2: Registrasi + deteksi `cor_qris_wd_gateway`

**Files:**
- Modify: `sources/services.py` (import + entry PARSERS)
- Modify: `sources/detect.py` (signature xlsx)
- Test: `sources/tests_uno_rpay.py` (tambah kelas tes)

**Interfaces:**
- Consumes: `CORQRISWDGatewayParser` dari Task 1.
- Produces: key `"cor_qris_wd_gateway"` di `PARSERS`; `detect_source()` mengembalikan key itu untuk file mutasi WD UNO.

- [ ] **Step 1: Tulis tes yang gagal** (tambah di `sources/tests_uno_rpay.py`)

```python
class UnoWDRegistrationTests(SimpleTestCase):
    def test_terdaftar_di_parsers(self):
        from sources.services import PARSERS
        from sources.parsers.cor import CORQRISWDGatewayParser
        self.assertIs(PARSERS.get("cor_qris_wd_gateway"), CORQRISWDGatewayParser)

    def test_terdeteksi_dari_header(self):
        from sources.detect import detect_source
        path = _xlsx([UNO_WD_HEADER,
                      ["Omega Vig66", "fd1a26d3-5dbe-411b-9f32-96e97184fe31",
                       "081270553953", "081270553953", "800900", "800000", "900",
                       "", "2026-07-03 23:54:40", "SUCCESS"]])
        try:
            ranked = detect_source(path, "MUTASI WD QR UNO SLO 03-07.xlsx")
        finally:
            os.remove(path)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["parser_key"], "cor_qris_wd_gateway")
        self.assertGreaterEqual(ranked[0]["confidence"], 0.9)
```

- [ ] **Step 2: Jalankan tes, pastikan gagal**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources.tests_uno_rpay.UnoWDRegistrationTests -v 2`
Expected: FAIL (`PARSERS.get(...)` = None; detect tak mengembalikan key)

- [ ] **Step 3: Implementasi**

`sources/services.py` — ubah baris import cor dan tambah entry:

```python
from .parsers.cor import (
    CORPanelBankParser,
    CORPanelQRISParser,
    CORQRISGatewayParser,
    CORQRISWDGatewayParser,
)
```

di dict `PARSERS`, setelah `"cor_qris_gateway"`:

```python
    "cor_qris_wd_gateway": CORQRISWDGatewayParser,
```

`sources/detect.py` — di blok `if ext in (".xlsx", ".xls"):`, setelah signature `cor_qris_gateway`:

```python
        if _has(t, "order id (merchant)") and (_has(t, "recipientname") or _has(t, "accountnumber")):
            add("cor_qris_wd_gateway", 0.95)
```

- [ ] **Step 4: Jalankan tes modul + tes deteksi lama (regresi)**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources.tests_uno_rpay sources.tests_detect sources.tests_cor -v 1`
Expected: semua PASS

- [ ] **Step 5: Commit**

```bash
git add sources/services.py sources/detect.py sources/tests_uno_rpay.py
git commit -m "feat(sources): registrasi + auto-deteksi cor_qris_wd_gateway"
```

---

### Task 3: Parser `RPayGatewayParser` (CSV DP RPay)

**Files:**
- Modify: `sources/parsers/gateways.py` (tambah kelas + import csv di atas)
- Test: `sources/tests_uno_rpay.py` (tambah kelas tes)

**Interfaces:**
- Consumes: `BaseParser`, `parse_decimal`, `parse_dt`, `row_hash` dari `.base` (sudah di-import di gateways.py); modul `csv` stdlib.
- Produces: kelas `RPayGatewayParser`, `source_key = "gateway"`, `parse(path, flow="") -> list[dict]`; dipakai Task 4.

- [ ] **Step 1: Tulis tes yang gagal** (tambah di `sources/tests_uno_rpay.py`; tambah `import csv` tidak perlu — tulis file via string)

```python
RPAY_HEADER = ("No.,Merchant,Customer Name,Customer Username,Date,UUID,"
               "External ID,RRN,Acquirer Merchant,Time,Elapsed Time (s),Amount,Fee,Status")


def _csv(lines):
    fd, path = tempfile.mkstemp(suffix=".csv"); os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


class RPayGatewayTests(SimpleTestCase):
    def _parse(self, lines, flow=""):
        from sources.parsers.gateways import RPayGatewayParser
        path = _csv([RPAY_HEADER] + lines)
        try:
            return RPayGatewayParser().parse(path, flow=flow)
        finally:
            os.remove(path)

    def test_dp_sukses_field_lengkap(self):
        rows = self._parse([
            '1,NOMINA ISI ULANG,kaleng1,kaleng1,"09 Jul 2026, 23:59",'
            '93c8f884-bd54-445f-96df-e899a660cb64,46645580,619180666745,'
            'Thundfire Game,49s,49,25000.0,325.0,success',
        ])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["jenis"], "depo")
        self.assertEqual(str(r["amount"]), "25000.0")
        self.assertGreater(r["money_delta"], 0)
        self.assertEqual(r["username"], "kaleng1")
        self.assertEqual(r["reference"], "")   # sengaja: lihat Global Constraints
        self.assertEqual(r["raw"]["UUID"], "93c8f884-bd54-445f-96df-e899a660cb64")
        self.assertEqual(r["counterparty"], "")  # Customer Name == Username
        self.assertEqual((r["occurred_at"].year, r["occurred_at"].month,
                          r["occurred_at"].day, r["occurred_at"].hour,
                          r["occurred_at"].minute), (2026, 7, 9, 23, 59))

    def test_non_success_dilewati(self):
        rows = self._parse([
            '2,NOMINA ISI ULANG,irma30,irma30,"09 Jul 2026, 23:59",'
            '8d422e0c-eb9c-4baa-a310-544055a7bac7,46645575,000139896397,'
            'Frostcry Game,45s,45,50000.0,650.0,failed',
        ])
        self.assertEqual(rows, [])

    def test_row_hash_stabil_dan_unik_per_uuid(self):
        a = ('1,NOMINA ISI ULANG,kaleng1,kaleng1,"09 Jul 2026, 23:59",'
             '93c8f884-bd54-445f-96df-e899a660cb64,46645580,619180666745,'
             'Thundfire Game,49s,49,25000.0,325.0,success')
        b = ('2,NOMINA ISI ULANG,irma30,irma30,"09 Jul 2026, 23:59",'
             '8d422e0c-eb9c-4baa-a310-544055a7bac7,46645575,000139896397,'
             'Frostcry Game,45s,45,25000.0,325.0,success')
        h1 = self._parse([a])[0]["row_hash"]
        h1b = self._parse([a])[0]["row_hash"]
        h2 = self._parse([b])[0]["row_hash"]
        self.assertEqual(h1, h1b)
        self.assertNotEqual(h1, h2)
```

- [ ] **Step 2: Jalankan tes, pastikan gagal**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources.tests_uno_rpay.RPayGatewayTests -v 2`
Expected: ERROR `ImportError: cannot import name 'RPayGatewayParser'`

- [ ] **Step 3: Implementasi minimal**

Di `sources/parsers/gateways.py`: tambah `import csv` di baris paling atas (sebelum `from decimal import Decimal`), lalu kelas baru di akhir file:

```python
class RPayGatewayParser(BaseParser):
    """Gateway QRIS RPay (CSV, dipakai brand panel-Nexus, mis. MUL).

    Membawa `Customer Username` == username panel -> anchor pass-1 username
    exact. `UUID` DISIMPAN di raw saja, TIDAK di `reference`: aturan blocked
    engine mengasingkan gateway ber-reference yang tak dikenal panel dari pass
    identitas, dan belum terbukti panel Nexus menanam UUID RPay di Remarks.
    Nyalakan reference bila sudah terbukti dari data se-tanggal.
    """

    source_key = "gateway"

    def parse(self, path, flow=""):
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            raw_rows = list(csv.DictReader(f))
        is_wd = flow == "wd"
        out = []
        for r in raw_rows:
            uuid = str(r.get("UUID", "") or "").strip()
            status = str(r.get("Status", "") or "").strip().lower()
            if not uuid or status != "success":
                continue
            amt = parse_decimal(r.get("Amount"))
            occurred = parse_dt(r.get("Date"))
            username = str(r.get("Customer Username", "") or "").strip()
            cname = str(r.get("Customer Name", "") or "").strip()
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "wd" if is_wd else "depo",
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": -amt if is_wd else amt,
                "fee": parse_decimal(r.get("Fee")),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": "",
                "username": username,
                "reference": "",
                "counterparty": "" if cname.lower() == username.lower() else cname,
                "description": f"RPay {r.get('RRN', '')}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items() if k},
            }
            row["row_hash"] = row_hash("rpay", [uuid, amt])
            out.append(row)
        return out
```

- [ ] **Step 4: Jalankan tes, pastikan lolos**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources.tests_uno_rpay.RPayGatewayTests -v 2`
Expected: 3 tes PASS

- [ ] **Step 5: Commit**

```bash
git add sources/parsers/gateways.py sources/tests_uno_rpay.py
git commit -m "feat(sources): parser gateway QRIS RPay (anchor username exact)"
```

---

### Task 4: Registrasi + deteksi `rpay`

**Files:**
- Modify: `sources/services.py` (import + entry PARSERS)
- Modify: `sources/detect.py` (signature csv)
- Test: `sources/tests_uno_rpay.py` (tambah kelas tes)

**Interfaces:**
- Consumes: `RPayGatewayParser` dari Task 3.
- Produces: key `"rpay"` di `PARSERS`; `detect_source()` mengembalikan `rpay` untuk CSV RPay.

- [ ] **Step 1: Tulis tes yang gagal** (tambah di `sources/tests_uno_rpay.py`)

```python
class RPayRegistrationTests(SimpleTestCase):
    def test_terdaftar_di_parsers(self):
        from sources.services import PARSERS
        from sources.parsers.gateways import RPayGatewayParser
        self.assertIs(PARSERS.get("rpay"), RPayGatewayParser)

    def test_terdeteksi_dari_header_csv(self):
        from sources.detect import detect_source
        path = _csv([RPAY_HEADER,
                     '1,NOMINA ISI ULANG,kaleng1,kaleng1,"09 Jul 2026, 23:59",'
                     '93c8f884-bd54-445f-96df-e899a660cb64,46645580,619180666745,'
                     'Thundfire Game,49s,49,25000.0,325.0,success'])
        try:
            ranked = detect_source(path, "dp rpay.csv")
        finally:
            os.remove(path)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["parser_key"], "rpay")
        self.assertGreaterEqual(ranked[0]["confidence"], 0.9)
```

- [ ] **Step 2: Jalankan tes, pastikan gagal**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources.tests_uno_rpay.RPayRegistrationTests -v 2`
Expected: FAIL

- [ ] **Step 3: Implementasi**

`sources/services.py` — ubah import gateways + tambah entry PARSERS (setelah `"cor_qris_wd_gateway"`):

```python
from .parsers.gateways import NXPayParser, QRFlyerParser, QHokiParser, RPayGatewayParser
```

```python
    "rpay": RPayGatewayParser,
```

`sources/detect.py` — di blok `elif ext == ".csv":`, setelah cek bca_csv:

```python
        if "customer username" in c and "acquirer merchant" in c:
            add("rpay", 0.95)
```

Catatan: `_csv_text` sudah me-lowercase isi — token harus lowercase.

- [ ] **Step 4: Jalankan seluruh modul sumber (regresi deteksi bank csv)**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources -v 1`
Expected: semua PASS

- [ ] **Step 5: Commit**

```bash
git add sources/services.py sources/detect.py sources/tests_uno_rpay.py
git commit -m "feat(sources): registrasi + auto-deteksi rpay"
```

---

### Task 5: Kalibrasi Fase-0 folder SAMPLING VIGOR (SLO)

Tujuan: membuktikan rail QRIS WD tertutup end-to-end oleh parser baru memakai matcher asli, TANPA menyentuh DB dev/prod.

**Files:**
- Tidak ada perubahan kode. Hanya menjalankan harness pada DB scratch.

- [ ] **Step 1: Siapkan folder datar & DB scratch**

```bash
SCRATCH=$(mktemp -d)
mkdir "$SCRATCH/slo"
find "/Users/macads/Downloads/Telegram Desktop/SAMPLING VIGOR (TM GAMING)" -type f \( -name "*.xlsx" -o -iname "*.csv" \) -exec cp {} "$SCRATCH/slo/" \;
export DATABASE_URL="sqlite:///$SCRATCH/slo.sqlite3"
/Users/macads/Truth-of-auditor/.venv/bin/python manage.py migrate
/Users/macads/Truth-of-auditor/.venv/bin/python manage.py shell -c "from sources.models import Toko; Toko.objects.get_or_create(key='slo', defaults={'name': 'SLO'})"
```

(PDF sengaja dilewati — BNI belum ada parsernya; di luar scope task ini.)

- [ ] **Step 2: Jalankan harness**

```bash
/Users/macads/Truth-of-auditor/.venv/bin/python manage.py validate_brands --dir "$SCRATCH/slo" --toko slo --flow-from-name
```

Expected:
- `MUTASI WD QR UNO SLO 03-07.xlsx` ter-ingest via `cor_qris_wd_gateway` (±287 baris SUCCESS, REFUND tak ikut).
- Batch 2026-07-03: baris panel QRIS WD (278) → `cocok` via reason `reference` (bukan `no_money`).
- Bila ada angka meleset, SELIDIKI dulu (bandingkan reason_code per rail seperti analisis Fase-0 COR) sebelum menyimpulkan.

- [ ] **Step 3: Catat hasil**

Tambahkan angka hasil kalibrasi (cocok/tinjau/tidak per rail) ke bagian "Hasil Kalibrasi" di bawah dokumen plan ini, lalu commit:

```bash
git add docs/superpowers/plans/2026-07-10-parser-uno-wd-rpay.md
git commit -m "docs: hasil kalibrasi Fase-0 SLO parser UNO WD"
```

---

### Task 6: Dokumentasi + push

**Files:**
- Modify: `CLAUDE.md` (bullet "Per-brand exact keys on the money side")

- [ ] **Step 1: Update CLAUDE.md**

Di bullet `**Per-brand exact keys on the money side**`, tambahkan sebelum kalimat "Some COR exports":

```
UNO QRIS-WD `Order ID (Merchant)` (UUID penuh) == panel Vigor/TMG WD `Transaction ID`; RPay (MUL) sengaja TANPA reference — anchor = `Customer Username` == username panel (UUID hanya di raw, tunggu bukti Remarks).
```

- [ ] **Step 2: Suite penuh**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test`
Expected: semua PASS (baseline 592 + tes baru)

- [ ] **Step 3: Commit + push (fast-forward only)**

```bash
git add CLAUDE.md
git commit -m "docs: kunci exact UNO QRIS-WD + anchor username RPay di CLAUDE.md"
git fetch origin
git rebase origin/main
git push origin HEAD:main
```

---

## Hasil Kalibrasi

Dijalankan 2026-07-10 pada DB scratch (sqlite), harness `validate_brands`.

**SLO (folder SAMPLING VIGOR, 03-07-2026, toko scratch `slo`):**

| Rail | Hasil | Reason |
|---|---|---|
| QRIS-WD (parser BARU `cor_qris_wd_gateway`) | **278/278 cocok (100%)** | semua `reference` (UUID penuh) |
| QRIS-DP (parser lama `cor_qris_gateway`) | 5.166/5.166 cocok (100%; 6 baris spillover ke batch 02-07) | semua `reference` |
| BANK-WD | 187/676 cocok | 489 `no_money` — mutasi BNI/BCA hanya PDF (dilewati), Mandiri terenkripsi; struktural, bukan matcher |
| BANK-DP | 9/109 cocok | 100 `no_money` — idem |

Mutasi WD QR UNO ter-ingest 287 baris SUCCESS (8 REFUND dilewati); 9 transfer manual non-UUID jadi uang-tanpa-panel sesuai desain.

**M77/RPay (panel Nexus 09-07-2026 + `dp rpay.csv`, toko scratch `m77`):**

- Panel ber-label `QRISRPAY`: 2.058 baris → **2.030 cocok (98,6%)** = 1.992 `amount+date+name` (username exact skor 100) + 38 `amount_fee`; 28 `no_money`.
- Uang RPay terpakai 2.051/2.054.
- 21 baris panel NXPAY/bank ikut menyedot uang RPay (pemain deposit nominal sama via dua kanal, ambigu tanpa ID — Remarks M77 terbukti TIDAK memuat UUID RPay, 0/2058). Di produksi terurai sendiri: file NXPay diklaim join ticket pass-0 sebelum pass username.
- Rail lain `no_money` karena file uangnya memang tidak disertakan (hanya menguji RPay).

**Tindak lanjut — kunci kanal gateway (disetujui user, commit terpisah):** `bank_title` panel ("QRISRPAY"/"NXPAY DEPOSIT QR"/…) vs awalan `description` uang gateway ("RPay"/"NXPAY"/"QHOKI"/"QRFLYER") — gateway berbeda yang sama-sama dikenal DIBLOKIR di `kandidat()` (semua pass identitas, termasuk late settlement); fail-open bila salah satu tak dikenal. 5 test `reconciliation/tests_channel_guard.py`. Kalibrasi ulang M77 09-07: QRISRPAY **2.048/2.058 cocok (99,5%)**, no_money 28→10 (sisa 10 memang tak ada di file RPay), baris NXPAY **0 tercuri** (506 no_money jujur menunggu file NXPay; dulu 18 tercuri). Sisa lintas-kanal 3 baris berlabel bank manual (BRI 2 + BCA 1) — fail-open sesuai scope. SLO regresi nol: QRIS-WD tetap 278/278 `reference`. Suite 608 hijau.
