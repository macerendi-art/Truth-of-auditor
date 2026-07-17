# Parser RafflesPay XLSX (BBS) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** File QRIS RPAY (RafflesPay) DP & WD varian XLSX milik brand BBS terdeteksi dan ter-ingest benar, tidak lagi nyasar ke parser nxpay/qrflyer.

**Architecture:** Dua parser baru di `sources/parsers/gateways.py` (konvensi satu class per format; parser CSV `rpay`/`rpay_wd` tidak disentuh), satu helper grid mentah di `sources/parsers/base.py`, dua tanda tangan deteksi 0.95 + pengetatan sinyal nxpay di `sources/detect.py`, registrasi di `sources/services.py`. Kalibrasi akhir dengan data nyata `16.zip`.

**Tech Stack:** Django 5.2 test runner (`SimpleTestCase`), openpyxl, helper `sources/parsers/base.py` (`parse_decimal`, `parse_dt`, `row_hash`, `read_xlsx_rows`, `_raw_xlsx_rows`).

**Spec:** `docs/superpowers/specs/2026-07-17-rpay-xlsx-bbs-design.md`

## Global Constraints

- Virtualenv di checkout utama: `/Users/macads/Truth-of-auditor/.venv` (worktree tidak punya `.venv`). Jalankan test dgn `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test ...` dari root worktree.
- Komentar/docstring bahasa Indonesia (konvensi repo).
- Baris gateway = sisi uang saja: `credit_delta = 0` selalu.
- `Amount (IDR)` & `Disbursed Amount` sudah **rupiah penuh** — JANGAN ×1000.
- `reference` DIKOSONGKAN pada kedua parser (RRN duplikat; aturan blocked engine mengasingkan reference asing).
- `flow` diabaikan kedua parser (DP selalu depo, WD selalu wd) — salah pilih di UI tak boleh membalik tanda.
- Commit per task; push `origin/main` fast-forward (`git push origin HEAD:main`) setelah `git fetch` + pastikan tidak tertinggal; JANGAN deploy (deploy manual, hanya dengan konfirmasi user).
- Sampel nyata: `/private/tmp/claude-501/-Users-macads-Truth-of-auditor--claude-worktrees-loving-joliot-2aa399/9dbea579-50f9-462c-ba4b-77d2bd34e9b0/scratchpad/16/16/` (isi `16.zip` — jika folder hilang, minta user unggah ulang zip).

---

### Task 1: Helper `read_xlsx_grid` di base.py

**Files:**
- Modify: `sources/parsers/base.py` (setelah `read_xlsx_rows`, sekitar baris 134)
- Test: `sources/tests_rpay_xlsx.py` (file baru)

**Interfaces:**
- Produces: `read_xlsx_grid(path) -> list[list]` — semua baris xlsx sebagai grid mentah (nilai sel typed dari openpyxl), fallback `_raw_xlsx_rows` bila openpyxl gagal/kosong. Dipakai Task 3 (parser WD).

- [ ] **Step 1: Tulis failing test**

Buat `sources/tests_rpay_xlsx.py`:

```python
"""Parser gateway RafflesPay varian XLSX (BBS): DP satu-header, WD dua-tingkat."""
import os
import tempfile

from django.test import SimpleTestCase
from openpyxl import Workbook


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    wb.save(path)
    return path


class ReadXlsxGridTests(SimpleTestCase):
    def test_grid_mentah_semua_baris(self):
        from sources.parsers.base import read_xlsx_grid
        path = _xlsx([["A", "B"], ["", "sub"], [1, 2]])
        try:
            grid = read_xlsx_grid(path)
        finally:
            os.remove(path)
        self.assertEqual(len(grid), 3)
        self.assertEqual(grid[0][0], "A")
        self.assertEqual(grid[1][1], "sub")
        self.assertEqual(grid[2][1], 2)
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources.tests_rpay_xlsx -v 2`
Expected: FAIL `ImportError: cannot import name 'read_xlsx_grid'`

- [ ] **Step 3: Implementasi minimal**

Di `sources/parsers/base.py`, tepat setelah fungsi `read_xlsx_rows` berakhir:

