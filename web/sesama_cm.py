"""Deteksi mutasi bank/gateway «Sesama CM» — selaras kategori FR Sesama CM.

FR menandai pindah dana internal dengan `raw[\"Kategori\"] == \"Sesama CM\"` dan
menyimpan rekening CM di `raw[\"Bank\"]` (segmen tengah = nama) +
`raw[\"No. Rek Bank Member\"]`.

Filter Mutasi Bank mengikuti identitas yang sama:
1. **Nama CM** dari FR Sesama CM (Bank `| nama |`) digabung owner upload bank
2. **No. rekening** dari FR Sesama CM (digit ≥ 8)
3. Baris money cocok bila counterparty/deskripsi memuat nama **atau** no.rek
   CM **lain** — bukan owner file mutasi yang sedang dibaca (WD member sering
   memuat nama pengirim = owner sendiri di deskripsi).

Tanpa migrasi; query-time; berlaku retroaktif.
"""
from __future__ import annotations

import re
from functools import lru_cache

from django.db.models import Q
from django.db.models.fields.json import KeyTextTransform

# Bukan nama orang CM (FR role / gateway / generik).
_NOISE = frozenset({
    "BANK", "BCA", "BRI", "MANDIRI", "BNI", "DANA", "GOPAY", "OVO", "SHOPEE",
    "QRIS", "NXPAY", "NEXUSPAY", "QHOKI", "RPAY", "ELITE", "FLYER", "GATEWAY",
    "TAMPUNG", "LAYER", "DEPOSIT", "WITHDRAW", "WITHDRAWAL", "WD", "DP", "MUL",
    "CV", "PT", "M", "MBCA", "COSTFINANCE", "TAMPUNGPUSAT", "DEPOSITWITHDRAW",
    "LAINLAIN", "LAIN",
})

