"""Rincian Rekening — breakdown sisi UANG (bank/gateway) per rekening operator.

Kembaran Breakdown Bracket untuk mutasi bank nyata. Baris per rekening
(`source_label_full`, mis. "BCA a/n HENDI"): Deposit / Withdraw / Biaya Admin /
Net / Trx / Saldo Awal / Saldo Akhir / Selisih Kontrol. Saldo memakai
`balance_after` (saldo berjalan statement) via metode rantai-saldo yang sama
dengan breakdown FR (`_saldo_batas`) — kebal acak urutan. Sumber tanpa saldo
(gateway QRIS, BCA PDF) → saldo & selisih "—".
"""
from decimal import Decimal

from transactions.models import Transaction
from web.breakdown import _saldo_batas

NOL = Decimal("0")
MONEY_KEYS = ("bank", "gateway")


def rekening_breakdown(toko, dari, sampai=None):
    """Agregasi sisi uang `toko` untuk `occurred_at ∈ [dari, sampai]` → dict view.

    Rentang [dari, sampai] (default `sampai=dari` = perilaku 1-hari lama, dipakai
    juga oleh sheet export per-batch). Saldo memakai `balance_after`: karena baris
    diurut `(occurred_at, id)` — `occurred_at` datetime penuh, jadi rantai saldo
    benar lintas hari — `_saldo_batas` atas baris in-range menghasilkan saldo_awal
    = saldo sebelum baris pertama rentang (carry-in dari hari sebelumnya, otomatis)
    dan saldo_akhir = penutup baris terakhir. Rekening tanpa baris in-range tak
    tampil (sama seperti mode 1-hari).

    {"accounts": [per rekening], "total": agregat, "count": jumlah baris,
     "dari": date, "sampai": date}
    """
    if sampai is None:
        sampai = dari
    if dari > sampai:
        dari, sampai = sampai, dari
    rows = (
        Transaction.objects.filter(
            toko=toko, source_type__key__in=MONEY_KEYS,
            occurred_at__date__range=(dari, sampai),
        )
        .select_related("source_type", "upload", "account", "upload__account")
        .order_by("occurred_at", "id")
    )

    per = {}  # label → {"items": [...], "is_gateway": bool}
    count = 0
    for t in rows:
        count += 1
        label = t.source_label_full
        slot = per.setdefault(label, {"items": [], "is_gateway": False})
        if t.source_type.key == "gateway":
            slot["is_gateway"] = True
        slug = "admin" if t.jenis == "admin" else ("deposit" if t.money_delta > 0 else "withdrawal")
        # bentuk tuple sama dgn breakdown FR agar _saldo_batas bisa dipakai ulang:
        # (jam, id, delta, balance, slug) — query sudah urut (occurred_at, id).
        slot["items"].append((t.occurred_at, t.id, t.money_delta or NOL, t.balance_after, slug))

    accounts = []
    for label, slot in per.items():
        items = slot["items"]
        deposit = withdraw = admin = mutasi = NOL
        trx = 0
        for _jam, _pk, delta, _bal, slug in items:
            mutasi += delta
            if slug == "admin":
                admin += delta
            elif delta > 0:
                deposit += delta
                trx += 1
            elif delta < 0:
                withdraw += delta
                trx += 1
        withdraw = abs(withdraw)
        saldo_awal, saldo_akhir = _saldo_batas(items)
        selisih = None
        if saldo_awal is not None and saldo_akhir is not None:
            selisih = saldo_akhir - (saldo_awal + mutasi)
        accounts.append({
            "label": label, "is_gateway": slot["is_gateway"],
            "deposit": deposit, "withdraw": withdraw, "admin": admin,
            "net": deposit - withdraw, "trx": trx, "mutasi": mutasi,
            "saldo_awal": saldo_awal, "saldo_akhir": saldo_akhir, "selisih": selisih,
        })

    accounts.sort(key=lambda a: (a["is_gateway"], a["label"]))

    total = {
        "deposit": NOL, "withdraw": NOL, "admin": NOL, "net": NOL, "trx": 0,
        "mutasi": NOL, "saldo_awal": None, "saldo_akhir": None, "selisih": None,
    }
    for a in accounts:
        for k in ("deposit", "withdraw", "admin", "net", "trx", "mutasi"):
            total[k] += a[k]
        for k in ("saldo_awal", "saldo_akhir", "selisih"):
            if a[k] is not None:
                total[k] = (total[k] or NOL) + a[k]
    return {
        "accounts": accounts, "total": total, "count": count,
        "dari": dari, "sampai": sampai,
    }