```python
def read_xlsx_grid(path):
    """Baca xlsx -> list-of-list mentah (SEMUA baris, tanpa interpretasi header).
    Untuk format ber-header dua-tingkat yang tak bisa diwakili `read_xlsx_rows`.
    Fallback ke reader mentah bila openpyxl gagal / kebaca kosong."""
    grid = None
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        grid = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
    except Exception:
        grid = None
    if not grid:
        grid = _raw_xlsx_rows(path)
    return grid or []
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources.tests_rpay_xlsx -v 2`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add sources/parsers/base.py sources/tests_rpay_xlsx.py
git commit -m "feat(base): read_xlsx_grid — grid mentah utk header dua-tingkat"
```

---

### Task 2: `RPayDPXlsxParser` + registrasi `rpay_xlsx`

**Files:**
- Modify: `sources/parsers/gateways.py` (tambah class di akhir file)
- Modify: `sources/services.py` (dict `PARSERS`, setelah `"rpay_wd"`)
- Test: `sources/tests_rpay_xlsx.py` (tambah class test)

**Interfaces:**
- Consumes: `BaseParser`, `parse_decimal`, `parse_dt`, `read_xlsx_rows`, `row_hash` (sudah diimpor di gateways.py).
- Produces: `PARSERS["rpay_xlsx"] = RPayDPXlsxParser`; baris keluaran berkolom `Transaction` standar; `ticket_no` = `Ticket Number` panel (`D…`).

- [ ] **Step 1: Tulis failing tests**

Tambahkan di `sources/tests_rpay_xlsx.py`:

```python
DP_HEADER = ["Website", "Date", "Ticket Number", "Player", "Payment Type",
             "Account Title", "Status", "Payment Gateway", "RRN", "Amount (IDR)",
             "Amount (Chip)", "Player Fee", "Agent Fee", "Admin Fee",
             "Player Nett Amount", "Agent Nett Amount", "Ticket Status", "Promotion"]


def _dp_row(ticket="D2553373", status="Success", ticket_status="approved",
            rrn="336884375", amount=30000.0):
    return ["BOBASLOT77", "2026-07-16 00:00:35.002000", ticket, "vivian01", "QR",
            "QRIS", status, "RafflesPay", rrn, amount, amount / 1000, 0.0, 0.0,
            600.0, amount, amount, ticket_status, ""]


