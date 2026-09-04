"""Hutang/Piutang — daftar baris FR berkategori hutang/piutang, query-time.

Pola sama `web/breakdown.py`: baca `Transaction.raw` bracket tanpa migrasi,
berlaku retroaktif untuk data lama. Read-only murni terhadap Transaction.

Overlay opsional: `web.models.HutangManual` menimpa **total per bulan**
untuk toko tunggal. Satu bulan atau lintas bulan: tiap bulan yang punya
override memakai nilai manual; bulan tanpa override memakai Σ FR auto.
Baris FR di tabel tetap mentah.

**Perf (D2, 2026-09-04): dua-fase, bukan "kurangi jumlah query".** Diukur
lokal (lihat laporan) sebelum menyentuh apa pun: pada data bertingkat
produksi (banyak baris bracket, sedikit yang berkategori hutang/piutang),
biaya sebenarnya adalah SATU scan yang memaksa Postgres mengekstrak
`raw->>'Kategori'` dan menjalankan regex per baris — tanpa index (index
JSONB ada di `Bank`, bukan `Kategori`; menambah satu butuh migrasi di
`transactions/`, di luar wewenang berkas ini). Memecah scan itu jadi
count+aggregate+slice TERPISAH (pola lazy-QuerySet biasa) TERBUKTI lebih
LAMBAT di sini — tiap query baru membayar ulang scan mahal yang sama.
Yang benar-benar mengurangi kerja: satu scan itu tetap SATU kali, tapi
kolom yang diekstraknya dipersempit ke yang perlu untuk filter+urutan+total
(id, tanggal, nominal, kategori, jam — bukan Bank/Member/Username/Expense).
Kolom "berat" itu ditunda ke query KEDUA yang di-PK (`id__in`) — indeks
primer, jadi tak pernah mengulang scan mahal — dan hanya membayar untuk
baris yang BENAR-BENAR dibaca (satu halaman lewat `Paginator`, atau semua
baris kalau memang diiterasi penuh). `_HutangRows` di bawah adalah objek
lazy itu.
"""
from calendar import monthrange
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models.fields.json import KeyTextTransform

from transactions.models import KATEGORI_HUTANG_PIUTANG_REGEX, Transaction
from web.breakdown import _slug_kategori

NOL = Decimal("0")

# Kolom "berat": tiap satu berarti satu ekstraksi JSON tambahan per baris.
# Hanya perlu utk baris yang benar-benar ditampilkan — lihat `_HutangRows`.
_KOLOM_BERAT = ("Bank", "Member", "Username", "Expense")


def _meta_manual(obj):
    """Snapshot metadata overlay untuk template/audit UI."""
    if obj is None:
        return None
    oleh = ""
    if obj.dibuat_oleh_id:
        oleh = getattr(obj.dibuat_oleh, "username", "") or ""
    return {
        "nilai": obj.nilai,
        "tanggal": obj.tanggal,
        "catatan": obj.catatan or "",
        "oleh": oleh,
        "periode": obj.periode,
        "updated_at": obj.updated_at,
    }


def _bulan_dalam_rentang(dari, sampai):
    """Daftar tanggal-1 tiap bulan yang bersinggungan [dari, sampai]."""
    if not dari or not sampai or dari > sampai:
        return []
    cur = date(dari.year, dari.month, 1)
    end = date(sampai.year, sampai.month, 1)
    out = []
    while cur <= end:
        out.append(cur)
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return out


