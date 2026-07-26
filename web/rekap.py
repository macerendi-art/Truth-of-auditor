"""Rekap Bulanan (Net Profit & Dana Lebih) — modul murni, meniru Excel end user.

Halaman `/rekap-bulanan/` (Task 9) hanya MERENDER hasil modul ini: seluruh rumus
tinggal di sini, template tidak pernah berhitung.

Peta ke Excel end user (4 seksi, urutan baris = urutan kolom Excel):

  1. NET PROFIT        WL, AKURAN, BONUS HARIAN, LUCKY DRAW, BONUS MINGGUAN,
                       BONUS LAINNYA, PULSA, ADMIN, ADMIN QRIS, BEBAN OTHER
                       EXPENSE, TOTAL COST, OTHER INCOME, MISTAKE
                       →  NET PROFIT
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

Oracle seksi 4 (kurung Excel = negatif): DANA LEBIH FNC (885.426.217) −
TOTAL DANA LEBIH (888.276.217) = SELISIH FNC +2.850.000.

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
bercabang: `web.bonus.rekonsiliasi_bonus` (bonus harian/mingguan/lucky draw +
PENAMPUNG `bonus_lain`, sisi panel: cocok + panel_only), agregat kategori FR
bracket (`beban admin bank`, `beban admin qris`, `beban other expense`,
`pending dp`), `web.hutang.hutang_piutang` (hutang/piutang), dan Σ
`Transaction` panel untuk DP/WD. DP/WD sengaja dihitung LANGSUNG dari transaksi
panel, bukan dari `ReconBatch.summary`, karena rekap bulanan harus mencerminkan
seluruh data yang sudah masuk — termasuk hari yang batch-nya belum dijalankan.

Catatan sumber yang mudah salah baca:

* `bonus_lain` ADA supaya tak ada rupiah bonus yang menguap: nama kategori
  nyata mayoritas tak memuat kata "harian/mingguan/lucky" ("BONUS BOLA 10%",
  "Redemption Coupon", "CRM", "NEW MEMBER"). Nama-nama yang masuk penampung
  ini diekspos di `row["detail"]` supaya auditor bisa melihat isinya.
* `beban other expense` PUNYA BARIS SENDIRI, tidak menempel ADMIN QRIS: baris
  nyata "Cost Tagihan 28 Juni" (386.837.314) adalah penyelesaian biaya, bukan
  fee QRIS (7,6 jt) — menggabungkannya menggelembungkan ADMIN QRIS ±30x.
* `pdp_bulan_ini` = NET Σ kategori `pending dp` bulan berjalan (pengembalian
  ikut mengurangi, bukan hanya penambahan) — semantik ini masih perlu
  dikonfirmasi ke end user.
* Kategori FR `biaya transaksi` SENGAJA bukan baris rekap: biaya itu sudah
  tercakup baris manual TOTAL COST — memasukkannya = hitung ganda.
* Overlay `web.models.FRKoreksi` TIDAK diterapkan di rekap (keterbatasan yang
  disadari): kunci koreksinya per SATU tanggal, sedangkan rekap beragregat satu
  bulan penuh. Selisih akibat koreksi harian diserap lewat baris manual.

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

KUNCI BULANAN (wajib dibaca): carry antar-bulan hanya sedalam SATU tingkat,
jadi **auditor wajib menyimpan nilai carry tiap bulan (kunci bulanan) — tanpa
itu angka bulan ke-3 dan seterusnya menyimpang**. Bulan lalu dihitung ulang
dengan `_carry=False`, sehingga warisan dari dua bulan sebelumnya hanya ikut
bila sudah dikunci sebagai `RekapManual`. Tiap baris `carry` membawa
`row["tersimpan"]` (sudah dikunci atau belum) dan `data["petunjuk"]` berisi
peringatan bila ada carry yang belum dikunci padahal bulan lalu berisi data.
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
    "wl", "akuran", "bonus_harian", "lucky_draw", "bonus_mingguan",
    "bonus_lain", "pulsa", "admin", "admin_qris", "other_expense",
    "total_cost", "other_income", "mistake",
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
    # Penampung: semua kategori bonus di luar tiga kata kunci di atas. Tanpa
    # baris ini nilainya hilang diam-diam dan NET PROFIT jadi terlalu besar.
    _f("bonus_lain", "BONUS LAINNYA", 1, "auto", arah=-1,
       catatan="kategori bonus di luar harian/mingguan/lucky draw"),
    _f("pulsa", "PULSA", 1, "manual"),
    _f("admin", "ADMIN", 1, "auto"),
    _f("admin_qris", "ADMIN QRIS", 1, "auto"),
    # Dipisah dari ADMIN QRIS: "beban other expense" adalah penyelesaian biaya
    # (mis. "Cost Tagihan 28 Juni" 386 jt), bukan fee QRIS (7,6 jt).
    _f("other_expense", "BEBAN OTHER EXPENSE", 1, "auto"),
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
    # Tanda DIBALIK terhadap FR (satu-satunya tempat pembalikan ini dikodekan).
    # Baris FR nyata: Kategori "Hutang", money_delta +30.000.000
    # ("( HUTANG ) G25 PINJAM DANA K25 30,000,000") — Excel end user
    # membukukannya (30.000.000) NEGATIF; piutang FR (uang keluar, negatif)
    # tampil +130.003.000 POSITIF.
    _f("hutang_web", "HUTANG WEB", 3, "auto", arah=-1),
    _f("piutang_web", "PIUTANG WEB", 3, "auto", arah=-1),
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
    # `+ NOL` menormalkan −0,00 (hasil kali `arah` atas nilai sub-sen) jadi 0,00
    # supaya laporan tak pernah mencetak "-0".
    return (nilai or NOL).quantize(_KUANTUM) + NOL


# Klasifikasi nama kategori bonus → slug baris. Diperiksa BERURUTAN, yang
# pertama cocok menang: nama gabungan ("Lucky Draw Mingguan") harus jatuh ke
# lucky draw. Nama produksi kebanyakan memakai istilah Inggris ("… DAILY"),
# jadi kata kunci id + en berdampingan.
_BONUS_KUNCI = (
    ("lucky_draw", ("lucky",)),
    ("bonus_mingguan", ("mingguan", "weekly")),
    ("bonus_harian", ("harian", "daily")),
)
# Penampung wajib: nama nyata seperti "BONUS BOLA 10%", "Redemption Coupon",
# "CRM", "NEW MEMBER" tak memuat satu pun kata kunci di atas — tanpa penampung
# ini nilainya hilang diam-diam dan NET PROFIT jadi terlalu besar.
_BONUS_LAIN = "bonus_lain"


def _slug_bonus(nama):
    low = (nama or "").lower()
    for slug, kunci in _BONUS_KUNCI:
        if any(k in low for k in kunci):
            return slug
    return _BONUS_LAIN


def _nilai_auto(toko, dari, sampai):
    """(nilai mentah tiap baris `auto`, detail penjelas) — tanda apa adanya.

    Pembalikan tanda TIDAK dilakukan di sini — itu tugas `arah` di `FIELDS`.
    `detail` memetakan slug → daftar nama sumber yang menyusunnya (dipakai
    `bonus_lain` supaya isi penampung terlihat auditor).
    """
    hasil, detail = {}, {}

    # 1. Bonus — sisi PANEL saja (cocok + panel_only): baris bracket tanpa
    #    pasangan bukan beban panel bulan ini. Setiap kategori PASTI masuk
    #    salah satu dari empat baris (lihat `_slug_bonus`), jadi jumlah keempat
    #    baris selalu sama dengan jumlah seluruh kategori — tak ada yang hilang.
    per_bonus = {"bonus_harian": NOL, "bonus_mingguan": NOL,
                 "lucky_draw": NOL, _BONUS_LAIN: NOL}
    nama_lain = []
    kategori = rekonsiliasi_bonus(toko, dari, sampai)["ringkas"]["kategori"]
    for nama, d in kategori.items():
        total = (d["cocok_total"] or NOL) + (d["panel_only_total"] or NOL)
        slug = _slug_bonus(nama)
        per_bonus[slug] += total
        if slug == _BONUS_LAIN and total:
            nama_lain.append(str(nama))
    hasil.update(per_bonus)
    detail[_BONUS_LAIN] = sorted(nama_lain)
    # Seksi 2 "BONUS" = seluruh bonus NON-lucky (lucky draw punya barisnya
    # sendiri di seksi 2, persis seperti Excel end user).
    hasil["bonus"] = (per_bonus["bonus_harian"] + per_bonus["bonus_mingguan"]
                      + per_bonus[_BONUS_LAIN])

    # 2. Kategori FR (bracket) — satu query grouped untuk seluruh bulan.
    admin = admin_qris = other_expense = pdp = NOL
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
        elif slug == "beban admin qris":
            admin_qris += total
        elif slug == "beban other expense":
            other_expense += total
        elif slug == "pending dp":
            pdp += total
    hasil["admin"] = admin
    hasil["admin_qris"] = admin_qris
    hasil["other_expense"] = other_expense
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

    # 4. Hutang/piutang — nilai mentah FR; pembalikan tandanya dikodekan sekali
    #    di registry (`arah=-1` pada `hutang_web`/`piutang_web`).
    hp = hutang_piutang(toko, dari, sampai)
    hasil["hutang_web"] = hp["total_hutang"]
    hasil["piutang_web"] = hp["total_piutang"]
    return hasil, detail


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


def _rujuk(nilai, slug, f):
    """Baca nilai baris lain — slug asing = salah tulis registry, bukan nol.

    Diam-diam mengembalikan 0 untuk slug yang tak ada pernah menyembunyikan
    baris yang lupa dihitung (angka laporan jadi salah tanpa gejala).
    """
    if slug not in nilai:
        raise KeyError(
            f"slug '{slug}' yang dirujuk baris '{f.slug}' tidak dikenal di "
            f"registry FIELDS (salah tulis atau urutan rumus keliru)")
    return nilai[slug]


def _hitung(f, nilai):
    if f.rumus:
        return sum((_rujuk(nilai, slug, f) * koef for slug, koef in f.rumus), NOL)
    if f.sumber:
        return _rujuk(nilai, f.sumber, f) * f.arah
    return NOL


def _baris(f, nilai, sumber, auto, manual, detail=()):
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
        # Nama sumber penyusun (mis. isi penampung BONUS LAINNYA) — halaman
        # menampilkannya sebagai hover supaya isi baris tak jadi kotak hitam.
        "detail": list(detail),
        # Hanya bermakna untuk baris `carry`: sudah dikunci bulan ini atau belum.
        "tersimpan": (manual is not None) if f.kind == "carry" else None,
    }


def rekap_bulanan(toko, year, month, _carry=True):
    """Rekap Bulanan satu toko untuk satu bulan — murni baca, tanpa request.

    `_carry=False` memutus rekursi antar-bulan (dipakai `_nilai_carry`):
    baris `carry` lalu hanya bernilai bila ada `RekapManual`-nya.
    """
    periode = date(year, month, 1)
    dari, sampai = rentang_bulan(year, month)

    auto, detail = _nilai_auto(toko, dari, sampai)
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
        baris[f.slug] = _baris(f, val, sumber, asal, m, detail.get(f.slug, ()))
    # Lintasan 2 — rumus, mengikuti urutan FIELDS (setiap rujukan sudah dihitung).
    for f in FIELDS:
        if f.kind != "computed":
            continue
        val = _q(khusus[f.slug]) if f.slug in khusus else _q(_hitung(f, nilai))
        nilai[f.slug] = val
        baris[f.slug] = _baris(f, val, "computed", None, None)

    # Peringatan kunci bulanan: carry hanya sedalam 1 bulan, jadi nilai carry
    # yang belum disimpan akan MELESET mulai bulan ke-3. Hanya relevan bila
    # bulan lalu memang berisi angka.
    belum_dikunci = [f.label for f in FIELDS
                     if f.kind == "carry" and baris[f.slug]["tersimpan"] is False]
    petunjuk = ""
    if belum_dikunci and any(carry.values()):
        petunjuk = (
            "Nilai carry bulan lalu belum dikunci: "
            + ", ".join(belum_dikunci)
            + ". Simpan (kunci) nilai carry setiap bulan — tanpa itu angka "
              "bulan ke-3 dan seterusnya menyimpang.")

    return {
        "periode": periode,
        "dari": dari,
        "sampai": sampai,
        "petunjuk": petunjuk,
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
