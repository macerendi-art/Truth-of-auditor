"""Rekap Bulanan (Net Profit & Dana Lebih) — modul murni, meniru Excel end user.

Halaman `/rekap-bulanan/` (Task 9) hanya MERENDER hasil modul ini: seluruh rumus
tinggal di sini, template tidak pernah berhitung.

Peta ke Excel end user (4 seksi, urutan baris = urutan kolom Excel):

  1. NET PROFIT        WL, AKURAN, BONUS HARIAN, LUCKY DRAW, BONUS MINGGUAN,
                       PULSA, ADMIN, ADMIN QRIS, TOTAL COST, OTHER INCOME,
                       MISTAKE  →  NET PROFIT
  2. SISA DANA MEMBER  WALLET BALANCE bulan lalu, DP, WD, BONUS, LUCKY DRAW,
                       WL  →  SISA DANA MEMBER
  3. TOTAL DANA LEBIH WEB  isian kas/bank + rujukan seksi 1-2  →  TOTAL DANA
                       LEBIH WEB
  4. SELISIH & PENYEBAB  DANA LEBIH BULAN LALU, SELISIH, PENYEBAB, DIFFERENT,
                       DANA LEBIH FNC, SELISIH FNC

Konvensi tanda (ORACLE, dipin di `web/tests_rekap.py::OracleTandaTests`) —
angka asli laporan end user, seksi 2:

    (301.601.680) wallet balance bulan lalu
  (5.167.346.330) DP            ← uang member MASUK = kewajiban naik → negatif
   4.692.080.000  WD            ← uang member KELUAR = kewajiban turun → positif
    (245.187.030) BONUS
      (2.850.000) LUCKY DRAW
     740.045.170  WL
  --------------- +
    (284.859.870) SISA DANA MEMBER

Aturan turunannya: nilai disimpan APA ADANYA seperti terbaca di Excel (biaya
negatif), dan SETIAP baris hasil hitung adalah jumlah LURUS anggotanya. Semua
pembalikan tanda dikodekan sekali di registry `FIELDS` (`arah`), jadi tidak ada
tanda minus yang tersembunyi di dalam rumus:

* baris `auto`/`carry` → `nilai = arah × nilai_sumber` (mis. DP `arah=-1` atas
  Σ deposit panel; bonus `arah=-1` karena bonus adalah BIAYA di Excel);
* baris `computed` rujukan → `nilai = arah × nilai(sumber)` (mis. NET PROFIT
  tampil positif di seksi 1 tapi `(571.040.245)` di seksi 3 → `arah=-1`);
* baris `computed` gabungan → `nilai = Σ koef × nilai(slug)` lewat `rumus`.

Sumber otomatis (satu query per sumber untuk SATU rentang bulan penuh, tanpa
loop harian) memakai ulang modul yang sudah ada supaya angkanya tak pernah
bercabang: `web.bonus.rekonsiliasi_bonus` (bonus harian/mingguan/lucky draw,
sisi panel: cocok + panel_only), agregat kategori FR bracket (`beban admin
bank`, `beban admin qris` + `beban other expense`, `pending dp`),
`web.hutang.hutang_piutang` (hutang/piutang), dan Σ `Transaction` panel untuk
DP/WD. DP/WD sengaja dihitung LANGSUNG dari transaksi panel, bukan dari
`ReconBatch.summary`, karena rekap bulanan harus mencerminkan seluruh data yang
sudah masuk — termasuk hari yang batch-nya belum dijalankan.

DEVIASI v1 — `dana_lebih_fnc` (DANA LEBIH FNC) sengaja `kind="manual"`:
angkanya di Excel end user berasal dari export panel "Credit Mutation (net)"
yang BELUM di-ingest aplikasi ini. Pemeriksaan angka nyata membuktikan ia bukan
turunan DP−WD bulan berjalan (DP 5,167 M vs WD 4,692 M → net 475 jt, sementara
laporan mencetak 885 jt), jadi menurunkannya otomatis akan mengarang angka.
Begitu export tersebut masuk pipeline, baris ini tinggal diubah jadi `auto`
tanpa mengubah kontrak halaman.

Setiap baris `manual`/`auto`/`carry` bisa ditimpa `web.models.RekapManual`
(pola `FRKoreksi`); baris `computed` TIDAK PERNAH bisa ditimpa — rumus tetap
rumus. `sumber` pada tiap baris mencatat siapa yang menang.
"""
from calendar import monthrange
from collections import namedtuple
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.db.models.fields.json import KeyTextTransform

