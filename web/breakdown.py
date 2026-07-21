"""Breakdown Bracket (FR) harian — agregasi per FR Account.

Meniru "Control Bracket Transaction (Harian)" (referensi user) dengan hitungan
bertanda yang benar: baris per FR Account (`raw["Bank"]`), pivot per kategori
asli FR (`raw["Kategori"]`), saldo awal/akhir dari `balance_after` (saldo
berjalan per akun, urut `(raw["Jam"], id)` = urutan file), dan

    Selisih Kontrol = saldo_akhir − (saldo_awal + Σ money_delta)

yang idealnya 0 — nilai ≠ 0 berarti mutasi FR tidak konsisten dengan saldo
berjalannya (sinyal audit, bukan angka penyeimbang seperti "Akuran").

Semua baris bracket ikut dihitung (termasuk fee `jenis="admin"` dan baris yang
sudah di-consume batch): ini view data, bukan matching. Tanpa migrasi — kolom
diambil query-time dari JSON `raw`, jadi berlaku retroaktif untuk data lama.
"""
from collections import Counter
from decimal import Decimal

from django.db.models import Max
from django.db.models.fields.json import KeyTextTransform

from transactions.models import Transaction

# Urutan kanonik kolom kategori (slug lower → label tampilan). Hanya kategori
# yang MUNCUL pada hari itu yang jadi kolom; slug di luar daftar (kategori baru
# dari FR) ditambahkan di ujung secara alfabetis — tidak ada data tersembunyi.
KATEGORI_KANONIK = [
    ("deposit", "Deposit"),
    ("pending dp", "Pending DP"),
    ("withdrawal", "Withdrawal"),
    ("bonus", "Bonus"),
    ("adjustment", "Adjustment"),
    ("sesama cm", "Sesama CM"),
    ("beban admin bank", "Beban Admin Bank"),
    ("beban admin qris", "Beban Admin QRIS"),
    ("biaya transaksi", "Biaya Transaksi"),
    ("beban other expense", "Beban Other Expense"),
    ("beban mistake cs", "Beban Mistake CS"),
    ("expense", "Expense"),
    ("hutang", "Hutang"),
    ("piutang", "Piutang"),
]
_KANONIK_LABEL = dict(KATEGORI_KANONIK)
_KANONIK_URUT = {slug: i for i, (slug, _) in enumerate(KATEGORI_KANONIK)}

# Peran akun (bagian terakhir "A | B | PERAN") → urutan tampilan,
# mengikuti referensi: rekening DP, rekening WD, QRIS, lalu lainnya.
_URUT_PERAN = {"DEPOSIT": 0, "WITHDRAW": 1, "WITHDRAWAL": 1, "DEPOSIT / WITHDRAW": 2}

NOL = Decimal("0")


def _slug_kategori(value):
    s = " ".join(str(value or "").split()).lower()
    if not s:
        return "(tanpa kategori)"
    if s == "withdraw":  # varian ejaan FR
        return "withdrawal"
    return s


def _saldo_batas(items):
    """(saldo_awal, saldo_akhir) akun dari baris ber-balance — kebal acak urutan.

    FR nyata mengacak urutan baris DI DALAM menit yang sama, jadi baris
    pertama/terakhir menurut (Jam, id) belum tentu ujung rantai saldo. Pada
    rantai yang konsisten, tepat SATU pre-balance (balance − delta) tidak
    pernah muncul sebagai balance baris lain (= saldo awal) dan tepat satu
    balance tidak pernah menjadi pre-balance baris lain (= saldo akhir),
    apa pun urutannya. Bila kandidat tidak tunggal (rantai putus = anomali
    FR asli), jatuh kembali ke urutan (Jam, id) agar selisihnya justru
    muncul di kolom kontrol.
    """
    bals, pres = Counter(), Counter()
    for _jam, _pk, delta, balance, _slug in items:
        if balance is not None:
            bals[balance] += 1
            pres[balance - delta] += 1
    if not bals:
        return None, None
    awal = list((pres - bals).elements())
    akhir = list((bals - pres).elements())
    if len(awal) == 1 and len(akhir) == 1:
        return awal[0], akhir[0]
    first = next(t for t in items if t[3] is not None)
    last = next(t for t in reversed(items) if t[3] is not None)
    return first[3] - first[2], last[3]


