# Parser Mutasi BNI (PDF) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tambah parser `bni_pdf` yang membaca mutasi BNI Mobile Banking "HISTORI TRANSAKSI" (PDF) sebagai sisi UANG WD, sehingga baris panel WD via BNI yang selama ini `no_money` bisa dicocokkan.

**Architecture:** Parser meniru pola `BCAPDFParser` — pdfplumber menarik teks per-baris, sebuah **fungsi murni** `parse_bni_lines(lines)` mengubahnya jadi baris `Transaction`. Anchor identitas = **nomor rekening tujuan yang tertanam di ekor deskripsi**, disimpan utuh di `raw`, dicocokkan oleh mesin yang sudah ada (`_money_phones`/`_phone_match`) ke `Player Bank` panel — **tanpa perubahan engine**. Deteksi PDF disempurnakan agar tak semua PDF jatuh ke `bca_pdf`.

**Tech Stack:** Python 3.11, Django 5.2, pdfplumber (sudah dipakai `bca_pdf`), regex. Test: `django.test.SimpleTestCase` (parser & deteksi = fungsi murni, tanpa DB) + `TestCase` untuk integrasi ingest.

## Global Constraints

- **BNI nominal = rupiah penuh** — `parse_decimal(x, "id")`, **JANGAN ×1000** (×1000 hanya untuk parser `panel`).
- **Tanpa perubahan `reconciliation/engine.py`** — matching lewat mesin existing.
- **`source_key = "bank"`** untuk parser BNI (sama seperti BRI/BCA/Mandiri).
- **Arah uang:** `Db.` → `money_delta` negatif (`jenis="wd"`); `Cr.` → positif (`jenis="depo"`). Fee → `jenis="admin"`.
- **Fee** = deskripsi memuat `BY TRX` **atau** `BIAYA ADMIN` (case-insensitive).
- **`USE_TZ=False`** — tanggal naive; BNI tanpa jam (midnight). `parse_dt(iso_date)`.
- **Bahasa Indonesia** untuk komentar, docstring, pesan commit (konvensi repo).
- **Nomor rekening tujuan WAJIB terpelihara di `raw`** (jangan dibuang) — inilah anchor identitas.
- **venv:** worktree tak punya `.venv`; jalankan test dengan venv checkout utama, mis. `source /Users/macads/Truth-of-auditor/.venv/bin/activate` lalu `python manage.py test ...` dari root worktree.
- **Fixture nyata** (gitignored `samples/`): `12_07_2026_WD_BNI_MARULLOH.pdf`, `13_07_2026_WD_BNI_MARULLOH.pdf`, `HISTORY WD BNI PANEL GP 13 JULI.xlsx` (ada di `~/Downloads/Telegram Desktop/`). Test integrasi skip bila absen.

---

### Task 1: Helper `extract_bni_name` (isolasi nama, fungsi murni)

**Files:**
- Create: `sources/parsers/bni_pdf.py` (bagian helper nama)
- Test: `sources/tests_bni.py`

**Interfaces:**
- Produces: `extract_bni_name(text: str) -> str` — nama orang dari deskripsi `TRANSFER KE ...`; `""` bila baris tanpa nama (echannel/GOPAY/LINKAJA hanya nomor).

- [ ] **Step 1: Tulis test yang gagal**