from transactions.models import Transaction
from web.bonus import rekonsiliasi_bonus
from web.breakdown import _slug_kategori
from web.hutang import hutang_piutang
from web.models import RekapManual, RekapPenyebab

NOL = Decimal("0")
_KUANTUM = Decimal("0.01")

SEKSI = [
    (1, "NET PROFIT"),
    (2, "SISA DANA MEMBER"),
    (3, "TOTAL DANA LEBIH WEB"),
    (4, "SELISIH & PENYEBAB"),
]

# slug   : kunci baris (dipakai RekapManual.field & template Task 9)
# kind   : manual  = isian FORM end user (default 0)
#          auto    = dari data (bisa ditimpa manual)
#          carry   = dari hasil bulan lalu (bisa ditimpa manual)
#          computed= rumus (TIDAK bisa ditimpa)
# arah   : pengali atas nilai sumber/rujukan → nilai yang TAMPIL
# sumber : slug yang dirujuk (baris computed rujukan tunggal)
# rumus  : ((slug, koef), …) untuk baris computed gabungan
Field = namedtuple(
    "Field", "slug label seksi kind arah sumber rumus catatan")


def _f(slug, label, seksi, kind, arah=1, sumber=None, rumus=(), catatan=""):
    return Field(slug, label, seksi, kind, arah, sumber, tuple(rumus), catatan)


def _jumlah(slugs):
    """Rumus 'jumlah lurus' — dipakai baris total tiap seksi."""
    return tuple((s, 1) for s in slugs)


_S1_ANGGOTA = [
    "wl", "akuran", "bonus_harian", "lucky_draw", "bonus_mingguan", "pulsa",
    "admin", "admin_qris", "total_cost", "other_income", "mistake",
]
_S2_ANGGOTA = [
    "wallet_balance_lalu", "dp", "wd", "bonus", "lucky_draw2", "wl_ref",
]
_S3_ANGGOTA = [
    "titip_saldo_awal", "dana_lebih_lalu_ref", "dana_tampung_pusat",
    "net_profit_ref", "akuran_ref", "oasis", "bank_dp", "qris", "bank_lain",
    "bank_wd", "tampung_web", "bank_beku", "mistake_belum_cost",
    "total_wallet_live", "hutang_web", "piutang_web", "akuran_lalu",
    "pdp_bulan_ini", "pdp_klaim", "claim_pdp_lalu", "expired_dana_pending",
]

