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
    ("beban mistake cs", "Beban Mistake CS"),
    ("beban other expense", "Beban Other Expense"),
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


def bracket_breakdown(toko, tanggal):
    """Agregasi bracket `toko` pada `posted_date == tanggal` → dict untuk view.

    {"accounts": [per akun], "kolom": [(slug, label) yang muncul],
     "total": agregat lintas akun, "count": jumlah baris}
    """
    rows = (
        Transaction.objects.filter(
            toko=toko, source_type__key="bracket", posted_date=tanggal
        )
        .annotate(
            fr_bank=KeyTextTransform("Bank", "raw"),
            fr_kategori=KeyTextTransform("Kategori", "raw"),
            fr_jam=KeyTextTransform("Jam", "raw"),
        )
        .values_list("id", "money_delta", "balance_after", "fr_bank", "fr_kategori", "fr_jam")
    )

    per_akun = {}  # account → list[(jam, id, delta, balance, slug)]
    for pk, delta, balance, bank, kategori, jam in rows:
        account = str(bank or "").strip() or "(Tanpa Akun)"
        per_akun.setdefault(account, []).append(
            (str(jam or ""), pk, delta or NOL, balance, _slug_kategori(kategori))
        )

    accounts, slugs_muncul = [], set()
    for account, items in per_akun.items():
        items.sort(key=lambda t: (t[0], t[1]))  # (Jam, id) = kronologi file
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
        saldo_awal, saldo_akhir = _saldo_batas(items)
        withdraw = abs(withdraw)
        selisih = None
        if saldo_awal is not None and saldo_akhir is not None:
            selisih = saldo_akhir - (saldo_awal + mutasi)
        slugs_muncul.update(kategori_sum)
        name, role = _pecah_akun(account)
        accounts.append({
            "account": account, "name": name, "role": role,
            "saldo_awal": saldo_awal, "saldo_akhir": saldo_akhir,
            "mutasi": mutasi, "selisih": selisih, "kategori": kategori_sum,
            "deposit": deposit, "withdraw": withdraw,
            "net": deposit - withdraw, "trx": trx,
        })

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
    }
