"""Helper bersama untuk semua parser sumber.

Tiap parser meng-output list of dict (baris kanonik) dengan kunci yang sama
dengan field model `transactions.Transaction`.
"""
from __future__ import annotations

import csv
import hashlib
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import openpyxl
from dateutil import parser as dateparser

# Ticket panel: D/W + 6-9 digit (mis. D1757153, W1757092). Sengaja dibatasi agar
# TIDAK ikut menangkap reference gateway yang panjang (>=12 digit).
TICKET_RE = re.compile(r"\b([DW]\d{6,9})\b")
# Reference gateway: 1 huruf + >=12 digit (mis. F260627206100206205).
REF_RE = re.compile(r"\b([A-Z]\d{12,})\b")


def read_xlsx_rows(path, header_row=1, sheet=None):
    """Baca xlsx -> (headers, list_of_dict). header_row 1-based."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
    headers = None
    out = []
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if i < header_row:
            continue
        if i == header_row:
            headers = [str(c).strip() if c is not None else "" for c in row]
            continue
        if row is None or all(c is None for c in row):
            continue
        out.append({h: c for h, c in zip(headers, row) if h})
    wb.close()
    return headers, out


def parse_decimal(value, number_format="intl"):
    """Parse angka (str/float/int) -> Decimal. Mendukung format intl & ID."""
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    s = str(value).strip().replace("Rp", "").replace("'", "").strip()
    if not s:
        return Decimal("0")
    neg = s.startswith("-") or s.endswith("DB") or s.endswith("Db")
    s = s.replace("DB", "").replace("Db", "").replace("CR", "").replace("Cr", "")
    s = s.strip().lstrip("+-").strip()
    if number_format == "id":  # 1.000,00 -> 1000.00
        s = s.replace(".", "").replace(",", ".")
    else:  # intl 1,000.00 -> 1000.00
        s = s.replace(",", "")
    s = re.sub(r"[^0-9.]", "", s)
    if s in ("", "."):
        return Decimal("0")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return Decimal("0")
    return -d if neg else d


def parse_dt(value, dayfirst=False):
    """Parse tanggal/jam -> datetime (atau None)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    s = str(value).strip().lstrip("'")
    if not s:
        return None
    try:
        return dateparser.parse(s, dayfirst=dayfirst)
    except (ValueError, OverflowError, TypeError):
        return None


def extract_ticket(text):
    m = TICKET_RE.search(text or "")
    return m.group(1) if m else ""


def extract_ref(text):
    m = REF_RE.search(text or "")
    return m.group(1) if m else ""


def row_hash(source_key, parts):
    """Hash stabil untuk idempotensi (cegah re-import baris yang sama)."""
    h = hashlib.sha256()
    h.update(source_key.encode())
    for p in parts:
        h.update(b"|")
        h.update(str(p).encode())
    return h.hexdigest()


def read_csv_raw(path, encoding="utf-8-sig", delimiter=","):
    """Baca CSV mentah -> list of list (semua baris, termasuk preamble)."""
    with open(path, newline="", encoding=encoding, errors="replace") as f:
        return list(csv.reader(f, delimiter=delimiter))


def rows_to_dicts(rows, header_idx):
    """list-of-list -> list-of-dict pakai baris header ke-`header_idx` (0-based)."""
    headers = [str(c).strip() for c in rows[header_idx]]
    out = []
    for r in rows[header_idx + 1 :]:
        if not any(str(c).strip() for c in r):
            continue
        out.append({(h if h else f"col{i}"): (r[i] if i < len(r) else "") for i, h in enumerate(headers)})
    return headers, out


def first_part(value, sep=","):
    """Ambil bagian sebelum `sep` (mis. buang ', Platform: ...' di tanggal Panel)."""
    return str(value or "").split(sep)[0].strip()


class BaseParser:
    """Interface parser. Subclass set `source_key` & implement `parse`."""

    source_key: str | None = None

    def parse(self, path, flow="") -> list[dict]:
        raise NotImplementedError
