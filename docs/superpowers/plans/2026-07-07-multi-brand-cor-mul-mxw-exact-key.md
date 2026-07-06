# Multi-brand (COR/MUL/MXW) + Exact-Key Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Onboard 3 brand (COR=Gacor25, MUL=Mulia77, MXW=MaxWin77) dengan 4 parser baru + 1 pass engine, sehingga QRIS terekonsiliasi via kunci exact (UUID/Ticket), bukan fuzzy.

**Architecture:** Ikuti pola pipeline existing — parser (`sources/parsers/`) meng-output dict kanonik → `ingest()` simpan `Transaction` → `_MoneyMatcher` cocokkan. Tambahan: reader xlsx tahan-styles (exporter COR non-standar), parser COR + QRIS HOKI, dan **reference-join pass** (Panel `reference` ↔ Gateway `reference`) simetris dengan ticket-join pass 0 yang sudah ada.

**Tech Stack:** Django 5.2, Python 3.11, openpyxl, rapidfuzz, `zipfile`+`xml.etree` (raw xlsx). Test: Django `TestCase`/`SimpleTestCase`.

## Global Constraints

- **Bahasa:** komentar kode & UI Indonesia (ikuti konvensi repo). JANGAN emoji-as-icon / teks Inggris di UI.
- **COR nominal = RUPIAH penuh** — parser COR JANGAN kali `SCALE`/×1000 (beda dari `PanelParser`).
- **Reference-join GATEWAY-ONLY** — hanya baris `source_type.key=="gateway"` yang di-index/blok by reference; JANGAN sentuh `reference` bank (mis. SEQ BRI).
- **Idempotensi:** tiap parser set `row_hash` stabil dari field kunci.
- **SourceType reuse:** panel COR pakai `source_key="panel"`, gateway pakai `source_key="gateway"` (SourceType sudah di-seed; tak buat baru).
- **Toko sudah di-seed** (migrasi `0007_seed_16_toko`): `mul`, `mxw`, `g25` (=Gacor25=COR). TAK perlu migrasi Toko baru.
- **Tiap task diakhiri commit.** Jalankan `python manage.py test` (venv `.venv`) — harus hijau.

## File Structure

- **Modify** `sources/parsers/base.py` — reader tahan-styles + helper `parse_bank_triplet`.
- **Create** `sources/parsers/cor.py` — `CORPanelBankParser`, `CORPanelQRISParser`, `CORQRISGatewayParser`.
- **Modify** `sources/parsers/gateways.py` — `QHokiParser`.
- **Modify** `sources/services.py` — daftar 4 parser + isi `player_bank`/`bank_title` saat ingest.
- **Modify** `sources/detect.py` — token tahan-styles + 4 signature.
- **Modify** `reconciliation/engine.py` — reference-join pass, PanelBracket skip ticketless, gate PANEL_BRACKET, warning agregat Panel↔Bracket.
- **Create** `reconciliation/management/commands/validate_brands.py` — harness Fase 0.
- **Create tests:** `sources/tests_xlsx_safe.py`, `sources/tests_cor.py`, `sources/tests_qhoki.py`, `reconciliation/tests_reference_join.py`, `reconciliation/tests_bracket_cor.py`, `reconciliation/tests_validate_brands.py`. **Modify** `sources/tests_detect.py`.

---

### Task 1: Reader xlsx tahan-styles

**Files:**
- Modify: `sources/parsers/base.py`
- Test: `sources/tests_xlsx_safe.py`

**Interfaces:**
- Produces: `read_xlsx_rows(path, header_row=1, sheet=None) -> (headers, list[dict])` — sekarang fallback ke reader mentah bila openpyxl gagal/menghasilkan ≤`header_row` baris. Reader mentah baru `_raw_xlsx_rows(path) -> list[list]` (semua baris, kolom terurut).

- [ ] **Step 1: Write the failing test**

```python
# sources/tests_xlsx_safe.py
import io, os, tempfile, zipfile
from django.test import SimpleTestCase
from sources.parsers.base import read_xlsx_rows, _raw_xlsx_rows

_CT = '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'
_RELS = '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
_WB = '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
_WBR = '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
# Sheet TANPA <dimension> (mereplikasi exporter COR): inline strings.
_SHEET = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
          '<row r="1"><c r="A1" t="inlineStr"><is><t>Transaction ID</t></is></c><c r="B1" t="inlineStr"><is><t>Amount</t></is></c></row>'
          '<row r="2"><c r="A2" t="inlineStr"><is><t>abc-123</t></is></c><c r="B2" t="inlineStr"><is><t>50000</t></is></c></row>'
          '</sheetData></worksheet>')

def _make_nodim_xlsx():
    fd, path = tempfile.mkstemp(suffix=".xlsx"); os.close(fd)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("xl/workbook.xml", _WB)
        z.writestr("xl/_rels/workbook.xml.rels", _WBR)
        z.writestr("xl/worksheets/sheet1.xml", _SHEET)
    return path

class XlsxSafeTests(SimpleTestCase):
    def test_raw_reader_membaca_inline_strings(self):
        path = _make_nodim_xlsx()
        try:
            rows = _raw_xlsx_rows(path)
        finally:
            os.remove(path)
        self.assertEqual(rows[0][:2], ["Transaction ID", "Amount"])
        self.assertEqual(rows[1][:2], ["abc-123", "50000"])

    def test_read_xlsx_rows_tahan_tanpa_dimension(self):
        path = _make_nodim_xlsx()
        try:
            headers, dicts = read_xlsx_rows(path, header_row=1)
        finally:
            os.remove(path)
        self.assertEqual(len(dicts), 1)
        self.assertEqual(dicts[0]["Transaction ID"], "abc-123")
        self.assertEqual(str(dicts[0]["Amount"]), "50000")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python manage.py test sources.tests_xlsx_safe -v2`
Expected: FAIL — `ImportError: cannot import name '_raw_xlsx_rows'`.

- [ ] **Step 3: Add raw reader + fallback to `sources/parsers/base.py`**

Tambah import di atas file: `import io, re, zipfile` dan `import xml.etree.ElementTree as ET` (sisakan import lama).

```python
# --- Reader mentah xlsx (tahan exporter non-standar tanpa <dimension>/styles) ---
def _xlsx_local(tag):
    return tag.rsplit("}", 1)[-1]

def _xlsx_col_idx(ref):
    m = re.match(r"([A-Z]+)", ref or "")
    if not m:
        return 0
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1

def _raw_xlsx_rows(path):
    """Baca xlsx via zip+xml langsung (abaikan styles.xml). -> list[list[str]]."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        sheet = "xl/worksheets/sheet1.xml"
        if sheet not in names:
            cand = sorted(n for n in names
                          if n.startswith("xl/worksheets/") and n.endswith(".xml"))
            sheet = cand[0] if cand else None
        sst = []
        if "xl/sharedStrings.xml" in names:
            for _, el in ET.iterparse(io.BytesIO(z.read("xl/sharedStrings.xml"))):
                if _xlsx_local(el.tag) == "si":
                    sst.append("".join(t.text or "" for t in el.iter()
                                       if _xlsx_local(t.tag) == "t"))
                    el.clear()
        rows = []
        for _, el in ET.iterparse(io.BytesIO(z.read(sheet))):
            if _xlsx_local(el.tag) != "row":
                continue
            cells, maxc = {}, 0
            for c in el:
                if _xlsx_local(c.tag) != "c":
                    continue
                idx = _xlsx_col_idx(c.attrib.get("r", "")); t = c.attrib.get("t", "")
                v, vt, ist = "", None, None
                for ch in c:
                    lt = _xlsx_local(ch.tag)
                    if lt == "v":
                        vt = ch.text
                    elif lt == "is":
                        ist = "".join(x.text or "" for x in ch.iter()
                                      if _xlsx_local(x.tag) == "t")
                if t == "s" and vt is not None:
                    try:
                        v = sst[int(vt)]
                    except (ValueError, IndexError):
                        v = vt
                elif t == "inlineStr" and ist is not None:
                    v = ist
                elif vt is not None:
                    v = vt
                cells[idx] = v; maxc = max(maxc, idx)
            rows.append([cells.get(i, "") for i in range(maxc + 1)])
            el.clear()
        return rows
```