class RPayDPXlsxTests(SimpleTestCase):
    def _parse(self, rows, flow=""):
        from sources.parsers.gateways import RPayDPXlsxParser
        path = _xlsx([DP_HEADER] + rows)
        try:
            return RPayDPXlsxParser().parse(path, flow=flow)
        finally:
            os.remove(path)

    def test_dp_sukses_field_lengkap(self):
        rows = self._parse([_dp_row()])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["jenis"], "depo")
        self.assertEqual(str(r["amount"]), "30000")        # rupiah penuh, BUKAN x1000
        self.assertEqual(str(r["money_delta"]), "30000")   # DP = uang masuk
        self.assertEqual(str(r["credit_delta"]), "0")
        self.assertEqual(r["ticket_no"], "D2553373")       # anchor pass-0
        self.assertEqual(r["username"], "vivian01")
        self.assertEqual(str(r["fee"]), "600")
        self.assertEqual(r["reference"], "")               # RRN hanya di raw
        self.assertEqual(r["raw"]["RRN"], "336884375")
        self.assertEqual(r["occurred_at"].year, 2026)
        self.assertEqual(r["occurred_at"].month, 7)
        self.assertEqual(r["occurred_at"].day, 16)

    def test_status_bukan_success_dilewati(self):
        rows = self._parse([_dp_row(status="Pending")])
        self.assertEqual(rows, [])

    def test_ticket_failed_tetap_diambil(self):
        # Uang QR masuk tapi tiket panel gagal -> harus muncul sebagai selisih.
        rows = self._parse([_dp_row(ticket_status="failed")])
        self.assertEqual(len(rows), 1)

    def test_flow_wd_diabaikan_tetap_depo(self):
        rows = self._parse([_dp_row()], flow="wd")
        self.assertEqual(rows[0]["jenis"], "depo")
        self.assertEqual(str(rows[0]["money_delta"]), "30000")

    def test_row_hash_stabil_dan_beda_per_tiket(self):
        a = self._parse([_dp_row()])[0]["row_hash"]
        b = self._parse([_dp_row()])[0]["row_hash"]
        c = self._parse([_dp_row(ticket="D2553374")])[0]["row_hash"]
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources.tests_rpay_xlsx.RPayDPXlsxTests -v 2`
Expected: FAIL `ImportError: cannot import name 'RPayDPXlsxParser'`

- [ ] **Step 3: Implementasi**

Di akhir `sources/parsers/gateways.py`:

```python
class RPayDPXlsxParser(BaseParser):
    """Gateway RafflesPay sisi DP, varian XLSX (brand panel-Nexus mis. BBS).

    Beda dari `rpay` (CSV ber-`Customer Username`/`UUID`): varian ini laporan
    "Deposit QRIS" panel ber-gateway RafflesPay yang membawa `Ticket Number`
    (D...) == panel DP -> pass 0 ticket-join engine. `RRN` DISIMPAN di raw
    saja, TIDAK di `reference`: ada duplikat nyata (9 dari 1.233, sampel BBS
    16-07-2026) dan aturan blocked engine mengasingkan reference asing.
    `Amount (IDR)` sudah rupiah penuh (`Amount (Chip)` = ribuan versi panel —
    JANGAN dipakai). Baris `Status=Success` diambil TERMASUK yang
    `Ticket Status=failed`: uang masuk tanpa kredit panel harus muncul sebagai
    "Tidak Ada di Panel", bukan hilang di parser. Selalu DP: `flow` diabaikan.
    """

    source_key = "gateway"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path)
        out = []
        for r in rows:
            ticket = str(r.get("Ticket Number", "") or "").strip()
            status = str(r.get("Status", "") or "").strip().lower()
            if not ticket or status != "success":
                continue
            amt = abs(parse_decimal(r.get("Amount (IDR)")))
            occurred = parse_dt(r.get("Date"), dayfirst=True)
            rrn = str(r.get("RRN", "") or "").strip()
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "depo",
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": amt,
                "fee": parse_decimal(r.get("Admin Fee")),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": ticket,
                "username": str(r.get("Player", "") or "").strip(),
                "reference": "",
                "counterparty": "",
                "description": f"RPAY QR {rrn}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items() if k},
            }
            row["row_hash"] = row_hash("rpay_xlsx", [ticket, rrn])
            out.append(row)
        return out
```

Registrasi di `sources/services.py` — di dict `PARSERS`, setelah baris `"rpay_wd": RPayWDGatewayParser,`:

```python
    "rpay_xlsx": RPayDPXlsxParser,
```

dan tambahkan `RPayDPXlsxParser` pada import dari `.parsers.gateways` di bagian atas file.

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources.tests_rpay_xlsx -v 2`
Expected: PASS (6 test)

- [ ] **Step 5: Commit**

```bash
git add sources/parsers/gateways.py sources/services.py sources/tests_rpay_xlsx.py
git commit -m "feat(rpay): RPayDPXlsxParser — DP RafflesPay varian XLSX BBS, anchor ticket"
```

---

### Task 3: `RPayWDXlsxParser` + registrasi `rpay_wd_xlsx`

**Files:**
- Modify: `sources/parsers/gateways.py` (class baru di akhir; tambah `read_xlsx_grid` pada import dari `.base`)
- Modify: `sources/services.py` (dict `PARSERS`)
- Test: `sources/tests_rpay_xlsx.py`

**Interfaces:**
- Consumes: `read_xlsx_grid(path) -> list[list]` (Task 1); `parse_decimal`, `parse_dt`, `row_hash`.
- Produces: `PARSERS["rpay_wd_xlsx"] = RPayWDXlsxParser`; `ticket_no` = `Ticket` panel (`W…`).

- [ ] **Step 1: Tulis failing tests**

Tambahkan di `sources/tests_rpay_xlsx.py`:

