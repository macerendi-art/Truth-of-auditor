"""Parser bank (sumber UANG). Format beda tiap bank.

- BRI : CSV, header baris 1, kolom MUTASI_DEBET/KREDIT + SALDO_AKHIR_MUTASI.
- BCA : CSV, ada preamble; header 'Tanggal,Keterangan,Cabang,Jumlah,,Saldo' (DB/CR).
- Mandiri: xlsx e-Statement; header 2 baris; tiap transaksi 2 baris (tgl lalu jam);
  angka format ID (1.000,00).
"""
import re
from decimal import Decimal

import openpyxl

from .base import (
    BaseParser,
    normalize_dest,
    parse_decimal,
    parse_dt,
    read_csv_raw,
    row_hash,
    rows_to_dicts,
)


def _jenis_from_money(money):
    return "depo" if money > 0 else "wd" if money < 0 else "lainnya"


# Baris biaya transaksi BCA ("BI-FAST DB BIAYA TXN ... 2.500"): tiap WD nyata
# berpasangan dengan satu baris fee ini. Ditandai 'admin' agar dikecualikan dari
# uang WD & pencocokan (baris tetap disimpan untuk audit).
BCA_FEE_RE = re.compile(r"BIAYA\s+TXN", re.IGNORECASE)


def is_bca_fee(desc):
    return bool(BCA_FEE_RE.search(str(desc or "")))


# ---------------------------------------------------------------------------
# Isolasi nama (Task 4). Urutan wajib: buang teks struktural per-sumber DULU,
# baru nama dinormalisasi (clean_name) di engine saat fuzzy matching.
# Angka/simbol masih dibutuhkan di tahap ini untuk mengenali pola struktural.
# ---------------------------------------------------------------------------

# --- BCA (dipakai CSV & PDF) ---
# Nama via baris lanjutan e-wallet: 'TRFDN-<nama>ESPAY DEBIT INDONE' (bisa menempel).
BCA_TRFDN_RE = re.compile(r"TRFDN-\s*(.+?)\s*(?:ESPAY\s+DEBIT\s+INDONE\S*|ESPAY|$)")
# Kode transaksi: '2706/FTSCY/WS95271', '2606/FTFVA/WS9501139010/DANA', dst.
BCA_CODE_RE = re.compile(r"\b\d{3,4}/[A-Z]+/\S+")
# Nominal menempel ke nama: '100000.00M. YULIANSAR SIREG' -> nama di belakang nominal.
BCA_GLUED_AMT_RE = re.compile(r"\d[\d,.]*\.\d{2}\s*(.*)$")
# Label/kata struktural yang bukan bagian nama (frasa dulu, baru kata tunggal).
BCA_NOISE_RE = re.compile(
    r"TRSF E-BANKING|BI-?FAST|SWITCHING|ESPAY\s+DEBIT\s+INDONE\S*|DEBIT\s+INDONE\S*|ESPAY"
    r"|Web BRILink|MyBCA|\bKBI\b|\bTOPUP\b|\bTANGGAL\b|\bTRANSFER\b|\bBIAYA\b|\bTXN\b"
    r"|\bTRF\b|\bDR\b|\bKE\b|\bCR\b|\bDB\b"
)


