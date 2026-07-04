"""Parser Panel (HISTORI DP/WD PANEL, xlsx). Header di baris 2 (baris 1 = judul).

Amount dalam RIBUAN -> dikali 1000 jadi rupiah. Mendeteksi DP vs WD dari kolom.
"""
import re
from decimal import Decimal

from .base import (
    BaseParser,
    extract_ref,
    first_part,
    normalize_dest,
    parse_decimal,
    parse_dt,
    read_xlsx_rows,
    row_hash,
)

SCALE = Decimal(1000)  # 1 kredit = Rp1.000


def extract_panel_dest(player_bank):
    """Nomor tujuan Panel dari kolom 'Player Bank' (format '<channel>|<nama>|<nomor>').

    Ambil segmen ke-3 (split '|'), lalu normalisasi sama dgn sisi bank. Terisi ~100%
    di data (DANA/GOPAY = HP, bank = norek). Segmen kurang / nomor pendek -> ''."""
    parts = str(player_bank or "").split("|")
    if len(parts) < 3:
        return ""
    return normalize_dest(parts[2])


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
                "dest_account": extract_panel_dest(r.get("Player Bank")),
                "description": remarks,
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items()},
            }
            row["row_hash"] = row_hash("panel", [ticket, row["username"], row["amount"]])
            out.append(row)
        return out
