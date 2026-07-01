"""Parser Panel (HISTORI DP/WD PANEL, xlsx). Header di baris 2 (baris 1 = judul).

Amount dalam RIBUAN -> dikali 1000 jadi rupiah. Mendeteksi DP vs WD dari kolom.
"""
import re
from decimal import Decimal

from .base import (
    BaseParser,
    extract_ref,
    first_part,
    parse_decimal,
    parse_dt,
    read_xlsx_rows,
    row_hash,
)

SCALE = Decimal(1000)  # 1 kredit = Rp1.000


class PanelParser(BaseParser):
    source_key = "panel"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=2)
        out = []
        for r in rows:
            is_wd = "Withdrawal Amount" in r
            if is_wd:
                jenis = "wd"
                amt = parse_decimal(r.get("Withdrawal Amount")) * SCALE
                credit_delta, money_delta = amt, -amt
                fee = (
                    parse_decimal(r.get("Player Fee Amount"))
                    + parse_decimal(r.get("Agent Fee Amount"))
                ) * SCALE
            else:
                jenis = "depo"
                amt = parse_decimal(r.get("Deposit Amount")) * SCALE
                credit_delta, money_delta = -amt, amt
                fee = (
                    parse_decimal(r.get("Admin Fee"))
                    + parse_decimal(r.get("Agent Fee"))
                    + parse_decimal(r.get("Player Fee"))
                ) * SCALE

            occurred = parse_dt(first_part(r.get("Requested Date")))
            posted = parse_dt(r.get("Bank Statement Date"))
            ticket = str(r.get("Ticket Number", "") or "").strip()
            if not re.match(r"^[DW]\d", ticket):  # skip baris footer/GRAND TOTAL
                continue
            remarks = str(r.get("Remarks", "") or "")

            row = {
                "source_type": "panel",
                "occurred_at": occurred,
                "posted_date": posted.date() if posted else None,
                "jenis": jenis,
                "amount": amt,
                "credit_delta": credit_delta,
                "money_delta": money_delta,
                "fee": fee,
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": ticket,
                "username": str(r.get("User Name", "") or "").strip(),
                "reference": extract_ref(remarks) or str(r.get("Reference", "") or "").strip(),
                "counterparty": str(r.get("Full Name", "") or "").strip(),
                "description": remarks,
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items()},
            }
            row["row_hash"] = row_hash("panel", [ticket, row["username"], row["amount"]])
            out.append(row)
        return out