def extract_bca_name(text):
    """Isolasi nama orang dari keterangan BCA: buang kode transaksi, label
    struktural, nominal menempel, & nomor rekening/HP. Baris tanpa nama
    (mis. topup DANA/GOPAY hanya nomor HP) -> '' (jangan dikarang)."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    trfdn = BCA_TRFDN_RE.search(s)
    s = BCA_TRFDN_RE.sub(" ", s)
    s = BCA_CODE_RE.sub(" ", s)
    s = BCA_NOISE_RE.sub(" ", s)
    m = BCA_GLUED_AMT_RE.search(s)
    if m:  # nama menempel di belakang nominal -> ambil bagian setelahnya
        s = m.group(1)
    # Sisa token murni angka/simbol = nomor rekening/HP/kode -> bukan nama.
    toks = [t for t in s.split() if re.search(r"[A-Za-z]", t) and not re.search(r"\d", t)]
    name = " ".join(toks).strip(" -.,:/")
    if not name and trfdn:  # fallback: nama dari baris lanjutan TRFDN
        name = trfdn.group(1).strip(" -.,:/")
    return re.sub(r"\s+", " ", name).strip()


# --- Ekstraksi nomor tujuan BCA (dipakai CSV & PDF) — HANYA topup e-wallet ---
# Terbukti di data: HP tujuan muncul setelah pola '- - <hp>' ('.../DANA - - 083..').
BCA_DEST_DASH_RE = re.compile(r"-\s+-\s+0?(\d{9,13})")
# Fallback: HP di ekor tanpa '- -' ('GOPAY TOPUP ... 085..'), tapi HANYA pada baris
# topup e-wallet agar tak menangkap nomor referensi transfer bank ('TRF 5316.. NAMA').
BCA_DEST_TAIL_RE = re.compile(r"0?(\d{9,13})(?:\s+TRSF|\s*$)")
BCA_EWALLET_RE = re.compile(r"\b(DANA|GOPAY|OVO|SHOPEEPAY|LINKAJA)\b", re.IGNORECASE)


def extract_bca_dest(text):
    """Nomor tujuan (HP e-wallet) dari keterangan BCA -> ternormalisasi, atau ''.

    Transfer bank-ke-bank ('TRANSFER KE 535 <NAMA> BI-FAST DB') hanya mencatat NAMA,
    tak ada nomor -> ''. Nomor hanya diambil dari topup e-wallet (DANA/GOPAY/dst)."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    m = BCA_DEST_DASH_RE.search(s)
    if m:
        return normalize_dest(m.group(1))
    if BCA_EWALLET_RE.search(s):  # fallback hanya utk baris topup e-wallet
        m = BCA_DEST_TAIL_RE.search(s)
        if m:
            return normalize_dest(m.group(1))
    return ""


# --- Ekstraksi nomor tujuan BRI ---
# Transfer keluar e-wallet 'BFST<nomor>' & virtual account 'BRIVA<va>'. Baris internal
# 'NBMB ... TO <NAMA> ESB:...' hanya punya NAMA (ekor angka = referensi ESB) -> ''.
BRI_DEST_BFST_RE = re.compile(r"BFST(\d{9,})")
BRI_DEST_BRIVA_RE = re.compile(r"BRIVA\s?(\d{11,})")


def extract_bri_dest(text):
    """Nomor tujuan BRI dari deskripsi (BFST/BRIVA) -> ternormalisasi, atau ''."""
    s = str(text or "")
    m = BRI_DEST_BFST_RE.search(s)
    if m:
        return normalize_dest(m.group(1))
    m = BRI_DEST_BRIVA_RE.search(s)
    if m:
        return normalize_dest(m.group(1))
    return ""


# --- Mandiri ---
# Prefiks: 'Transfer dari/ke ...', 'Transfer BI Fast Dari/Ke ...',
# 'Transfer antar Mandiri DARI ...' (+ opsional 'Bank lain').
MANDIRI_PREFIX_RE = re.compile(
    r"^Transfer\s+(?:BI\s*Fast\s+)?(?:dari|ke|antar)\s+(?:Mandiri\s+(?:dari|ke)\s+)?(?:Bank\s+lain\s+)?",
    re.IGNORECASE,
)
# Nama bank pengirim/penerima (terpanjang dulu agar 'BANK MANDIRI TASPEN'
# tidak terpotong jadi 'BANK MANDIRI' + sisa 'TASPEN').
MANDIRI_BANK_NAMES = (
    "BANK MANDIRI TASPEN", "SUPER BANK INDONESIA", "SEABANK INDONESIA",
    "BANK RAKYAT INDONESIA", "BANK CENTRAL ASIA", "BANK NEGARA INDONESIA",
    "BANK SYARIAH INDONESIA", "BANK NEO COMMERCE", "BANK CIMB NIAGA",
    "BANK MANDIRI", "BANK DANAMON", "BANK PERMATA", "BANK JAGO", "BANK MEGA",
    "BANK BTPN", "BANK BNI", "BANK BRI", "BANK BCA", "BANK BTN", "BANK BJB",
    "BCA DIGITAL", "CIMB NIAGA", "SUPERBANK", "ALLO BANK", "SEABANK",
    "BCA", "BRI", "BNI", "BTN", "BSI",
)
# Ekor struktural GoPay/fee: buang sampai akhir teks.
MANDIRI_TAIL_RES = (
    re.compile(r"\bGoPay\s+Bank\s+Transfer\b.*$", re.IGNORECASE),
    re.compile(r"\bTransfer\s+Fee\b.*$", re.IGNORECASE),
)


