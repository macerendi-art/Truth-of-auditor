"""Rekonsiliasi Bonus panel<->bracket — query-time, tanpa menyentuh run_batch.

Baris bonus tak punya ticket/uang — kunci cocok: username (lowercase) +
nominal bulat + tanggal. Pairing 1:1 greedy per kunci; sisa jadi
panel_only / bracket_only. Pola retroaktif seperti hutang.py/biaya.py.

Kategori tampilan (query-time, kunci pairing TIDAK berubah): sisi panel memakai
detail program yang diekstrak dari Description ("Promotion Claim: BONUS X -
[D...] - user" -> "BONUS X"), fallback ke kategori kanonik; sisi bracket tetap
kategorinya sendiri (kolom Category sudah detail). Filter kategori dieksekusi
PASCA-pairing (display-only) supaya baris bracket yang terkonsumsi pasangan
tidak berubah oleh filter.
"""
import re
from collections import defaultdict, deque
from datetime import date
from decimal import Decimal

from transactions.models import Transaction

NOL = Decimal("0")

# "<Kategori>: <detail> - [D...]" — lazy berhenti di " - [" pertama; spasi
# ganda pada data nyata ("-  M77user") tertoleransi \s*. Redemption/Lucky
# Draw/Adjustment tak punya segmen " - [" sehingga sengaja TIDAK match.
_DETAIL_RE = re.compile(r"^\s*[^:]+:\s*(.+?)\s*-\s*\[")


def kategori_detail(kategori, deskripsi):
    """Detail program promo dari Description panel; fallback kategori kanonik.

    Hanya pola ber-"[tiket]" yang diekstrak — deskripsi tanpa " - [" (mis.
    "Adjustment: M77ubay789") jatuh ke kategori lama, sehingga username tak
    pernah bocor jadi kategori."""
    m = _DETAIL_RE.match(deskripsi or "")
    if m:
        detail = m.group(1).strip()
        if detail:
            return detail
    return kategori or "Bonus"


def _baris(t, panel=False):
    kategori = (t.raw or {}).get("Kategori", "") or "Bonus"
    return {
        "id": t.id,
        "tanggal": t.posted_date,
        "username": t.username,
        "kategori": kategori,
        # Kategori tampilan: panel diekstrak dari Description, bracket sudah
        # detail dari kolom Category-nya sendiri (jangan regex desc bracket —
        # desc Credit Bonus berisi salinan desc panel).
        "kategori_detail": kategori_detail(kategori, t.description) if panel else kategori,
        "nominal": t.amount,
        "deskripsi": t.description,
    }


def _kunci(t):
    return ((t.username or "").strip().lower(), int(abs(t.amount or 0)), t.posted_date)


def rekonsiliasi_bonus(toko, dari=None, sampai=None, kategori=None):
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
            cocok.append({"panel": _baris(p, panel=True),
                          "bracket": _baris(antre.popleft())})
        else:
            panel_only.append(_baris(p, panel=True))
    bracket_only = [_baris(b) for antre in sisa.values() for b in antre]
    bracket_only.sort(key=lambda r: (r["tanggal"] or date.min, r["id"]))

    # Opsi dropdown dari SEMUA baris (pra-filter). Kategori pasangan diambil
    # sisi panel — sama dengan kunci ringkasan & filter di bawah.
    opsi = sorted(
        {c["panel"]["kategori_detail"] for c in cocok}
        | {r["kategori_detail"] for r in panel_only}
        | {r["kategori_detail"] for r in bracket_only})

    if kategori:
        # Display-only, pairing di atas sudah final — hasil cocok tak berubah.
        cocok = [c for c in cocok if c["panel"]["kategori_detail"] == kategori]
        panel_only = [r for r in panel_only if r["kategori_detail"] == kategori]
        bracket_only = [r for r in bracket_only
                        if r["kategori_detail"] == kategori]

    def _tot(rows):
        return sum((r["nominal"] for r in rows), NOL)

    per_kat = {}

    def _kat(k):
        return per_kat.setdefault(k, {
            "cocok": 0, "panel_only": 0, "bracket_only": 0,
            "cocok_total": NOL, "panel_only_total": NOL,
            "bracket_only_total": NOL})

    for c in cocok:
        d = _kat(c["panel"]["kategori_detail"])
        d["cocok"] += 1
        d["cocok_total"] += c["panel"]["nominal"]
    for r in panel_only:
        d = _kat(r["kategori_detail"])
        d["panel_only"] += 1
        d["panel_only_total"] += r["nominal"]
    for r in bracket_only:
        d = _kat(r["kategori_detail"])
        d["bracket_only"] += 1
        d["bracket_only_total"] += r["nominal"]

    ringkas = {
        "cocok": {"n": len(cocok), "total": sum((c["panel"]["nominal"] for c in cocok), NOL)},
        "panel_only": {"n": len(panel_only), "total": _tot(panel_only)},
        "bracket_only": {"n": len(bracket_only), "total": _tot(bracket_only)},
        "kategori": dict(sorted(per_kat.items())),
    }
    return {"cocok": cocok, "panel_only": panel_only,
            "bracket_only": bracket_only, "ringkas": ringkas,
            "kategori_opsi": opsi}