Ubah `read_xlsx_rows` agar fallback ke reader mentah:

```python
def read_xlsx_rows(path, header_row=1, sheet=None):
    """Baca xlsx -> (headers, list_of_dict). header_row 1-based.
    Fallback ke reader mentah bila openpyxl gagal / hanya kebaca <= header_row baris
    (exporter non-standar tanpa <dimension>)."""
    grid = None
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        grid = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
    except Exception:
        grid = None
    if grid is None or len(grid) <= header_row:
        grid = _raw_xlsx_rows(path)
    headers, out = None, []
    for i, row in enumerate(grid, start=1):
        if i < header_row:
            continue
        if i == header_row:
            headers = [str(c).strip() if c is not None else "" for c in row]
            continue
        if row is None or all(c is None or c == "" for c in row):
            continue
        out.append({h: c for h, c in zip(headers, row) if h})
    return headers, (out or [])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python manage.py test sources.tests_xlsx_safe -v2`
Expected: PASS (2 tests).

- [ ] **Step 5: Run full suite (guard regresi reader)**

Run: `.venv/bin/python manage.py test sources -v1`
Expected: PASS (parser existing tetap jalan).

- [ ] **Step 6: Commit**

```bash
git add sources/parsers/base.py sources/tests_xlsx_safe.py
git commit -m "feat(sources): reader xlsx tahan-styles (fallback zip+xml) untuk exporter non-standar"
```

---

### Task 2: Helper `parse_bank_triplet`

**Files:**
- Modify: `sources/parsers/base.py`
- Test: `sources/tests_cor.py` (kelas `BankTripletTests`)

**Interfaces:**
- Produces: `parse_bank_triplet(value) -> (kode, norek, nama)` untuk string COR `"KODE - NOREK - NAMA"` (mis. `"BCA - 2941413058 - BAGAS"`). Toleran spasi & segmen kosong; `("", "", "")` bila kosong.

- [ ] **Step 1: Write the failing test**

```python
# sources/tests_cor.py
import os, tempfile
from django.test import SimpleTestCase
from openpyxl import Workbook
from sources.parsers.base import parse_bank_triplet

class BankTripletTests(SimpleTestCase):
    def test_triplet_bank(self):
        self.assertEqual(parse_bank_triplet("BCA - 2941413058 - BAGAS ARMANDO"),
                         ("BCA", "2941413058", "BAGAS ARMANDO"))

    def test_triplet_ewallet_dengan_slash_di_nama(self):
        self.assertEqual(
            parse_bank_triplet("OTH - 4840394374 - IGNATIUS IVAN / WITHDRAW BCA"),
            ("OTH", "4840394374", "IGNATIUS IVAN / WITHDRAW BCA"))

    def test_triplet_kosong(self):
        self.assertEqual(parse_bank_triplet(""), ("", "", ""))
        self.assertEqual(parse_bank_triplet(None), ("", "", ""))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python manage.py test sources.tests_cor.BankTripletTests -v2`
Expected: FAIL — `ImportError: cannot import name 'parse_bank_triplet'`.

- [ ] **Step 3: Add helper to `sources/parsers/base.py`**

```python
def parse_bank_triplet(value):
    """String COR "KODE - NOREK - NAMA" -> (kode, norek, nama). Nama boleh memuat
    ' - ' internal (mis. '.../ WITHDRAW BCA') -> hanya split 2 pemisah pertama."""
    s = str(value or "").strip()
    if not s:
        return "", "", ""
    parts = [p.strip() for p in s.split(" - ", 2)]
    while len(parts) < 3:
        parts.append("")
    return parts[0].upper(), parts[1], parts[2]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python manage.py test sources.tests_cor.BankTripletTests -v2`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add sources/parsers/base.py sources/tests_cor.py
git commit -m "feat(sources): helper parse_bank_triplet untuk format bank COR"
```

---

### Task 3: `CORPanelBankParser`

**Files:**
- Create: `sources/parsers/cor.py`
- Test: `sources/tests_cor.py` (kelas `CORPanelBankTests`)

**Interfaces:**
- Consumes: `read_xlsx_rows`, `parse_bank_triplet`, `parse_decimal`, `parse_dt`, `derive_bank_fields`, `row_hash` dari `base`.
- Produces: `CORPanelBankParser(BaseParser)` `source_key="panel"`; `flow` "dp"/"wd" menentukan jenis & sisi pemain/operator; `amount`=rupiah; set `raw["Player Bank"]`=`KODE|NAMA|NOREK` (sisi pemain) & `raw["Bank Title"]`=operator.

- [ ] **Step 1: Write the failing test**

```python
# tambahkan ke sources/tests_cor.py
from sources.parsers.cor import CORPanelBankParser

def _xlsx(rows):
    wb = Workbook(); ws = wb.active
    for r in rows:
        ws.append(r)
    fd, path = tempfile.mkstemp(suffix=".xlsx"); os.close(fd)
    wb.save(path)
    return path