FIELDS = [
    # --- Seksi 1: NET PROFIT ---------------------------------------------
    _f("wl", "WL", 1, "manual"),
    _f("akuran", "AKURAN", 1, "manual"),
    _f("bonus_harian", "BONUS HARIAN", 1, "auto", arah=-1),
    _f("lucky_draw", "LUCKY DRAW", 1, "auto", arah=-1),
    _f("bonus_mingguan", "BONUS MINGGUAN", 1, "auto", arah=-1),
    _f("pulsa", "PULSA", 1, "manual"),
    _f("admin", "ADMIN", 1, "auto"),
    _f("admin_qris", "ADMIN QRIS", 1, "auto"),
    _f("total_cost", "TOTAL COST", 1, "manual"),
    _f("other_income", "OTHER INCOME", 1, "manual"),
    _f("mistake", "MISTAKE", 1, "manual"),
    _f("net_profit", "NET PROFIT", 1, "computed", rumus=_jumlah(_S1_ANGGOTA)),
    # --- Seksi 2: SISA DANA MEMBER ---------------------------------------
    _f("wallet_balance_lalu", "WALLET BALANCE BULAN LALU", 2, "carry"),
    _f("dp", "DP", 2, "auto", arah=-1),
    _f("wd", "WD", 2, "auto"),
    _f("bonus", "BONUS", 2, "auto", arah=-1),
    _f("lucky_draw2", "LUCKY DRAW", 2, "computed", sumber="lucky_draw"),
    _f("wl_ref", "WL", 2, "computed", sumber="wl"),
    _f("sisa_dana_member", "SISA DANA MEMBER", 2, "computed",
       rumus=_jumlah(_S2_ANGGOTA)),
    # --- Seksi 3: TOTAL DANA LEBIH WEB -----------------------------------
    _f("titip_saldo_awal", "TITIP SALDO AWAL", 3, "manual"),
    _f("dana_lebih_lalu_ref", "DANA LEBIH BULAN LALU", 3, "computed",
       sumber="dana_lebih_lalu"),
    _f("dana_tampung_pusat", "DANA TAMPUNG PUSAT BULAN INI", 3, "manual"),
    # NET PROFIT dikeluarkan dari dana web (milik owner) → tanda dibalik.
    _f("net_profit_ref", "NET PROFIT/LOSS", 3, "computed",
       sumber="net_profit", arah=-1),
    # AKURAN dikembalikan: yang dikeluarkan hanyalah profit DI LUAR akuran.
    _f("akuran_ref", "AKURAN", 3, "computed", sumber="akuran"),
    _f("oasis", "OASIS", 3, "manual"),
    _f("bank_dp", "BANK DP", 3, "manual"),
    _f("qris", "QRIS", 3, "manual"),
    _f("bank_lain", "BANK LAIN", 3, "manual"),
    _f("bank_wd", "BANK WD", 3, "manual"),
    _f("tampung_web", "TAMPUNG WEB", 3, "manual"),
    _f("bank_beku", "BANK BEKU (JIKA BELUM MASUK COST)", 3, "manual"),
    _f("mistake_belum_cost", "MISTAKE (JIKA BELUM MASUK COST)", 3, "manual"),
    _f("total_wallet_live", "TOTAL WALLET BALANCE (LIVE)", 3, "computed",
       sumber="sisa_dana_member"),
    _f("hutang_web", "HUTANG WEB", 3, "auto"),
    _f("piutang_web", "PIUTANG WEB", 3, "auto"),
    _f("akuran_lalu", "AKURAN BULAN LALU", 3, "carry"),
    _f("pdp_bulan_ini", "PDP BULAN INI", 3, "auto"),
    _f("pdp_klaim", "PDP KLAIM BULAN INI", 3, "manual"),
    _f("claim_pdp_lalu", "CLAIM PDP BULAN LALU", 3, "manual"),
    _f("expired_dana_pending", "EXPIRED DANA PENDING", 3, "manual",
       catatan="PDP di atas 30 hari — v1 diisi manual"),
    _f("total_dana_lebih", "TOTAL DANA LEBIH WEB", 3, "computed",
       rumus=_jumlah(_S3_ANGGOTA)),
    # --- Seksi 4: SELISIH & PENYEBAB -------------------------------------
    _f("dana_lebih_lalu", "DANA LEBIH BULAN LALU", 4, "carry"),
    _f("selisih", "SELISIH", 4, "computed",
       rumus=(("total_dana_lebih", 1), ("dana_lebih_lalu", -1))),
    _f("penyebab_total", "PENYEBAB", 4, "computed"),   # Σ RekapPenyebab
    _f("different", "DIFFERENT", 4, "computed",
       rumus=(("selisih", 1), ("penyebab_total", -1))),
    _f("dana_lebih_fnc", "DANA LEBIH FNC", 4, "manual",
       catatan="isi dari Panel Credit Mutation (net)"),
    _f("selisih_fnc", "SELISIH FNC", 4, "computed",
       rumus=(("dana_lebih_fnc", 1), ("total_dana_lebih", -1))),
]

