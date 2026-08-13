"""Parser bonus: panel Credit Balance & bracket Credit/Non-Credit Bonus (MUL/M77).

Panel `Credit Balance` = ledger kredit penuh; yang diambil HANYA baris bonus
(Redemption Coupon / Promotion Claim / Lucky Draw Agent / Adjustment). Baris
Deposit/Withdraw/Offset/Opening/Reject dilewati — DP/WD sudah diimpor parser
panel biasa, dan Offset = penyeimbang net-nol Lucky Draw (bukan bonusnya).
Bracket bonus: file `Credit Bonus` (ada kolom Category) dan `Non Credit Bonus`
(tanpa Category; kode di Description — K-BLD = Lucky Draw) — satu parser.

Panel bonus punya DUA bentuk: `PanelBonusParser` (Nexus, Credit Balance) dan
`CORPanelBonusParser` (keluarga COR/Vigor/TM Gaming) — keduanya menulis ke
SourceType `panel_bonus` yang sama.

Amt panel Nexus dalam RIBUAN (×1000); Nominal bracket DAN nominal panel COR
sudah rupiah penuh.
Bonus bukan uang: money_delta=0, tak pernah ikut matcher/completeness harian
(SourceType terpisah `panel_bonus`/`bracket_bonus`).
"""
import re
from decimal import Decimal

from .base import BaseParser, parse_decimal, parse_dt, read_xlsx_rows, row_hash

SCALE = Decimal(1000)  # 1 kredit panel = Rp1.000
NOL = Decimal("0")

# Awalan Description panel yang merupakan bonus -> kategori kanonik.
_PANEL_KATEGORI = [
    ("Redemption Coupon", "Redemption Coupon"),
    ("Promotion Claim", "Promotion Claim"),
    ("Lucky Draw Agent", "Lucky Draw"),
    ("Adjustment:", "Adjustment"),
]

# Kode Description bracket non-credit -> kategori kanonik (mapping klien).
KODE_BONUS = {"K-BLD": "Lucky Draw"}

_PLAYER_RE = re.compile(r"Player:\s*(.+)", re.IGNORECASE)


def _username_panel(desc, brand):
    """Token terakhir Description; buang prefix brand ('M77Maxx28' -> 'Maxx28')."""
    tokens = desc.split()
    if not tokens:
        return ""
    u = tokens[-1]
    if brand and u.lower().startswith(brand.lower()) and len(u) > len(brand):
        u = u[len(brand):]
    return u.strip()


class PanelBonusParser(BaseParser):
    source_key = "panel_bonus"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=2)
        out = []
        for r in rows:
            desc = str(r.get("Description", "") or "").strip()
            kategori = next(
                (k for pfx, k in _PANEL_KATEGORI if desc.startswith(pfx)), None)
            if kategori is None:
                continue  # Deposit/Withdraw/Offset/Opening/Reject dll.
            amt = parse_decimal(r.get("Amt.")) * SCALE
            occurred = parse_dt(r.get("Date & Time"))
            brand = str(r.get("Brand", "") or "").strip()
            raw = {k: ("" if v is None else str(v)) for k, v in r.items()}
            raw["Kategori"] = kategori
            row = {
                "source_type": "panel_bonus",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "bonus",
                "amount": abs(amt),
                "credit_delta": amt,  # negatif = kredit keluar ke player
                "money_delta": NOL,
                "fee": NOL,
                "bonus": abs(amt),
                "balance_after": None,
                "ticket_no": "",
                "username": _username_panel(desc, brand),
                "reference": "",
                "counterparty": "",
                "description": desc,
                "player_bank": "",
                "bank_title": "",
                "raw": raw,
            }
            row["row_hash"] = row_hash(
                "panel_bonus", [raw.get("Date & Time", ""), desc, row["amount"]])
            out.append(row)
        return out


class BracketBonusParser(BaseParser):
    source_key = "bracket_bonus"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=1)
        out = []
        for r in rows:
            if str(r.get("Deleted", "") or "").strip().lower() == "yes":
                continue
            desc = str(r.get("Description", "") or "").strip()
            tid = str(r.get("Transaction ID", "") or "").strip()
            if not desc and not tid:
                continue  # baris kosong/footer
            kategori = str(r.get("Category", "") or "").strip()
            if not kategori:
                kode = desc.split()[0] if desc.split() else ""
                kategori = KODE_BONUS.get(kode, kode or "Bonus")
            m = _PLAYER_RE.search(desc)
            nominal = abs(parse_decimal(r.get("Nominal")))  # rupiah penuh
            occurred = parse_dt(r.get("Date"))
            raw = {k: ("" if v is None else str(v)) for k, v in r.items()}
            raw["Kategori"] = kategori
            row = {
                "source_type": "bracket_bonus",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "bonus",
                "amount": nominal,
                "credit_delta": -nominal,
                "money_delta": NOL,
                "fee": NOL,
                "bonus": nominal,
                "balance_after": None,
                "ticket_no": "",
                "username": (m.group(1).strip() if m else ""),
                "reference": "",
                "counterparty": "",
                "description": desc,
                "player_bank": "",
                "bank_title": "",
                "raw": raw,
            }
            row["row_hash"] = row_hash(
                "bracket_bonus", [tid, raw.get("Date", ""), desc, row["amount"]])
            out.append(row)
        return out


