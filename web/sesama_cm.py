"""Deteksi mutasi bank/gateway «Sesama CM» (pindah dana antar rekening CM toko).

Sesama CM di FR = transfer internal antar bank milik toko (bukan DP/WD member).
Di mutasi bank, sinyal yang sama: counterparty / deskripsi memuat **nama pemilik
rekening CM lain** pada toko yang sama — bukan owner file mutasi yang sedang
dibaca (itu pengirim/penerima di statement sendiri, sering muncul di deskripsi WD
ke member).

Sumber nama CM: `Upload.owner_name` file bank toko (hasil header/nama file).
Tanpa migrasi; query-time; berlaku retroaktif.
"""
from __future__ import annotations

import re

from django.db.models import Q

# Token/ entri yang bukan nama orang CM.
_NOISE = frozenset({
    "BANK", "BCA", "BRI", "MANDIRI", "BNI", "DANA", "GOPAY", "OVO", "SHOPEE",
    "QRIS", "NXPAY", "QHOKI", "RPAY", "ELITE", "FLYER", "GATEWAY", "TAMPUNG",
    "LAYER", "DEPOSIT", "WITHDRAW", "WITHDRAWAL", "WD", "DP", "MUL", "CV", "PT",
    "M", "BCA", "MBCA",
})

# Potong sufiks peran/layer + sisa di belakangnya.
_SUFFIX_CUT = re.compile(
    r"\b(TAMPUNG|LAYER|DEPOSIT|WITHDRAW|WITHDRAWAL|WD|DP)\b.*$",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


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
    """Normalisasi owner_name upload → nama orang CM yang bisa di-match."""
    s = " ".join(str(raw or "").split()).strip()
    if not s:
        return ""
    s = _SUFFIX_CUT.sub("", s).strip()
    # Buang 1–2 token kode di ekor selama masih ada nama di depan.
    parts = s.split()
    while len(parts) >= 2 and _is_code_token(parts[-1]):
        parts.pop()
    s = " ".join(parts).strip()
    # Tolak noise murni / terlalu pendek.
    compact = _NON_ALNUM.sub("", s).upper()
    if len(compact) < 6:
        return ""
    if compact in _NOISE:
        return ""
    return s


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


def nama_cm_toko(toko_id: int) -> list[str]:
    """Daftar nama CM unik (sudah dibersihkan) dari upload bank toko."""
    from sources.models import Upload

    mentah = (
        Upload.objects.filter(toko_id=toko_id, source_type__key="bank")
        .exclude(owner_name="")
        .values_list("owner_name", flat=True)
        .distinct()
    )
    seen = set()
    hasil = []
    for raw in mentah:
        n = _bersih_nama(raw)
        if not n:
            continue
        key = _NON_ALNUM.sub("", n).upper()
        if key in seen:
            continue
        seen.add(key)
        hasil.append(n)
    # Nama panjang dulu — memudahkan debug / preferensi match.
    hasil.sort(key=lambda s: (-len(s), s.lower()))
    return hasil


def q_sesama_cm(toko_id: int) -> Q:
    """Filter ORM: baris money yang deskripsi/counterparty memuat nama CM **lain**.

    Untuk tiap nama N: (cp|desc mengandung N) AND (owner file BUKAN N).
    Owner file diuji lewat `upload__owner_name` (icontains tiap varian N).
    """
    names = nama_cm_toko(toko_id)
    if not names:
        return Q(pk__in=[])  # kosong tegas

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
    if not any_branch:
        return Q(pk__in=[])
    return total


def tandai_sesama_cm(rows, toko_id: int) -> None:
    """Set atribut transient `is_sesama_cm` pada tiap baris (tampil badge)."""
    names = nama_cm_toko(toko_id)
    if not names:
        for r in rows:
            r.is_sesama_cm = False
        return

    # Precompute compact keys + varian lower untuk cek Python (sama semangat SQL).
    prepared = []
    for nama in names:
        keys = {v.lower() for v in _varian(nama)}
        compact = _NON_ALNUM.sub("", nama).upper()
        prepared.append((nama, keys, compact))

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
        hit = False
        for _nama, keys, compact in prepared:
            # Skip nama yang merupakan owner file ini.
            if owner_l and any(k in owner_l for k in keys):
                continue
            if owner_c and compact and compact in owner_c:
                continue
            if any(k in blob_l for k in keys) or (compact and compact in blob_c):
                hit = True
                break
        r.is_sesama_cm = hit