TOTALS = ["net_profit", "sisa_dana_member", "total_dana_lebih", "selisih",
          "different", "selisih_fnc"]


def rentang_bulan(year, month):
    """(hari pertama, hari terakhir) bulan — satu rentang untuk semua query."""
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _q(nilai):
    return (nilai or NOL).quantize(_KUANTUM)


def _nilai_auto(toko, dari, sampai):
    """Nilai mentah tiap baris `auto` (tanda apa adanya dari sumbernya).

    Pembalikan tanda TIDAK dilakukan di sini — itu tugas `arah` di `FIELDS`.
    """
    hasil = {}

    # 1. Bonus — sisi PANEL saja (cocok + panel_only): baris bracket tanpa
    #    pasangan bukan beban panel bulan ini. Klasifikasi nama kategori
    #    case-insensitive; "lucky" diperiksa lebih dulu agar nama gabungan
    #    ("Lucky Draw Mingguan") tetap jatuh ke lucky draw.
    harian = mingguan = lucky = NOL
    kategori = rekonsiliasi_bonus(toko, dari, sampai)["ringkas"]["kategori"]
    for nama, d in kategori.items():
        total = (d["cocok_total"] or NOL) + (d["panel_only_total"] or NOL)
        low = (nama or "").lower()
        if "lucky" in low:
            lucky += total
        elif "mingguan" in low:
            mingguan += total
        elif "harian" in low:
            harian += total
    hasil["bonus_harian"] = harian
    hasil["bonus_mingguan"] = mingguan
    hasil["lucky_draw"] = lucky
    hasil["bonus"] = harian + mingguan   # seksi 2: bonus harian + mingguan

    # 2. Kategori FR (bracket) — satu query grouped untuk seluruh bulan.
    admin = admin_qris = pdp = NOL
    fr = (
        Transaction.objects.filter(
            toko=toko, source_type__key="bracket",
            posted_date__gte=dari, posted_date__lte=sampai)
        .annotate(fr_kategori=KeyTextTransform("Kategori", "raw"))
        .values("fr_kategori")
        .annotate(total=Sum("money_delta"))
    )
    for baris in fr:
        slug = _slug_kategori(baris["fr_kategori"])
        total = baris["total"] or NOL
        if slug == "beban admin bank":
            admin += total
        elif slug in ("beban admin qris", "beban other expense"):
            admin_qris += total
        elif slug == "pending dp":
            pdp += total
    hasil["admin"] = admin
    hasil["admin_qris"] = admin_qris
    hasil["pdp_bulan_ini"] = pdp

    # 3. DP/WD panel — satu query grouped (bukan ReconBatch.summary: rekap
    #    harus utuh meski batch harian belum dijalankan).
    dp = wd = NOL
    panel = (
        Transaction.objects.filter(
            toko=toko, source_type__key="panel", is_duplicate=False,
            jenis__in=[Transaction.Jenis.DEPO, Transaction.Jenis.WD],
            posted_date__gte=dari, posted_date__lte=sampai)
        .values("jenis")
        .annotate(total=Sum("amount"))
    )
    for baris in panel:
        if baris["jenis"] == Transaction.Jenis.DEPO:
            dp += baris["total"] or NOL
        else:
            wd += baris["total"] or NOL
    hasil["dp"] = dp
    hasil["wd"] = wd

    # 4. Hutang/piutang — nilai lewat apa adanya (data FR sudah bertanda:
    #    hutang negatif, piutang positif — lihat `hutang_piutang().netto`).
    hp = hutang_piutang(toko, dari, sampai)
    hasil["hutang_web"] = hp["total_hutang"]
    hasil["piutang_web"] = hp["total_piutang"]
    return hasil


