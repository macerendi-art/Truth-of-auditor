"""Rekonsiliasi Bonus panel<->bracket — query-time, tanpa menyentuh run_batch.

Baris bonus tak punya ticket/uang — kunci cocok: username (lowercase) +
nominal bulat + tanggal. Pairing 1:1 greedy per kunci; sisa jadi
panel_only / bracket_only. Pola retroaktif seperti hutang.py/biaya.py.
"""
from collections import defaultdict, deque
from datetime import date
from decimal import Decimal

from transactions.models import Transaction

NOL = Decimal("0")


def _baris(t):
    return {
        "id": t.id,
        "tanggal": t.posted_date,
        "username": t.username,
        "kategori": (t.raw or {}).get("Kategori", "") or "Bonus",
        "nominal": t.amount,
        "deskripsi": t.description,
    }


def _kunci(t):
    return ((t.username or "").strip().lower(), int(abs(t.amount or 0)), t.posted_date)


def rekonsiliasi_bonus(toko, dari=None, sampai=None):
    def ambil(key):
        qs = Transaction.objects.filter(
            toko=toko, source_type__key=key, is_duplicate=False)
        if dari:
            qs = qs.filter(posted_date__gte=dari)
        if sampai:
            qs = qs.filter(posted_date__lte=sampai)
        return list(qs.order_by("posted_date", "id"))

    panel, bracket = ambil("panel_bonus"), ambil("bracket_bonus")

    sisa = defaultdict(deque)
    for b in bracket:
        sisa[_kunci(b)].append(b)

    cocok, panel_only = [], []
    for p in panel:
        antre = sisa.get(_kunci(p))
        if antre:
            cocok.append({"panel": _baris(p), "bracket": _baris(antre.popleft())})
        else:
            panel_only.append(_baris(p))
    bracket_only = [_baris(b) for antre in sisa.values() for b in antre]
    bracket_only.sort(key=lambda r: (r["tanggal"] or date.min, r["id"]))

    def _tot(rows):
        return sum((r["nominal"] for r in rows), NOL)

    per_kat = {}

    def _kat(k):
        return per_kat.setdefault(k, {"cocok": 0, "panel_only": 0, "bracket_only": 0})

    for c in cocok:
        _kat(c["panel"]["kategori"])["cocok"] += 1
    for r in panel_only:
        _kat(r["kategori"])["panel_only"] += 1
    for r in bracket_only:
        _kat(r["kategori"])["bracket_only"] += 1

    ringkas = {
        "cocok": {"n": len(cocok), "total": sum((c["panel"]["nominal"] for c in cocok), NOL)},
        "panel_only": {"n": len(panel_only), "total": _tot(panel_only)},
        "bracket_only": {"n": len(bracket_only), "total": _tot(bracket_only)},
        "kategori": dict(sorted(per_kat.items())),
    }
    return {"cocok": cocok, "panel_only": panel_only,
            "bracket_only": bracket_only, "ringkas": ringkas}