```python
WD_TOP = ["ID", "Website", "Date", "Ticket", "Player", "Source of Funds",
          "Beneficiary", "", "", "Amount", "", "", "Status", "", "", ""]
WD_SUB = ["", "", "", "", "", "", "Bank", "Name", "Number", "Amount",
          "Disbursed Amount", "Fee", "Status", "Approve", "Reject", "Transfer"]


def _wd_row(ticket="W2553796", transfer="success", bank="DANA",
            number="81311189314", amount=1950000.0, disbursed=1950000.0):
    return [6001917, "BOBASLOT77", "2026-07-16 04:45:16", ticket, "Rio171",
            "[BOBASLOT77] [RafflesPay] [577068433908]", bank, "AJRIAN ALANSYAH",
            number, amount, disbursed, 5000.0, "approved", "success", "", transfer]


class RPayWDXlsxTests(SimpleTestCase):
    def _parse(self, rows, flow=""):
        from sources.parsers.gateways import RPayWDXlsxParser
        path = _xlsx([WD_TOP, WD_SUB] + rows)
        try:
            return RPayWDXlsxParser().parse(path, flow=flow)
        finally:
            os.remove(path)

    def test_wd_sukses_field_lengkap(self):
        rows = self._parse([_wd_row()])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["jenis"], "wd")
        self.assertEqual(str(r["amount"]), "1950000")       # Disbursed, rupiah penuh
        self.assertEqual(str(r["money_delta"]), "-1950000")  # WD = uang keluar
        self.assertEqual(str(r["credit_delta"]), "0")
        self.assertEqual(r["ticket_no"], "W2553796")         # anchor pass-0
        self.assertEqual(r["username"], "Rio171")
        self.assertEqual(r["counterparty"], "AJRIAN ALANSYAH")
        self.assertEqual(str(r["fee"]), "5000")
        self.assertEqual(r["reference"], "")
        self.assertEqual(r["raw"]["Number"], "81311189314")  # nomor tujuan utk paket B
        self.assertEqual(r["occurred_at"].hour, 4)

    def test_disbursed_dipakai_bukan_amount(self):
        rows = self._parse([_wd_row(amount=2000000.0, disbursed=1950000.0)])
        self.assertEqual(str(rows[0]["amount"]), "1950000")

    def test_transfer_bukan_success_dilewati(self):
        rows = self._parse([_wd_row(transfer="")])
        self.assertEqual(rows, [])

    def test_flow_dp_diabaikan_tetap_wd(self):
        rows = self._parse([_wd_row()], flow="dp")
        self.assertEqual(rows[0]["jenis"], "wd")
        self.assertEqual(str(rows[0]["money_delta"]), "-1950000")

    def test_row_hash_dari_id_dan_ticket_tanpa_nominal(self):
        a = self._parse([_wd_row(amount=1950000.0)])[0]["row_hash"]
        b = self._parse([_wd_row(amount=1950000.49)])[0]["row_hash"]  # nominal beda
        self.assertEqual(a, b)  # idempoten thd variasi format angka
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources.tests_rpay_xlsx.RPayWDXlsxTests -v 2`
Expected: FAIL `ImportError: cannot import name 'RPayWDXlsxParser'`

- [ ] **Step 3: Implementasi**

Di `sources/parsers/gateways.py` — ubah baris import dari `.base` menjadi:

```python
from .base import BaseParser, parse_decimal, parse_dt, read_xlsx_grid, read_xlsx_rows, row_hash
```

lalu class baru di akhir file:

```python
class RPayWDXlsxParser(BaseParser):
    """Gateway RafflesPay sisi WD, varian XLSX header dua-tingkat (brand BBS).

    Beda dari `rpay_wd` (CSV ber-`External ID`/`Transfer Status`): header grup
    di baris 1 (Beneficiary / Amount / Status) + sub-kolom di baris 2 (Bank,
    Name, Number / Amount, Disbursed Amount, Fee / Status, Approve, Reject,
    Transfer), data mulai baris 3 -> di-flatten manual (sub-kolom menang bila
    terisi). Kunci pasti = `Ticket` (W...) == `Ticket Number` panel WD -> pass
    0. Hanya baris `Transfer=success` (uang benar-benar keluar). `Disbursed
    Amount` = uang riil keluar. `Beneficiary Number` (nomor rekening/e-wallet
    tujuan) tersimpan di raw. Selalu WD: `flow` diabaikan.
    """

    source_key = "gateway"

    def parse(self, path, flow=""):
        grid = read_xlsx_grid(path)
        if len(grid) < 3:
            return []
        top, sub = grid[0], grid[1]
        width = max(len(top), len(sub))

        def _cell(row, i):
            v = row[i] if i < len(row) else None
            return str(v).strip() if v is not None else ""

        headers = [(_cell(sub, i) or _cell(top, i)) for i in range(width)]
        out = []
        for raw_row in grid[2:]:
            r = {h: c for h, c in zip(headers, raw_row) if h}
            ticket = str(r.get("Ticket", "") or "").strip()
            transfer = str(r.get("Transfer", "") or "").strip().lower()
            if not ticket or transfer != "success":
                continue
            amt = abs(parse_decimal(r.get("Disbursed Amount")))
            occurred = parse_dt(r.get("Date"), dayfirst=True)
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
                "ticket_no": ticket,
                "username": str(r.get("Player", "") or "").strip(),
                "reference": "",
                "counterparty": str(r.get("Name", "") or "").strip(),
                "description": f"RPAY WD {r.get('Bank', '')}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items() if k},
            }
            # ID RafflesPay unik per baris; + ticket cadangan. TANPA nominal
            # supaya idempotensi tak goyah oleh variasi format angka.
            row["row_hash"] = row_hash(
                "rpay_wd_xlsx", [str(r.get("ID", "") or "").strip(), ticket])
            out.append(row)
        return out
```

Registrasi di `sources/services.py` — di dict `PARSERS`, setelah `"rpay_xlsx"`:

```python
    "rpay_wd_xlsx": RPayWDXlsxParser,
```