def _pecah_akun(account):
    """'BANK BRI | YOGA | WITHDRAW' → ('BANK BRI — YOGA', 'WITHDRAW');
    'QRIS HOKI | DEPOSIT / WITHDRAW' → ('QRIS HOKI', 'DEPOSIT / WITHDRAW')."""
    parts = [p.strip() for p in account.split("|") if p.strip()]
    if len(parts) >= 2:
        return " — ".join(parts[:-1]), " ".join(parts[-1].upper().split())
    return account, ""


def _apply_koreksi(toko, tanggal, accounts, slugs_muncul):
    """Timpa nilai sel dengan `FRKoreksi` lalu hitung ulang turunannya.

    Data mentah tak disentuh — hanya dict tampilan. Mutasi = Σ kategori
    (setara Σ delta mentah karena tiap baris FR masuk tepat satu kategori),
    jadi setelah sel kategori diganti, mutasi/deposit/withdraw/net/selisih
    dihitung ulang dari nilai terkoreksi. Koreksi pada akun yang tak hadir
    pada tanggal itu diabaikan (sel tampilan tidak ada).
    """
    from web.models import FRKoreksi  # impor lokal: hindari siklus saat startup

    per_acc = {}
    for k in FRKoreksi.objects.filter(
        toko=toko, tanggal=tanggal
    ).select_related("dibuat_oleh"):
        per_acc.setdefault(k.account, []).append(k)
    if not per_acc:
        return
    for acc in accounts:
        daftar = per_acc.get(acc["account"])
        if not daftar:
            continue
        info = {}
        for k in daftar:
            if k.kolom in ("saldo_awal", "saldo_akhir"):
                asli = acc[k.kolom]
                acc[k.kolom] = k.nilai
            else:
                asli = acc["kategori"].get(k.kolom)
                acc["kategori"][k.kolom] = k.nilai
                slugs_muncul.add(k.kolom)
            info[k.kolom] = {
                "asli": asli, "nilai": k.nilai,
                "alasan": k.get_alasan_display() if k.alasan else "",
                "catatan": k.catatan,
                "oleh": getattr(k.dibuat_oleh, "username", "") or "",
                "waktu": k.updated_at,
            }
        acc["koreksi"] = info
        acc["mutasi"] = sum(acc["kategori"].values(), NOL)
        acc["deposit"] = acc["kategori"].get("deposit", NOL)
        acc["withdraw"] = abs(acc["kategori"].get("withdrawal", NOL))
        acc["net"] = acc["deposit"] - acc["withdraw"]
        acc["selisih"] = None
        if acc["saldo_awal"] is not None and acc["saldo_akhir"] is not None:
            acc["selisih"] = acc["saldo_akhir"] - (acc["saldo_awal"] + acc["mutasi"])


def _norm_akun(bank):
    return str(bank or "").strip() or "(Tanpa Akun)"


