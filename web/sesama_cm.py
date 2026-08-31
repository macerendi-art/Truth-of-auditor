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

# Nama depan sangat umum di ID — jangan jadi varian/token-match mandiri.
# BTS 25-08: CM FR «MUHAMMAD YUDHA» menelan WD member «MUHAMMAD ICHSAN» /
# «MUHAMMAD ILHAM…» / «MUHAMMAD MISBAHUDDIN» lewat icontains «MUHAMMAD».
_NAMA_DEPAN_UMUM = frozenset({
    "MUHAMMAD", "MUHAMAD", "MOHAMMAD", "MOHAMAD", "MUHAMMED", "MOHAMMED",
    "MOCH", "MOCHAMAD", "MOCHAMMAD", "MUCHAMMAD", "MUH", "MOH",
    "AHMAD", "AHMED", "ABDUL", "ABD", "SITI", "NUR",
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


def _varian_blob(nama: str) -> list[str]:
    """Varian untuk match di counterparty/deskripsi — **tanpa** token pertama pendek.

    Token pertama (`APRI`, `ANDRI`) dulu ikut `_varian` + `icontains` blob →
    false Sesama CM: OKE 30-08 merchant `RAPRI` ⊂ token `APRI` (CM APRI YANI),
    cp `HANDRI` ⊂ token `ANDRI` (CM ANDRI FIRMANSYAH). Nama lengkap /
    compact (`APRIYANI`, `ANDRIFIRMANSYAH`) tetap cukup untuk pair bank benar.
    """
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


def _varian(nama: str) -> list[str]:
    """Varian icontains: blob-safe + token pertama untuk **owner** self-exclude.

    Token pertama (≥4, bukan noise/nama-depan-umum) hanya aman di owner file
    (`SERVA` / `NASRUL`), bukan di cp/desc member (lihat `_varian_blob`).
    """
    n = " ".join(str(nama or "").split()).strip()
    if not n:
        return []
    out = list(_varian_blob(n))
    seen = {v.lower() for v in out}
    first = n.split()[0] if n.split() else ""
    fu = first.upper()
    if (
        len(first) >= 4
        and first.lower() not in seen
        and fu not in _NOISE
        and fu not in _NAMA_DEPAN_UMUM
    ):
        out.append(first)
        seen.add(first.lower())
    return out


def _compact_nama(s: str) -> str:
    return _NON_ALNUM.sub("", str(s or "")).upper()


def cm_names_match(a: str, b: str, *, min_ratio: float = 90.0) -> bool:
    """True bila dua label CM merujuk orang yang sama (typo FR vs owner bank).

    Contoh: YULIAYANTI PRATIWI ≈ YULIYANTI PRATIWI (ratio ~97),
    KIKI SUASANTO ≈ KIKISUASANTO, SERVA ≈ SERVA MUHAMAD SEBASTIAN (prefix token).

    **Bukan** cocok pendek: `HOKI` ⊂ `TPQRISHOKIUNITED` — itu menelan seluruh
    mutasi DP QHOKI (owner file a/n HOKI) sebagai Sesama CM (BTS 23-08-2026).
    Substring containment butuh min 6 karakter di sisi pendek.
    """
    ca, cb = _compact_nama(a), _compact_nama(b)
    if not ca or not cb or len(ca) < 4 or len(cb) < 4:
        return False
    if ca == cb:
        return True
    # containment: sisi pendek ≥6 agar "HOKI"/"RPAY" tidak menelan channel FR
    short, long_ = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    if len(short) >= 6 and short in long_:
        return True
    # token pertama sama + cukup panjang — HANYA bila salah satu sisi single-token
    # (SERVA ≈ SERVA MUHAMAD SEBASTIAN). Bukan MUHAMMAD ICHSAN ≈ MUHAMMAD YUDHA
    # (keduanya multi-kata, orang beda; BTS 25-08 false Sesama CM).
    ta = (str(a or "").split() or [""])[0]
    tb = (str(b or "").split() or [""])[0]
    cta, ctb = _compact_nama(ta), _compact_nama(tb)
    if (
        cta
        and ctb
        and len(cta) >= 5
        and cta == ctb
        and cta not in _NOISE
        and cta not in _NAMA_DEPAN_UMUM
        and (len(ca) == len(cta) or len(cb) == len(ctb))
        and (len(ca) >= 6 or len(cb) >= 6)
    ):
        return True
    try:
        from rapidfuzz import fuzz
        if min(len(ca), len(cb)) >= 8 and fuzz.ratio(ca, cb) >= min_ratio:
            return True
        if min(len(ca), len(cb)) >= 6 and fuzz.partial_ratio(ca, cb) >= 95:
            return True
    except Exception:
        if abs(len(ca) - len(cb)) <= 2 and len(ca) >= 8:
            diff = sum(1 for x, y in zip(ca, cb) if x != y) + abs(len(ca) - len(cb))
            if diff <= 2:
                return True
    return False


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


def _norm_elite_label(desc: str) -> str:
    """Samakan `QRIS ELITE` (spasi, parser OKE) dengan `QRISELITE` (tanpa spasi)."""
    return (desc or "").upper().replace("QRIS ELITE", "QRISELITE")


def _is_tampung_qr_desc(desc: str) -> bool:
    """True bila deskripsi baris mutasi tampung Flyer/Elite."""
    d = _norm_elite_label(desc)
    return "QRFLYER TAMPUNG" in d or "QRISELITE TAMPUNG" in d


def _is_gateway_member_money(desc: str) -> bool:
    """DP/WD member gateway (QHOKI, Flyer, …) — BUKAN Sesama CM.

    Sesama CM untuk jalur gateway hanya mutasi **tampung** (payout float).
    DP QRIS HOKI owner=HOKI dulu tertelan karena `HOKI` ⊂ `TP QRISHOKI UNITED`
    (BTS 23-08-2026).

    OKE 30-08: desc parser = `QRIS ELITE RAPRI…` / `WD QRIS ELITE SEABANK`
    (ada spasi + prefix WD) — dulu cuma `QRISELITE` exact-prefix → lolos guard.
    """
    raw = (desc or "").strip().upper()
    if not raw:
        return False
    if _is_tampung_qr_desc(raw):
        return False
    d = _norm_elite_label(raw)
    # "WD QRIS ELITE …" / "DP QRISELITE …" → cek setelah buang arah
    d_check = d
    for lead in ("WD ", "DP ", "WITHDRAW ", "DEPOSIT "):
        if d_check.startswith(lead):
            d_check = d_check[len(lead):].lstrip()
            break
    prefixes = (
        "QHOKI",
        "QRFLYER",
        "QRISELITE",
        "NXPAY",
        "RPAY",
        "KINGSPAY",
        "ZPAY",
        "COR QRIS",
        "CORQRIS",
        "QRIS HOKI",
        "QRISHOKI",
    )
    return any(d_check.startswith(p) or d.startswith(p) for p in prefixes)


def _is_bank_dp_upload(upload) -> bool:
    """True bila nama file mutasi bank bertoken DP (Deposit).

    Contoh: ``23-08-2026 TGS MUTASI DP BRI KARIS….csv``, ``( BRI DP ) KARIS…``.
    Seluruh baris di file DP = uang masuk ke rekening — **bukan** Sesama CM
    (TGS/BTS 23-08: BFST/DANA + norek FR ikut badge CM).
    """
    if upload is None:
        return False
    name = getattr(upload, "original_name", None) or ""
    if not name:
        return False
    try:
        from sources.flow import detect_flow
        return detect_flow(name) == "dp"
    except Exception:
        return False


def _q_bukan_bank_dp_upload(toko_id: int) -> Q:
    """ORM: kecualikan baris dari upload bank berlabel DP di nama file."""
    from sources.models import Upload

    dp_ids = [
        u.id
        for u in Upload.objects.filter(toko_id=toko_id, source_type__key="bank")
        .only("id", "original_name")
        .iterator(chunk_size=200)
        if _is_bank_dp_upload(u)
    ]
    if not dp_ids:
        return Q()  # tidak mengecualikan apa pun
    return ~Q(upload_id__in=dp_ids)


def _q_bukan_gateway_member() -> Q:
    """ORM: kecualikan DP/WD member gateway (tetap izinkan tampung)."""
    # Tampung lolos lewat cabang T terpisah; di sini blok member-only.
    # Elite: `QRISELITE` dan `QRIS ELITE` (+ prefix WD/DP) — OKE parser pakai spasi.
    elite_member = (
        Q(description__istartswith="QRISELITE")
        | Q(description__istartswith="QRIS ELITE")
        | Q(description__istartswith="WD QRISELITE")
        | Q(description__istartswith="WD QRIS ELITE")
        | Q(description__istartswith="DP QRISELITE")
        | Q(description__istartswith="DP QRIS ELITE")
    ) & ~Q(description__icontains="TAMPUNG")
    blok = (
        Q(description__istartswith="QHOKI")
        | Q(description__istartswith="NXPAY")
        | Q(description__istartswith="RPAY")
        | Q(description__istartswith="KINGSPAY")
        | Q(description__istartswith="ZPAY")
        | Q(description__istartswith="COR QRIS")
        | Q(description__istartswith="CORQRIS")
        | (
            Q(description__istartswith="QRFLYER")
            & ~Q(description__icontains="TAMPUNG")
        )
        | elite_member
    )
    return ~blok


def _alnum_upper_expr(field_name: str):
    """Ekspresi ORM: UPPER + buang spasi/tanda — setara `_compact_nama` di Python.

    Chained Replace (bukan regexp) → jalan di SQLite tes + Postgres prod.
    OKE: `MARIO KARO-KARO` / `MARIO KARO KARO` ↔ compact `MARIOKAROKARO`.
    """
    from django.db.models import CharField, F, Value
    from django.db.models.functions import Cast, Coalesce, Replace, Upper

    # Cast ke CharField dulu — counterparty/desc bisa TextField vs CharField campur
    expr = Upper(Coalesce(Cast(F(field_name), CharField()), Value("")))
    for ch in (" ", "-", ".", "/", "|", "_", "'", '"', ","):
        expr = Replace(expr, Value(ch), Value(""))
    # pastikan output_field eksplisit (hindari FieldError mixed types)
    return Cast(expr, CharField())


def _is_settlement_counterparty(cp: str) -> bool:
    """Kredit settlement ke rekening CM (bukan DP member).

    OKE 30-08: `PT SAHABAT KIRIM D` / `SAHABAT KIRIM DIGITA` masuk BCA MARIO
    (PINDAH DANA ROMEQR / PENCAIRAN QRIS ELITE) — cp terisi nama PT, dulu
    ditolak cabang opaque (hanya cp kosong).
    """
    u = " ".join(str(cp or "").split()).strip().upper()
    if not u:
        return True  # opaque kosong = settlement/unknown credit di rekening CM
    if u.startswith("PT ") or u.startswith("CV ") or u.startswith("UD "):
        return True
    markers = (
        "SAHABAT KIRIM",
        "KIRIM DIGIT",
        "KIRIM DIGITA",
        "ROMEQR",
        "ROME QR",
    )
    return any(m in u for m in markers)


def _q_settlement_or_empty_cp() -> Q:
    return (
        Q(counterparty="")
        | Q(counterparty__isnull=True)
        | Q(counterparty__istartswith="PT ")
        | Q(counterparty__istartswith="CV ")
        | Q(counterparty__istartswith="UD ")
        | Q(counterparty__icontains="SAHABAT KIRIM")
        | Q(counterparty__icontains="KIRIM DIGIT")
        | Q(counterparty__icontains="ROMEQR")
    )


def _build_sesama_cm_q(toko_id: int, *, use_compact_ann: bool) -> Q:
    """Inti filter Sesama CM.

    `use_compact_ann=True` butuh queryset sudah di-annotate
    `_scm_cp_c` / `_scm_desc_c` / `_scm_owner_c` (lihat `filter_sesama_cm`).
    """
    names, reks = identitas_cm_toko(toko_id)

    total = Q()
    any_branch = False

    # T) Mutasi tampung Flyer/Elite — produk = pindah dana internal
    total |= (
        Q(description__icontains="QRFLYER TAMPUNG")
        | Q(description__icontains="QRISELITE TAMPUNG")
        | Q(description__icontains="QRIS ELITE TAMPUNG")
    )
    any_branch = True

    if not names and not reks:
        return total

    bukan_gw_member = _q_bukan_gateway_member()
    bukan_bank_dp = _q_bukan_bank_dp_upload(toko_id)
    settle_cp = _q_settlement_or_empty_cp()

    for nama in names:
        blob_vars = _varian_blob(nama)
        owner_vars = _varian(nama)
        compact = _NON_ALNUM.sub("", nama).upper()
        if not blob_vars and not owner_vars and len(compact) < 6:
            continue
        hit = Q()
        self_owner = Q()
        for v in blob_vars:
            hit |= Q(counterparty__icontains=v) | Q(description__icontains=v)
        if use_compact_ann and len(compact) >= 6:
            hit |= Q(_scm_cp_c__contains=compact) | Q(_scm_desc_c__contains=compact)
        for v in owner_vars:
            self_owner |= Q(upload__owner_name__icontains=v)
        if use_compact_ann and len(compact) >= 6:
            self_owner |= Q(_scm_owner_c__contains=compact)
        first = (nama.split() or [""])[0]
        fu = first.upper()
        if len(first) >= 4 and fu not in _NOISE and fu not in _NAMA_DEPAN_UMUM:
            self_owner |= Q(upload__owner_name__icontains=first)
        if hit:
            total |= hit & ~self_owner & bukan_gw_member & bukan_bank_dp
            any_branch = True

        # A) Kredit opaque / settlement PT ke rekening CM (owner ≈ CM)
        own = Q()
        for v in owner_vars:
            own |= Q(upload__owner_name__icontains=v)
        if use_compact_ann and len(compact) >= 6:
            own |= Q(_scm_owner_c__contains=compact)
        if len(first) >= 4 and fu not in _NOISE and fu not in _NAMA_DEPAN_UMUM:
            own |= Q(upload__owner_name__icontains=first)
        if own:
            total |= (
                own
                & Q(money_delta__gt=0)
                & settle_cp
                & Q(source_type__key="bank")
                & bukan_bank_dp
            )
            any_branch = True

    for d in reks:
        total |= (
            (Q(counterparty__icontains=d) | Q(description__icontains=d))
            & bukan_gw_member
            & bukan_bank_dp
        )
        any_branch = True

    if not any_branch:
        return Q(pk__in=[])
    return total


def q_sesama_cm(toko_id: int) -> Q:
    """Filter ORM kasar (icontains + settlement).

    **Compact space/hyphen** (`MARIO KARO KARO` ↔ `MARIOKAROKARO`) butuh
    `filter_sesama_cm(qs, toko_id)` — annotate + contains compact.
    """
    return _build_sesama_cm_q(toko_id, use_compact_ann=False)


def filter_sesama_cm(qs, toko_id: int):
    """Filter queryset mutasi Sesama CM — **compact-safe** (selaras `tandai_sesama_cm`).

    Pakai ini di engine / Mutasi Bank / B2. Jangan andalkan `q_sesama_cm` saja
    untuk pair nama ber-spasi/hyphen.
    """
    qs = qs.annotate(
        _scm_cp_c=_alnum_upper_expr("counterparty"),
        _scm_desc_c=_alnum_upper_expr("description"),
        _scm_owner_c=_alnum_upper_expr("upload__owner_name"),
    )
    return qs.filter(_build_sesama_cm_q(toko_id, use_compact_ann=True)).distinct()


def tandai_sesama_cm(rows, toko_id: int) -> None:
    """Set atribut transient `is_sesama_cm` pada tiap baris (badge UI)."""
    names, reks = identitas_cm_toko(toko_id)

    prepared = []
    for nama in names:
        keys_blob = {v.lower() for v in _varian_blob(nama)}
        keys_owner = {v.lower() for v in _varian(nama)}
        compact = _NON_ALNUM.sub("", nama).upper()
        prepared.append((nama, keys_blob, keys_owner, compact))

    for r in rows:
        # Tampung QR dulu — tidak butuh daftar CM FR
        if _is_tampung_qr_desc(r.description or ""):
            r.is_sesama_cm = True
            continue

        # DP/WD member gateway (QHOKI, Flyer biasa, …) → Deposit/Withdraw, bukan CM
        if _is_gateway_member_money(r.description or ""):
            r.is_sesama_cm = False
            continue

        owner_raw = ""
        up = getattr(r, "upload", None)
        if up is not None:
            owner_raw = up.owner_name or ""

        src = getattr(getattr(r, "source_type", None), "key", None) or ""
        # File mutasi bank berlabel DP → seluruh baris Deposit/biaya, bukan Sesama CM
        if src == "bank" and _is_bank_dp_upload(up):
            r.is_sesama_cm = False
            continue

        if not names and not reks:
            r.is_sesama_cm = False
            continue

        owner_l = owner_raw.lower()
        owner_c = _NON_ALNUM.sub("", owner_raw).upper()
        blob = f"{r.counterparty or ''} {r.description or ''}"
        blob_l = blob.lower()
        blob_c = _NON_ALNUM.sub("", blob).upper()
        blob_digits = _DIGITS.sub("", blob)

        hit = False
        for nama, keys_blob, keys_owner, compact in prepared:
            # self: owner = CM ini (termasuk SERVA vs SERVA MUHAMAD…)
            if owner_raw and cm_names_match(owner_raw, nama):
                continue
            if owner_l and any(k in owner_l for k in keys_owner):
                continue
            if owner_c and compact and (compact in owner_c or owner_c in compact):
                continue
            # blob: hanya nama lengkap/compact — jangan token pendek APRI⊂RAPRI
            if any(k in blob_l for k in keys_blob) or (compact and compact in blob_c):
                hit = True
                break
            # fuzzy: counterparty ≈ nama CM lain
            cp = r.counterparty or ""
            if cp and cm_names_match(cp, nama) and not (
                owner_raw and cm_names_match(owner_raw, nama)
            ):
                hit = True
                break
        if not hit:
            for d in reks:
                if d and d in blob_digits:
                    hit = True
                    break
        # A opaque / settlement credit on CM-owned **bank** (bukan file DP)
        if not hit and src == "bank" and not _is_bank_dp_upload(up):
            try:
                md = r.money_delta
                is_credit = md is not None and md > 0
            except Exception:
                is_credit = False
            if is_credit and owner_raw and _is_settlement_counterparty(r.counterparty or ""):
                for nama, _kb, _ko, _c in prepared:
                    if cm_names_match(owner_raw, nama):
                        hit = True
                        break
        r.is_sesama_cm = hit


def clear_cm_cache() -> None:
    """Untuk tes — kosongkan cache identitas CM."""
    identitas_cm_toko.cache_clear()