class CORPanelBankTests(SimpleTestCase):
    HEADER = ["#", "Approved Date", "Requested Date", "Username", "From Bank",
              "Destination Bank", "Amount", "Status", "By"]

    def test_dp_rupiah_dan_bank_fields(self):
        path = _xlsx([
            self.HEADER,
            ["1", "01 Jul 2026 23:52:18", "01 Jul 2026 23:50:06", "febri72",
             "DANA - 081270670097 - FEBRIA MEGASARI",
             "BCA - 2941413058 - BAGAS ARMANDO", "200000", "approved", "gacor25sub59"],
        ])
        try:
            rows = CORPanelBankParser().parse(path, flow="dp")
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["jenis"], "depo")
        self.assertEqual(str(r["amount"]), "200000")        # RUPIAH, tanpa x1000
        self.assertEqual(str(r["money_delta"]), "200000")
        self.assertEqual(str(r["credit_delta"]), "-200000")
        self.assertEqual(r["counterparty"], "FEBRIA MEGASARI")   # pemain = From Bank
        self.assertEqual(r["player_bank"], "DANA")
        self.assertEqual(r["bank_title"], "BCA")                 # operator = Destination
        self.assertEqual(r["ticket_no"], "")
        self.assertIn("081270670097", r["raw"]["Player Bank"])   # utk phone-match

    def test_wd_membalik_sisi_dan_tanda(self):
        path = _xlsx([
            self.HEADER,
            ["1", "01 Jul 2026 23:57:08", "01 Jul 2026 23:56:43", "zhaa1234",
             "OTH - 4840394374 - IGNATIUS IVAN / WITHDRAW BCA",
             "DANA - 082112822248 - RUSMAN", "350000", "approved", "gacor25sub40"],
        ])
        try:
            rows = CORPanelBankParser().parse(path, flow="wd")
        finally:
            os.remove(path)
        r = rows[0]
        self.assertEqual(r["jenis"], "wd")
        self.assertEqual(str(r["money_delta"]), "-350000")
        self.assertEqual(str(r["credit_delta"]), "350000")
        self.assertEqual(r["counterparty"], "RUSMAN")            # pemain = Destination (WD)
        self.assertEqual(r["player_bank"], "DANA")

    def test_skip_non_approved(self):
        path = _xlsx([self.HEADER,
            ["1", "01 Jul 2026 00:00:00", "01 Jul 2026 00:00:00", "x",
             "BCA - 1 - A", "BCA - 2 - B", "1000", "pending", "op"]])
        try:
            self.assertEqual(CORPanelBankParser().parse(path, flow="dp"), [])
        finally:
            os.remove(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python manage.py test sources.tests_cor.CORPanelBankTests -v2`
Expected: FAIL — `ModuleNotFoundError: No module named 'sources.parsers.cor'`.

- [ ] **Step 3: Create `sources/parsers/cor.py`**

```python
"""Parser operator COR (Gacor25). Panel terpisah 2 rail (bank & QRIS) + gateway QRIS.

Nominal dalam RUPIAH penuh (JANGAN x1000). File dari exporter non-standar -> dibaca
lewat read_xlsx_rows yang sudah tahan-styles. Kolom bank format "KODE - NOREK - NAMA".
"""
from decimal import Decimal

from .base import (
    BaseParser,
    derive_bank_fields,
    parse_bank_triplet,
    parse_decimal,
    parse_dt,
    read_xlsx_rows,
    row_hash,
)


class CORPanelBankParser(BaseParser):
    source_key = "panel"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=1)
        is_wd = flow == "wd"
        out = []
        for r in rows:
            username = str(r.get("Username", "") or "").strip()
            if not username or str(r.get("Status", "") or "").strip().lower() != "approved":
                continue
            amt = parse_decimal(r.get("Amount"))
            if is_wd:
                jenis, credit_delta, money_delta = "wd", amt, -amt
                player_raw, oper_raw = r.get("Destination Bank"), r.get("From Bank")
            else:
                jenis, credit_delta, money_delta = "depo", -amt, amt
                player_raw, oper_raw = r.get("From Bank"), r.get("Destination Bank")
            pk_code, pk_acct, pk_name = parse_bank_triplet(player_raw)
            op_code, op_acct, op_name = parse_bank_triplet(oper_raw)
            occurred = parse_dt(r.get("Requested Date"))
            posted = parse_dt(r.get("Approved Date"))
            raw = {k: ("" if v is None else str(v)) for k, v in r.items()}
            raw["Player Bank"] = f"{pk_code}|{pk_name}|{pk_acct}"
            raw["Bank Title"] = f"{op_code}|{op_name}|{op_acct}"
            player_bank, bank_title = derive_bank_fields("panel", raw)
            row = {
                "source_type": "panel",
                "occurred_at": occurred,
                "posted_date": posted.date() if posted else None,
                "jenis": jenis,
                "amount": amt,
                "credit_delta": credit_delta,
                "money_delta": money_delta,
                "fee": Decimal("0"),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": "",
                "username": username,
                "reference": "",
                "counterparty": pk_name,
                "description": f"{op_code} {op_name}".strip(),
                "player_bank": player_bank,
                "bank_title": bank_title,
                "raw": raw,
            }
            row["row_hash"] = row_hash("cor_panel_bank",
                                       [username, amt, occurred, pk_acct])
            out.append(row)
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python manage.py test sources.tests_cor.CORPanelBankTests -v2`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add sources/parsers/cor.py sources/tests_cor.py
git commit -m "feat(sources): parser cor_panel_bank (rail bank COR, rupiah, KODE-NOREK-NAMA)"
```

---

### Task 4: `CORPanelQRISParser`

**Files:**
- Modify: `sources/parsers/cor.py`
- Test: `sources/tests_cor.py` (kelas `CORPanelQRISTests`)

**Interfaces:**
- Produces: `CORPanelQRISParser(BaseParser)` `source_key="panel"`; **`reference=Transaction ID` (UUID)** = kunci exact ke gateway; `amount`=rupiah; filter `Status=success`.

- [ ] **Step 1: Write the failing test**

```python
# tambahkan ke sources/tests_cor.py
from sources.parsers.cor import CORPanelQRISParser

class CORPanelQRISTests(SimpleTestCase):
    HEADER = ["#", "Approved Date", "Requested Date", "Username",
              "Transaction ID", "Amount", "Bonus", "Status"]

    def test_dp_reference_uuid(self):
        path = _xlsx([
            self.HEADER,
            ["1", "01 Jul 2026 23:59:56", "01 Jul 2026 23:59:19", "zidanhoki11",
             "03f747e8-ac9c-48e0-a", "85000", "", "success"],
        ])
        try:
            rows = CORPanelQRISParser().parse(path, flow="dp")
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["jenis"], "depo")
        self.assertEqual(str(r["amount"]), "85000")
        self.assertEqual(r["reference"], "03f747e8-ac9c-48e0-a")   # kunci exact
        self.assertEqual(r["ticket_no"], "")
        self.assertEqual(r["username"], "zidanhoki11")

    def test_skip_tanpa_txid(self):
        path = _xlsx([self.HEADER,
            ["1", "x", "x", "user", "", "1000", "", "success"]])
        try:
            self.assertEqual(CORPanelQRISParser().parse(path, flow="dp"), [])
        finally:
            os.remove(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python manage.py test sources.tests_cor.CORPanelQRISTests -v2`
Expected: FAIL — `ImportError: cannot import name 'CORPanelQRISParser'`.

- [ ] **Step 3: Add parser to `sources/parsers/cor.py`**

```python
class CORPanelQRISParser(BaseParser):
    source_key = "panel"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=1)
        is_wd = flow == "wd"
        out = []
        for r in rows:
            username = str(r.get("Username", "") or "").strip()
            txid = str(r.get("Transaction ID", "") or "").strip()
            status = str(r.get("Status", "") or "").strip().lower()
            if not txid or not username or status not in ("success", ""):
                continue
            amt = parse_decimal(r.get("Amount"))
            raw = {k: ("" if v is None else str(v)) for k, v in r.items()}
            if is_wd:
                jenis, credit_delta, money_delta = "wd", amt, -amt
                pk_code, pk_acct, pk_name = parse_bank_triplet(r.get("Destination Bank"))
                raw["Player Bank"] = f"{pk_code}|{pk_name}|{pk_acct}"
                counterparty = pk_name
            else:
                jenis, credit_delta, money_delta = "depo", -amt, amt
                counterparty = ""
            occurred = parse_dt(r.get("Requested Date"))
            posted = parse_dt(r.get("Approved Date"))
            player_bank, bank_title = derive_bank_fields("panel", raw)
            row = {
                "source_type": "panel",
                "occurred_at": occurred,
                "posted_date": posted.date() if posted else None,
                "jenis": jenis,
                "amount": amt,
                "credit_delta": credit_delta,
                "money_delta": money_delta,
                "fee": Decimal("0"),
                "bonus": parse_decimal(r.get("Bonus")),
                "balance_after": None,
                "ticket_no": "",
                "username": username,
                "reference": txid,
                "counterparty": counterparty,
                "description": f"QRIS {txid}".strip(),
                "player_bank": player_bank,
                "bank_title": bank_title,
                "raw": raw,
            }
            row["row_hash"] = row_hash("cor_panel_qris", [txid, username, amt])
            out.append(row)
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python manage.py test sources.tests_cor.CORPanelQRISTests -v2`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add sources/parsers/cor.py sources/tests_cor.py
git commit -m "feat(sources): parser cor_panel_qris (reference=UUID untuk match exact)"
```

---

### Task 5: `CORQRISGatewayParser`

**Files:**
- Modify: `sources/parsers/cor.py`
- Test: `sources/tests_cor.py` (kelas `CORQRISGatewayTests`)

**Interfaces:**
- Produces: `CORQRISGatewayParser(BaseParser)` `source_key="gateway"`; **`reference=OrderId`** (UUID) = kunci exact ke `cor_panel_qris`; `amount=GrandTotal` (gross), `fee=GrandTotal-BranchNominal`; hanya DEPOSIT.

- [ ] **Step 1: Write the failing test**

```python
# tambahkan ke sources/tests_cor.py
from sources.parsers.cor import CORQRISGatewayParser