def _saldo_carry(toko, dari):
    """account(ternormalisasi) → saldo penutup pada hari-berbaris TERBARU < `dari`.

    (1) satu agregat SQL `Max(posted_date)` per akun untuk baris
    `posted_date < dari` → tanggal-penutup per akun (biasanya `dari−1`);
    (2) fetch baris HANYA untuk himpunan tanggal-penutup itu, lalu hitung
    penutup per (akun, tanggal) via `_saldo_batas`. Akun dorman bersaldo-lama
    tetap ikut (tak ada batas lookback).

    Catatan biaya: agregat (1) tetap MEMINDAI (sisi-DB) semua baris bracket
    toko pra-`dari` — bukan full-scan yang dimaterialisasi ke Python (itu yang
    dibatasi ke hari-hari "last" saja), tapi scan-nya tumbuh dgn sejarah. Satu
    agregat per render, bukan N+1; ringan pada skala sekarang. Bila baris
    bracket per toko membengkak (ratusan ribu), tambah indeks komposit
    (toko, source_type, posted_date) agar jadi index-range-scan.
    """
    last = (
        Transaction.objects.filter(
            toko=toko, source_type__key="bracket", posted_date__lt=dari
        )
        .annotate(fr_bank=KeyTextTransform("Bank", "raw"))
        .values("fr_bank")
        .annotate(d=Max("posted_date"))
    )
    per_acc_date = {}  # account_norm → tanggal-penutup
    for r in last:
        per_acc_date[_norm_akun(r["fr_bank"])] = r["d"]
    if not per_acc_date:
        return {}

    dates = set(per_acc_date.values())  # biasanya {dari−1}
    rows = (
        Transaction.objects.filter(
            toko=toko, source_type__key="bracket", posted_date__in=dates
        )
        .annotate(
            fr_bank=KeyTextTransform("Bank", "raw"),
            fr_jam=KeyTextTransform("Jam", "raw"),
        )
        .values_list("posted_date", "id", "money_delta", "balance_after", "fr_bank", "fr_jam")
    )
    by = {}  # (account_norm, posted_date) → items untuk _saldo_batas
    for pd, pk, delta, bal, bank, jam in rows:
        by.setdefault((_norm_akun(bank), pd), []).append(
            (f"{pd}T{jam or ''}", pk, delta or NOL, bal, None)
        )

    carry = {}
    for acc, d in per_acc_date.items():
        items = by.get((acc, d))
        if not items:
            continue
        items.sort(key=lambda t: (t[0], t[1]))
        _awal, akhir = _saldo_batas(items)
        if akhir is not None:
            carry[acc] = akhir
    return carry


