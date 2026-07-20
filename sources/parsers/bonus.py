"""Parser bonus: panel Credit Balance & bracket Credit/Non-Credit Bonus (MUL/M77).

Panel `Credit Balance` = ledger kredit penuh; yang diambil HANYA baris bonus
(Redemption Coupon / Promotion Claim / Lucky Draw Agent / Adjustment). Baris
Deposit/Withdraw/Offset/Opening/Reject dilewati — DP/WD sudah diimpor parser
panel biasa, dan Offset = penyeimbang net-nol Lucky Draw (bukan bonusnya).
Bracket bonus: file `Credit Bonus` (ada kolom Category) dan `Non Credit Bonus`
(tanpa Category; kode di Description — K-BLD = Lucky Draw) — satu parser.

Amt panel dalam RIBUAN (×1000); Nominal bracket sudah rupiah penuh.
Bonus bukan uang: money_delta=0, tak pernah ikut matcher/completeness harian
(SourceType terpisah `panel_bonus`/`bracket_bonus`).
"""
import re
from decimal import Decimal

from .base import BaseParser, parse_decimal, parse_dt, read_xlsx_rows, row_hash

SCALE = Decimal(1000)  # 1 kredit panel = Rp1.000
NOL = Decimal("0")

# Awalan Description panel yang merupakan bonus -> kategori kanonik.
_PANEL_KATEGORI = [
    ("Redemption Coupon", "Redemption Coupon"),
    ("Promotion Claim", "Promotion Claim"),
    ("Lucky Draw Agent", "Lucky Draw"),
    ("Adjustment:", "Adjustment"),
]

# Kode Description bracket non-credit -> kategori kanonik (mapping klien).
KODE_BONUS = {"K-BLD": "Lucky Draw"}

_PLAYER_RE = re.compile(r"Player:\s*(.+)", re.IGNORECASE)


def _username_panel(desc, brand):
    """Token terakhir Description; buang prefix brand ('M77Maxx28' -> 'Maxx28')."""
    tokens = desc.split()
    if not tokens:
        return ""
    u = tokens[-1]
    if brand and u.lower().startswith(brand.lower()) and len(u) > len(brand):
        u = u[len(brand):]
    return u.strip()


class PanelBonusParser(BaseParser):
    source_key = "panel_bonus"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=2)
        out = []
        for r in rows:
            desc = str(r.get("Description", "") or "").strip()
            kategori = next(
                (k for pfx, k in _PANEL_KATEGORI if desc.startswith(pfx)), None)
            if kategori is None:
                continue  # Deposit/Withdraw/Offset/Opening/Reject dll.
            amt = parse_decimal(r.get("Amt.")) * SCALE
            occurred = parse_dt(r.get("Date & Time"))
            brand = str(r.get("Brand", "") or "").strip()
            raw = {k: ("" if v is None else str(v)) for k, v in r.items()}
            raw["Kategori"] = kategori
            row = {
                "source_type": "panel_bonus",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "bonus",
                "amount": abs(amt),
                "credit_delta": amt,  # negatif = kredit keluar ke player
                "money_delta": NOL,
                "fee": NOL,
                "bonus": abs(amt),
                "balance_after": None,
                "ticket_no": "",
                "username": _username_panel(desc, brand),
                "reference": "",
                "counterparty": "",
                "description": desc,
                "player_bank": "",
                "bank_title": "",
                "raw": raw,
            }
            row["row_hash"] = row_hash(
                "panel_bonus", [raw.get("Date & Time", ""), desc, row["amount"]])
            out.append(row)
        return out


class BracketBonusParser(BaseParser):
    source_key = "bracket_bonus"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=1)
        out = []
        for r in rows:
            if str(r.get("Deleted", "") or "").strip().lower() == "yes":
                continue
            desc = str(r.get("Description", "") or "").strip()
            tid = str(r.get("Transaction ID", "") or "").strip()
            if not desc and not tid:
                continue  # baris kosong/footer
            kategori = str(r.get("Category", "") or "").strip()
            if not kategori:
                kode = desc.split()[0] if desc.split() else ""
                kategori = KODE_BONUS.get(kode, kode or "Bonus")
            m = _PLAYER_RE.search(desc)
            nominal = abs(parse_decimal(r.get("Nominal")))  # rupiah penuh
            occurred = parse_dt(r.get("Date"))
            raw = {k: ("" if v is None else str(v)) for k, v in r.items()}
            raw["Kategori"] = kategori
            row = {
                "source_type": "bracket_bonus",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "bonus",
                "amount": nominal,
                "credit_delta": -nominal,
                "money_delta": NOL,
                "fee": NOL,
                "bonus": nominal,
                "balance_after": None,
                "ticket_no": "",
                "username": (m.group(1).strip() if m else ""),
                "reference": "",
                "counterparty": "",
                "description": desc,
                "player_bank": "",
                "bank_title": "",
                "raw": raw,
            }
            row["row_hash"] = row_hash(
                "bracket_bonus", [tid, raw.get("Date", ""), desc, row["amount"]])
            out.append(row)
        return out
