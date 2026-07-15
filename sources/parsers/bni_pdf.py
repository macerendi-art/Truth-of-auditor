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