class CORQRISGatewayTests(SimpleTestCase):
    HEADER = ["BranchName", "GrandTotal", "BranchNominal", "OrderId",
              "TransactionTime", "RRN", "IssuerName", "CustomerName",
              "Channel", "Order Id Merchant"]

    def test_gateway_reference_gross_fee(self):
        path = _xlsx([
            self.HEADER,
            ["QRIS-7-Beta-TMG3", "85000", "83980", "03f747e8-ac9c-48e0-a",
             "01-Jul-2026 23:59:56", "1pysbjp67783", "-", "-", "Channel 7",
             "03f747e8-ac9c-48e0-a"],
        ])
        try:
            rows = CORQRISGatewayParser().parse(path, flow="dp")
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["source_type"], "gateway")
        self.assertEqual(r["jenis"], "depo")
        self.assertEqual(str(r["amount"]), "85000")          # gross
        self.assertEqual(str(r["money_delta"]), "85000")
        self.assertEqual(str(r["fee"]), "1020")              # 85000 - 83980
        self.assertEqual(r["reference"], "03f747e8-ac9c-48e0-a")
        self.assertEqual(r["ticket_no"], "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python manage.py test sources.tests_cor.CORQRISGatewayTests -v2`
Expected: FAIL — `ImportError: cannot import name 'CORQRISGatewayParser'`.

- [ ] **Step 3: Add parser to `sources/parsers/cor.py`**

```python
class CORQRISGatewayParser(BaseParser):
    source_key = "gateway"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=1)
        out = []
        for r in rows:
            order = str(r.get("OrderId", "") or "").strip()
            if not order:
                continue
            gross = parse_decimal(r.get("GrandTotal"))
            net = parse_decimal(r.get("BranchNominal"))
            occurred = parse_dt(r.get("TransactionTime"))
            money_delta = -gross if flow == "wd" else gross
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "wd" if flow == "wd" else "depo",
                "amount": gross,
                "credit_delta": Decimal("0"),
                "money_delta": money_delta,
                "fee": gross - net,
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": "",
                "username": "",
                "reference": order,
                "counterparty": "",
                "description": f"QRIS COR {r.get('RRN','')}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items()},
            }
            row["row_hash"] = row_hash("cor_qris_gw", [order, gross])
            out.append(row)
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python manage.py test sources.tests_cor.CORQRISGatewayTests -v2`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add sources/parsers/cor.py sources/tests_cor.py
git commit -m "feat(sources): parser cor_qris_gateway (reference=OrderId, gross vs net)"
```

---

### Task 6: `QHokiParser` (QRIS HOKI — gateway MUL)

**Files:**
- Modify: `sources/parsers/gateways.py`
- Test: `sources/tests_qhoki.py`

**Interfaces:**
- Produces: `QHokiParser(BaseParser)` `source_key="gateway"`; **`ticket_no=Whitelabel Transaction ID`** (D…, cocok via pass 0) + **`reference=Transaction ID`** (UUID, cocok via reference-join); `amount=Amount` gross, `fee=Downline Fee Amount`; filter `Status=Success`.

- [ ] **Step 1: Write the failing test**

```python
# sources/tests_qhoki.py
import os, tempfile
from django.test import SimpleTestCase
from openpyxl import Workbook
from sources.parsers.gateways import QHokiParser

def _xlsx(rows):
    wb = Workbook(); ws = wb.active
    for r in rows:
        ws.append(r)
    fd, path = tempfile.mkstemp(suffix=".xlsx"); os.close(fd)
    wb.save(path)
    return path

HEADER = ["Transaction Date", "Paid Date", "Finished Date", "Settlement Date",
          "Settled At", "Member ID", "Rrn", "NMID", "Transaction ID",
          "Whitelabel Transaction ID", "Status", "Amount", "Downline Fee Amount",
          "Total Amount", "Memo", "Payment Method"]

class QHokiTests(SimpleTestCase):
    def test_ticket_dan_reference(self):
        path = _xlsx([
            HEADER,
            ["2026-07-03 23:59:23", "2026-07-03 23:59:49", "2026-07-03 23:59:51",
             "2026-07-04 08:00:00", "2026-07-04 08:01:55", "Politiku",
             "1q10a0v18001", "", "019f28eb-b15f-7ee2-83ea-ad5cddc9a287", "D6179892",
             "Success", "50000", "650", "49350", "", "qris"],
        ])
        try:
            rows = QHokiParser().parse(path, flow="dp")
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["source_type"], "gateway")
        self.assertEqual(r["ticket_no"], "D6179892")                      # pass 0
        self.assertEqual(r["reference"], "019f28eb-b15f-7ee2-83ea-ad5cddc9a287")  # ref-join
        self.assertEqual(str(r["amount"]), "50000")
        self.assertEqual(str(r["fee"]), "650")
        self.assertEqual(r["username"], "Politiku")

    def test_skip_non_success(self):
        path = _xlsx([HEADER,
            ["2026-07-03 00:00:00", "", "", "", "", "u", "r", "", "uuid", "D1",
             "Pending", "1000", "0", "1000", "", "qris"]])
        try:
            self.assertEqual(QHokiParser().parse(path, flow="dp"), [])
        finally:
            os.remove(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python manage.py test sources.tests_qhoki -v2`
Expected: FAIL — `ImportError: cannot import name 'QHokiParser'`.

- [ ] **Step 3: Add `QHokiParser` to `sources/parsers/gateways.py`**

```python
class QHokiParser(BaseParser):
    """QRIS HOKI (gateway MUL). Whitelabel Transaction ID = Ticket Panel (D...),
    Transaction ID = UUID (juga muncul di Remarks panel)."""

    source_key = "gateway"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=1)
        out = []
        for r in rows:
            if str(r.get("Status", "") or "").strip().lower() != "success":
                continue
            wl = str(r.get("Whitelabel Transaction ID", "") or "").strip()
            txid = str(r.get("Transaction ID", "") or "").strip()
            amt = abs(parse_decimal(r.get("Amount")))
            occurred = parse_dt(r.get("Transaction Date"))
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "wd" if flow == "wd" else "depo",
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": _money(amt, flow),
                "fee": parse_decimal(r.get("Downline Fee Amount")),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": wl,
                "username": str(r.get("Member ID", "") or "").strip(),
                "reference": txid,
                "counterparty": "",
                "description": f"QHOKI {r.get('Rrn','')}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items()},
            }
            row["row_hash"] = row_hash("qhoki", [txid, wl, amt])
            out.append(row)
        return out