```python
# sources/tests_bni.py
from django.test import SimpleTestCase
from sources.parsers.bni_pdf import extract_bni_name


class ExtractBNINameTests(SimpleTestCase):
    def test_transfer_ke_nama_tunggal(self):
        self.assertEqual(extract_bni_name("TRANSFER KE FAJAR"), "FAJAR")

    def test_transfer_ke_dengan_gelar(self):
        self.assertEqual(extract_bni_name("TRANSFER KE Bpk KELPIN BORNEO"), "KELPIN BORNEO")

    def test_transfer_ke_simon(self):
        self.assertEqual(extract_bni_name("TRANSFER KE Bpk SIMON ROSON"), "SIMON ROSON")

    def test_echannel_tanpa_nama_kosong(self):
        # baris echannel: hanya nomor & kode -> tanpa nama
        s = ("TRF/PAY/TOP-UP ECHANNEL KARTU 0000000000000000 BIZID "
             "20260713BNINIDJA010 O0217812687 901113275828")
        self.assertEqual(extract_bni_name(s), "")

    def test_gopay_hanya_nomor_kosong(self):
        self.assertEqual(extract_bni_name("TRANSFER KE GOPAY) NO :050525"), "")

    def test_linkaja_hanya_hp_kosong(self):
        self.assertEqual(extract_bni_name("TRANSFER KE aba8513014490053 LINKAJA 083177257639"), "")

    def test_dana_nama_tersamar_dipertahankan(self):
        # nama e-wallet tersamar (huruf, tanpa angka) boleh lolos apa adanya
        s = "TRANSFER KE ESPAY DEBIT INDONESIA KOE 8810085849792965 Dana-DNID FICXX"
        self.assertEqual(extract_bni_name(s), "FICXX")

    def test_kosong_tetap_kosong(self):
        self.assertEqual(extract_bni_name(""), "")
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

Run: `python manage.py test sources.tests_bni.ExtractBNINameTests -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'sources.parsers.bni_pdf'`

- [ ] **Step 3: Implementasi minimal**

```python
# sources/parsers/bni_pdf.py
"""Parser PDF mutasi BNI Mobile Banking ("HISTORI TRANSAKSI"), sisi UANG.

Baris utama tiap transaksi tampil satu baris:
`<tgl> <uraian-awal> <Db./Cr.> <nominal> <saldo>`, deskripsi lanjutan di baris
berikutnya. Watermark "Mobile Banking" (miring) menyusup sbg baris 1-karakter &
huruf nyasar -> disaring. Anchor identitas = nomor rekening tujuan tertanam di
ekor deskripsi (disimpan utuh di raw untuk _money_phones).
"""
import re
from decimal import Decimal

from .base import parse_decimal, parse_dt, row_hash

# Gelar di depan nama transfer bank.
BNI_HONORIFIC_RE = re.compile(r"\b(?:Bpk|Bapak|Bp|Ibu|Sdr|Sdri)\.?\s+", re.IGNORECASE)
# Token struktural (bukan nama). Frasa panjang dulu.
BNI_STRUCT_RE = re.compile(
    r"TRANSFER\s+KE|TRF/PAY/TOP-UP|ECHANNEL\s+KARTU|BIZID|"
    r"ESPAY\s+DEBIT\s+INDONESIA|AIRPAY\s+INTERNATIONAL\s+INDONESIA|"
    r"Dana-DNID|LINKAJA|GOPAY|BY\s+TRX|BI-?FAST|BIAYA\s+ADMIN|ATM\s+BERSAMA|"
    r"LANDMARK|\bKOE\b|\bNO\b|\baba\w*",
    re.IGNORECASE,
)