def _overlay_total_bulanan(toko, dari, sampai, total_h, total_p, auto_bulan):
    """Timpa total per bulan bila ada HutangManual (satu atau multi bulan).

    Multi-toko (list) tidak di-overlay — form tulis single-toko saja.
    Tanpa dari/sampai: tidak di-overlay (tak ada kunci bulan).

    `auto_bulan` sudah dihitung SEKALI di `hutang_piutang` (dari scan ringan
    yang sama yang menghasilkan total_h/total_p) — fungsi ini tidak lagi
    mengulang query atau iterasi baris apa pun.

    Per bulan M dalam rentang:
      - ada override field → pakai nilai manual (total bulan, tidak di-prorata)
      - tidak ada → pakai Σ FR auto baris di bulan itu (sudah ter-clip filter)
    Total = jumlah kontribusi semua bulan.
    """
    kosong = {
        "hutang": None, "piutang": None, "aktif": False,
        "periode": None, "periodes": [],
        "asli_hutang": total_h, "asli_piutang": total_p,
        "bulan_override": [],
    }
    if toko is None or isinstance(toko, (list, tuple, set, frozenset)):
        return total_h, total_p, kosong
    if not dari or not sampai:
        return total_h, total_p, kosong

    from web.models import HutangManual

    bulan = _bulan_dalam_rentang(dari, sampai)
    if not bulan:
        return total_h, total_p, kosong

    manuals = list(
        HutangManual.objects
        .filter(toko=toko, periode__in=bulan)
        .select_related("dibuat_oleh")
    )
    if not manuals:
        meta = dict(kosong)
        meta["periode"] = bulan[0] if len(bulan) == 1 else None
        meta["periodes"] = bulan
        return total_h, total_p, meta

    by_manual = {}
    for m in manuals:
        by_manual[(m.periode, m.field)] = m

    out_h, out_p = NOL, NOL
    bulan_override = []
    # Meta field: pakai manual terbaru (periode terbesar) yang ter-apply — UI badge.
    h_meta_obj = None
    p_meta_obj = None

    for periode in bulan:
        ah = auto_bulan.get(periode, {}).get("hutang", NOL)
        ap = auto_bulan.get(periode, {}).get("piutang", NOL)
        mh = by_manual.get((periode, HutangManual.FIELD_HUTANG))
        mp = by_manual.get((periode, HutangManual.FIELD_PIUTANG))
        used = False
        if mh is not None:
            out_h += mh.nilai
            h_meta_obj = mh
            used = True
        else:
            out_h += ah
        if mp is not None:
            out_p += mp.nilai
            p_meta_obj = mp
            used = True
        else:
            out_p += ap
        if used:
            bulan_override.append(periode)

    return out_h, out_p, {
        "hutang": _meta_manual(h_meta_obj),
        "piutang": _meta_manual(p_meta_obj),
        "aktif": True,
        "periode": bulan_override[-1] if len(bulan_override) == 1 else None,
        "periodes": bulan,
        "asli_hutang": total_h,
        "asli_piutang": total_p,
        "bulan_override": bulan_override,
    }


class _HutangRows:
    """Sequence lazy: `Paginator`/iterasi penuh membaca kolom berat hanya
    untuk baris yang benar-benar dibutuhkan — lihat catatan modul di atas.

    `count()`/`__len__`/`__bool__` tidak pernah query lagi (jumlah baris
    sudah diketahui dari scan fase-1). `__getitem__`/`__iter__` menjalankan
    SATU query tambahan yang di-PK (`id__in`) untuk baris yang diminta.
    """

    def __init__(self, urut_ids, meta_by_id, banyak):
        self._ids = urut_ids
        self._meta = meta_by_id
        self._banyak = banyak

    def count(self):
        return len(self._ids)

    def __len__(self):
        return len(self._ids)

    def __bool__(self):
        return bool(self._ids)

    def _detail(self, ids):
        """Query kedua, di-PK — TIDAK mengulang filter kategori mahal.

        `.order_by()` eksplisit: kita hanya butuh dict per-id (urutan tampil
        datang dari `self._ids`, bukan dari query ini) — tanpa ini, `Meta`
        yang kelak dapat `ordering` akan diam-diam menambah sort atas
        `id__in` untuk nol manfaat.
        """
        if not ids:
            return {}
        anotasi = {f"fr_{k.lower()}": KeyTextTransform(k, "raw") for k in _KOLOM_BERAT}
        kolom = ["id"] + [f"fr_{k.lower()}" for k in _KOLOM_BERAT]
        qs = (Transaction.objects.filter(id__in=ids).annotate(**anotasi)
              .order_by().values_list(*kolom))
        return {baris[0]: baris[1:] for baris in qs}

    def _bentuk(self, pk, detail):
        meta = self._meta[pk]
        # Urutan tuple `detail` = urutan `_KOLOM_BERAT` ("Bank","Member",
        # "Username","Expense") — kopling posisional yang disengaja, jaga
        # keduanya sinkron kalau menambah/mengubah kolom berat.
        bank, member, username, expense = detail
        baris = {
            "id": pk, "tanggal": meta["tanggal"], "jam": meta["jam"],
            "account": str(bank or "").strip() or "(Tanpa Akun)",
            "kategori": meta["kategori"],
            "member": str(member or "").strip() or str(username or "").strip(),
            "keterangan": str(expense or "").strip(),
            "nominal": meta["nominal"],
        }
        if self._banyak:
            baris["toko"] = meta["toko"]
        return baris

    def __iter__(self):
        kosong = (None, None, None, None)
        detail = self._detail(self._ids)
        for pk in self._ids:
            yield self._bentuk(pk, detail.get(pk, kosong))

    def __getitem__(self, key):
        kosong = (None, None, None, None)
        if isinstance(key, slice):
            ids = self._ids[key]
            detail = self._detail(ids)
            return [self._bentuk(pk, detail.get(pk, kosong)) for pk in ids]
        idx = key if key >= 0 else key + len(self._ids)
        if idx < 0 or idx >= len(self._ids):
            raise IndexError("_HutangRows index out of range")
        pk = self._ids[idx]
        detail = self._detail([pk])
        return self._bentuk(pk, detail.get(pk, kosong))


