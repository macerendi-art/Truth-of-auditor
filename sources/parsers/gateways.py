"""Parser gateway pembayaran (sumber UANG, setara bank): NXPAY, QR FLYER, QHOKI, RPAY."""
import csv
from decimal import Decimal

from .base import BaseParser, parse_decimal, parse_dt, read_xlsx_rows, row_hash


def _money(amount, flow):
    """Tanda money_delta berdasarkan flow file (dp = masuk +, wd = keluar -)."""
    return -amount if flow == "wd" else amount


class NXPayParser(BaseParser):
    source_key = "gateway"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=2)  # baris 1 = judul report
        out = []
        for r in rows:
            ticket = str(r.get("Ticket Number", "") or "").strip()
            if not ticket or "total" in str(r.get("Username", "")).lower():
                continue  # skip footer / Grand Total
            amt = abs(parse_decimal(r.get("Amount")))
            occurred = parse_dt(r.get("Date"))  # format US: M/D/YYYY h:m:s AM/PM
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "wd" if flow == "wd" else "depo",
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": _money(amt, flow),
                "fee": parse_decimal(r.get("Admin Fee")),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": ticket,
                "username": str(r.get("Username", "") or "").strip(),
                "reference": "",
                "counterparty": str(r.get("Account Title", "") or "").strip(),
                "description": f"NXPAY {r.get('Payment Type','')} {r.get('Status','')}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items()},
            }
            row["row_hash"] = row_hash("nxpay", [ticket, row["username"], amt, occurred])
            out.append(row)
        return out


class QRFlyerParser(BaseParser):
    source_key = "gateway"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=1)
        out = []
        for r in rows:
            amt = abs(parse_decimal(r.get("Transaction Value")))
            occurred = parse_dt(r.get("Transaction Date"))
            settle = parse_dt(r.get("Settlement Time"))
            ticket = str(r.get("TXN ID", "") or "").strip()
            ref = str(r.get("Client Reference", "") or "").strip()
            if not ticket and not ref:  # skip footer/total
                continue
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": (settle or occurred).date() if (settle or occurred) else None,
                "jenis": "wd" if flow == "wd" else "depo",
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": _money(amt, flow),
                "fee": Decimal("0"),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": ticket,
                "username": str(r.get("Customer ID / User Account", "") or "").strip(),
                "reference": ref,
                "counterparty": "",
                "description": f"QRFLYER {r.get('Payment Status','')}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items()},
            }
            row["row_hash"] = row_hash("qrflyer", [ticket, ref, amt])
            out.append(row)
        return out


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


class RPayGatewayParser(BaseParser):
    """Gateway QRIS RPay (CSV, dipakai brand panel-Nexus, mis. MUL/M77).

    Membawa `Customer Username` == username panel -> anchor pass-1 username
    exact. `UUID` DISIMPAN di raw saja, TIDAK di `reference`: aturan blocked
    engine mengasingkan gateway ber-reference yang tak dikenal panel dari pass
    identitas, dan panel Nexus TERBUKTI tidak menanam UUID RPay di Remarks
    (verifikasi panel M77 09-Jul-2026: 0 dari 2.058 baris QRISRPAY).
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
