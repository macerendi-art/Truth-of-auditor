"""Parser PDF rekening BCA (text-based, tanpa OCR).

Tiap transaksi = 1 baris tanggal + nominal + CR/DB, kadang diikuti baris lanjutan
(nama/jenis: 'TRSF E-BANKING', 'BI-FAST', 'TRFDN-<nama>ESPAY...'). Tidak ada saldo per baris.
"""
import re
from decimal import Decimal

import pdfplumber

from .banks import extract_bca_name
from .base import BaseParser, parse_decimal, parse_dt, row_hash

DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(.*)$")
AMT_RE = re.compile(r"([\d.,]+\.\d{2})\s+(CR|DB)\s*$")
SKIP = (
    "Bersambung", "TANGGAL KETERANGAN", "MUTASI REKENING", "NO. REKENING",
    "NAMA :", "HALAMAN", "JENIS TRANSAKSI", "PERIODE", "MATA UANG", "CATATAN",
    "Apabila nasabah", "dengan akhir", "tercantum pada", "SALDO AWAL",
    "SALDO AKHIR", "MUTASI CR", "MUTASI DB",
)


def _is_skip(s):
    return any(k in s for k in SKIP)


def _clean_name(middle, cont):
    """Isolasi nama: gabung baris utama + baris lanjutan, lalu ekstrak lewat
    helper BCA bersama (buang teks struktural dulu, baru normalisasi di engine)."""
    return extract_bca_name(" ".join([middle, *cont]))


class BCAPDFParser(BaseParser):
    source_key = "bank"

    def parse(self, path, flow=""):
        lines = []
        with pdfplumber.open(path) as pdf:
            for pg in pdf.pages:
                lines += (pg.extract_text() or "").split("\n")

        txns, cur = [], None
        for ln in lines:
            s = ln.strip()
            if not s:
                continue
            m = DATE_RE.match(s)
            if m:
                cur = {"date": m.group(1), "rest": m.group(2), "cont": []}
                txns.append(cur)
            elif cur is not None and not _is_skip(s):
                cur["cont"].append(s)

        out = []
        for idx, t in enumerate(txns):
            am = AMT_RE.search(t["rest"])
            if not am:
                continue
            amount = parse_decimal(am.group(1))
            money = amount if am.group(2) == "CR" else -amount
            middle = t["rest"][: am.start()].strip()
            occurred = parse_dt(t["date"], dayfirst=True)
            desc = (middle + " " + " ".join(t["cont"])).strip()
            row = {
                "source_type": "bank",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "depo" if money > 0 else "wd" if money < 0 else "lainnya",
                "amount": amount,
                "credit_delta": Decimal("0"),
                "money_delta": money,
                "fee": Decimal("0"),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": "",
                "username": "",
                "reference": "",
                "counterparty": _clean_name(middle, t["cont"]),
                "description": desc,
                "raw": {"date": t["date"], "line": t["rest"], "cont": " ".join(t["cont"])},
            }
            row["row_hash"] = row_hash(
                "bca_pdf", [t["date"], amount, am.group(2), desc[:40], idx]
            )
            out.append(row)
        return out