def bracket_breakdown(toko, dari, sampai=None, dengan_koreksi=True):
    """Agregasi bracket `toko` untuk `posted_date ∈ [dari, sampai]` → dict view.

    Rentang [dari, sampai] (default `sampai=dari` = perilaku 1-hari). Untuk tiap
    akun: `saldo_awal` = saldo penutup (dari−1) bila ada (carry-forward), jika
    tidak pembukaan rantai in-range; `saldo_akhir` = penutup baris hari TERBARU
    ≤ sampai. Akun tanpa baris in-range tapi masih bersaldo (carry ≠ 0) tetap
    tampil sebagai baris carry murni (mutasi 0); yang carry == 0 disembunyikan.
    Koreksi FR (`FRKoreksi`) hanya berlaku pada tampilan 1 hari (`dari == sampai`).

    {"accounts": [per akun], "kolom": [(slug, label) yang muncul],
     "total": agregat lintas akun, "count": jumlah baris in-range,
     "dari": date, "sampai": date}
    """
    if sampai is None:
        sampai = dari
    if dari > sampai:
        dari, sampai = sampai, dari

    rows = (
        Transaction.objects.filter(
            toko=toko, source_type__key="bracket", posted_date__range=(dari, sampai)
        )
        .annotate(
            fr_bank=KeyTextTransform("Bank", "raw"),
            fr_kategori=KeyTextTransform("Kategori", "raw"),
            fr_jam=KeyTextTransform("Jam", "raw"),
        )
        .values_list(
            "posted_date", "id", "money_delta", "balance_after",
            "fr_bank", "fr_kategori", "fr_jam",
        )
    )

    per_akun = {}  # account → list[(komposit_jam, id, delta, balance, slug)]
    for pd, pk, delta, balance, bank, kategori, jam in rows:
        # kunci urutan komposit "tanggalTjam" agar rantai saldo benar lintas hari
        per_akun.setdefault(_norm_akun(bank), []).append(
            (f"{pd}T{jam or ''}", pk, delta or NOL, balance, _slug_kategori(kategori))
        )

    carry = _saldo_carry(toko, dari)  # account_norm → penutup (dari−1)

    accounts, slugs_muncul, seen = [], set(), set()
    for account, items in per_akun.items():
        items.sort(key=lambda t: (t[0], t[1]))  # (tanggalTjam, id) = kronologi
        kategori_sum, mutasi, trx = {}, NOL, 0
        deposit = withdraw = NOL
        for _jam, _pk, delta, balance, slug in items:
            kategori_sum[slug] = kategori_sum.get(slug, NOL) + delta
            mutasi += delta
            if slug == "deposit":
                deposit += delta
                trx += 1
            elif slug == "withdrawal":
                withdraw += delta
                trx += 1
        chain_awal, saldo_akhir = _saldo_batas(items)
        # utamakan penutup (dari−1) sebagai saldo awal; fallback pembukaan rantai
        saldo_awal = carry.get(account, chain_awal)
        withdraw = abs(withdraw)
        selisih = None
        if saldo_awal is not None and saldo_akhir is not None:
            selisih = saldo_akhir - (saldo_awal + mutasi)
        slugs_muncul.update(kategori_sum)
        name, role = _pecah_akun(account)
        seen.add(account)
        accounts.append({
            "account": account, "name": name, "role": role,
            "saldo_awal": saldo_awal, "saldo_akhir": saldo_akhir,
            "mutasi": mutasi, "selisih": selisih, "kategori": kategori_sum,
            "deposit": deposit, "withdraw": withdraw,
            "net": deposit - withdraw, "trx": trx,
            "koreksi": {},
        })

    # akun dorman: tak ada baris in-range tapi masih bersaldo (carry ≠ 0)
    for account, closing in carry.items():
        if account in seen or closing is None or closing == NOL:
            continue  # sudah tampil, atau saldo nol → disembunyikan
        name, role = _pecah_akun(account)
        accounts.append({
            "account": account, "name": name, "role": role,
            "saldo_awal": closing, "saldo_akhir": closing,
            "mutasi": NOL, "selisih": NOL, "kategori": {},
            "deposit": NOL, "withdraw": NOL, "net": NOL, "trx": 0,
            "koreksi": {},
        })

    if dengan_koreksi and dari == sampai:
        _apply_koreksi(toko, dari, accounts, slugs_muncul)

    accounts.sort(key=lambda a: (_URUT_PERAN.get(a["role"], 3), a["name"], a["account"]))

    kolom = [(slug, label) for slug, label in KATEGORI_KANONIK if slug in slugs_muncul]
    kolom += [
        (slug, slug.title())
        for slug in sorted(slugs_muncul - set(_KANONIK_URUT))
    ]

    total = {
        "kategori": {}, "mutasi": NOL, "deposit": NOL, "withdraw": NOL,
        "net": NOL, "trx": 0, "saldo_awal": None, "saldo_akhir": None, "selisih": None,
    }
    for acc in accounts:
        for slug, val in acc["kategori"].items():
            total["kategori"][slug] = total["kategori"].get(slug, NOL) + val
        total["mutasi"] += acc["mutasi"]
        total["deposit"] += acc["deposit"]
        total["withdraw"] += acc["withdraw"]
        total["net"] += acc["net"]
        total["trx"] += acc["trx"]
        for key in ("saldo_awal", "saldo_akhir", "selisih"):
            if acc[key] is not None:
                total[key] = (total[key] or NOL) + acc[key]

    return {
        "accounts": accounts,
        "kolom": kolom,
        "total": total,
        "count": sum(len(v) for v in per_akun.values()),
        "dari": dari,
        "sampai": sampai,
    }