```

Pastikan import di puncak `gateways.py` menyertakan `read_xlsx_rows`:
`from .base import BaseParser, parse_decimal, parse_dt, read_xlsx_rows, row_hash`

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python manage.py test sources.tests_qhoki -v2`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add sources/parsers/gateways.py sources/tests_qhoki.py
git commit -m "feat(sources): parser qhoki (QRIS HOKI gateway MUL, ticket=Whitelabel + ref=UUID)"
```

---

### Task 7: Registrasi parser + isi `player_bank`/`bank_title` saat ingest

**Files:**
- Modify: `sources/services.py`
- Test: `sources/tests_cor.py` (kelas `IngestBankFieldsTests`)

**Interfaces:**
- Consumes: parser dari Task 3–6.
- Produces: `PARSERS` bertambah `cor_panel_bank`, `cor_panel_qris`, `cor_qris_gateway`, `qhoki`. `ingest()` mengisi `Transaction.player_bank`/`bank_title` dari `row.get(...)` (sebelumnya hanya di-backfill migrasi).

- [ ] **Step 1: Write the failing test**

```python
# tambahkan ke sources/tests_cor.py
from django.test import TestCase
from sources import services
from transactions.models import Transaction

class IngestBankFieldsTests(TestCase):
    def test_ingest_panel_mengisi_player_bank(self):
        path = _xlsx([
            CORPanelBankTests.HEADER,
            ["1", "01 Jul 2026 23:52:18", "01 Jul 2026 23:50:06", "febri72",
             "DANA - 081270670097 - FEBRIA MEGASARI",
             "BCA - 2941413058 - BAGAS ARMANDO", "200000", "approved", "gacor25sub59"],
        ])
        try:
            services.ingest("cor_panel_bank", path, flow="dp")
        finally:
            os.remove(path)
        t = Transaction.objects.get()
        self.assertEqual(t.player_bank, "DANA")
        self.assertEqual(t.bank_title, "BCA")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python manage.py test sources.tests_cor.IngestBankFieldsTests -v2`
Expected: FAIL — `ValueError: Parser 'cor_panel_bank' tidak dikenal` (atau `player_bank` kosong).

- [ ] **Step 3: Register parsers + wire bank fields in `sources/services.py`**

Tambah import:
```python
from .parsers.cor import CORPanelBankParser, CORPanelQRISParser, CORQRISGatewayParser
from .parsers.gateways import NXPayParser, QRFlyerParser, QHokiParser
```
Tambah ke dict `PARSERS`:
```python
    "cor_panel_bank": CORPanelBankParser,
    "cor_panel_qris": CORPanelQRISParser,
    "cor_qris_gateway": CORQRISGatewayParser,
    "qhoki": QHokiParser,
```
Di blok `Transaction(...)` dalam `ingest()`, tambah dua field (parser bank/gateway tak menyertakan key ini → `row.get` aman):
```python
                    player_bank=row.get("player_bank", ""),
                    bank_title=row.get("bank_title", ""),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python manage.py test sources.tests_cor.IngestBankFieldsTests -v2`
Expected: PASS.

- [ ] **Step 5: Run sources suite (guard)**

Run: `.venv/bin/python manage.py test sources -v1`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sources/services.py sources/tests_cor.py
git commit -m "feat(sources): daftar 4 parser baru + isi player_bank/bank_title saat ingest"
```

---

### Task 8: Auto-deteksi 4 format baru + token tahan-styles

**Files:**
- Modify: `sources/detect.py`
- Test: `sources/tests_detect.py`

**Interfaces:**
- Produces: `detect_source` mengenali `cor_panel_bank`, `cor_panel_qris`, `cor_qris_gateway`, `qhoki`; `_xlsx_tokens` fallback ke reader mentah (file COR).

- [ ] **Step 1: Write the failing test**

Lihat pola pembuatan xlsx di `sources/tests_detect.py` (fungsi `_xlsx`/`openpyxl.Workbook`). Tambah kelas:

```python
# tambahkan ke sources/tests_detect.py
from sources.detect import detect_source

class DetectMultiBrandTests(TestCase):   # gunakan base TestCase yang sudah ada di file
    def _mk(self, header, name):
        path = _xlsx([header, ["x"] * len(header)])   # _xlsx helper existing di file
        return path, name

    def test_deteksi_cor_qris_gateway(self):
        path = _xlsx([["BranchName", "GrandTotal", "BranchNominal", "OrderId",
                       "TransactionTime", "RRN"], ["a", "1", "1", "u", "t", "r"]])
        try:
            keys = [d["parser_key"] for d in detect_source(path, "01 DP_QRIS_TRANSACTION.xlsx")]
        finally:
            os.remove(path)
        self.assertEqual(keys[0], "cor_qris_gateway")

    def test_deteksi_qhoki(self):
        path = _xlsx([["Member ID", "Whitelabel Transaction ID", "NMID",
                       "Transaction ID", "Status", "Amount"], ["m", "D1", "", "u", "Success", "1"]])
        try:
            keys = [d["parser_key"] for d in detect_source(path, "DP QH MUL.xlsx")]
        finally:
            os.remove(path)
        self.assertIn("qhoki", keys)

    def test_deteksi_cor_panel_bank(self):
        path = _xlsx([["Approved Date", "Requested Date", "Username", "From Bank",
                       "Destination Bank", "Amount", "Status"], ["a"] * 7])
        try:
            keys = [d["parser_key"] for d in detect_source(path, "BANK_approved_deposit.xlsx")]
        finally:
            os.remove(path)
        self.assertIn("cor_panel_bank", keys)
```