_SUFFIX_CUT = re.compile(
    r"\b(TAMPUNG|LAYER|DEPOSIT|WITHDRAW|WITHDRAWAL|WD|DP)\b.*$",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
_DIGITS = re.compile(r"\D+")


def _is_code_token(tok: str) -> bool:
    """Token ekor mirip kode acak nama file (YGLWHAK, LIVVYCU), bukan nama orang."""
    t = (tok or "").upper()
    if not t.isalpha() or not (5 <= len(t) <= 10):
        return False
    vowels = sum(1 for c in t if c in "AEIOU")
    if vowels <= 1:
        return True
    if len(t) >= 6 and vowels / len(t) < 0.30:
        return True
    return False


def _bersih_nama(raw: str) -> str:
    """Normalisasi label CM → nama yang bisa di-match di mutasi."""
    s = " ".join(str(raw or "").split()).strip()
    if not s:
        return ""
    # FR kadang "DEPOSIT / WITHDRAW"
    if "/" in s and not any(c.isalpha() and c.islower() for c in s):
        # tetap proses; noise di-filter lewat compact
        pass
    s = _SUFFIX_CUT.sub("", s).strip()
    s = s.replace("/", " ")
    s = " ".join(s.split())
    parts = s.split()
    while len(parts) >= 2 and _is_code_token(parts[-1]):
        parts.pop()
    s = " ".join(parts).strip()
    compact = _NON_ALNUM.sub("", s).upper()
    if len(compact) < 6:
        return ""
    if compact in _NOISE:
        return ""
    return s


def _nama_dari_bank_fr(bank: str) -> str:
    """`BANK BRI | KIKI SUASANTO | TAMPUNG LAYER 2` → `KIKI SUASANTO`."""
    parts = [p.strip() for p in str(bank or "").split("|")]
    if len(parts) >= 2:
        return _bersih_nama(parts[1])
    return _bersih_nama(bank)


def _digit_rek(raw: str) -> str:
    """`BRI 119101022152500` / `BCA 8447072062` → digit murni (min 8)."""
    d = _DIGITS.sub("", str(raw or ""))
    if len(d) < 8:
        return ""
    # buang placeholder genap (0000007788 masih valid QRIS — biarkan)
    if set(d) <= {"0", "7"} and len(d) <= 7:
        return ""
    return d


def _varian(nama: str) -> list[str]:
    """Varian string untuk icontains: ber-spasi + tanpa spasi (Kikisuasanto)."""
    n = " ".join(str(nama or "").split()).strip()
    if not n:
        return []
    out = []
    seen = set()
    for v in (n, n.replace(" ", ""), n.replace(" ", "").title(), n.title(), n.upper(), n.lower()):
        v = v.strip()
        if len(v) < 6:
            continue
        key = v.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def _tambah_nama(hasil: list[str], seen: set[str], raw: str) -> None:
    n = _bersih_nama(raw)
    if not n:
        return
    key = _NON_ALNUM.sub("", n).upper()
    if key in seen or key in _NOISE:
        return
    seen.add(key)
    hasil.append(n)


@lru_cache(maxsize=64)
def identitas_cm_toko(toko_id: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(nama_cm, no_rek_digit) dari FR Sesama CM + owner upload bank.

    Cache per-process: daftar CM jarang berubah; upload FR baru butuh worker
    recycle / cache clear — cukup untuk filter UI. Tes memanggil
    `identitas_cm_toko.cache_clear()`.
    """
    from sources.models import Upload
    from transactions.models import Transaction

    names: list[str] = []
    seen_n: set[str] = set()
    reks: list[str] = []
    seen_r: set[str] = set()

    # 1) FR Sesama CM — sumber otoritatif (selaras Control Bracket).
    fr = (
        Transaction.objects.filter(toko_id=toko_id, source_type__key="bracket")
        .annotate(
            kat=KeyTextTransform("Kategori", "raw"),
            bank=KeyTextTransform("Bank", "raw"),
            rek=KeyTextTransform("No. Rek Bank Member", "raw"),
        )
        .filter(kat__icontains="sesama")
        .values_list("bank", "rek")
        .distinct()
    )
    for bank, rek in fr.iterator():
        mid = _nama_dari_bank_fr(bank or "")
        if mid:
            key = _NON_ALNUM.sub("", mid).upper()
            if key not in seen_n and key not in _NOISE:
                seen_n.add(key)
                names.append(mid)
        d = _digit_rek(rek or "")
        if d and d not in seen_r:
            # skip nomor super-generik pendek berulang
            if len(set(d)) <= 2 and len(d) < 10:
                continue
            seen_r.add(d)
            reks.append(d)

    # 2) Owner file bank — pelengkap (toko yang FR-nya jarang/ belum ada Sesama CM).
    for raw in (
        Upload.objects.filter(toko_id=toko_id, source_type__key="bank")
        .exclude(owner_name="")
        .values_list("owner_name", flat=True)
        .distinct()
    ):
        _tambah_nama(names, seen_n, raw)

    # Buang token tunggal pendek yang sudah jadi bagian nama multi-kata
    # (cegah "MUHAMMAD"/"SEBASTIAN" menelan WD member).
    names = _saring_nama_ambigu(names)

    names.sort(key=lambda s: (-len(s), s.lower()))
    reks.sort(key=lambda s: (-len(s), s))
    return tuple(names), tuple(reks)


def _saring_nama_ambigu(names: list[str]) -> list[str]:
    """Drop nama 1 kata yang merupakan token di nama CM multi-kata lain."""
    multi_tokens: set[str] = set()
    for n in names:
        parts = n.split()
        if len(parts) >= 2:
            for p in parts:
                multi_tokens.add(p.upper())
    out = []
    for n in names:
        parts = n.split()
        if len(parts) == 1 and parts[0].upper() in multi_tokens:
            continue
        out.append(n)
    return out


def nama_cm_toko(toko_id: int) -> list[str]:
    """Daftar nama CM (FR + upload). API stabil untuk tes/pemanggil lama."""
    return list(identitas_cm_toko(toko_id)[0])


def q_sesama_cm(toko_id: int) -> Q:
    """Filter ORM: mutasi yang merujuk nama/no.rek CM lain (bukan owner file)."""
    names, reks = identitas_cm_toko(toko_id)
    if not names and not reks:
        return Q(pk__in=[])

    total = Q()
    any_branch = False

    for nama in names:
        vars_ = _varian(nama)
        if not vars_:
            continue
        hit = Q()
        self_owner = Q()
        for v in vars_:
            hit |= Q(counterparty__icontains=v) | Q(description__icontains=v)
            self_owner |= Q(upload__owner_name__icontains=v)
        total |= hit & ~self_owner
        any_branch = True

    # No. rek CM: cocok di deskripsi/counterparty. Self-exclusion kasar:
    # baris yang HANYA memuat rek tanpa nama tetap lolos (pindah via norek).
    # Owner file jarang menulis norek sendiri di deskripsi WD member.
    for d in reks:
        total |= Q(counterparty__icontains=d) | Q(description__icontains=d)
        any_branch = True

    if not any_branch:
        return Q(pk__in=[])
    return total


def tandai_sesama_cm(rows, toko_id: int) -> None:
    """Set atribut transient `is_sesama_cm` pada tiap baris (badge UI)."""
    names, reks = identitas_cm_toko(toko_id)
    if not names and not reks:
        for r in rows:
            r.is_sesama_cm = False
        return

    prepared = []
    for nama in names:
        keys = {v.lower() for v in _varian(nama)}
        compact = _NON_ALNUM.sub("", nama).upper()
        prepared.append((keys, compact))

    for r in rows:
        owner_raw = ""
        up = getattr(r, "upload", None)
        if up is not None:
            owner_raw = up.owner_name or ""
        owner_l = owner_raw.lower()
        owner_c = _NON_ALNUM.sub("", owner_raw).upper()
        blob = f"{r.counterparty or ''} {r.description or ''}"
        blob_l = blob.lower()
        blob_c = _NON_ALNUM.sub("", blob).upper()
        blob_digits = _DIGITS.sub("", blob)

        hit = False
        for keys, compact in prepared:
            if owner_l and any(k in owner_l for k in keys):
                continue
            if owner_c and compact and compact in owner_c:
                continue
            if any(k in blob_l for k in keys) or (compact and compact in blob_c):
                hit = True
                break
        if not hit:
            for d in reks:
                if d and d in blob_digits:
                    hit = True
                    break
        r.is_sesama_cm = hit


def clear_cm_cache() -> None:
    """Untuk tes — kosongkan cache identitas CM."""
    identitas_cm_toko.cache_clear()