def extract_bni_name(text):
    """Isolasi nama orang dari uraian BNI. Buang label struktural, gelar, dan
    token bernomor (rekening/HP/kode/VA). Baris tanpa nama (echannel/GOPAY/
    LINKAJA) -> '' (jangan dikarang)."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    s = BNI_HONORIFIC_RE.sub(" ", s)
    s = BNI_STRUCT_RE.sub(" ", s)
    # Sisakan hanya token beralfabet murni (tanpa angka) -> buang nomor/kode.
    toks = [t for t in s.split() if re.search(r"[A-Za-z]", t) and not re.search(r"\d", t)]
    return re.sub(r"\s+", " ", " ".join(toks)).strip(" -.,:/)(")
```

- [ ] **Step 4: Jalankan test, pastikan LULUS**

Run: `python manage.py test sources.tests_bni.ExtractBNINameTests -v 2`
Expected: PASS (7 test)

- [ ] **Step 5: Commit**

```bash
git add sources/parsers/bni_pdf.py sources/tests_bni.py
git commit -m "feat(bni): helper extract_bni_name — isolasi nama transfer, echannel/e-wallet -> ''"
```

---

### Task 2: Inti parsing baris `parse_bni_lines` + `is_bni_fee` (fungsi murni)

**Files:**
- Modify: `sources/parsers/bni_pdf.py`
- Test: `sources/tests_bni.py`

**Interfaces:**
- Consumes: `extract_bni_name` (Task 1).
- Produces:
  - `is_bni_fee(desc: str) -> bool`
  - `parse_bni_lines(lines: list[str]) -> list[dict]` — tiap dict = field `Transaction` lengkap + `row_hash`. `money_delta` negatif utk `Db.`, positif utk `Cr.`; `amount` = abs; `balance_after` = Saldo Akhir; `raw["uraian"]` = deskripsi utuh (berisi nomor rekening tujuan).

- [ ] **Step 1: Tulis test yang gagal**

```python
# tambahkan ke sources/tests_bni.py
from decimal import Decimal
from sources.parsers.bni_pdf import is_bni_fee, parse_bni_lines


# Baris nyata (disederhanakan) dari 13_07_2026_WD_BNI_MARULLOH.pdf.
SAMPLE_LINES = [
    "HISTORI TRANSAKSI",                 # header -> diabaikan (sebelum transaksi)
    "Rekening: TAPLUS DIGITAL",
    "Tanggal Uraian Transaksi Tipe Nominal Saldo Akhir",
    "2026-07-13 TRANSFER KE Bpk KELPIN BORNEO Db. 800.000,00 2.065.363,00",
    "2026-07-13 BY TRX BIFAST lDb. 2.500,00 3.622.863,00",   # fee + huruf nyasar 'l'
    "g",                                                     # watermark 1-karakter
    "2026-07-13 TRF/PAY/TOP-UP Db. 900.000,00 3.882.363,00",  # echannel (main line)
    "ECHANNEL KARTU",                                        # lanjutan
    "0000000000000000 BIZID",                                # lanjutan
    "20260713BNINIDJA010",                                   # lanjutan
    "O0217812687 901113275828",                              # lanjutan: no rek tujuan
    "2026-07-13 TRF/PAY/TOP-UP ECHANNEL KARTU 0000000000000000 BIZID 20260713 Cr. 2.000.000,00 4.431.363,00",
    "Printed on 13/7/2026 6:27:15 Waktu",                    # footer -> diabaikan
    "Page 1 of 3",
]


class ParseBNILinesTests(SimpleTestCase):
    def setUp(self):
        self.rows = parse_bni_lines(SAMPLE_LINES)

    def test_jumlah_baris_transaksi(self):
        # 4 transaksi (KELPIN, fee, echannel 900k, Cr topup); watermark & footer diabaikan
        self.assertEqual(len(self.rows), 4)

    def test_arah_db_negatif_cr_positif(self):
        by_amt = {r["amount"]: r for r in self.rows}
        self.assertEqual(by_amt[Decimal("800000")]["money_delta"], Decimal("-800000"))
        self.assertEqual(by_amt[Decimal("2000000")]["money_delta"], Decimal("2000000"))

    def test_jenis_wd_depo_admin(self):
        by_amt = {r["amount"]: r["jenis"] for r in self.rows}
        self.assertEqual(by_amt[Decimal("800000")], "wd")
        self.assertEqual(by_amt[Decimal("2500")], "admin")     # BY TRX BIFAST
        self.assertEqual(by_amt[Decimal("2000000")], "depo")   # Cr topup

    def test_fee_terdeteksi(self):
        self.assertTrue(is_bni_fee("BY TRX BIFAST"))
        self.assertTrue(is_bni_fee("TRANSFER KE BIAYA ADMIN (GOPAY) NO :000724750525"))
        self.assertFalse(is_bni_fee("TRANSFER KE Bpk KELPIN BORNEO"))

    def test_saldo_dan_nominal_format_id(self):
        r = next(r for r in self.rows if r["amount"] == Decimal("800000"))
        self.assertEqual(r["balance_after"], Decimal("2065363"))
        self.assertEqual(r["credit_delta"], Decimal("0"))
        self.assertEqual(r["source_type"], "bank")

    def test_nomor_rekening_tujuan_terpelihara_di_raw(self):
        # anchor identitas: 901113275828 harus ada di raw echannel 900k
        r = next(r for r in self.rows if r["amount"] == Decimal("900000"))
        joined = " ".join(str(v) for v in r["raw"].values())
        self.assertIn("901113275828", joined)

    def test_counterparty_nama_transfer_bank(self):
        r = next(r for r in self.rows if r["amount"] == Decimal("800000"))
        self.assertEqual(r["counterparty"], "KELPIN BORNEO")

    def test_counterparty_echannel_kosong(self):
        r = next(r for r in self.rows if r["amount"] == Decimal("900000"))
        self.assertEqual(r["counterparty"], "")

    def test_tanggal_tanpa_jam(self):
        r = self.rows[0]
        self.assertEqual(r["occurred_at"].year, 2026)
        self.assertEqual(r["occurred_at"].hour, 0)

    def test_row_hash_stabil_dan_unik(self):
        hashes = [r["row_hash"] for r in self.rows]
        self.assertEqual(len(hashes), len(set(hashes)))
        # deterministik: parse ulang -> hash sama
        again = [r["row_hash"] for r in parse_bni_lines(SAMPLE_LINES)]
        self.assertEqual(hashes, again)
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

Run: `python manage.py test sources.tests_bni.ParseBNILinesTests -v 2`
Expected: FAIL — `ImportError: cannot import name 'parse_bni_lines'`

- [ ] **Step 3: Implementasi minimal** (tambahkan ke `sources/parsers/bni_pdf.py`)

```python
# --- Fee (dikecualikan dari total WD & matching) ---
BNI_FEE_RE = re.compile(r"BY\s+TRX|BIAYA\s+ADMIN", re.IGNORECASE)


def is_bni_fee(desc):
    return bool(BNI_FEE_RE.search(str(desc or "")))


# Baris/footer/header yang bukan lanjutan deskripsi transaksi.
_SKIP = (
    "HISTORI TRANSAKSI", "Kriteria Pencarian", "Rekening:", "Tanggal Awal",
    "Tanggal Akhir", "Kategori", "Transactions List", "Uraian Transaksi",
    "Saldo Akhir", "Printed on", "Page ", "Transaksi",
)
# Baris utama: diawali tanggal ISO; sisanya diakhiri Tipe + nominal + saldo.
_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\b(.*)$")
_ROW_RE = re.compile(r"^(.*?)\s*[A-Za-z]?(Db|Cr)\.\s+([\d.]+,\d{2})\s+([\d.]+,\d{2})\s*$")


def _is_skip(s):
    return any(k in s for k in _SKIP)


def parse_bni_lines(lines):
    """Ubah baris teks PDF BNI jadi daftar dict Transaction. Buang watermark
    (baris <=1 karakter), toleran huruf nyasar sebelum Db/Cr (mis. 'lDb.')."""
    txns, cur = [], None
    for ln in lines:
        s = ln.strip()
        if len(s) <= 1:                    # watermark 1-karakter
            continue
        m = _DATE_RE.match(s)
        if m and _ROW_RE.match(m.group(2).strip()):
            cur = {"date": m.group(1), "rest": m.group(2).strip(), "cont": []}
            txns.append(cur)
        elif cur is not None and not _is_skip(s):
            cur["cont"].append(s)

    out = []
    for idx, t in enumerate(txns):
        rm = _ROW_RE.match(t["rest"])
        if not rm:
            continue
        desc_head, tipe, nom, saldo = (rm.group(1).strip(), rm.group(2),
                                       rm.group(3), rm.group(4))
        amount = parse_decimal(nom, "id")
        money = amount if tipe == "Cr" else -amount
        saldo_val = parse_decimal(saldo, "id")
        full_desc = (desc_head + " " + " ".join(t["cont"])).strip()
        occurred = parse_dt(t["date"])     # ISO, tanpa jam
        jenis = "admin" if is_bni_fee(full_desc) else ("depo" if money > 0 else "wd")
        row = {
            "source_type": "bank",
            "occurred_at": occurred,
            "posted_date": occurred.date() if occurred else None,
            "jenis": jenis,
            "amount": amount,
            "credit_delta": Decimal("0"),
            "money_delta": money,
            "fee": Decimal("0"),
            "bonus": Decimal("0"),
            "balance_after": saldo_val,
            "ticket_no": "",
            "username": "",
            "reference": "",
            "counterparty": extract_bni_name(full_desc),
            "description": full_desc,
            "raw": {"tanggal": t["date"], "uraian": full_desc, "tipe": tipe,
                    "nominal": str(amount), "saldo": str(saldo_val)},
        }
        row["row_hash"] = row_hash("bni", [t["date"], amount, tipe, saldo_val, idx])
        out.append(row)
    return out
```

- [ ] **Step 4: Jalankan test, pastikan LULUS**

Run: `python manage.py test sources.tests_bni.ParseBNILinesTests -v 2`
Expected: PASS (10 test)

- [ ] **Step 5: Commit**

```bash
git add sources/parsers/bni_pdf.py sources/tests_bni.py
git commit -m "feat(bni): parse_bni_lines — arah Db/Cr, fee, filter watermark, no.rek tujuan di raw"
```

---

### Task 3: Kelas `BNIPDFParser` + registrasi di `PARSERS`

**Files:**
- Modify: `sources/parsers/bni_pdf.py` (kelas parser)
- Modify: `sources/services.py` (impor + entri `PARSERS`)
- Test: `sources/tests_bni.py` (integrasi file nyata, skip bila absen)

**Interfaces:**
- Consumes: `parse_bni_lines` (Task 2).
- Produces: `class BNIPDFParser(BaseParser)` dengan `source_key = "bank"` dan `parse(self, path, flow="") -> list[dict]`. Terdaftar di `PARSERS["bni_pdf"]`.

- [ ] **Step 1: Tulis test yang gagal**

```python
# tambahkan ke sources/tests_bni.py
import os


class BNIPDFParserSampleTests(SimpleTestCase):
    SAMPLE = "samples/bni/13_07_2026_WD_BNI_MARULLOH.pdf"

    def test_parse_file_nyata(self):
        if not os.path.exists(self.SAMPLE):
            self.skipTest("file kanonik BNI WD PDF tidak tersedia")
        from sources.parsers.bni_pdf import BNIPDFParser
        rows = BNIPDFParser().parse(self.SAMPLE)
        # semua baris bersumber bank & punya money_delta != 0
        self.assertTrue(rows)
        self.assertTrue(all(r["source_type"] == "bank" for r in rows))
        # nomor rekening tujuan wahyudi (SEABANK) harus muncul di salah satu raw
        joined_all = " ".join(
            str(v) for r in rows for v in r["raw"].values()
        )
        self.assertIn("901113275828", joined_all)


class ParsersRegistryTests(SimpleTestCase):
    def test_bni_pdf_terdaftar(self):
        from sources.services import PARSERS
        from sources.parsers.bni_pdf import BNIPDFParser
        self.assertIs(PARSERS["bni_pdf"], BNIPDFParser)
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

Run: `python manage.py test sources.tests_bni.ParsersRegistryTests -v 2`
Expected: FAIL — `KeyError: 'bni_pdf'`

- [ ] **Step 3a: Implementasi kelas parser** (tambahkan ke `sources/parsers/bni_pdf.py`)

```python
import pdfplumber

from .base import BaseParser


class BNIPDFParser(BaseParser):
    source_key = "bank"

    def parse(self, path, flow=""):
        lines = []
        with pdfplumber.open(path) as pdf:
            for pg in pdf.pages:
                lines += (pg.extract_text() or "").split("\n")
        return parse_bni_lines(lines)
```

> Catatan: `owner_name` tak diekstrak dari isi PDF (header BNI hanya "TAPLUS
> DIGITAL", bukan nama orang). `ingest()` sudah fallback ke `owner_from_filename`
> (mis. `13_07_2026_WD_BNI_MARULLOH.pdf` -> "MARULLOH").

- [ ] **Step 3b: Daftarkan di `PARSERS`** (`sources/services.py`)

Tambah impor bersama impor parser lain, lalu entri di dict `PARSERS`:

```python
from .parsers.bni_pdf import BNIPDFParser
```

```python
# di dalam dict PARSERS (dekat entri "bca_pdf"):
    "bni_pdf": BNIPDFParser,
```

- [ ] **Step 4: Jalankan test, pastikan LULUS**

Run: `python manage.py test sources.tests_bni.ParsersRegistryTests sources.tests_bni.BNIPDFParserSampleTests -v 2`
Expected: PASS (`ParsersRegistryTests` lulus; sample test lulus bila file ada, jika tidak SKIP)

- [ ] **Step 5: Commit**

```bash
git add sources/parsers/bni_pdf.py sources/services.py sources/tests_bni.py
git commit -m "feat(bni): BNIPDFParser (pdfplumber) + registrasi PARSERS['bni_pdf']"
```

---

### Task 4: Deteksi PDF — pisahkan `bni_pdf` dari `bca_pdf`

**Files:**
- Modify: `sources/detect.py`
- Test: `sources/tests_detect.py`

**Interfaces:**
- Produces: `_pdf_key(text: str) -> str` — `"bni_pdf"` bila teks BNI, selain itu `"bca_pdf"`. Dipakai di cabang `.pdf` `detect_source`.

- [ ] **Step 1: Tulis test yang gagal**

```python
# tambahkan ke sources/tests_detect.py
from sources.detect import _pdf_key


class PDFKeyRoutingTests(SimpleTestCase):
    def test_bni_dari_teks(self):
        txt = ("HISTORI TRANSAKSI\nRekening: TAPLUS DIGITAL\n"
               "Tanggal Uraian Transaksi Tipe Nominal Saldo Akhir")
        self.assertEqual(_pdf_key(txt), "bni_pdf")

    def test_bca_default(self):
        txt = "MUTASI REKENING\nNO. REKENING : 712-6201-591\nNAMA : HENDI"
        self.assertEqual(_pdf_key(txt), "bca_pdf")

    def test_teks_kosong_default_bca(self):
        self.assertEqual(_pdf_key(""), "bca_pdf")
```

> Jika `SimpleTestCase` belum diimpor di `tests_detect.py`, tambahkan
> `from django.test import SimpleTestCase` di atas.

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

Run: `python manage.py test sources.tests_detect.PDFKeyRoutingTests -v 2`
Expected: FAIL — `ImportError: cannot import name '_pdf_key'`

- [ ] **Step 3: Implementasi** (`sources/detect.py`)

Tambah dua helper (dekat `_csv_text`):

```python
def _pdf_text(path, max_chars=1500):
    """Teks halaman-1 PDF (lower-case) untuk sniff tanda-tangan. '' bila gagal."""
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return (pdf.pages[0].extract_text() or "")[:max_chars].lower()
    except Exception:
        return ""


def _pdf_key(text):
    """Rute PDF: mutasi BNI 'HISTORI TRANSAKSI' -> bni_pdf; selain itu bca_pdf."""
    t = (text or "").lower()
    if "histori transaksi" in t and ("uraian transaksi" in t or "saldo akhir" in t):
        return "bni_pdf"
    return "bca_pdf"
```

Ganti cabang `.pdf` di `detect_source` (baris ~99-100):

```python
    elif ext == ".pdf":
        key = _pdf_key(_pdf_text(path))
        add(key, 0.9 if key == "bni_pdf" else 0.75)
```

- [ ] **Step 4: Jalankan test, pastikan LULUS**

Run: `python manage.py test sources.tests_detect -v 2`
Expected: PASS (semua test deteksi lama + `PDFKeyRoutingTests` baru)

- [ ] **Step 5: Commit**

```bash
git add sources/detect.py sources/tests_detect.py
git commit -m "feat(detect): sniff isi PDF — HISTORI TRANSAKSI -> bni_pdf, selain itu bca_pdf"
```

---

### Task 5: Kalibrasi data nyata (verifikasi end-to-end, tanpa kode baru)

**Files:**
- (tak ada file kode diubah; hanya menaruh fixture & menjalankan pipeline di DB scratch)

**Interfaces:**
- Consumes: seluruh Task 1–4.

- [ ] **Step 1: Salin fixture nyata ke `samples/` (gitignored)**

```bash
mkdir -p samples/bni
cp "/Users/macads/Downloads/Telegram Desktop/13_07_2026_WD_BNI_MARULLOH.pdf" samples/bni/
cp "/Users/macads/Downloads/Telegram Desktop/12_07_2026_WD_BNI_MARULLOH.pdf" samples/bni/
cp "/Users/macads/Downloads/Telegram Desktop/HISTORY WD BNI PANEL GP 13 JULI.xlsx" samples/bni/
```

- [ ] **Step 2: Jalankan seluruh suite (regresi) + test sample**

Run: `python manage.py test sources -v 1`
Expected: semua LULUS (termasuk `BNIPDFParserSampleTests` yang kini menemukan file).

- [ ] **Step 3: Verifikasi deteksi memilih `bni_pdf`**

Run:
```bash
python -c "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', __import__('sources.detect', fromlist=['x']) and 'core.settings' or 'core.settings')" 2>/dev/null; \
python manage.py shell -c "from sources.detect import detect_source; print(detect_source('samples/bni/13_07_2026_WD_BNI_MARULLOH.pdf','13_07_2026_WD_BNI_MARULLOH.pdf'))"
```
Expected: elemen teratas `{'parser_key': 'bni_pdf', 'confidence': 0.9}`.

> Jika nama modul settings berbeda, temukan dengan `grep DJANGO_SETTINGS_MODULE manage.py`.

- [ ] **Step 4: Ingest + match end-to-end di DB scratch**

Jalankan di DB throwaway agar tak menyentuh dev DB (pola CLAUDE.md):

```bash
export DATABASE_URL=sqlite:////tmp/bni_calib.sqlite3
python manage.py migrate --noinput
# panel WD (kredit) — brand SUH, ×1000 oleh parser panel standar:
python manage.py ingest panel "samples/bni/HISTORY WD BNI PANEL GP 13 JULI.xlsx" --flow wd
# uang WD — mutasi BNI:
python manage.py ingest bni_pdf "samples/bni/13_07_2026_WD_BNI_MARULLOH.pdf"
python manage.py match panel_bank --from 2026-07-13 --to 2026-07-13
unset DATABASE_URL
```

Expected (sesuai temuan spec): dari 7 WD panel SUH, **6 cocok** via nomor rekening
tujuan; **W1460045 (372k, Somad/SEABANK)** → `no_money`/`tidak_cocok` (baris BNI
372k = rail LANDMARK/kartu tanpa nomor rekening cocok). Baris BNI non-SUH → `no_panel`.

> `ingest`/`match` mungkin memerlukan argumen `--toko`; sesuaikan dengan
> `python manage.py ingest --help` bila perlu, atau pakai harness `validate_brands`
> (lihat Step 5).

- [ ] **Step 5: (Opsional) Laporan match-rate via harness**

```bash
DATABASE_URL=sqlite:////tmp/bni_calib2.sqlite3 python manage.py migrate --noinput
DATABASE_URL=sqlite:////tmp/bni_calib2.sqlite3 python manage.py validate_brands \
    --dir "samples/bni" --toko suh --flow-from-name
```
Expected: laporan mencetak match-rate WD BNI; verifikasi 6/7 dan catat porsi
`no_money` struktural (rail LANDMARK, e-wallet nama tersamar) — bukan cacat matcher.

- [ ] **Step 6: Catat hasil kalibrasi**

Tambah ringkasan hasil (angka cocok/`no_money`/`no_panel` + investigasi 372k) ke
bagian bawah spec `docs/superpowers/specs/2026-07-15-parser-mutasi-bni-pdf-design.md`
(bagian "## Hasil kalibrasi"), lalu commit:

```bash
git add docs/superpowers/specs/2026-07-15-parser-mutasi-bni-pdf-design.md
git commit -m "docs(bni): hasil kalibrasi data nyata 13 Juli (6/7 cocok via no.rek)"
```

---

## Self-Review

**1. Spec coverage:**
- Ekstraksi baris-teks + filter watermark → Task 2. ✅
- Pemetaan field (arah Db/Cr, tanpa ×1000, saldo, tanpa jam) → Task 2. ✅
- Fee `BY TRX`/`BIAYA ADMIN` → Task 2. ✅
- Identitas = no.rek tujuan di `raw` (tanpa engine baru) → Task 2 (`raw["uraian"]`) + verifikasi Task 3/5. ✅
- Nama transfer bank → Task 1. ✅
- Deteksi PDF (`HISTORI TRANSAKSI` → bni_pdf) + registrasi → Task 3 & 4. ✅
- WD-only / baris Cr. inert (jenis jujur) → Task 2 (`depo`/`wd`). ✅
- Idempotensi row_hash pakai saldo → Task 2. ✅
- Uji TDD + end-to-end 13 Juli + validate_brands → Task 1–5. ✅
- Rekening bersama (no_panel wajar) → diverifikasi Task 5, dicatat di spec. ✅
- Di luar lingkup (OCR, referensi echannel, dedup lintas-toko) → tak ada task (benar). ✅

**2. Placeholder scan:** Tak ada TBD/TODO; semua step punya kode/perintah nyata. ✅

**3. Type consistency:** `extract_bni_name(str)->str`, `is_bni_fee(str)->bool`, `parse_bni_lines(list)->list[dict]`, `BNIPDFParser.parse(path,flow="")`, `_pdf_key(str)->str` — dipakai konsisten lintas task. `row_hash("bni", [...])`, `parse_decimal(x,"id")`, `parse_dt(iso)` sesuai signature `base.py`. ✅
