"""Parser PDF mutasi BNI Mobile Banking ("HISTORI TRANSAKSI"), sisi UANG.

Baris utama tiap transaksi tampil satu baris:
`<tgl> <uraian-awal> <Db./Cr.> <nominal> <saldo>`, deskripsi lanjutan di baris
berikutnya. Watermark "Mobile Banking" (miring) menyusup sbg baris 1-karakter &
huruf nyasar -> disaring. Anchor identitas = nomor rekening tujuan tertanam di
ekor deskripsi (disimpan utuh di raw untuk _money_phones).
"""
import re
from decimal import Decimal

from .base import parse_decimal, parse_dt, row_hash

# Gelar di depan nama transfer bank.
BNI_HONORIFIC_RE = re.compile(r"\b(?:Bpk|Bapak|Bp|Ibu|Sdr|Sdri)\.?\s+", re.IGNORECASE)
# Token struktural (bukan nama). Frasa panjang dulu.
BNI_STRUCT_RE = re.compile(
    r"TRANSFER\s+KE|TRF/PAY/TOP-UP|ECHANNEL\s+KARTU|BIZID|"
    r"ESPAY\s+DEBIT\s+INDONESIA|AIRPAY\s+INTERNATIONAL\s+INDONESIA|"
    r"Dana-DNID|LINKAJA|GOPAY|BY\s+TRX|BI-?FAST|BIAYA\s+ADMIN|ATM\s+BERSAMA|"
    r"LANDMARK|\bKOE\b|\bNO\b|\baba\w*",
    re.IGNORECASE,
)


def extract_bni_name(text):
    """Isolasi nama orang dari uraian BNI. Buang label struktural, gelar, dan
    token bernomor (rekening/HP/kode/VA). Baris tanpa nama (echannel/GOPAY/
    LINKAJA) -> '' (jangan dikarang)."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    s = BNI_HONORIFIC_RE.sub(" ", s)
    s = BNI_STRUCT_RE.sub(" ", s)
    # Sisakan hanya token beralfabet murni (tanpa angka) -> buang nomor/kode.
    toks = [t for t in s.split() if re.search(r"[A-Za-z]", t) and not re.search(r"\d", t)]
    return re.sub(r"\s+", " ", " ".join(toks)).strip(" -.,:/)(")


# --- Fee (dikecualikan dari total WD & matching) ---
BNI_FEE_RE = re.compile(r"BY\s+TRX|BIAYA\s+ADMIN", re.IGNORECASE)


def is_bni_fee(desc):
    return bool(BNI_FEE_RE.search(str(desc or "")))


# Baris/footer/header yang bukan lanjutan deskripsi transaksi.
_SKIP = (
    "HISTORI TRANSAKSI", "Kriteria Pencarian", "Rekening:", "Tanggal Awal",
    "Tanggal Akhir", "Kategori", "Transactions List", "Uraian Transaksi",
    "Saldo Akhir", "Printed on", "Page ", "Transaksi",
)
# Baris utama: diawali tanggal ISO; sisanya diakhiri Tipe + nominal + saldo.
_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\b(.*)$")
_ROW_RE = re.compile(r"^(.*?)\s*[A-Za-z]?(Db|Cr)\.\s+([\d.]+,\d{2})\s+([\d.]+,\d{2})\s*$")


def _is_skip(s):
    return any(k in s for k in _SKIP)


def parse_bni_lines(lines):
    """Ubah baris teks PDF BNI jadi daftar dict Transaction. Buang watermark
    (baris <=1 karakter), toleran huruf nyasar sebelum Db/Cr (mis. 'lDb.')."""
    txns, cur = [], None
    for ln in lines:
        s = ln.strip()
        if len(s) <= 1:                    # watermark 1-karakter
            continue
        m = _DATE_RE.match(s)
        if m and _ROW_RE.match(m.group(2).strip()):
            cur = {"date": m.group(1), "rest": m.group(2).strip(), "cont": []}
            txns.append(cur)
        elif cur is not None and not _is_skip(s):
            cur["cont"].append(s)

    out = []
    for idx, t in enumerate(txns):
        rm = _ROW_RE.match(t["rest"])
        if not rm:
            continue
        desc_head, tipe, nom, saldo = (rm.group(1).strip(), rm.group(2),
                                       rm.group(3), rm.group(4))
        amount = parse_decimal(nom, "id")
        money = amount if tipe == "Cr" else -amount
        saldo_val = parse_decimal(saldo, "id")
        full_desc = (desc_head + " " + " ".join(t["cont"])).strip()
        occurred = parse_dt(t["date"])     # ISO, tanpa jam
        jenis = "admin" if is_bni_fee(full_desc) else ("depo" if money > 0 else "wd")
        row = {
            "source_type": "bank",
            "occurred_at": occurred,
            "posted_date": occurred.date() if occurred else None,
            "jenis": jenis,
            "amount": amount,
            "credit_delta": Decimal("0"),
            "money_delta": money,
            "fee": Decimal("0"),
            "bonus": Decimal("0"),
            "balance_after": saldo_val,
            "ticket_no": "",
            "username": "",
            "reference": "",
            "counterparty": extract_bni_name(full_desc),
            "description": full_desc,
            "raw": {"tanggal": t["date"], "uraian": full_desc, "tipe": tipe,
                    "nominal": str(amount), "saldo": str(saldo_val)},
        }
        row["row_hash"] = row_hash("bni", [t["date"], amount, tipe, saldo_val, idx])
        out.append(row)
    return out
