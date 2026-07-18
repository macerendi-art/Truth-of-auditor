"""Aturan baris fee admin bank — nominal tetap + pola deskripsi per bank.

Tarif dari matriks klien: e-wallet 1.000 · BI Fast 2.500 · transfer
realtime/online 6.500. Bukti kalibrasi prod 18-07-2026 (8.937 baris legacy):
BRI `ATMSTRPRM…`@6500, `BFST…`@2500 (transfer BI-Fast min 10rb → 2.500 pasti
fee), `BRIVA…`@1000 (fee kembar); Mandiri teks eksplisit "Biaya …".
Dipakai DUA arah: parser saat ingest (data baru) dan laporan Rincian Biaya
saat baca (baris legacy yang terlanjur tanpa tanda). Pola numerik BRI 6.500
yang ambigu SENGAJA tidak ditandai (tunggu kalibrasi lanjutan).
"""
from decimal import Decimal

_F1000 = Decimal("1000")
_F2500 = Decimal("2500")
_F6500 = Decimal("6500")


def is_admin_fee(bank, description, amount):
    """True bila baris KELUAR ini biaya admin menurut pola bank tsb.

    `bank` = kunci parser lower ("bri"/"mandiri"/"bca"/…); `amount` nilai
    non-negatif (abs) — pemanggil memastikan arah keluar (money_delta < 0).
    """
    d = str(description or "").strip().upper()
    if not d:
        return False
    try:
        amt = Decimal(str(amount))
    except Exception:  # noqa: BLE001 — nilai aneh dianggap bukan fee
        return False
    if bank == "mandiri":
        return d.startswith("BIAYA")
    if bank == "bri":
        return (
            (d.startswith("ATMSTRPRM") and amt == _F6500)
            or (d.startswith("BFST") and amt == _F2500)
            or (d.startswith("BRIVA") and amt == _F1000)
        )
    if bank == "bca":
        return "BIAYA TXN" in d
    return False
