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

MODUS KEDUA — agregat (lump per kategori per hari)
--------------------------------------------------
Keluarga Vigor/TM Gaming membukukan sebagian bonus di bracket sebagai SATU
baris gelondongan per kategori per hari (username kosong), sementara panel
mencatatnya per pemain. Dicocokkan per pemain, satu lump 1,04 juta melahirkan
±671 baris "hanya di panel" — bunyi palsu, padahal angkanya cocok.

Modus ini **hanya menyala** bila ada baris panel yang membawa penanda
`raw["Sumber"] == MARKER_AGREGAT`, yaitu baris keluaran parser
`cor_panel_bonus`. Gerbang itu dipilih menggantikan `Toko.panel` karena nol
baris produksi membawanya hari ini dan hanya parser itu yang bisa
menciptakannya — jadi 321 baris bracket Nexus tanpa username **mustahil**
terseret ke modus ini, jaminan struktural, bukan hasil tes. Saat penanda tak
ada, fungsi ini menjalankan badan lama apa adanya dan mengembalikan dict lama
dengan himpunan kunci sama persis (tanpa `agregat`, tanpa `agregat_*`).

**Artefak tepi rentang, disengaja:** `ambil()` menyaring `posted_date` di
`[dari, sampai]`, jadi lump 04-08 yang menunjuk `TGL 03.08.2026` hanya
dibandingkan dengan baris panel yang SUDAH termuat. Bila `dari == 04-08`, lump
itu jatuh ke `bracket_only`. Query sengaja TIDAK dilebarkan: halaman tak boleh
bergantung pada baris yang tak diminta pengguna. Default halaman 30 hari, jadi
ini artefak tepi saja.
"""
import re
from collections import defaultdict, deque
from datetime import date
from decimal import Decimal

from django.db.models import TextField
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast

from sources.parsers.bonus import MARKER_AGREGAT
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
    kategori = t["kat_raw"] or "Bonus"
    return {
        "id": t["id"],
        "tanggal": t["posted_date"],
        "username": t["username"],
        "kategori": kategori,
        # Kategori tampilan: panel diekstrak dari Description, bracket sudah
        # detail dari kolom Category-nya sendiri (jangan regex desc bracket —
        # desc Credit Bonus berisi salinan desc panel).
        "kategori_detail": (kategori_detail(kategori, t["description"])
                            if panel else kategori),
        "nominal": t["amount"],
        "deskripsi": t["description"],
    }


def _kunci(t):
    return ((t["username"] or "").strip().lower(),
            int(abs(t["amount"] or 0)), t["posted_date"])


# --- Modus agregat -------------------------------------------------------

# Ambang selisih lump. ALASANNYA BUKAN "bracket memangkas desimal" — dugaan itu
# sudah diukur dan SALAH (artefak pembacaan berformat bulat). Berkasnya sendiri
# cocok SAMPAI SEN: 04-08 panel 1.038.747,200 vs bracket 1.038.747,20; 06-08
# panel 1.491.972,250 vs bracket 1.491.972,25.
#
# Yang benar-benar menggeser angka adalah KOLOM KITA SENDIRI.
# `Transaction.amount` itu `DecimalField(decimal_places=2)`, sedangkan ekspor
# panel memuat baris berdesimal TIGA (mis. '13435.875' — 10 dari 74 baris
# rollingan 04-08). Tiap baris dibulatkan saat disimpan, dan jumlah-dari-yang-
# dibulatkan != pembulatan-dari-jumlah: 1.038.747,200 tersimpan jadi
# 1.038.747,24. Jadi ambang ini LOAD-BEARING hari ini, bukan pagar masa depan.
#
# Karena sumbernya pembulatan per baris, batas atasnya bisa DIBUKTIKAN, bukan
# ditebak: tiap baris bergeser paling banyak 0,005, jadi sel berisi n baris
# panel bergeser paling banyak n x 0,005. Ambang tetap Rp1 akan pecah begitu
# satu brand melewati ~200 baris berdesimal-tiga per kategori per hari (2.000
# baris -> sampai Rp10 -> "selisih" palsu tiap hari). Karena itu ambangnya
# menskala: lantai Rp1 (marjin aman yang disetujui) ATAU batas aritmetis
# pembulatan, mana yang lebih besar. Ia tak pernah bisa menyembunyikan sesuatu
# yang lebih besar dari artefaknya sendiri — selisih nyata tetap terlihat:
# 92.550 vs 92.925 -> 375 -> "selisih"; 157.500 vs 215.000 -> 57.500.
TOLERANSI_AGREGAT = Decimal("1")
_DRIFT_PER_BARIS = Decimal("0.005")  # setengah dari satu sen (decimal_places=2)


def toleransi_agregat(n_panel):
    """Ambang selisih untuk sel berisi `n_panel` baris panel."""
    return max(TOLERANSI_AGREGAT, n_panel * _DRIFT_PER_BARIS)

# Jalan keluar manual bila pemetaan otomatis putus (mis. vendor menghapus kata
# depan "BONUS" sehingga prefiks tak lagi menambat). Kunci DAN nilai keduanya
# dalam bentuk ternormalisasi `_norm_kat`; nilai boleh str atau tuple. Kosong
# saat lahir — sengaja: sel yang tak terpetakan jatuh ke jalur per pemain dan
# BERBUNYI di halaman (panel_only + bracket_only), lalu ditambal satu entri.
ALIAS_AGREGAT = {}

# "TGL 03.08.2026" di deskripsi bracket. `re.search` (bukan `match`) dan tanpa
# jangkar: deskripsi nyata multi-baris ("... TGL 03.08.2026\nPlayer:").
# DILINGKUPI KETAT ke jalur agregat — deskripsi bracket Nexus adalah teks bebas
# dan bisa memuat "TGL"; memakainya di jalur per pemain akan mengubah pasangan
# yang sudah ada.
_TGL_RE = re.compile(
    r"\bTGL\.?\s*[:\-]?\s*(\d{1,2})[./\-](\d{1,2})[./\-](\d{2,4})\b", re.I)
_NON_ALNUM_RE = re.compile(r"[^0-9A-Za-z]+")


def _norm_kat(nama):
    """Bentuk banding kategori: huruf besar, tiap rentetan non-alfanumerik jadi
    satu spasi, strip. "BONUS ROLLINGAN SLOT HARIAN 0.5%" -> "... 0 5"."""
    return _NON_ALNUM_RE.sub(" ", (nama or "").upper()).strip()


def _kategori_bonus(t):
    """Kategori mentah sebuah baris — fallback sama dengan `_baris`."""
    return t["kat_raw"] or "Bonus"


def _tanggal_tgl(deskripsi):
    """Tanggal dari teks "TGL dd.mm.yyyy", atau None.

    Tanggal mustahil (`32.13.2026`) mengembalikan None lewat `try/except`,
    BUKAN exception — sel itu lalu memakai tanggal pembukuan."""
    m = _TGL_RE.search(deskripsi or "")
    if not m:
        return None
    hari, bulan, tahun = (int(m.group(i)) for i in (1, 2, 3))
    if tahun < 100:
        tahun += 2000
    try:
        return date(tahun, bulan, hari)
    except ValueError:
        return None


def _kategori_cocok(bracket_norm, panel_norm):
    """Pemetaan lintas-namespace, keduanya sudah ternormalisasi.

    Alias eksplisit diperiksa lebih dulu, lalu `sama` atau prefiks BATAS-KATA.
    Prefiks menambatkan label pendek operator ("BONUS ROLLINGAN") di awal nama
    promo vendor ("BONUS ROLLINGAN SLOT HARIAN 0 5") — persis relasi kedua
    namespace itu. Subset token DILARANG: ia akan meloloskan "BONUS HARIAN" ->
    "BONUS ROLLINGAN SLOT HARIAN 0 5" dan menelan sel rollingan Rp1,04 juta.
    """
    alias = ALIAS_AGREGAT.get(bracket_norm)
    if alias is not None:
        pilihan = {alias} if isinstance(alias, str) else set(alias)
        if panel_norm in pilihan:
            return True
    return (panel_norm == bracket_norm
            or panel_norm.startswith(bracket_norm + " "))


def _pisah_agregat(panel, bracket):
    """(panel sisa, bracket sisa, daftar entri agregat).

    Baris panel yang LAYAK diserap hanya yang berpenanda; baris tak berpenanda
    tak pernah teragregasi walau modus menyala. Sel = (kategori bracket
    ternormalisasi, tanggal efektif), dan gerbangnya butuh keduanya:

    (i)  SEMUA baris bracket di sel itu ber-username kosong — sel campuran
         jatuh SELURUHNYA ke jalur lama (aman & terlihat, disengaja);
    (ii) ada baris panel berpenanda, BELUM diklaim, pada tanggal efektif itu,
         yang kategorinya cocok.

    Klaim deterministik: sel diiterasi terurut `(tanggal, kategori)` dan sebuah
    baris panel tak bisa diklaim sel kedua — disiplin yang sama dengan
    `order_by("id")` di `reconciliation/engine.py`, supaya hasil tak pernah
    bergantung pada rencana eksekusi DB.
    """
    layak = defaultdict(list)   # tanggal -> baris panel berpenanda
    for p in panel:
        if p["sumber_raw"] == MARKER_AGREGAT and p["posted_date"]:
            layak[p["posted_date"]].append(p)

    sel = defaultdict(list)
    for b in bracket:
        efektif = _tanggal_tgl(b["description"]) or b["posted_date"]
        sel[(efektif, _norm_kat(_kategori_bonus(b)))].append(b)

    entri, diklaim, dipakai = [], set(), set()
    for kunci in sorted(sel, key=lambda k: (k[0] or date.min, k[1])):
        efektif, kat_norm = kunci
        baris = sel[kunci]
        if efektif is None:
            continue
        if any((b["username"] or "").strip() for b in baris):
            continue
        pas = [p for p in layak.get(efektif, ())
               if p["id"] not in diklaim
               and _kategori_cocok(kat_norm, _norm_kat(_kategori_bonus(p)))]
        if not pas:
            continue

        kat_panel = sorted({_kategori_bonus(p) for p in pas})
        panel_total = sum((p["amount"] or NOL for p in pas), NOL)
        bracket_total = sum((b["amount"] or NOL for b in baris), NOL)
        selisih = panel_total - bracket_total
        # Tanggal pembukuan diambil dari baris bracket pertama sel — hanya
        # ditampilkan ("dibukukan dd/mm"), dan hanya bila `TGL` menggesernya.
        dibukukan = baris[0]["posted_date"]
        entri.append({
            "tanggal": efektif,
            "tanggal_bracket": dibukukan if dibukukan != efektif else None,
            "kategori": _kategori_bonus(baris[0]),
            # Kunci ringkasan & filter — satu kategori bracket bisa memprefiks
            # BEBERAPA kategori panel di hari yang sama; yang pertama secara
            # alfabetis jadi wakilnya, seluruhnya didaftar di `kategori_panel`.
            "kategori_detail": kat_panel[0],
            "kategori_panel": kat_panel,
            "n_panel": len(pas),
            "panel_total": panel_total,
            "n_bracket": len(baris),
            "bracket_total": bracket_total,
            "selisih": selisih,
            "status": ("cocok" if abs(selisih) < toleransi_agregat(len(pas))
                       else "selisih"),
            "deskripsi": baris[0]["description"],
        })
        diklaim.update(p["id"] for p in pas)
        dipakai.update(b["id"] for b in baris)

    return ([p for p in panel if p["id"] not in diklaim],
            [b for b in bracket if b["id"] not in dipakai],
            entri)


def rekonsiliasi_bonus(toko, dari=None, sampai=None, kategori=None):
    def ambil(key):
        qs = Transaction.objects.filter(
            toko=toko, source_type__key=key, is_duplicate=False)
        if dari:
            qs = qs.filter(posted_date__gte=dari)
        if sampai:
            qs = qs.filter(posted_date__lte=sampai)
        # `.values()` DAN DUA KUNCI `raw` SAJA — bukan gaya, ini biaya halaman.
        # `raw` adalah JSONB besar yang di-detoast lalu di-`json.loads` per
        # baris; menariknya utuh untuk membaca dua kunci membuat /bonus/
        # menghabiskan waktunya di Python, bukan di SQL. `KeyTextTransform`
        # mengekstraknya di server (Cast → TextField supaya bentuknya `str`
        # yang sama di Postgres maupun SQLite). NULL/kunci absen sama-sama
        # menjadi None, persis seperti `(raw or {}).get(k, "")` yang digantinya
        # — pemakainya selalu `... or "Bonus"` / perbandingan kesetaraan.
        #
        # `order_by` DIPERTAHANKAN: pemasangan 1:1 memakai deque per kunci,
        # jadi urutan baris menentukan pasangan mana yang terbentuk. Ini
        # kebenaran, bukan kerapian (lihat catatan determinisme di CLAUDE.md).
        return list(
            qs.annotate(
                kat_raw=Cast(KeyTextTransform("Kategori", "raw"), TextField()),
                sumber_raw=Cast(KeyTextTransform("Sumber", "raw"), TextField()),
            )
            .order_by("posted_date", "id")
            .values("id", "posted_date", "username", "amount", "description",
                    "kat_raw", "sumber_raw")
        )

    panel, bracket = ambil("panel_bonus"), ambil("bracket_bonus")

    # GERBANG modus agregat. `agregat is None` = badan lama apa adanya, dan
    # dict yang dikembalikan berkunci sama persis seperti sebelum rilis ini.
    agregat = None
    if any(p["sumber_raw"] == MARKER_AGREGAT for p in panel):
        panel, bracket, agregat = _pisah_agregat(panel, bracket)

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
    if agregat is not None:
        opsi = sorted(set(opsi) | {e["kategori_detail"] for e in agregat})
    if kategori and kategori not in opsi:
        # Rentang tanggal baru bisa tak memuat kategori yang sedang difilter —
        # tetap tampilkan sebagai opsi terpilih supaya state filter terlihat,
        # bukan menyaru jadi "Semua kategori" padahal filternya masih aktif.
        opsi = sorted(opsi + [kategori])

    if kategori:
        # Display-only, pairing di atas sudah final — hasil cocok tak berubah.
        cocok = [c for c in cocok if c["panel"]["kategori_detail"] == kategori]
        panel_only = [r for r in panel_only if r["kategori_detail"] == kategori]
        bracket_only = [r for r in bracket_only
                        if r["kategori_detail"] == kategori]
        if agregat is not None:
            agregat = [e for e in agregat
                       if e["kategori_detail"] == kategori]

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
    # Kunci `agregat_*` disemai BERSYARAT — hanya pada kategori yang benar-benar
    # punya entri agregat. Menyemainya tanpa syarat di `_kat()` akan mengubah
    # bentuk dict untuk SEMUA toko Nexus, persis yang dilarang rilis ini.
    for e in (agregat or ()):
        d = _kat(e["kategori_detail"])
        d["agregat"] = d.get("agregat", 0) + 1
        d["agregat_panel_total"] = d.get("agregat_panel_total", NOL) + e["panel_total"]
        d["agregat_bracket_total"] = (
            d.get("agregat_bracket_total", NOL) + e["bracket_total"])
        d["agregat_selisih"] = d.get("agregat_selisih", NOL) + e["selisih"]

    ringkas = {
        "cocok": {"n": len(cocok), "total": sum((c["panel"]["nominal"] for c in cocok), NOL)},
        "panel_only": {"n": len(panel_only), "total": _tot(panel_only)},
        "bracket_only": {"n": len(bracket_only), "total": _tot(bracket_only)},
        "kategori": dict(sorted(per_kat.items())),
    }
    hasil = {"cocok": cocok, "panel_only": panel_only,
             "bracket_only": bracket_only, "ringkas": ringkas,
             "kategori_opsi": opsi}
    if agregat is not None:
        # Ember TERPISAH, tidak dilebur ke `cocok_total`: "Cocok" tetap berarti
        # pasangan 1:1 di daftar `cocok`, jumlah kartu tetap konsisten dengan
        # panjang daftarnya, dan setiap tes lama tetap benar secara konstruksi.
        ringkas["agregat"] = {
            "n": len(agregat),
            "panel_total": sum((e["panel_total"] for e in agregat), NOL),
            "bracket_total": sum((e["bracket_total"] for e in agregat), NOL),
            "selisih": sum((e["selisih"] for e in agregat), NOL),
            "selisih_n": sum(1 for e in agregat if e["status"] == "selisih"),
        }
        hasil["agregat"] = agregat
    return hasil