dan tambahkan `RPayWDXlsxParser` pada import dari `.parsers.gateways`.

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources.tests_rpay_xlsx -v 2`
Expected: PASS (11 test)

- [ ] **Step 5: Commit**

```bash
git add sources/parsers/gateways.py sources/services.py sources/tests_rpay_xlsx.py
git commit -m "feat(rpay): RPayWDXlsxParser — WD RafflesPay XLSX dua-tingkat BBS"
```

---

### Task 4: Deteksi kedua format + pengetatan nxpay

**Files:**
- Modify: `sources/detect.py:80-104` (cabang xlsx)
- Test: `sources/tests_detect.py` (tambah class)

**Interfaces:**
- Consumes: key `rpay_xlsx` & `rpay_wd_xlsx` terdaftar di `PARSERS` (Task 2–3).
- Produces: `detect_source` mengembalikan key baru dgn confidence 0.95 di peringkat 1.

- [ ] **Step 1: Tulis failing tests**

Tambahkan di akhir `sources/tests_detect.py`:

```python
class DetectRPayXlsxTests(SimpleTestCase):
    """RafflesPay varian XLSX (BBS) — dulu nyasar ke nxpay/qrflyer (bug nyata 16-07)."""

    DP_HEADER = ["Website", "Date", "Ticket Number", "Player", "Payment Type",
                 "Account Title", "Status", "Payment Gateway", "RRN",
                 "Amount (IDR)", "Amount (Chip)", "Player Fee", "Agent Fee",
                 "Admin Fee", "Player Nett Amount", "Agent Nett Amount",
                 "Ticket Status", "Promotion"]
    WD_TOP = ["ID", "Website", "Date", "Ticket", "Player", "Source of Funds",
              "Beneficiary", "", "", "Amount", "", "", "Status", "", "", ""]
    WD_SUB = ["", "", "", "", "", "", "Bank", "Name", "Number", "Amount",
              "Disbursed Amount", "Fee", "Status", "Approve", "Reject", "Transfer"]

    def test_dp_rpay_xlsx_menang_atas_nxpay(self):
        # Nama file mengandung QRIS -> dulu qrflyer 0.85 & header mirip nxpay 0.90.
        path = _xlsx([self.DP_HEADER, ["x"] * len(self.DP_HEADER)])
        try:
            hasil = detect_source(path, "16_07_2026_BBS_DP_QRIS_RPAY_CSV.xlsx")
        finally:
            os.remove(path)
        self.assertEqual(hasil[0]["parser_key"], "rpay_xlsx")
        self.assertGreaterEqual(hasil[0]["confidence"], 0.95)
        self.assertNotIn("nxpay", [d["parser_key"] for d in hasil])

    def test_wd_rpay_xlsx_menang_atas_qrflyer(self):
        path = _xlsx([self.WD_TOP, self.WD_SUB, ["x"] * len(self.WD_TOP)])
        try:
            hasil = detect_source(path, "16_07_2026_BBS_WD_QRIS_RPAY.xlsx")
        finally:
            os.remove(path)
        self.assertEqual(hasil[0]["parser_key"], "rpay_wd_xlsx")
        self.assertGreaterEqual(hasil[0]["confidence"], 0.95)

    def test_nxpay_asli_tetap_terdeteksi(self):
        # Non-regresi: header NXPay (tanpa 'Payment Gateway') tetap nxpay.
        path = _xlsx([["judul report"], ["Ticket Number", "Username", "Amount",
                      "Date", "Admin Fee", "Account Title"], ["t", "u", 1, "d", 0, "a"]])
        try:
            hasil = detect_source(path, "nxpay.xlsx")
        finally:
            os.remove(path)
        self.assertEqual(hasil[0]["parser_key"], "nxpay")
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources.tests_detect.DetectRPayXlsxTests -v 2`
Expected: 2 FAIL (`rpay_xlsx`/`rpay_wd_xlsx` belum ada di hasil; test nxpay asli PASS)

- [ ] **Step 3: Implementasi**

Di `sources/detect.py`, dalam cabang `if ext in (".xlsx", ".xls"):`.

Ubah sinyal nxpay (baris 84–85) menjadi:

```python
        if _has(t, "ticket number") and (_has(t, "admin fee") or _has(t, "account title")) \
                and not _has(t, "deposit amount") and not _has(t, "payment gateway"):
            add("nxpay", 0.90)
```

Tambahkan sebelum blok qrflyer (setelah blok nxpay):

```python
        if _has(t, "payment gateway") and _has(t, "rrn") and _has(t, "amount (chip)"):
            add("rpay_xlsx", 0.95)  # RafflesPay DP varian XLSX (BBS)
        if _has(t, "source of funds") and _has(t, "disbursed amount") and _has(t, "beneficiary"):
            add("rpay_wd_xlsx", 0.95)  # RafflesPay WD XLSX dua-tingkat (BBS)
```

- [ ] **Step 4: Jalankan test modul deteksi penuh, pastikan lulus**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test sources.tests_detect -v 2`
Expected: PASS semua (termasuk `test_nxpay_not_confused_with_panel` lama)

- [ ] **Step 5: Cek empiris file NXPay BBS nyata tak kena pengetatan**

```bash
/Users/macads/Truth-of-auditor/.venv/bin/python - <<'EOF'
import sys, os, django
sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'truth_auditor.settings')
django.setup()
from sources.detect import detect_source
base = "/private/tmp/claude-501/-Users-macads-Truth-of-auditor--claude-worktrees-loving-joliot-2aa399/9dbea579-50f9-462c-ba4b-77d2bd34e9b0/scratchpad/16/16"
for n in ["16-07-2026 BBS DP NXPAY.xlsx", "16-07-2026 BBS WD NXPAY.xlsx",
          "16_07_2026_BBS_DP_QRIS_RPAY_CSV.xlsx", "16_07_2026_BBS_WD_QRIS_RPAY.xlsx"]:
    print(n, "->", detect_source(f"{base}/{n}", n)[:2])
EOF
```

Expected: dua file NXPAY → `nxpay` tetap peringkat 1; dua file RPAY → `rpay_xlsx`/`rpay_wd_xlsx` 0.95 peringkat 1. Bila NXPAY nyata ternyata memuat token "payment gateway", HENTIKAN dan laporkan (pengetatan perlu didiskusikan ulang), jangan dipaksakan.