def hutang_piutang(toko, dari=None, sampai=None):
    """Baris bracket berkategori Hutang/Piutang + ringkasan total.

    `toko` boleh satu objek Toko ATAU list/tuple/set Toko (mode Semua Toko):
    daftar toko dijalankan lewat satu `toko__in`, bukan satu query per toko.
    Mode banyak-toko menambahkan kunci `"toko"` (nama) pada tiap baris; bentuk
    baris mode satu-toko sengaja dibiarkan PERSIS seperti semula supaya halaman
    lama tak perlu tahu apa-apa tentang mode ini.

    Filter kategori didorong ke DB (iregex pada key JSON) supaya scan tetap
    SATU kali; slug final tetap lewat `_slug_kategori` agar normalisasi
    varian ejaan satu pintu. `"rows"` adalah `_HutangRows` (lazy, lihat
    docstring modul) — berperilaku seperti list untuk iterasi/indeks/
    `Paginator`, tapi menunda kolom berat ke baris yang benar-benar dibaca.

    Bila toko tunggal + ada `HutangManual` pada bulan dalam rentang,
    `total_hutang` / `total_piutang` / `netto` memakai nilai override per bulan
    (bulan lain tetap auto). Baris FR tidak diubah. Metadata di kunci `manual`.
    """
    banyak = isinstance(toko, (list, tuple, set, frozenset))
    lingkup = {"toko__in": list(toko)} if banyak else {"toko": toko}
    qs = Transaction.objects.filter(source_type__key="bracket", **lingkup)
    if dari:
        qs = qs.filter(posted_date__gte=dari)
    if sampai:
        qs = qs.filter(posted_date__lte=sampai)

    # Fase 1 — SATU scan mahal (regex kategori, tanpa index). Kolom SEMPIT:
    # hanya yang perlu utk filter + urutan + total. Bank/Member/Username/
    # Expense ditunda ke `_HutangRows` (fase 2, di-PK).
    kolom_ringan = ["id", "posted_date", "money_delta"]
    qs = (
        qs.annotate(
            fr_kategori=KeyTextTransform("Kategori", "raw"),
            fr_jam=KeyTextTransform("Jam", "raw"),
        )
        .filter(fr_kategori__iregex=KATEGORI_HUTANG_PIUTANG_REGEX)
    )
    kolom_ringan += ["fr_kategori", "fr_jam"]
    if banyak:
        kolom_ringan.append("toko__name")

    meta_by_id = {}
    urutan = []  # (tanggal_key, jam_key, id) — kunci sort, id = tiebreak
    total_h, total_p = NOL, NOL
    auto_bulan = defaultdict(lambda: {"hutang": NOL, "piutang": NOL})

    for baris in qs.values_list(*kolom_ringan).iterator():
        pk, tanggal, delta, kategori, jam = baris[:5]
        slug = _slug_kategori(kategori)
        delta = NOL if delta is None else delta
        jam_s = str(jam or "")
        meta = {"tanggal": tanggal, "jam": jam_s, "kategori": slug, "nominal": delta}
        if banyak:
            meta["toko"] = baris[5]
        meta_by_id[pk] = meta
        urutan.append((tanggal, jam_s, pk))
        # Guard dua-cabang eksplisit (M5, 04-09-2026): regex kategori hari
        # ini hanya meloloskan dua nilai ini, tapi begitu ada yang memperlebar
        # KATEGORI_HUTANG_PIUTANG_REGEX (mis. `utang`), `else` diam-diam
        # menumpuk ke piutang dan `auto_bulan[periode][slug]` KeyError -> 500
        # di halaman Hutang/Piutang. Slug lain: tetap tampil di daftar, tapi
        # tidak masuk total mana pun -- lebih jujur daripada salah kolom.
        if slug == "hutang":
            total_h += delta
        elif slug == "piutang":
            total_p += delta
        if tanggal is not None and slug in ("hutang", "piutang"):
            periode = date(tanggal.year, tanggal.month, 1)
            auto_bulan[periode][slug] += delta

    urutan.sort(key=lambda k: (k[0] or date.min, k[1], k[2]), reverse=True)
    urut_ids = [k[2] for k in urutan]

    rows = _HutangRows(urut_ids, meta_by_id, banyak)

    total_h_out, total_p_out, manual = _overlay_total_bulanan(
        toko, dari, sampai, total_h, total_p, auto_bulan)

    return {
        "rows": rows,
        "total_hutang": total_h_out,
        "total_piutang": total_p_out,
        "netto": total_h_out + total_p_out,
        "count": len(urut_ids),
        "manual": manual,
        # Total mentah FR (pra-overlay) — berguna UI admin & tes.
        "total_hutang_auto": total_h,
        "total_piutang_auto": total_p,
        "netto_auto": total_h + total_p,
    }


def periode_bulan(d):
    """Tanggal 1 bulan dari sebuah date (atau None)."""
    if d is None:
        return None
    return date(d.year, d.month, 1)


def akhir_bulan(d):
    """Hari terakhir bulan dari sebuah date."""
    return date(d.year, d.month, monthrange(d.year, d.month)[1])