def extract_mandiri_name(text):
    """Isolasi nama dari Keterangan Mandiri e-statement: buang prefiks
    'Transfer dari/ke <BANK>', nama bank, dan nomor rekening/referensi di ekor.
    Baris biaya/pembayaran tanpa nama -> ''. """
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s.lower().startswith("transfer"):
        return ""  # 'Biaya ...' / 'Pembayaran GoPay Customer <HP>' -> tanpa nama
    stripped = MANDIRI_PREFIX_RE.sub("", s)
    if stripped == s:  # bukan pola transfer yang dikenal -> jangan menebak
        return ""
    s = stripped.strip()
    upper = s.upper()
    for bank in MANDIRI_BANK_NAMES:  # buang nama bank di depan (batas kata)
        if upper == bank or upper.startswith(bank + " "):
            s = s[len(bank):].strip()
            break
    s = re.sub(r"^DANA-\s*", "", s)  # e-wallet: 'DANA-<nama>' menempel
    for tail_re in MANDIRI_TAIL_RES:
        s = tail_re.sub("", s).strip()
    # Ekor nomor rekening/HP/referensi (mengandung angka) + tanda '-'.
    toks = s.split()
    while toks and (re.search(r"\d", toks[-1]) or toks[-1] in ("-", "transfer")):
        toks.pop()
    return " ".join(toks).strip(" -.,:/")


class BRIParser(BaseParser):
    source_key = "bank"

    def parse(self, path, flow=""):
        rows = read_csv_raw(path)
        _, dicts = rows_to_dicts(rows, 0)
        out = []
        for r in dicts:
            debit = parse_decimal(r.get("MUTASI_DEBET"))
            credit = parse_decimal(r.get("MUTASI_KREDIT"))
            money = credit - debit
            occurred = parse_dt(r.get("TGL_TRAN"))
            desc = str(r.get("DESK_TRAN", "") or "")
            m = re.search(r"NBMB (.+?) TO (.+?) ESB", desc)
            sender, receiver = (m.group(1).strip(), m.group(2).strip()) if m else ("", "")
            counterparty = sender if money > 0 else receiver
            seq = str(r.get("SEQ", "") or "").strip()
            row = {
                "source_type": "bank",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": _jenis_from_money(money),
                "amount": abs(money),
                "credit_delta": Decimal("0"),
                "money_delta": money,
                "fee": Decimal("0"),
                "bonus": Decimal("0"),
                "balance_after": parse_decimal(r.get("SALDO_AKHIR_MUTASI")),
                "ticket_no": "",
                "username": "",
                "reference": seq,
                "counterparty": counterparty,
                "dest_account": extract_bri_dest(desc),
                "description": desc,
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items()},
            }
            row["row_hash"] = row_hash("bri", [r.get("NOREK", ""), seq, occurred, money])
            out.append(row)
        return out