- [ ] **Step 6: Commit**

```bash
git add sources/detect.py sources/tests_detect.py
git commit -m "feat(detect): sinyal rpay_xlsx/rpay_wd_xlsx 0.95 + ketatkan nxpay"
```

---

### Task 5: Suite penuh, kalibrasi data nyata, dokumentasi, push

**Files:**
- Modify: `CLAUDE.md` (bagian "Per-brand exact keys on the money side")
- Modify: `docs/superpowers/specs/2026-07-17-rpay-xlsx-bbs-design.md` (tambah bagian hasil kalibrasi)

**Interfaces:**
- Consumes: semua task sebelumnya.
- Produces: bukti kalibrasi + dokumentasi; push origin/main.

- [ ] **Step 1: Suite penuh**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test`
Expected: semua lulus (≈754+ test). Bila ada kegagalan `Missing staticfiles manifest entry`, jalankan dulu `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py collectstatic --noinput` lalu ulangi.

- [ ] **Step 2: Kalibrasi data nyata di DB scratch**

```bash
export SCRATCH=sqlite:////tmp/bbs-rpay-cal.sqlite3
rm -f /tmp/bbs-rpay-cal.sqlite3
DATABASE_URL=$SCRATCH /Users/macads/Truth-of-auditor/.venv/bin/python manage.py migrate --verbosity 0
DATABASE_URL=$SCRATCH /Users/macads/Truth-of-auditor/.venv/bin/python manage.py shell -c "
from sources.models import Toko
Toko.objects.get_or_create(key='bbs', defaults={'name': 'BBS'})"
DATABASE_URL=$SCRATCH /Users/macads/Truth-of-auditor/.venv/bin/python manage.py validate_brands \
  --dir "/private/tmp/claude-501/-Users-macads-Truth-of-auditor--claude-worktrees-loving-joliot-2aa399/9dbea579-50f9-462c-ba4b-77d2bd34e9b0/scratchpad/16/16" \
  --toko bbs --flow-from-name
```

Expected: kedua file RPAY terdeteksi (`rpay_xlsx`, `rpay_wd_xlsx`) dan ter-ingest (DP ±1.233 baris, WD 17); WD RPAY match ke panel WD via ticket, DP RPAY ke panel DP. Catat match-rate. File Mandiri terenkripsi (password `07032003` dari nama file) boleh gagal/dilewati harness — bukan lingkup paket ini; catat saja. Bila harness malah BERHENTI karena file itu, pindahkan sementara `16_07_2026_BBS_WD_MANDIRI_ARDIANTO_07032003.xlsx` keluar folder lalu ulangi.

- [ ] **Step 3: Verifikasi idempotensi ingest ulang**

Jalankan ulang perintah `validate_brands` yang sama sekali lagi.
Expected: 0 baris baru untuk kedua file RPAY (semua kena dedup `row_hash`).

- [ ] **Step 4: Dokumentasi**

Di `CLAUDE.md`, bagian "Per-brand exact keys on the money side", tambahkan sesudah kalimat RPay:

```
BBS RafflesPay varian XLSX: DP `rpay_xlsx` (`Ticket Number` D... == panel; RRN hanya di raw, ada duplikat nyata) dan WD `rpay_wd_xlsx` (header dua-tingkat, `Ticket` W... == panel, hanya `Transfer=success`, `Disbursed Amount` = uang keluar).
```

Di spec `docs/superpowers/specs/2026-07-17-rpay-xlsx-bbs-design.md`, tambah bagian `## Hasil kalibrasi (16.zip)` berisi angka nyata dari Step 2–3 (baris ter-ingest, match-rate, temuan).

- [ ] **Step 5: Commit + push**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-07-17-rpay-xlsx-bbs-design.md
git commit -m "docs(rpay): kunci BBS RafflesPay XLSX + hasil kalibrasi 16.zip"
git fetch origin && git push origin HEAD:main
```

Expected: fast-forward ke origin/main. JANGAN deploy — tunggu konfirmasi user.
