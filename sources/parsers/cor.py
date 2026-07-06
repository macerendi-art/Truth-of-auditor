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