(Jika `_xlsx`/`os` belum di-import di `tests_detect.py`, tambahkan sesuai pola file itu.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python manage.py test sources.tests_detect.DetectMultiBrandTests -v2`
Expected: FAIL (key tak dikenal).

- [ ] **Step 3: Update `sources/detect.py`**

Ganti isi `_xlsx_tokens` agar fallback ke reader mentah:
```python
def _xlsx_tokens(path, max_rows=3):
    from .parsers.base import _raw_xlsx_rows
    toks = set()
    grid = None
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        grid = [list(r) for _, r in zip(range(max_rows), ws.iter_rows(values_only=True))]
        wb.close()
    except Exception:
        grid = None
    if not grid:
        try:
            grid = _raw_xlsx_rows(path)[:max_rows]
        except Exception:
            grid = []
    for row in grid:
        for c in row:
            if c is not None and c != "":
                toks.add(str(c).strip().lower())
    return toks
```

Tambah signature di blok `if ext in (".xlsx", ".xls"):` (setelah signature existing):
```python
        if _has(t, "orderid") and _has(t, "grandtotal") and _has(t, "branchnominal"):
            add("cor_qris_gateway", 0.95)
        if _has(t, "whitelabel transaction id") and _has(t, "nmid"):
            add("qhoki", 0.95)
        if _has(t, "from bank") and _has(t, "destination bank") and _has(t, "approved date"):
            add("cor_panel_bank", 0.95)
        if _has(t, "transaction id") and _has(t, "amount") and _has(t, "bonus") \
                and not _has(t, "kategori"):
            add("cor_panel_qris", 0.90)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python manage.py test sources.tests_detect -v2`
Expected: PASS (termasuk test existing).

- [ ] **Step 5: Commit**

```bash
git add sources/detect.py sources/tests_detect.py
git commit -m "feat(sources): auto-deteksi 4 format baru + token xlsx tahan-styles"
```

---

### Task 9: Engine — reference-join pass (gateway-only)

**Files:**
- Modify: `reconciliation/engine.py` (`_MoneyMatcher.match`)
- Test: `reconciliation/tests_reference_join.py`

**Interfaces:**
- Consumes: `Transaction.reference` di sisi panel (kredit) & gateway (uang).
- Produces: pass 0b — panel `reference` == gateway `reference` (non-kosong, arah uang sama): nominal sama → `cocok` reason `"reference"`; beda → `perlu_tinjau` reason `"reference_amount"`. Gateway ber-reference asing (tak dikenal panel) diblok dari fuzzy (muncul `no_panel`), simetris ticket-join.

- [ ] **Step 1: Write the failing test**

```python
# reconciliation/tests_reference_join.py
from datetime import datetime
from decimal import Decimal
from django.test import TestCase
from reconciliation.engine import run_match
from reconciliation.models import MatchResult, MatchRun, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

D = Decimal

def _st(key):
    return SourceType.objects.get_or_create(key=key, defaults={"name": key.title()})[0]

class ReferenceJoinTests(TestCase):
    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1})[0]
        self.toko = Toko.objects.get(key="g25")
        self.panel, self.gw = _st("panel"), _st("gateway")
        self.up_p = Upload.objects.create(source_type=self.panel, toko=self.toko,
                                           original_name="QRIS_deposit.xlsx")
        self.up_g = Upload.objects.create(source_type=self.gw, toko=self.toko,
                                          original_name="DP_QRIS_TRANSACTION.xlsx")
        self._n = 0

    def tx(self, st, up, amount, md, dt, *, ref="", ticket=""):
        self._n += 1
        return Transaction.objects.create(
            upload=up, source_type=st, toko=self.toko, jenis="depo",
            amount=D(amount), money_delta=D(md), occurred_at=dt,
            reference=ref, ticket_no=ticket, row_hash=f"h{self._n}")

    def test_reference_sama_nominal_sama_cocok(self):
        p = self.tx(self.panel, self.up_p, "85000", "85000",
                    datetime(2026, 7, 1, 23, 59), ref="03f747e8-ac9c-48e0-a")
        g = self.tx(self.gw, self.up_g, "85000", "85000",
                    datetime(2026, 7, 1, 23, 59), ref="03f747e8-ac9c-48e0-a")
        run = run_match(MatchRun.Relation.PANEL_BANK, self.tol, toko=self.toko)
        r = MatchResult.objects.get(left=p)
        self.assertEqual(r.right_id, g.id)
        self.assertEqual(r.bucket, MatchResult.Bucket.COCOK)
        self.assertEqual(r.reason_code, "reference")

    def test_reference_asing_tidak_fuzzy(self):
        # gateway ref tak dikenal panel + nominal sama → JANGAN direbut fuzzy.
        p = self.tx(self.panel, self.up_p, "50000", "50000",
                    datetime(2026, 7, 1, 10), ref="known-uuid")
        g = self.tx(self.gw, self.up_g, "50000", "50000",
                    datetime(2026, 7, 1, 10), ref="ASING-uuid")
        run_match(MatchRun.Relation.PANEL_BANK, self.tol, toko=self.toko)
        r = MatchResult.objects.get(left=p)
        self.assertIsNone(r.right_id)   # p tak dapat uang (ref beda), g diblok fuzzy
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python manage.py test reconciliation.tests_reference_join -v2`
Expected: FAIL — `reason_code` bukan `"reference"` (pass belum ada; kemungkinan fuzzy/no_money).

- [ ] **Step 3: Edit `reconciliation/engine.py` — `_MoneyMatcher.match`**

Di loop bangun index (tempat `gw_ticket` diisi), tambah `gw_ref`:
```python
        gw_ref = defaultdict(list)
```
lalu di dalam `for b in right:` (samping `if b.source_type.key == "gateway" and b.ticket_no:`):
```python
            if b.source_type.key == "gateway" and b.reference:
                gw_ref[b.reference].append(b)
```
Setelah `panel_tickets = {...}`, tambah:
```python
        panel_refs = {p.reference for p in left if p.reference}
```
Sisipkan **pass 0b** tepat SETELAH loop pass 0 (`# --- pass 0 ...`) dan SEBELUM baris `blocked = {`:
```python
        # --- pass 0b: reference-join gateway (kunci pasti non-ticket, mis. UUID QRIS) ---
        for p in left:
            if p.id in matched or not p.reference:
                continue
            for b in gw_ref.get(p.reference, []):
                if b.id in used or (p.money_delta > 0) != (b.money_delta > 0):
                    continue
                diff = abs(int(abs(p.money_delta)) - int(abs(b.money_delta)))
                if diff == 0:
                    emit(p, b, MatchResult.Bucket.COCOK, 100, "reference")
                else:
                    emit(p, b, MatchResult.Bucket.TINJAU, 90, "reference_amount",
                         f"reference sama, selisih nominal {diff:,}")
                break
```
Perluas `blocked` (gabung foreign-ref):
```python
        blocked = {
            b.id for t, lst in gw_ticket.items() if t not in panel_tickets for b in lst
        } | {
            b.id for ref, lst in gw_ref.items() if ref not in panel_refs for b in lst
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python manage.py test reconciliation.tests_reference_join -v2`
Expected: PASS (2 tests).

- [ ] **Step 5: Run reconciliation suite (guard)**

Run: `.venv/bin/python manage.py test reconciliation -v1`
Expected: PASS (matcher lama tak berubah perilaku).

- [ ] **Step 6: Commit**

```bash
git add reconciliation/engine.py reconciliation/tests_reference_join.py
git commit -m "feat(engine): reference-join pass (Panel.reference <-> Gateway.reference exact)"
```

---

### Task 10: Engine — PanelBracket lewati panel tanpa ticket + gate PANEL_BRACKET

**Files:**
- Modify: `reconciliation/engine.py` (`PanelBracketMatcher.match`, `run_batch`)
- Test: `reconciliation/tests_bracket_cor.py` (kelas `PanelBracketTicketlessTests`)

**Interfaces:**
- Produces: `PanelBracketMatcher` skip baris panel `ticket_no==""` (tak emit `no_bracket`). `run_batch` hanya menambah relasi `PANEL_BRACKET` bila ADA baris panel aktif ber-ticket (COR tanpa ticket → relasi di-skip, tak ada run kosong / warning palsu).

- [ ] **Step 1: Write the failing test**