def _nilai_carry(toko, year, month):
    """Nilai baris `carry` dari bulan sebelumnya — rekursi kedalaman 1.

    Bulan lalu dihitung dengan `_carry=False`: baris carry-nya sendiri hanya
    dibaca dari `RekapManual`, sehingga rantai berhenti di satu tingkat
    (tanpa ini, membuka bulan Juli akan menghitung ulang seluruh riwayat).
    """
    py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
    lalu = rekap_bulanan(toko, py, pm, _carry=False)
    per_slug = {r["slug"]: r["nilai"] for s in lalu["sections"] for r in s["rows"]}
    return {
        "wallet_balance_lalu": lalu["totals"]["sisa_dana_member"],
        "dana_lebih_lalu": lalu["totals"]["total_dana_lebih"],
        "akuran_lalu": per_slug.get("akuran", NOL),
    }


def _hitung(f, nilai):
    if f.rumus:
        return sum((nilai.get(slug, NOL) * koef for slug, koef in f.rumus), NOL)
    if f.sumber:
        return nilai.get(f.sumber, NOL) * f.arah
    return NOL


def _baris(f, nilai, sumber, auto, manual):
    return {
        "slug": f.slug,
        "label": f.label,
        "kind": f.kind,
        "nilai": nilai,
        "sumber": sumber,
        "auto": auto,
        "manual": None if manual is None else {
            "nilai": _q(manual.nilai),
            "catatan": manual.catatan,
            "oleh": manual.dibuat_oleh.username if manual.dibuat_oleh_id else "",
            "waktu": manual.updated_at,
        },
        "petunjuk": f.catatan,
    }


def rekap_bulanan(toko, year, month, _carry=True):
    """Rekap Bulanan satu toko untuk satu bulan — murni baca, tanpa request.

    `_carry=False` memutus rekursi antar-bulan (dipakai `_nilai_carry`):
    baris `carry` lalu hanya bernilai bila ada `RekapManual`-nya.
    """
    periode = date(year, month, 1)
    dari, sampai = rentang_bulan(year, month)

    auto = _nilai_auto(toko, dari, sampai)
    carry = _nilai_carry(toko, year, month) if _carry else {}
    manual = {
        m.field: m for m in RekapManual.objects
        .filter(toko=toko, periode=periode).select_related("dibuat_oleh")
    }
    penyebab = list(RekapPenyebab.objects.filter(toko=toko, periode=periode))
    khusus = {"penyebab_total": sum((p.nilai for p in penyebab), NOL)}

    nilai, baris = {}, {}
    # Lintasan 1 — nilai dasar (manual/auto/carry). Dipisah dari lintasan rumus
    # supaya rujukan boleh melompat antar-seksi (seksi 3 merujuk carry seksi 4).
    for f in FIELDS:
        if f.kind == "computed":
            continue
        asal = None
        if f.kind == "auto":
            asal = _q(auto.get(f.slug, NOL) * f.arah)
        elif f.kind == "carry":
            asal = _q(carry.get(f.slug, NOL) * f.arah)
        m = manual.get(f.slug)
        if m is not None:
            # Nilai manual disimpan seperti yang TAMPIL (arah tak dipakai lagi).
            val, sumber = _q(m.nilai), "manual"
        else:
            val, sumber = (asal if asal is not None else _q(NOL)), f.kind
        nilai[f.slug] = val
        baris[f.slug] = _baris(f, val, sumber, asal, m)
    # Lintasan 2 — rumus, mengikuti urutan FIELDS (setiap rujukan sudah dihitung).
    for f in FIELDS:
        if f.kind != "computed":
            continue
        val = _q(khusus[f.slug]) if f.slug in khusus else _q(_hitung(f, nilai))
        nilai[f.slug] = val
        baris[f.slug] = _baris(f, val, "computed", None, None)

    return {
        "periode": periode,
        "dari": dari,
        "sampai": sampai,
        "sections": [
            {"no": no, "judul": judul,
             "rows": [baris[f.slug] for f in FIELDS if f.seksi == no]}
            for no, judul in SEKSI
        ],
        "penyebab": [
            {"id": p.id, "label": p.label, "nilai": _q(p.nilai),
             "urutan": p.urutan}
            for p in penyebab
        ],
        "totals": {slug: nilai[slug] for slug in TOTALS},
    }