# --- Bonus panel keluarga COR (Vigor / TM Gaming) ------------------------

# Penanda di `raw["Sumber"]` setiap baris parser ini. Dipakai fase lanjut
# (rekonsiliasi dua modus) sebagai GERBANG: modus agregat hanya menyala bila
# ada baris berpenanda. Nol baris produksi membawanya hari ini, dan hanya
# parser ini yang bisa menciptakannya — jadi baris Nexus mustahil terseret.
MARKER_AGREGAT = "cor_panel_bonus"

# Kolom yang harus ada. Pelajaran QRFlyer: penjaga tingkat-HASIL tak bisa
# melihat ganti-nama kolom yang tetap menghasilkan baris (bentuk 3: 1.519 baris
# ber-nominal 0 dan tanpa tanggal, terlihat "berhasil"). Jadi digerbang di
# header, dan sengaja cocok-nama PERSIS: rename harus berbunyi keras.
_WAJIB_COR_BONUS = ("Date", "Username", "Event Name", "Amount")

_LABEL_PAGE = "page total"
_LABEL_GRAND = "grand total"


def _teks(v):
    return "" if v is None else str(v).strip()


class CORPanelBonusParser(BaseParser):
    """Bonus panel bentuk kedua: ekspor keluarga COR (Vigor/TM Gaming).

    Header di baris 1: `# | Date | Username | Event Type | Event Name |
    Amount | Description`. Beda struktur total dari ekspor Nexus
    `Credit Balance` di atas, tapi invariannya sama persis — karena itu ia
    tinggal di modul ini: `raw["Kategori"]`, `money_delta=0`, SourceType
    terpisah, tak pernah menyentuh matcher/kelengkapan harian.

    `source_key = "panel_bonus"` — memakai ULANG SourceType yang ada, tanpa
    migrasi (preseden: `bca_pdf`/`bni_pdf` sama-sama `source_key="bank"`).

    Tiga fakta lokal COR:

    * **Rupiah penuh, TANPA ×1000** — lihat komentar di baris nominal.
    * openpyxl **gagal** membuka berkas ini (`could not read stylesheet`), jadi
      `read_xlsx_rows` jatuh ke reader mentah dan setiap sel tiba sebagai
      `str`. Kalau vendor kelak memperbaiki stylesheet-nya, sel yang sama tiba
      BERTIPE — karena itu `row_hash` dihitung dari nilai hasil parse, bukan
      teks sel mentah (kalau tidak, seluruh baris lama terduplikasi).
    * Username ditulis apa adanya, **tanpa prefix brand** — jangan dikupas,
      `w25master` adalah nama pemain yang sah.

    Tiga penjaga, berurutan: penjaga header, lompatan baris kaki secara
    STRUKTURAL (tanggal tak terurai DAN username kosong — bukan cocok-label,
    supaya `Subtotal`/label terterjemahkan ikut tertangkap), lalu tie-out
    jumlah baris data terhadap angka yang **dicetak berkas itu sendiri**.
    Tie-out itulah yang membuat lompatan kaki aman: salah klasifikasi ke arah
    mana pun menggeser jumlahnya. Blocker kelas KEPASTIAN — berkas hanya
    dibandingkan dengan dirinya sendiri, jadi mustahil menuduh brand baru.
    """

    source_key = "panel_bonus"

    def parse(self, path, flow=""):
        headers, rows = read_xlsx_rows(path, header_row=1)
        headers = [h for h in (headers or []) if h]
        kurang = [k for k in _WAJIB_COR_BONUS if k not in headers]
        if kurang:
            raise ValueError(
                "Bonus panel COR: kolom wajib tidak ditemukan: "
                f"{', '.join(kurang)}. Header yang ada: "
                f"{', '.join(headers) if headers else '(tidak ada)'}. "
                "Kemungkinan vendor mengganti nama kolom — kirim berkasnya "
                "ke pengembang, jangan diunggah ulang."
            )

        out = []
        total_data = NOL
        page_total, ada_page = NOL, False
        grand_total, ada_grand = NOL, False

        for r in rows:
            occurred = parse_dt(r.get("Date"))  # 'dd Mmm yyyy' -> tak ambigu
            username = _teks(r.get("Username"))
            if occurred is None:
                if username:
                    # BUKAN baris kaki (username terisi). Menerbitkannya tanpa
                    # tanggal = persis kegagalan senyap yang rilis ini tutup:
                    # occurred_at NULL menghilangkan baris dari jendela mesin,
                    # posted_date NULL menghilangkannya dari semua laporan.
                    raise ValueError(
                        "Bonus panel COR: baris ber-username "
                        f"'{username}' punya tanggal yang tak terbaca "
                        f"('{_teks(r.get('Date'))}'). Bentuk berkasnya berubah "
                        "— kirim berkasnya ke pengembang, jangan diunggah ulang."
                    )
                # Baris kaki. Labelnya dibaca HANYA untuk tie-out di bawah.
                label = {_teks(v).lower() for v in r.values()}
                if _LABEL_PAGE in label:
                    ada_page = True
                    page_total += parse_decimal(r.get("Amount"))
                elif _LABEL_GRAND in label:
                    ada_grand = True
                    grand_total += parse_decimal(r.get("Amount"))
                continue

            # RUPIAH PENUH — JANGAN kalikan `SCALE`. `SCALE` di atas milik panel
            # Nexus (Amt. dalam ribuan); ekspor COR sudah rupiah. Bukti: 677
            # baris berkas 04-08-2026 berjumlah 1.358.797,20 = persis baris
            # "Grand Total" berkas itu sendiri. Mode desimal `intl` (default):
            # '85,770' -> 85770 (mode 'id' akan memberi 85,770).
            amt = parse_decimal(r.get("Amount"))
            total_data += amt
            event_name = _teks(r.get("Event Name"))
            event_type = _teks(r.get("Event Type"))
            # `Event Type` meleburkan 'Daily Login' + 'Single Deposit' jadi satu,
            # padahal bracket membukukannya sebagai DUA lump terpisah.
            kategori = event_name or event_type or "Bonus"
            desc = _teks(r.get("Description"))
            raw = {k: ("" if v is None else str(v)) for k, v in r.items()}
            raw["Kategori"] = kategori
            raw["Sumber"] = MARKER_AGREGAT  # setelah raw: kolom vendor tak menimpa
            row = {
                "source_type": "panel_bonus",
                "occurred_at": occurred,
                "posted_date": occurred.date(),
                "jenis": "bonus",
                "amount": abs(amt),
                # Vendor menulis nominal POSITIF (Nexus sudah negatif di
                # sumbernya, jadi parser lamanya tidak membalik). Peristiwa
                # ekonominya identik: kredit keluar ke pemain.
                "credit_delta": -amt,
                "money_delta": NOL,
                "fee": NOL,
                "bonus": abs(amt),
                "balance_after": None,
                "ticket_no": "",
                "username": username,  # verbatim, prefix brand TIDAK dikupas
                "reference": "",
                "counterparty": "",
                "description": desc,
                "player_bank": "",
                "bank_title": "",
                "raw": raw,
            }
            # Di-hash dari nilai hasil PARSE (datetime/Decimal), bukan teks sel.
            # `#` sengaja tak ikut: penghitung relatif-halaman, ekspor ulang
            # menomori ulang -> seluruh baris akan terlihat baru.
            row["row_hash"] = row_hash(
                MARKER_AGREGAT, [str(occurred), username, kategori, amt])
            out.append(row)

        # Tie-out. Σ Page Total lebih dipercaya daripada Grand Total: Page Total
        # hanya mencakup halaman yang ADA di berkas, sehingga ekspor
        # multi-halaman tak bisa memblokir unggahan yang sah.
        if ada_page:
            dicetak, sumber = page_total, "Page Total"
        elif ada_grand:
            dicetak, sumber = grand_total, "Grand Total"
        else:
            dicetak, sumber = None, ""
        if dicetak is not None and dicetak != total_data:
            raise ValueError(
                f"Bonus panel COR: jumlah {len(out)} baris data ({total_data}) "
                f"tidak sama dengan {sumber} yang dicetak berkas ({dicetak}). "
                "Ada baris yang salah terbaca. JANGAN diunggah ulang (hasilnya "
                "akan sama) — kirim berkasnya ke pengembang."
            )
        return out