```python
# reconciliation/tests_bracket_cor.py
from datetime import date, datetime
from decimal import Decimal
from django.test import TestCase
from reconciliation.engine import run_batch, run_match
from reconciliation.models import MatchResult, MatchRun, ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

D = Decimal

def _st(key):
    return SourceType.objects.get_or_create(key=key, defaults={"name": key.title()})[0]

class PanelBracketTicketlessTests(TestCase):
    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1})[0]
        self.toko = Toko.objects.get(key="g25")
        self.panel, self.bracket = _st("panel"), _st("bracket")
        self.up_p = Upload.objects.create(source_type=self.panel, toko=self.toko,
                                          original_name="QRIS_deposit.xlsx")
        self.up_b = Upload.objects.create(source_type=self.bracket, toko=self.toko,
                                          original_name="Finance Report.xlsx")
        self._n = 0

    def tx(self, st, up, amount, dt, *, ticket=""):
        self._n += 1
        md = D(amount)
        return Transaction.objects.create(
            upload=up, source_type=st, toko=self.toko, jenis="depo",
            amount=D(amount), money_delta=md, occurred_at=dt,
            ticket_no=ticket, row_hash=f"h{self._n}")

    def test_panel_tanpa_ticket_tak_emit_no_bracket(self):
        p = self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10))  # no ticket
        run = run_match(MatchRun.Relation.PANEL_BRACKET, self.tol, toko=self.toko)
        self.assertFalse(MatchResult.objects.filter(left=p).exists())

    def test_run_batch_skip_panel_bracket_bila_tak_ada_ticket(self):
        self.tx(self.panel, self.up_p, "85000", datetime(2026, 7, 1, 10))       # panel COR
        self.tx(self.bracket, self.up_b, "85000", datetime(2026, 7, 1, 10))     # bracket COR (no ticket)
        batch = run_batch(self.toko, self.tol, date_from=date(2026, 7, 1),
                          date_to=date(2026, 7, 1), recon_date=date(2026, 7, 1))
        rels = [r.relation for r in batch.runs.all()]
        self.assertNotIn(MatchRun.Relation.PANEL_BRACKET, rels)
        self.assertIn(MatchRun.Relation.PANEL_BRACKET.value, batch.summary["skipped"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python manage.py test reconciliation.tests_bracket_cor.PanelBracketTicketlessTests -v2`
Expected: FAIL — `no_bracket` ter-emit / relasi tidak di-skip.

- [ ] **Step 3: Edit `reconciliation/engine.py`**