class BCACSVParser(BaseParser):
    source_key = "bank"

    def parse(self, path, flow=""):
        rows = read_csv_raw(path)
        hidx = None
        for i, r in enumerate(rows):
            cells = [str(c).strip() for c in r]
            if "Tanggal" in cells and "Saldo" in cells:
                hidx = i
                break
        if hidx is None:
            return []
        _, dicts = rows_to_dicts(rows, hidx)
        out = []
        for r in dicts:
            jumlah = parse_decimal(r.get("Jumlah"))
            dbcr = ""
            for v in r.values():
                vv = str(v).strip().upper()
                if vv in ("DB", "CR"):
                    dbcr = vv
                    break
            money = jumlah if dbcr == "CR" else -jumlah
            occurred = parse_dt(r.get("Tanggal"), dayfirst=True)
            if occurred is None:  # skip baris ringkasan (Saldo Awal/Akhir/Mutasi)
                continue
            desc = str(r.get("Keterangan", "") or "")
            row = {
                "source_type": "bank",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "admin" if is_bca_fee(desc) else _jenis_from_money(money),
                "amount": abs(money),
                "credit_delta": Decimal("0"),
                "money_delta": money,
                "fee": Decimal("0"),
                "bonus": Decimal("0"),
                "balance_after": parse_decimal(r.get("Saldo")),
                "ticket_no": "",
                "username": "",
                "reference": "",
                "counterparty": extract_bca_name(desc),
                "dest_account": extract_bca_dest(desc),
                "description": desc,
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items()},
            }
            row["row_hash"] = row_hash("bca", [occurred, money, r.get("Saldo", ""), desc[:60]])
            out.append(row)
        return out


class MandiriParser(BaseParser):
    source_key = "bank"

    def parse(self, path, flow=""):
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        allrows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()

        hidx = None
        for i, r in enumerate(allrows):
            cells = [str(c).strip() if c is not None else "" for c in r]
            if "Tanggal" in cells and "Keterangan" in cells:
                hidx = i
                break
        if hidx is None:
            return []
        hdr = [str(c).strip() if c is not None else "" for c in allrows[hidx]]

        def colof(name):
            return hdr.index(name) if name in hdr else None

        c_no, c_tgl, c_ket = colof("No"), colof("Tanggal"), colof("Keterangan")
        c_in, c_out, c_saldo = (
            colof("Dana Masuk (IDR)"),
            colof("Dana Keluar (IDR)"),
            colof("Saldo (IDR)"),
        )

        def cell(r, j):
            return r[j] if (j is not None and j < len(r)) else None

        out = []
        i, n = hidx + 1, len(allrows)
        while i < n:
            r = allrows[i]
            cells = [str(c).strip() if c is not None else "" for c in r]
            if "Date" in cells and "Remarks" in cells:  # sub-header bahasa Inggris
                i += 1
                continue
            no, tgl = cell(r, c_no), cell(r, c_tgl)
            if (no in (None, "")) and (tgl in (None, "")):
                i += 1
                continue

            datestr = str(tgl).strip() if tgl else ""
            ket = str(cell(r, c_ket) or "").strip()
            masuk = parse_decimal(cell(r, c_in), "id")
            keluar = parse_decimal(cell(r, c_out), "id")
            saldo = parse_decimal(cell(r, c_saldo), "id")

            timestr = ""
            if i + 1 < n:
                nr = allrows[i + 1]
                ntgl = str(cell(nr, c_tgl) or "").strip()
                nno = cell(nr, c_no)
                if (nno in (None, "")) and re.search(r"\d{1,2}:\d{2}", ntgl):
                    timestr = ntgl.replace("WIB", "").strip()
                    nket = str(cell(nr, c_ket) or "").strip()
                    if nket:
                        ket = f"{ket} {nket}".strip()
                    i += 1

            occurred = parse_dt(f"{datestr} {timestr}".strip(), dayfirst=True)
            money = masuk - keluar
            row = {
                "source_type": "bank",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": _jenis_from_money(money),
                "amount": abs(money),
                "credit_delta": Decimal("0"),
                "money_delta": money,
                "fee": Decimal("0"),
                "bonus": Decimal("0"),
                "balance_after": saldo,
                "ticket_no": "",
                "username": "",
                "reference": "",
                "counterparty": extract_mandiri_name(ket.replace("\n", " ")),
                "description": ket.replace("\n", " "),
                "raw": {"Tanggal": datestr, "Jam": timestr, "Keterangan": ket.replace("\n", " "),
                        "Masuk": str(masuk), "Keluar": str(keluar), "Saldo": str(saldo)},
            }
            row["row_hash"] = row_hash("mandiri", [saldo, occurred, money, ket[:30]])
            out.append(row)
            i += 1
        return out
