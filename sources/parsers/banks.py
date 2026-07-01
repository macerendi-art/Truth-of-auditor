"""Parser bank (sumber UANG). Format beda tiap bank.

- BRI : CSV, header baris 1, kolom MUTASI_DEBET/KREDIT + SALDO_AKHIR_MUTASI.
- BCA : CSV, ada preamble; header 'Tanggal,Keterangan,Cabang,Jumlah,,Saldo' (DB/CR).
- Mandiri: xlsx e-Statement; header 2 baris; tiap transaksi 2 baris (tgl lalu jam);
  angka format ID (1.000,00).
"""
import re
from decimal import Decimal

import openpyxl

from .base import (
    BaseParser,
    parse_decimal,
    parse_dt,
    read_csv_raw,
    row_hash,
    rows_to_dicts,
)


def _jenis_from_money(money):
    return "depo" if money > 0 else "wd" if money < 0 else "lainnya"


class BRIParser(BaseParser):
    source_key = "bank"

    def parse(self, path, flow=""):
        rows = read_csv_raw(path)
        _, dicts = rows_to_dicts(rows, 0)
        out = []
        for r in dicts:
            debit = parse_decimal(r.get("MUTASI_DEBET"))
            credit = parse_decimal(r.get("MUTASI_KREDIT"))
            money = credit - debit
            occurred = parse_dt(r.get("TGL_TRAN"))
            desc = str(r.get("DESK_TRAN", "") or "")
            m = re.search(r"NBMB (.+?) TO (.+?) ESB", desc)
            sender, receiver = (m.group(1).strip(), m.group(2).strip()) if m else ("", "")
            counterparty = sender if money > 0 else receiver
            seq = str(r.get("SEQ", "") or "").strip()
            row = {
                "source_type": "bank",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": _jenis_from_money(money),
                "amount": abs(money),
                "credit_delta": Decimal("0"),
                "money_delta": money,
                "fee": Decimal("0"),
                "bonus": Decimal("0"),
                "balance_after": parse_decimal(r.get("SALDO_AKHIR_MUTASI")),
                "ticket_no": "",
                "username": "",
                "reference": seq,
                "counterparty": counterparty,
                "description": desc,
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items()},
            }
            row["row_hash"] = row_hash("bri", [r.get("NOREK", ""), seq, occurred, money])
            out.append(row)
        return out


class BCACSVParser(BaseParser):
    source_key = "bank"

    def parse(self, path, flow=""):
        rows = read_csv_raw(path)
        hidx = None
        for i, r in enumerate(rows):
            cells = [str(c).strip() for c in r]
            if "Tanggal" in cells and "Saldo" in cells:
                hidx = i
                break
        if hidx is None:
            return []
        _, dicts = rows_to_dicts(rows, hidx)
        out = []
        for r in dicts:
            jumlah = parse_decimal(r.get("Jumlah"))
            dbcr = ""
            for v in r.values():
                vv = str(v).strip().upper()
                if vv in ("DB", "CR"):
                    dbcr = vv
                    break
            money = jumlah if dbcr == "CR" else -jumlah
            occurred = parse_dt(r.get("Tanggal"), dayfirst=True)
            if occurred is None:  # skip baris ringkasan (Saldo Awal/Akhir/Mutasi)
                continue
            desc = str(r.get("Keterangan", "") or "")
            row = {
                "source_type": "bank",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": _jenis_from_money(money),
                "amount": abs(money),
                "credit_delta": Decimal("0"),
                "money_delta": money,
                "fee": Decimal("0"),
                "bonus": Decimal("0"),
                "balance_after": parse_decimal(r.get("Saldo")),
                "ticket_no": "",
                "username": "",
                "reference": "",
                "counterparty": "",
                "description": desc,
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items()},
            }
            row["row_hash"] = row_hash("bca", [occurred, money, r.get("Saldo", ""), desc[:60]])
            out.append(row)
        return out


class MandiriParser(BaseParser):
    source_key = "bank"

    def parse(self, path, flow=""):
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        allrows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()

        hidx = None
        for i, r in enumerate(allrows):
            cells = [str(c).strip() if c is not None else "" for c in r]
            if "Tanggal" in cells and "Keterangan" in cells:
                hidx = i
                break
        if hidx is None:
            return []
        hdr = [str(c).strip() if c is not None else "" for c in allrows[hidx]]

        def colof(name):
            return hdr.index(name) if name in hdr else None

        c_no, c_tgl, c_ket = colof("No"), colof("Tanggal"), colof("Keterangan")
        c_in, c_out, c_saldo = (
            colof("Dana Masuk (IDR)"),
            colof("Dana Keluar (IDR)"),
            colof("Saldo (IDR)"),
        )

        def cell(r, j):
            return r[j] if (j is not None and j < len(r)) else None

        out = []
        i, n = hidx + 1, len(allrows)
        while i < n:
            r = allrows[i]
            cells = [str(c).strip() if c is not None else "" for c in r]
            if "Date" in cells and "Remarks" in cells:  # sub-header bahasa Inggris
                i += 1
                continue
            no, tgl = cell(r, c_no), cell(r, c_tgl)
            if (no in (None, "")) and (tgl in (None, "")):
                i += 1
                continue

            datestr = str(tgl).strip() if tgl else ""
            ket = str(cell(r, c_ket) or "").strip()
            masuk = parse_decimal(cell(r, c_in), "id")
            keluar = parse_decimal(cell(r, c_out), "id")
            saldo = parse_decimal(cell(r, c_saldo), "id")

            timestr = ""
            if i + 1 < n:
                nr = allrows[i + 1]
                ntgl = str(cell(nr, c_tgl) or "").strip()
                nno = cell(nr, c_no)
                if (nno in (None, "")) and re.search(r"\d{1,2}:\d{2}", ntgl):
                    timestr = ntgl.replace("WIB", "").strip()
                    nket = str(cell(nr, c_ket) or "").strip()
                    if nket:
                        ket = f"{ket} {nket}".strip()
                    i += 1

            occurred = parse_dt(f"{datestr} {timestr}".strip(), dayfirst=True)
            money = masuk - keluar
            row = {
                "source_type": "bank",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": _jenis_from_money(money),
                "amount": abs(money),
                "credit_delta": Decimal("0"),
                "money_delta": money,
                "fee": Decimal("0"),
                "bonus": Decimal("0"),
                "balance_after": saldo,
                "ticket_no": "",
                "username": "",
                "reference": "",
                "counterparty": ket.replace("\n", " "),
                "description": ket.replace("\n", " "),
                "raw": {"Tanggal": datestr, "Jam": timestr, "Keterangan": ket.replace("\n", " "),
                        "Masuk": str(masuk), "Keluar": str(keluar), "Saldo": str(saldo)},
            }
            row["row_hash"] = row_hash("mandiri", [saldo, occurred, money, ket[:30]])
            out.append(row)
            i += 1
        return out