Di `PanelBracketMatcher.match`, di awal `for p in left:`, tambah:
```python
        for p in left:
            if not p.ticket_no:   # baris tanpa ticket dinilai money-matcher, bukan bracket
                continue
```
Di `run_batch`, ganti kondisi PANEL_BRACKET agar syaratkan panel ber-ticket:
```python
    panel_has_ticket = _active(
        _toko_filter(Transaction.objects.filter(
            source_type__key="panel", is_duplicate=False), toko)
    ).exclude(ticket_no="").exists()
    if comp["bracket"] and _inc(include, "bracket") and panel_has_ticket:
        relations.append(MatchRun.Relation.PANEL_BRACKET)
    else:
        skipped.append(MatchRun.Relation.PANEL_BRACKET.value)
```
(gantikan blok `if comp["bracket"] and _inc(include, "bracket"):` yang lama.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python manage.py test reconciliation.tests_bracket_cor.PanelBracketTicketlessTests -v2`
Expected: PASS (2 tests).

- [ ] **Step 5: Guard suite**

Run: `.venv/bin/python manage.py test reconciliation -v1`
Expected: PASS (MUL/MXW panel selalu ber-ticket → tak terpengaruh).

- [ ] **Step 6: Commit**

```bash
git add reconciliation/engine.py reconciliation/tests_bracket_cor.py
git commit -m "feat(engine): PanelBracket skip panel tanpa ticket + gate relasi untuk COR"
```

---

### Task 11: Engine — warning agregat Panel↔Bracket (COR)

**Files:**
- Modify: `reconciliation/engine.py` (`_aggregate_batch` + helper baru)
- Test: `reconciliation/tests_bracket_cor.py` (kelas `PanelBracketAggregateTests`)

**Interfaces:**
- Produces: `_panel_bracket_total_warning(toko, date_from, date_to, include) -> str|None` — bandingkan Σ panel depo.amount vs Σ bracket depo.amount (& wd) aktif; kembalikan string warning bila selisih relatif > 2% dan kedua sisi > 0. Dipanggil di `_aggregate_batch`, hasil masuk `summary["warnings"]`.

- [ ] **Step 1: Write the failing test**

```python
# tambahkan ke reconciliation/tests_bracket_cor.py
class PanelBracketAggregateTests(TestCase):
    def setUp(self):
        self.tol = ToleranceProfile.objects.get_or_create(
            name="Default", defaults={"date_window_days": 1})[0]
        self.toko = Toko.objects.get(key="g25")
        self.panel, self.bracket = _st("panel"), _st("bracket")
        self.up_p = Upload.objects.create(source_type=self.panel, toko=self.toko,
                                          original_name="QRIS_deposit.xlsx")
        self.up_b = Upload.objects.create(source_type=self.bracket, toko=self.toko,
                                          original_name="Finance Report.xlsx")
        self._n = 0

    def tx(self, st, up, amount):
        self._n += 1
        return Transaction.objects.create(
            upload=up, source_type=st, toko=self.toko, jenis="depo",
            amount=Decimal(amount), money_delta=Decimal(amount),
            occurred_at=datetime(2026, 7, 1, 10), row_hash=f"a{self._n}")

    def test_warning_muncul_saat_total_beda(self):
        self.tx(self.panel, self.up_p, "100000")
        self.tx(self.bracket, self.up_b, "150000")   # beda 50% dari panel
        batch = run_batch(self.toko, self.tol, date_from=date(2026, 7, 1),
                          date_to=date(2026, 7, 1), recon_date=date(2026, 7, 1))
        joined = " ".join(batch.summary.get("warnings", []))
        self.assertIn("Panel↔Bracket", joined)

    def test_tak_ada_warning_saat_total_sama(self):
        self.tx(self.panel, self.up_p, "100000")
        self.tx(self.bracket, self.up_b, "100000")
        batch = run_batch(self.toko, self.tol, date_from=date(2026, 7, 1),
                          date_to=date(2026, 7, 1), recon_date=date(2026, 7, 1))
        joined = " ".join(batch.summary.get("warnings", []))
        self.assertNotIn("Panel↔Bracket", joined)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python manage.py test reconciliation.tests_bracket_cor.PanelBracketAggregateTests -v2`
Expected: FAIL — warning tak ada.

- [ ] **Step 3: Edit `reconciliation/engine.py`**

Tambah helper (dekat `_bracket_overlap_warning`):
```python
def _panel_bracket_total_warning(toko, date_from, date_to, include):
    """Cross-check AGREGAT Panel vs Bracket per arah (untuk toko tanpa join ticket,
    mis. COR): bila total DP/WD beda > 2% padahal kedua sisi ada, beri peringatan."""
    if not _inc(include, "bracket"):
        return None
    base = _date_filter(_active(_toko_filter(
        Transaction.objects.filter(is_duplicate=False), toko)), date_from, date_to)

    def tot(key, jenis):
        return float(base.filter(source_type__key=key, jenis=jenis)
                     .aggregate(x=Sum("amount"))["x"] or 0)

    for flow, jenis in (("DP", "depo"), ("WD", "wd")):
        p, b = tot("panel", jenis), tot("bracket", jenis)
        if p > 0 and b > 0 and abs(p - b) / max(p, b) > 0.02:
            return (f"Panel↔Bracket {flow} total beda: Panel {p:,.0f} vs "
                    f"Bracket {b:,.0f} (selisih {abs(p - b):,.0f}). Cek kelengkapan file.")
    return None
```
Di `_aggregate_batch`, setelah `w = _bracket_overlap_warning(runs)` block, tambah:
```python
    w2 = _panel_bracket_total_warning(toko, date_from, date_to, include)
    if w2:
        warnings.append(w2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python manage.py test reconciliation.tests_bracket_cor.PanelBracketAggregateTests -v2`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add reconciliation/engine.py reconciliation/tests_bracket_cor.py
git commit -m "feat(engine): warning agregat Panel<->Bracket total (cross-check COR)"
```

---

### Task 12: Harness validasi Fase 0 (`validate_brands`) + onboarding

**Files:**
- Create: `reconciliation/management/commands/validate_brands.py`
- Test: `reconciliation/tests_validate_brands.py`

**Interfaces:**
- Produces: command `validate_brands --dir <folder> --toko <key> [--flow-from-name]` yang ingest semua file di folder (auto-detect), jalankan `run_batches_auto`, lalu cetak laporan match-rate per bucket + persen `cocok`. Dipakai MANUAL utk membuktikan angka pada file nyata sebelum integrasi UI.

- [ ] **Step 1: Write the failing test**

```python
# reconciliation/tests_validate_brands.py
from io import StringIO
from django.core.management import call_command
from django.test import TestCase

class ValidateBrandsCommandTests(TestCase):
    def test_command_ada_dan_butuh_dir(self):
        out = StringIO()
        # tanpa --dir → command harus error argumen (bukan crash import)
        with self.assertRaises(SystemExit):
            call_command("validate_brands", stderr=out)

    def test_report_format_helper(self):
        from reconciliation.management.commands.validate_brands import format_rate
        self.assertEqual(format_rate(95, 100), "95/100 (95.0%)")
        self.assertEqual(format_rate(0, 0), "0/0 (n/a)")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python manage.py test reconciliation.tests_validate_brands -v2`
Expected: FAIL — command/`format_rate` belum ada.

- [ ] **Step 3: Create `reconciliation/management/commands/validate_brands.py`**

```python
"""Fase 0 — buktikan match-rate pada file nyata SEBELUM integrasi UI.

Contoh:
  python manage.py validate_brands --dir "~/Downloads/Telegram Desktop/COR/01" --toko g25 --flow-from-name
"""
import os
from django.core.management.base import BaseCommand

from reconciliation.engine import run_batches_auto
from reconciliation.models import MatchResult
from sources import services
from sources.detect import detect_source
from sources.models import Toko


def format_rate(n, d):
    return f"{n}/{d} ({100 * n / d:.1f}%)" if d else f"{n}/0 (n/a)"


def _flow(name):
    low = name.lower()
    if "withdraw" in low or "_wd" in low or " wd" in low or low.startswith("wd"):
        return "wd"
    if "deposit" in low or "_dp" in low or " dp" in low or low.startswith("dp"):
        return "dp"
    return ""


class Command(BaseCommand):
    help = "Ingest folder + rekonsiliasi otomatis + laporan match-rate (Fase 0)."

    def add_arguments(self, parser):
        parser.add_argument("--dir", required=True)
        parser.add_argument("--toko", required=True)
        parser.add_argument("--flow-from-name", action="store_true")

    def handle(self, *args, **opts):
        toko = Toko.objects.get(key=opts["toko"])
        folder = os.path.expanduser(opts["dir"])
        ingested = 0
        for fn in sorted(os.listdir(folder)):
            path = os.path.join(folder, fn)
            if not os.path.isfile(path):
                continue
            ranked = detect_source(path, fn)
            if not ranked:
                self.stdout.write(f"  ? skip (tak terdeteksi): {fn}")
                continue
            key = ranked[0]["parser_key"]
            flow = _flow(fn) if opts["flow_from_name"] else ""
            try:
                _, created, dup = services.ingest(key, path, flow=flow, toko=toko)
                ingested += created
                self.stdout.write(f"  + {key:16s} {created:5d} baris  ({fn})")
            except Exception as e:  # noqa: BLE001
                self.stdout.write(f"  ! GAGAL {key} {fn}: {e}")
        self.stdout.write(f"Total transaksi ter-ingest: {ingested}")

        res = run_batches_auto(toko)
        self.stdout.write(f"\nrun_batches_auto ok={res['ok']} "
                          f"batch={len(res.get('batches', []))} "
                          f"violations={len(res.get('violations', []))}")
        for b in res.get("batches", []):
            c = MatchResult.objects.filter(run__batch=b, left__isnull=False)
            total = c.count()
            cocok = c.filter(bucket=MatchResult.Bucket.COCOK).count()
            tinjau = c.filter(bucket=MatchResult.Bucket.TINJAU).count()
            tidak = c.filter(bucket=MatchResult.Bucket.TIDAK).count()
            self.stdout.write(
                f"  {b.recon_date}: cocok {format_rate(cocok, total)} | "
                f"tinjau {tinjau} | tidak {tidak}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python manage.py test reconciliation.tests_validate_brands -v2`
Expected: PASS (2 tests).

- [ ] **Step 5: Full suite**

Run: `.venv/bin/python manage.py test`
Expected: PASS (semua modul).

- [ ] **Step 6: Commit**

```bash
git add reconciliation/management/commands/validate_brands.py reconciliation/tests_validate_brands.py
git commit -m "feat(recon): command validate_brands (harness Fase 0 match-rate)"
```

- [ ] **Step 7: JALANKAN Fase 0 pada file nyata (gate — bukan test)**

Toko sudah ada (`mul`, `mxw`, `g25`). Jalankan & LAPORKAN angka ke user:
```bash
.venv/bin/python manage.py validate_brands --dir "/Users/macads/Downloads/Telegram Desktop/COR/01" --toko g25 --flow-from-name
.venv/bin/python manage.py validate_brands --dir "/Users/macads/Downloads/Telegram Desktop/MUL" --toko mul --flow-from-name
.venv/bin/python manage.py validate_brands --dir "/Users/macads/Downloads/Telegram Desktop/web_mxw_extracted/WEB MXW/WEB MXW" --toko mxw --flow-from-name
```
Ambang lolos: bucket `cocok` DP ≥ 95% per brand. Bila < 95%, STOP & investigasi (jangan lanjut integrasi UI). Pakai DB uji terpisah (`DATABASE_URL` sqlite sementara) agar tak mengotori data dev.

---

## Self-Review

**Spec coverage:**
- Reader tahan-styles → Task 1 ✓
- 4 parser (`cor_panel_bank`/`cor_panel_qris`/`cor_qris_gateway`/`qhoki`) → Task 3,4,5,6 ✓
- Registrasi + deteksi → Task 7,8 ✓
- reference-join pass → Task 9 ✓
- PanelBracket skip tanpa ticket → Task 10 ✓
- Cross-check agregat bracket COR → Task 11 ✓
- Fase 0 harness → Task 12 ✓
- Onboarding (Toko `mul`/`mxw`/`g25` sudah seeded; MUL/MXW reuse parser) → Task 12 step 7 + Global Constraints ✓
- Gotcha rupiah (no ×1000) → Task 3/4/5 test asserts ✓; exporter non-standar → Task 1 ✓
- KATEGORI_MAP COR: kategori tak dipetakan (`sesama cm`,`pending dp`,`adjustment`,`hutang`) jatuh ke `lainnya` via `.get` default (BracketParser existing) → TAK butuh perubahan; diverifikasi oleh harness Task 12. ✓
- `player_bank`/`bank_title` pada ingest (gap ditemukan) → Task 7 ✓

**Placeholder scan:** tak ada TBD/TODO; tiap step berisi kode/asersi konkret.

**Type consistency:** `read_xlsx_rows` (headers, list[dict]) dipakai konsisten; `_raw_xlsx_rows` list[list]; `parse_bank_triplet -> (kode,norek,nama)`; reason_code baru `reference`/`reference_amount`; `format_rate(n,d)`. Parser `source_key` sesuai SourceType seed.

**Catatan lingkup:** COR WD QRIS (tanpa file gateway WD) & statement BNI/SeaBank = di-luar-lingkup (baris jadi `no_money`, aman — lihat spec). Match nomor rekening bank-vs-bank di-defer.
