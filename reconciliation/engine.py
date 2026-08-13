"""Engine pencocokan (rule-based & tunable).

Tiap relasi punya Matcher sendiri (pluggable lewat MATCHERS). Hasil = MatchResult
dengan bucket cocok / tidak_cocok / perlu_tinjau + reason. Toleransi dari ToleranceProfile.
"""
import re
from collections import Counter, defaultdict
from datetime import date, timedelta

from django.db import transaction as db_tx
from django.db.models import Count, Q, Sum
from rapidfuzz import fuzz

from sources.parsers.base import clean_name
from transactions.models import Transaction

from .models import MatchResult, MatchRun, ReconBatch, ToleranceProfile

MONEY_SOURCES = ["bank", "gateway"]

# Nama korporat agregator e-wallet yang muncul di mutasi bank (riset 2026-07-05):
# transfer dari/ke e-wallet tampil atas nama PT pengelolanya, bukan nama pemain.
_AGGREGATORS = [
    ("ESPAY", "DANA"), ("ANAK BANGSA", "GoPay"), ("DOMPET ANAK", "GoPay"),
    ("AIRPAY", "ShopeePay"), ("VISIONET", "OVO"), ("FINARYA", "LinkAja"),
    ("BIFAST", "BI-FAST"),
]


def _wallet_label(name):
    """Label kanal e-wallet bila `name` adalah nama korporat agregator."""
    up = (name or "").upper()
    for token, label in _AGGREGATORS:
        if token in up:
            return label
    return None


_NORM_RE = re.compile(r"[^A-Z]")
_DIGIT_RUN_RE = re.compile(r"\d{9,15}")
# WD e-wallet via BRI: 'BRIVA<kode kanal><no HP>' — kode menempel di depan
# nomor sehingga deret totalnya 16-18 digit dan LOLOS dari _DIGIT_RUN_RE
# (terpotong 15 digit + kode ikut terbawa). Kode kanal dari matriks klien:
# DANA 88810, GOPAY 30135, OVO 88099, SHOPEEPAY 112, LINK AJA 91188.
# Dipakai via .sub() yang MENGGANTI span dengan nomornya: sekaligus membuang
# deret tercemar kode dari hasil _DIGIT_RUN_RE (temuan review adversarial).
_BRIVA_RE = re.compile(
    r"BRIVA\s*(?:88810|30135|88099|91188|112)(\d{9,15})", re.IGNORECASE
)


def _panel_phone(t):
    """Nomor HP/rekening wallet pemain dari raw['Player Bank'] (segmen ke-3),
    dinormalisasi: buang non-digit + nol/62 di depan. '' bila tak ada."""
    pb = (t.raw or {}).get("Player Bank") or ""
    parts = pb.split("|")
    digits = re.sub(r"\D", "", parts[2] if len(parts) > 2 else "")
    return digits.lstrip("0").removeprefix("62").lstrip("0")


def _norm_acct_digits(s):
    """Normalisasi nomor rekening gateway (raw['AccountNumber'], sisi UNO WD) —
    aturan SAMA dengan _panel_phone agar kedua sisi menghasilkan kunci yang
    bisa dibandingkan langsung: buang non-digit, nol depan, prefix 62, nol
    depan lagi. Hasil < 6 digit terlalu ambigu untuk diindeks -> ''."""
    digits = re.sub(r"\D", "", s or "")
    digits = digits.lstrip("0").removeprefix("62").lstrip("0")
    return digits if len(digits) >= 6 else ""


def _money_phones(t):
    """Deret digit (≥9) di baris uang — mutasi VA e-wallet (FTFVA/DANA, GOPAY
    TOPUP, dst) menaruh nomor HP/VA tujuan di teks keterangan."""
    text = " ".join(str(v) for v in (t.raw or {}).values())
    out = set()
    joined = text + " " + (t.counterparty or "")
    # Span BRIVA diganti nomor bersihnya SEBELUM scan deret digit: nomor ikut
    # terekstrak DAN deret tercemar kode (mis. '301350831448892') hilang.
    joined = _BRIVA_RE.sub(lambda m: f" {m.group(1)} ", joined)
    for run in _DIGIT_RUN_RE.findall(joined):
        norm = run.lstrip("0").removeprefix("62").lstrip("0")
        if len(norm) >= 9:
            out.add(norm)
    return out


def _phone_match(pp, phones):
    """Cocok bila salah satu ujung sama (bank sering memotong digit)."""
    if not pp or len(pp) < 9:
        return False
    for ph in phones:
        if pp == ph or pp.endswith(ph) or ph.endswith(pp) \
           or pp.startswith(ph) or ph.startswith(pp):
            return True
    return False


def _norm_owner(s):
    return _NORM_RE.sub("", (s or "").upper())


def _expected_owner(t):
    """Pemilik rekening TUJUAN menurut panel: segmen tengah raw['Bank Title']
    (mis. 'BCA|HENDI|712...' → 'HENDI'). Kosong bila tidak ada."""
    bt = (t.raw or {}).get("Bank Title") or ""
    parts = bt.split("|")
    return _norm_owner(parts[1] if len(parts) > 1 else bt)


def _route_ok(expected, owner, source_key):
    """Apakah baris uang berada di rekening yang ditunjuk panel?
    None = tak bisa dinilai (tanpa Bank Title / tanpa nama file)."""
    if not expected or not owner:
        return None
    if source_key == "gateway":
        for tok in ("FLYER", "NXPAY"):
            if tok in expected and tok in owner:
                return True
    return fuzz.partial_ratio(expected, owner) >= 85


# --- Kunci kanal gateway ------------------------------------------------------
# Panel mendeklarasikan kanal pembayarannya di bank_title ("QRISRPAY",
# "NXPAY DEPOSIT QR", "QRISHOKI", ...); parser gateway menulis identitasnya di
# awal description ("RPay ...", "NXPAY ...", "QHOKI ...", "QRFLYER ..."). Uang
# gateway X dilarang dipasangkan pass identitas dengan baris panel yang menunjuk
# gateway Y yang dikenal berbeda — mencegah deposit kembar beda kanal saling
# curi saat file uang belum lengkap (kasus M77: uang RPay tersedot baris NXPAY).
# Fail-open: token tak dikenal / kosong -> tanpa larangan (perilaku lama).
_GW_CHANNEL_TOKENS = ("NXPAY", "RPAY", "HOKI", "FLYER")


def _channel_from(text):
    up = (text or "").upper()
    for tok in _GW_CHANNEL_TOKENS:
        if tok in up:
            return tok
    return ""


def _panel_channel(t):
    return _channel_from(getattr(t, "bank_title", ""))


def _money_channel(t):
    if t.source_type.key != "gateway":
        return ""
    # Hanya awalan description (ditulis parser sendiri) — bukan teks bebas.
    return _channel_from((t.description or "")[:12])

# Detail baku hasil no_money — juga dipakai untuk MENGEMBALIKAN hasil yang
# di-flip late settlement, jadi string ini harus tetap satu sumber kebenaran.
NO_MONEY_DETAIL = "Tak ada padanan nominal+tanggal di Mutasi Bank"
# Detail no_money ketika ADA kandidat nominal+tanggal tapi identitasnya beda
# (skor < NAME_REVIEW_FLOOR) → biarkan menunggu settlement tanggal berikutnya.
NO_MONEY_WAIT_DETAIL = "Ada kandidat nominal+tanggal tapi identitas beda — menunggu settlement"

# Anchor UTAMA (identitas unik) yang menentukan pasangan; nominal+tanggal hanya
# PENDUKUNG. Nama mirip pada pita ini → perlu_tinjau ('nama mirip'); di bawahnya
# TIDAK dipasangkan (menunggu settlement). Kalibrasi via `validate_brands`;
# dinaikkan ke ToleranceProfile bila per-toko perlu beda (YAGNI sekarang).
NAME_REVIEW_FLOOR = 60
# Lantai toleransi selisih nominal pass 2 (fee transfer MENEMPEL di debit bank):
# BI-Fast 2.500, online/switching antarbank 6.500 — kasus nyata LBS: panel WD
# 400.000 didebit 406.500 satu baris. Identitas tetap gerbang; ini hanya
# memperlebar kandidat yang BOLEH dinilai.
FEE_TOL_MIN = 6500
# Batas atas "kode unik" deposit: pemain menambah ekor kecil (<=999, 3 digit)
# ke nominal DP agar mudah dikenali — bank SELALU > panel. Pasangan sudah
# ber-anchor ticket/reference EXACT; ini murni reklasifikasi bucket TINJAU→COCOK.
# Underpay (bank<panel), selisih >999, dan WD TIDAK ikut (tetap TINJAU).
KODE_UNIK_MAX = 999


def _kode_unik_or_amount(p, b, diff, amount_reason, amount_detail):
    """Selisih nominal pada pasangan yang SUDAH ber-anchor ticket/reference EXACT.

    Bila DEPOSIT (p.money_delta>0) DAN bank>panel (int(abs(b))>int(abs(p)))
    DAN ekor <=KODE_UNIK_MAX → "kode unik" (COCOK). Selain itu (underpay,
    diff>999, atau WD) → TINJAU selisih nominal, perilaku lama tak berubah.
    Dipakai pass 0 (ticket) & pass 0b (reference) agar keduanya tak divergen.
    """
    if (p.money_delta > 0
            and int(abs(b.money_delta)) > int(abs(p.money_delta))
            and diff <= KODE_UNIK_MAX):
        return (MatchResult.Bucket.COCOK, 100, "kode_unik", f"kode unik +{diff:,}")
    return (MatchResult.Bucket.TINJAU, 90, amount_reason, amount_detail)


def _included_money_sources(include):
    """Sumber uang yang ikut run. include=None → semua (bank+gateway, perilaku lama).
    Jika include diberikan, hanya sumber dengan inc_* dicentang yang dipakai."""
    if include is None:
        return list(MONEY_SOURCES)
    return [k for k in MONEY_SOURCES if include.get(k, True)]


def amount_ok(a, b, tol):
    a, b = abs(a), abs(b)
    diff = abs(a - b)
    if diff <= tol.amount_abs_tol:
        return True, diff
    if tol.amount_pct_tol and max(a, b) > 0 and (diff / max(a, b)) <= float(tol.amount_pct_tol):
        return True, diff
    return diff == 0, diff


def _name_score(a, b):
    """Skor kemiripan nama, toleran nama terpotong (BCA ~18 char, BRI ~17).
    Nama sudah diisolasi di parser; di sini tinggal normalisasi + fuzzy."""
    a = clean_name(a).upper()
    b = clean_name(b).upper()
    if not a or not b:
        return 0.0
    score = fuzz.token_set_ratio(a, b)
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 10:  # nama sangat pendek jangan dianggap potongan nama lain
        score = max(score, fuzz.ratio(shorter, longer[: len(shorter)]))
    return score


def date_ok(left_dt, right_dt, tol):
    """Terarah: sisi uang (right) >= sisi kredit (left), dalam window hari."""
    if left_dt is None or right_dt is None:
        return False
    return 0 <= (right_dt.date() - left_dt.date()).days <= tol.date_window_days


def _date_filter(qs, dfrom, dto):
    if dfrom:
        qs = qs.filter(occurred_at__date__gte=dfrom)
    if dto:
        qs = qs.filter(occurred_at__date__lte=dto)
    return qs


def _toko_filter(qs, toko):
    return qs.filter(toko=toko) if toko is not None else qs


def _can_still_settle(d, recon_date, window):
    """Baris kredit tanggal `d` masih bisa dapat uang pada run tanggal berikutnya
    (>= recon_date+1): d + window >= recon_date + 1  ⟺  d > recon_date - window.
    Catatan: window diambil dari toleransi run BERJALAN — ganti profil antar hari
    (mis. Longgar → Ketat) membuat carry lama langsung dianggap kadaluarsa."""
    return d is not None and d > recon_date - timedelta(days=window)


def _active(qs):
    """Pool AKTIF = transaksi yang belum dikonsumsi batch mana pun. Transaksi yang
    sudah dipakai (consumed_by_batch terisi) tidak ikut kelengkapan/pencocokan/total."""
    return qs.filter(consumed_by_batch__isnull=True)


def _tanggal_baris(t):
    """Tanggal acuan pembukuan satu baris: `posted_date` (tanggal 'masuk'
    statement/FR) dengan cadangan tanggal transaksi. None bila tak bertanggal —
    baris begitu tidak punya anchor PENDUKUNG sama sekali."""
    if t.posted_date:
        return t.posted_date
    return t.occurred_at.date() if t.occurred_at else None


def _kunci_username(t):
    """Kunci join Panel↔Bracket mode username: (username, |nominal|, arah).

    None bila baris tak bisa di-anchor: tanpa username, atau bukan DP/WD (baris
    FR bonus/beban admin/adjustment bukan transaksi panel). Nominal memakai
    `money_delta` (bertanda, sudah rupiah penuh di kedua sisi) dan jatuh ke
    `amount` bila deltanya nol."""
    u = (t.username or "").strip().lower()
    if not u or t.jenis not in ("depo", "wd"):
        return None
    nominal = t.money_delta or t.amount
    return (u, int(abs(nominal)), t.jenis)


def check_completeness(toko, date_from=None, date_to=None):
    qs = _active(_toko_filter(Transaction.objects.filter(is_duplicate=False), toko))
    qs = _date_filter(qs, date_from, date_to)

    def has(**kw):
        return qs.filter(**kw).exists()

    comp = {
        "panel_dp": has(source_type__key="panel", jenis="depo"),
        "panel_wd": has(source_type__key="panel", jenis="wd"),
        "bracket": has(source_type__key="bracket"),
        "bank": has(source_type__key="bank"),
        "gateway": has(source_type__key="gateway"),
    }
    comp["panel"] = comp["panel_dp"] or comp["panel_wd"]
    comp["minimum_met"] = comp["panel"] and (comp["bank"] or comp["gateway"])
    return comp


class PanelBracketMatcher:
    """Join Panel↔Bracket — DUA MODE, dipilih otomatis dari isi data:

    * mode "ticket" (Nexus): join via Ticket Number, kunci TRANSAKSI yang kuat.
      Perilaku lama, tidak berubah sedikit pun.
    * mode "username" (Vigor / TM Gaming, mis. COR): panelnya sama sekali TIDAK
      mengekspor Ticket Number, jadi join memakai anchor identitas UTAMA lain
      yang dimiliki kedua sisi — username PERSIS (preseden: anchor
      `Customer Username` RafflesPay). Nominal, arah uang, dan tanggal tetap
      hanya anchor PENDUKUNG: tanpa username sama TIDAK ada pasangan.

    Mode ditentukan per-run oleh `match()` dan dilaporkan lewat `summary["mode"]`.
    """

    #: diisi ulang tiap `match()`; dibaca run_match untuk `summary["mode"]`.
    join_mode = "ticket"
    #: jumlah baris bracket yang RELEVAN dengan mode terpilih — dipakai run_match
    #: sebagai `summary["right"]` (penyebut `_bracket_overlap_warning`).
    right_relevant = None
    #: jumlah baris Panel TANPA ticket pada run terakhir — di mode ticket baris
    #: itu tidak dinilai sama sekali, jadi angkanya dilaporkan sebagai peringatan.
    left_tanpa_ticket = 0

    #: ambang RASIO baris panel ber-ticket untuk memilih mode ticket (inklusif:
    #: seri 50/50 jatuh ke mode ticket = perilaku lama).
    TICKET_RATIO = 0.5

    def sides(self, dfrom, dto, toko=None, include=None):
        left = Transaction.objects.filter(source_type__key="panel", is_duplicate=False)
        # include: hilangkan sisi Panel yang tidak dicentang (depo/wd) bila diberikan.
        if include is not None:
            if not include.get("panel_dp", True):
                left = left.exclude(jenis="depo")
            if not include.get("panel_wd", True):
                left = left.exclude(jenis="wd")
        left = _date_filter(_active(_toko_filter(left, toko)), dfrom, dto)
        # Sisi bracket diambil UTUH (tanpa .exclude(ticket_no="")): FR Vigor/TMG
        # tak punya ticket. Penyaringan per-mode dilakukan di `match()` — mode
        # ticket menyaring ulang baris ber-ticket saja, jadi populasi masukannya
        # identik dengan versi lama.
        right = _date_filter(
            _active(_toko_filter(
                Transaction.objects.filter(source_type__key="bracket", is_duplicate=False), toko
            )),
            dfrom, dto,
        )
        # ORDER BY EKSPLISIT — alasan sama dengan `_MoneyMatcher.sides()` di
        # bawah: tanpa ini urutan baris ditentukan query planner. Mode username
        # sudah punya kunci sort total `(delta, p.id, b.id)`, tapi mode ticket
        # greedy murni (`next(...)` atas bidx) — kalau satu ticket muncul dobel
        # di bracket, baris bracket MANA yang diklaim panel bergantung pada
        # urutan masukan ini.
        return list(left.order_by("id")), list(right.order_by("id"))

    def match(self, run, left, right):
        # Mode dipilih dari RASIO, bukan dari ADA/TIDAKNYA satu baris ber-ticket.
        # Aturan "ada satu ticket → mode ticket" adalah pembunuh-hari senyap: satu
        # baris nyasar (ekspor bergaya Nexus salah unggah ke toko COR) cukup untuk
        # memaksa mode ticket, sisi kanan menyusut ke 0 baris ber-ticket, dan
        # SELURUH hari lewat tanpa pasangan sekaligus tanpa peringatan.
        # Kedua populasi nyata tak berubah: Nexus ~100% ber-ticket → ticket,
        # COR/Vigor/TMG 0% → username. Sisi kosong tetap mode ticket (perilaku lama).
        ber_ticket = sum(1 for p in left if p.ticket_no)
        self.left_tanpa_ticket = len(left) - ber_ticket
        if not right or not left or ber_ticket >= len(left) * self.TICKET_RATIO:
            self.join_mode = "ticket"
            return self._match_ticket(run, left, right)
        self.join_mode = "username"
        return self._match_username(run, left, right)

    def _match_ticket(self, run, left, right):
        # Baris bracket TANPA ticket tak pernah terlihat di mode ini (bonus,
        # beban admin, dst) — memulihkan populasi masukan versi lama persis.
        right = [b for b in right if b.ticket_no]
        self.right_relevant = len(right)
        tol = run.tolerance
        bidx = {}
        for b in right:
            bidx.setdefault(b.ticket_no, []).append(b)
        used, out = set(), []
        for p in left:
            if not p.ticket_no:   # baris tanpa ticket dinilai money-matcher, bukan bracket
                continue
            chosen = next((b for b in bidx.get(p.ticket_no, []) if b.id not in used), None)
            if chosen:
                used.add(chosen.id)
                ok, diff = amount_ok(p.amount, chosen.amount, tol)
                if ok:
                    out.append(MatchResult(run=run, bucket=MatchResult.Bucket.COCOK, left=p, right=chosen,
                                           score=100, reason_code="ticket+amount"))
                else:
                    out.append(MatchResult(run=run, bucket=MatchResult.Bucket.TINJAU, left=p, right=chosen,
                                           score=70, reason_code="amount_mismatch",
                                           reason_detail=f"selisih {diff}: Panel {p.amount} vs Bracket {chosen.amount}"))
            else:
                out.append(MatchResult(run=run, bucket=MatchResult.Bucket.TIDAK, left=p, right=None,
                                       score=0, reason_code="no_bracket",
                                       reason_detail="Ticket Panel tidak ada di Bracket"))
        for b in right:
            if b.id not in used:
                out.append(MatchResult(run=run, bucket=MatchResult.Bucket.TIDAK, left=None, right=b,
                                       score=0, reason_code="no_panel",
                                       reason_detail="Ticket Bracket tidak ada di Panel"))
        return out

    def _match_username(self, run, left, right):
        """Panel tanpa ticket: pasangkan lewat (username, |nominal|, arah).

        Hanya baris FR ber-kategori Deposit/Withdrawal yang ikut — baris bonus,
        beban admin, 'Sesama CM', adjustment, dst BUKAN transaksi panel; kalau
        ikut, mereka melahirkan no_panel palsu sekaligus bisa mencuri pasangan.
        """
        tol = run.tolerance
        kandidat_b = [b for b in right if b.jenis in ("depo", "wd")]
        self.right_relevant = len(kandidat_b)

        bidx = defaultdict(list)
        for b in kandidat_b:
            k = _kunci_username(b)
            if k:
                bidx[k].append(b)

        # Assignment GLOBAL urut selisih hari (idiom pass 0c/1/3 money-matcher):
        # pemain yang setor nominal SAMA di dua hari dengan satu baris FR harus
        # jatuh ke hari yang paling pas, bukan ke baris panel yang kebetulan
        # lebih dulu diiterasi. Jendela tanggal SIMETRIS (|selisih|): posting FR
        # bisa mendahului maupun tertinggal dari approval panel (baris backdated
        # / transaksi yang melewati tengah malam).
        pairs = []
        for p in left:
            kp = _kunci_username(p)
            if kp is None:
                continue
            pd = _tanggal_baris(p)
            if pd is None:
                continue
            pt = (p.ticket_no or "").strip()
            for b in bidx.get(kp, []):
                # Ticket yang MEMBANTAH mengalahkan kunci pemain. Di rezim
                # campuran (minoritas baris ber-ticket) bisa muncul pasangan yang
                # KEDUA sisinya ber-ticket dan tickets-nya BEDA — itu bukti keras
                # dua transaksi berlainan. Aturan anchor: username adalah anchor
                # UTAMA, tapi kunci transaksi yang eksplisit membantah harus
                # membatalkan pasangan (biarkan keduanya jadi no_bracket/no_panel)
                # ketimbang dikalahkan kebetulan username+nominal sama. Satu sisi
                # kosong = tak ada bantahan (kasus COR normal); ticket IDENTIK
                # justru konfirmasi.
                bt = (b.ticket_no or "").strip()
                if pt and bt and pt != bt:
                    continue
                bd = _tanggal_baris(b)
                if bd is None:
                    continue
                delta = abs((bd - pd).days)
                if delta <= tol.date_window_days:
                    pairs.append((delta, p.id, b.id, p, b))
        pairs.sort(key=lambda x: (x[0], x[1], x[2]))   # deterministik

        out, used, matched = [], set(), set()
        for _delta, _pid, _bid, p, b in pairs:
            if p.id in matched or b.id in used:
                continue
            matched.add(p.id)
            used.add(b.id)
            out.append(MatchResult(
                run=run, bucket=MatchResult.Bucket.COCOK, left=p, right=b, score=100,
                reason_code="username_amount",
                reason_detail=f"username '{p.username.strip()}' + nominal sama"))
        for p in left:
            if p.id in matched:
                continue
            detail = ("Baris Panel tanpa username — tak ada anchor ke Bracket"
                      if not (p.username or "").strip()
                      else "Tidak ada baris Bracket dgn username+nominal sama")
            out.append(MatchResult(run=run, bucket=MatchResult.Bucket.TIDAK, left=p, right=None,
                                   score=0, reason_code="no_bracket", reason_detail=detail))
        for b in kandidat_b:
            if b.id not in used:
                # Simetris dengan sisi Panel di atas: baris tanpa username sama
                # sekali TIDAK punya anchor — menuduhnya "tak ada pasangannya"
                # mengarahkan auditor mencari baris yang memang mustahil dicari.
                detail = ("Baris Bracket tanpa username — tidak bisa dijangkarkan"
                          if not (b.username or "").strip()
                          else "Tidak ada baris Panel dgn username+nominal sama")
                out.append(MatchResult(run=run, bucket=MatchResult.Bucket.TIDAK, left=None, right=b,
                                       score=0, reason_code="no_panel",
                                       reason_detail=detail))
        return out


class _MoneyMatcher:
    """Cocokkan sisi kredit (Panel/Bracket) ke sisi UANG (Bank/Gateway) — multi-pass:

    pass 0  ticket-join gateway (kunci pasti; gateway ber-ticket asing TIDAK
            pernah dipasangkan fuzzy — biar tampil sebagai uang tanpa pasangan),
    pass 0b reference-join gateway (kunci pasti non-ticket, mis. UUID QRIS),
    pass 0c account-join gateway (UNO QRIS WD): AccountNumber == rekening
            panel, HANYA nominal persis (kunci PEMAIN, bukan kunci transaksi),
            jendela tanggal terarah + assignment GLOBAL urut selisih hari,
    pass 1  identitas kuat (skor >= threshold) di-assign GLOBAL urut skor —
            baris lemah tidak bisa mencuri kandidat milik baris kuat,
    pass 2  near-miss identitas kuat: nominal beda kecil (fee) / uang H-1,
    pass 3  sisa berbasis nominal+tanggal → perlu_tinjau, prioritas rekening
            yang ditunjuk panel (raw['Bank Title']) supaya tidak salah sanding.
    """

    left_key = "panel"

    def sides(self, dfrom, dto, toko=None, include=None):
        left = Transaction.objects.filter(
            source_type__key=self.left_key, is_duplicate=False
        ).filter(jenis__in=["depo", "wd"])
        # include: sisi Panel — buang depo/wd yang tidak dicentang.
        if include is not None:
            if not include.get("panel_dp", True):
                left = left.exclude(jenis="depo")
            if not include.get("panel_wd", True):
                left = left.exclude(jenis="wd")
        left = _date_filter(_active(_toko_filter(left, toko)), dfrom, dto)

        # right: hanya sumber UANG yang dicentang (bank dan/atau gateway).
        money_keys = _included_money_sources(include)
        right = _date_filter(
            _active(_toko_filter(
                Transaction.objects.filter(source_type__key__in=money_keys, is_duplicate=False).exclude(jenis="admin"),
                toko,
            )),
            dfrom, dto,
        ).select_related("source_type", "upload")
        # ORDER BY EKSPLISIT — JANGAN DIHAPUS. `Transaction.Meta` tak punya
        # `ordering`, jadi tanpa ini urutan barisnya adalah keputusan QUERY
        # PLANNER: menambah index (atau sekadar pertumbuhan data yang menggeser
        # statistik Postgres) bisa mengubahnya. Pass 1/2/3 mengiterasi list ini
        # secara greedy, jadi urutan masukan menentukan siapa yang lebih dulu
        # mengklaim kandidat yang SERI — artinya jumlah "Cocok" bisa berbeda
        # antar-run untuk data yang PERSIS SAMA. Sudah terbukti: satu pemain,
        # 4 baris nominal sama tanggal sama, urutan [P1,P2] → cocok=1 sedangkan
        # [P2,P1] → cocok=2 (lihat reconciliation/tests_determinisme.py).
        # `id` dipilih sebagai kunci karena primary key: UNIK (urutannya total,
        # tak pernah seri), IMUTABEL (stabil antar-run), dan searah urutan
        # ingest — jadi urutannya juga yang paling masuk akal bagi manusia.
        # Pass 2 tidak punya sort sama sekali (memilih `best` dengan `>` yang
        # ketat dan `break` pada kandidat H-1 pertama); determinismenya
        # BERSANDAR PENUH pada urutan di sini.
        return list(left.order_by("id")), list(right.order_by("id"))

    @staticmethod
    def _identity(p, b):
        """Skor identitas: nomor HP/VA wallet persis > username persis > fuzzy nama.
        Mutasi VA e-wallet (FTFVA/DANA, GOPAY TOPUP) tak membawa nama pengirim,
        tapi membawa nomor tujuan — sama dengan raw['Player Bank'] panel."""
        pp = getattr(p, "_phone", None)
        if pp is None:
            pp = p._phone = _panel_phone(p)
        phones = getattr(b, "_phones", None)
        if phones is None:
            phones = b._phones = _money_phones(b)
        if _phone_match(pp, phones):
            return 100.0
        if p.username and b.username:
            s = 100.0 if p.username.lower() == b.username.lower() else 40.0
            if p.counterparty and b.counterparty:
                s = max(s, _name_score(p.counterparty, b.counterparty))
            return s
        return _name_score(p.counterparty, b.counterparty)

    def match(self, run, left, right):
        tol = run.tolerance
        out, used, matched = [], set(), set()

        bidx = defaultdict(list)
        gw_ticket = defaultdict(list)
        gw_ref = defaultdict(list)
        gw_acct = defaultdict(list)
        owners = {}
        for b in right:
            bidx[(int(abs(b.money_delta)), b.money_delta > 0)].append(b)
            if b.source_type.key == "gateway" and b.ticket_no:
                gw_ticket[b.ticket_no].append(b)
            if b.source_type.key == "gateway" and b.reference:
                gw_ref[b.reference].append(b)
            if b.source_type.key == "gateway":
                acct = _norm_acct_digits((b.raw or {}).get("AccountNumber", ""))
                if acct:
                    gw_acct[acct].append(b)
            if b.upload_id not in owners:
                owners[b.upload_id] = _norm_owner(
                    b.upload.original_name if b.upload else ""
                )
        panel_tickets = {p.ticket_no for p in left if p.ticket_no}
        panel_refs = {p.reference for p in left if p.reference}
        # Hangatkan cache p._phone (idiom sama dgn _identity) — dipakai pass 0c
        # sebagai anchor rekening, dan lagi oleh gerbang identitas pass 1-3.
        for p in left:
            if getattr(p, "_phone", None) is None:
                p._phone = _panel_phone(p)

        def emit(p, b, bucket, score, reason, detail=""):
            matched.add(p.id)
            if b is not None:
                used.add(b.id)
            out.append(MatchResult(run=run, bucket=bucket, left=p, right=b,
                                   score=score, reason_code=reason, reason_detail=detail))

        # --- pass 0: ticket-join gateway (seperti Panel↔Bracket) ---
        for p in left:
            if not p.ticket_no:
                continue
            for b in gw_ticket.get(p.ticket_no, []):
                if b.id in used or (p.money_delta > 0) != (b.money_delta > 0):
                    continue
                diff = abs(int(abs(p.money_delta)) - int(abs(b.money_delta)))
                if diff == 0:
                    emit(p, b, MatchResult.Bucket.COCOK, 100, "ticket")
                else:
                    emit(p, b, *_kode_unik_or_amount(
                        p, b, diff, "ticket_amount",
                        f"ticket sama, selisih nominal {diff:,}"))
                break
        # --- pass 0b: reference-join gateway (kunci pasti non-ticket, mis. UUID QRIS) ---
        for p in left:
            if p.id in matched or not p.reference:
                continue
            for b in gw_ref.get(p.reference, []):
                if b.id in used or (p.money_delta > 0) != (b.money_delta > 0):
                    continue
                diff = abs(int(abs(p.money_delta)) - int(abs(b.money_delta)))
                if diff == 0:
                    emit(p, b, MatchResult.Bucket.COCOK, 100, "reference")
                else:
                    emit(p, b, *_kode_unik_or_amount(
                        p, b, diff, "reference_amount",
                        f"reference sama, selisih nominal {diff:,}"))
                break
        # --- pass 0c: account-join gateway (UNO QRIS WD) — jaring robustness ---
        # AccountNumber gateway adalah kunci PEMAIN (rekening tujuan), BUKAN kunci
        # transaksi seperti ticket/reference — satu pemain bisa WD berkali-kali ke
        # rekening yang sama. Dua konsekuensi:
        #  1. HANYA nominal PERSIS (diff==0) yang dipasangkan; tak ada cabang
        #     toleran seperti pass 0/0b. Selisih nominal (fee-shifted) sengaja
        #     jatuh ke pass 1/2 yang menggerbangi lewat skor identitas.
        #  2. Assignment GLOBAL urut selisih hari (idiom sama dgn pass 1/3):
        #     pemain sama + nominal sama di dua hari dengan SATU baris uang harus
        #     jatuh ke hari yang paling pas, bukan ke baris panel yang kebetulan
        #     lebih dulu diiterasi (pasangan salah-hari = flip late_settlement
        #     palsu ke batch kemarin).
        # Jendela tanggal TERARAH seperti `kandidat`: uang tak boleh mendahului
        # kredit, dan kedua sisi wajib bertanggal — tanpa tanggal tak ada anchor
        # pendukung sama sekali, biarkan jatuh ke pass berikutnya.
        acct_pairs = []
        for p in left:
            # p._phone sudah dihangatkan oleh loop pemanasan cache di atas.
            if p.id in matched or not p._phone or p.occurred_at is None:
                continue
            p_date = p.occurred_at.date()
            for b in gw_acct.get(p._phone, []):
                if b.occurred_at is None or (p.money_delta > 0) != (b.money_delta > 0):
                    continue
                if int(abs(p.money_delta)) != int(abs(b.money_delta)):
                    continue
                delta = (b.occurred_at.date() - p_date).days
                if 0 <= delta <= tol.date_window_days:
                    acct_pairs.append((delta, p.id, b.id, p, b))
        acct_pairs.sort(key=lambda x: (x[0], x[1], x[2]))  # deterministik
        for _delta, _pid, _bid, p, b in acct_pairs:
            if p.id in matched or b.id in used:
                continue
            emit(p, b, MatchResult.Bucket.COCOK, 100, "account")
        # Gateway ber-ticket/ber-reference yang TAK dikenal panel bukan kandidat
        # fuzzy siapa pun (cermin semantik: uang yang identitas TRANSAKSInya
        # asing bagi panel tampil sebagai uang tanpa pasangan, bukan dicuri
        # fuzzy pass 1-3). Ticket & reference adalah kunci per-TRANSAKSI: satu
        # nilai = satu transaksi, jadi "tak dikenal panel" benar-benar berarti
        # "transaksi ini tak ada di panel".
        #
        # REKENING SENGAJA TIDAK IKUT MEMBLOKIR. AccountNumber adalah kunci
        # PEMAIN, bukan kunci transaksi: satu rekening menampung banyak WD, dan
        # sisi panel hanya membawanya lewat segmen `Player Bank` yang sering
        # kosong/beda format. Rekening gateway yang tak muncul di panel karena
        # itu cuma membuktikan CELAH DATA PANEL, bukan transaksi yang berbeda —
        # memblokirnya membuat SATU pemain berrekening (yang mengisi
        # panel_accts) membungkam pemain lain di toko yang sama menjadi
        # no_money. Yang menjaga tetap gerbang identitas pass 1-3 (HP/username/
        # nama ≥ threshold); pass 0c di atas tetap memakai rekening secara
        # POSITIF sebagai anchor untuk memasangkan.
        blocked = {
            b.id for t, lst in gw_ticket.items() if t not in panel_tickets for b in lst
        } | {
            b.id for ref, lst in gw_ref.items() if ref not in panel_refs for b in lst
        }

        def kandidat(p, *, lo=0, hi=None, tol_amt=0):
            hi = tol.date_window_days if hi is None else hi
            d = p.occurred_at.date() if p.occurred_at else None
            if d is None:
                return
            pchan = getattr(p, "_chan", None)
            if pchan is None:
                pchan = p._chan = _panel_channel(p)
            amt, pos = int(abs(p.money_delta)), p.money_delta > 0
            if tol_amt:
                keys = [(a, s) for (a, s) in bidx
                        if s == pos and 0 < abs(a - amt) <= tol_amt]
            else:
                keys = [(amt, pos)]
            for key in keys:
                for b in bidx.get(key, []):
                    if b.id in used or b.id in blocked or b.occurred_at is None:
                        continue
                    if pchan:
                        bchan = getattr(b, "_mchan", None)
                        if bchan is None:
                            bchan = b._mchan = _money_channel(b)
                        # Kunci kanal: gateway berbeda yang sama-sama dikenal.
                        if bchan and bchan != pchan:
                            continue
                    delta = (b.occurred_at.date() - d).days
                    if lo <= delta <= hi:
                        yield b, delta

        # --- pass 1: identitas kuat, assignment global urut skor ---
        pairs = []
        for p in left:
            if p.id in matched:
                continue
            expected = _expected_owner(p)
            for b, delta in kandidat(p):
                s = self._identity(p, b)
                if s >= tol.fuzzy_threshold:
                    route = _route_ok(expected, owners.get(b.upload_id), b.source_type.key)
                    pairs.append((s, route is True, -delta, p, b))
        # KUNCI SORT WAJIB TOTAL — `id` di ekor bukan hiasan. Tanpa pemecah seri
        # ini kuncinya `(skor, route, -delta)` saja: pasangan yang seri dibiarkan
        # dipecahkan oleh stabilitas `list.sort`, alias oleh urutan append —
        # alias oleh urutan queryset `sides()` — alias oleh RENCANA EKSEKUSI
        # POSTGRES. Sudah terbukti: satu pemain, 4 baris nominal sama tanggal
        # sama, urutan panel [P1,P2] menghasilkan cocok=1 sedangkan [P2,P1]
        # menghasilkan cocok=2 (reconciliation/tests_determinisme.py). Menambah
        # index komposit apa pun — atau sekadar pertumbuhan data yang menggeser
        # statistik planner — cukup untuk menggeser jumlah "Cocok" pada data
        # yang PERSIS SAMA. `sides()` kini ber-`order_by("id")`, tapi itu sabuk;
        # ini bretelnya: hasil tetap sama walau urutan queryset berubah nanti.
        # `id` dinegasikan supaya di bawah `reverse=True` seri jatuh ke id
        # TERKECIL lebih dulu — idiom yang sama dengan pass 0c dan mode username
        # Panel↔Bracket, sekaligus persis perilaku de-facto yang selama ini
        # berlaku. Ini HANYA memecah seri; siapa yang BOLEH berpasangan tetap
        # ditentukan aturan anchor di atas, tak satu pun berubah.
        pairs.sort(key=lambda x: (x[0], x[1], x[2], -x[3].id, -x[4].id), reverse=True)
        for s, _, _, p, b in pairs:
            if p.id in matched or b.id in used:
                continue
            emit(p, b, MatchResult.Bucket.COCOK, s, "amount+date+name")

        # --- pass 2: near-miss identitas kuat (fee kecil & uang H-1) ---
        for p in left:
            if p.id in matched:
                continue
            amt = int(abs(p.money_delta))
            best = None
            for b, delta in kandidat(p, tol_amt=max(FEE_TOL_MIN, amt // 100)):
                s = self._identity(p, b)
                if s >= tol.fuzzy_threshold and (best is None or s > best[0]):
                    best = (s, b)
            if best:
                s, b = best
                diff = abs(int(abs(b.money_delta)) - amt)
                # Identitas PERSIS (nomor HP/username/nama identik = 100) + selisih
                # kecil khas biaya transfer → cocok; identitas fuzzy tetap ditinjau.
                bucket = (MatchResult.Bucket.COCOK if s >= 100
                          else MatchResult.Bucket.TINJAU)
                emit(p, b, bucket, s, "amount_fee",
                     f"identitas cocok, selisih nominal {diff:,} (indikasi fee)")
                continue
            for b, delta in kandidat(p, lo=-1, hi=-1):
                s = self._identity(p, b)
                if s >= tol.fuzzy_threshold:
                    emit(p, b, MatchResult.Bucket.TINJAU, s, "date_before",
                         "uang tiba sehari SEBELUM tanggal panel")
                    break

        # --- pass 3: sisa berbasis IDENTITAS — nominal+tanggal cuma pendukung ---
        # Nama mirip pada pita [NAME_REVIEW_FLOOR..threshold) → perlu_tinjau,
        # di-assign GLOBAL urut skor (anti-curi, seperti pass 1). Di bawah floor
        # TIDAK dipasangkan: biarkan menunggu settlement tanggal berikutnya —
        # ini yang mencegah WD "Samsul" nyasar ke mutasi "ARI" (skor 36).
        band_pairs = []
        has_candidate = {}
        for p in left:
            if p.id in matched:
                continue
            expected = _expected_owner(p)
            any_cand = False
            for b, delta in kandidat(p):
                any_cand = True
                s = self._identity(p, b)
                if s >= NAME_REVIEW_FLOOR:
                    route = _route_ok(expected, owners.get(b.upload_id), b.source_type.key)
                    band_pairs.append((s, route is True, -delta, p, b))
            has_candidate[p.id] = any_cand
        # Kunci total, alasan identik dengan pass 1 di atas (cacat yang sama
        # persis, tinggal menunggu data yang seri di pita nama 60–84).
        band_pairs.sort(key=lambda x: (x[0], x[1], x[2], -x[3].id, -x[4].id), reverse=True)
        for s, _, _, p, b in band_pairs:
            if p.id in matched or b.id in used:
                continue
            wallet = _wallet_label(b.counterparty)
            extra = f" — kanal {wallet}" if wallet else ""
            emit(p, b, MatchResult.Bucket.TINJAU, s, "name_partial",
                 f"nama mirip (score {s:.0f}){extra}")
        for p in left:
            if p.id in matched:
                continue
            detail = NO_MONEY_WAIT_DETAIL if has_candidate.get(p.id) else NO_MONEY_DETAIL
            emit(p, None, MatchResult.Bucket.TIDAK, 0, "no_money", detail)
        return out


class PanelBankMatcher(_MoneyMatcher):
    left_key = "panel"


class BracketBankMatcher(_MoneyMatcher):
    left_key = "bracket"


MATCHERS = {
    MatchRun.Relation.PANEL_BRACKET: PanelBracketMatcher,
    MatchRun.Relation.PANEL_BANK: PanelBankMatcher,
    MatchRun.Relation.BRACKET_BANK: BracketBankMatcher,
}


def run_match(relation, tolerance=None, date_from=None, date_to=None, user=None, toko=None, batch=None, include=None,
              carried=None, retro=None):
    """`carried` = dict left_id → MatchResult no_money lama (carry-over harian).
    Baris carried ikut pool relasi UANG agar bisa settle terlambat, tapi tidak
    pernah membuat MatchResult baru di run ini; pasangan yang match dikembalikan
    lewat atribut transien `run.late_pairs` untuk di-flip oleh run_batch.
    `retro` = dict tx_id → ReconBatch asal (baris susulan). Baris susulan ikut
    pool biasa, tapi hasil yang ber-anchor padanya dialihkan ke atribut transien
    `run.retro_results` untuk ditulis ke batch asalnya oleh run_batch."""
    tolerance = tolerance or ToleranceProfile.objects.get(name="Default")
    matcher = MATCHERS[relation]()
    run = MatchRun.objects.create(
        relation=relation, tolerance=tolerance, date_from=date_from, date_to=date_to,
        created_by=user, batch=batch,
    )
    left, right = matcher.sides(date_from, date_to, toko, include=include)
    if carried and relation == MatchRun.Relation.PANEL_BRACKET:
        # Kesempatan pairing bracket baris carried sudah lewat di batch asalnya —
        # jangan menghasilkan no_bracket/no_panel dobel di batch baru.
        left = [t for t in left if t.id not in carried]
        right = [t for t in right if t.id not in carried]
    results = matcher.match(run, left, right)
    late_pairs, keep = [], results
    if carried and relation != MatchRun.Relation.PANEL_BRACKET:
        keep = []
        for r in results:
            if r.left_id in carried:
                if r.right_id is not None:  # settle terlambat → flip di batch asal
                    late_pairs.append((carried[r.left_id], r))
                # carried tanpa pasangan → drop (tidak_cocok sudah tercatat di asalnya)
            else:
                keep.append(r)
    retro_results = []
    if retro:
        kept = []
        for r in keep:
            anchor = r.left_id if r.left_id is not None else r.right_id
            if anchor is not None and anchor in retro:
                retro_results.append(r)  # hasil baris susulan → milik batch asalnya
            else:
                kept.append(r)
        keep = kept
    with db_tx.atomic():
        MatchResult.objects.bulk_create(keep, batch_size=2000)
    c = Counter(r.bucket for r in keep)
    n_excluded_left = sum(
        1 for t in left
        if (carried and t.id in carried) or (retro and t.id in retro)
    )
    # Sisi kanan yang DILAPORKAN = baris yang relevan dengan mode join matcher
    # (Panel↔Bracket mode ticket: baris ber-ticket; mode username: baris DP/WD).
    # Penyebut `_bracket_overlap_warning` ikut angka ini supaya rasio cocok tetap
    # bermakna — kalau memakai panjang mentah, baris FR bonus/beban admin akan
    # menggelembungkan penyebut dan memicu peringatan palsu. Matcher yang tak
    # punya mode (money-matcher) mengembalikan None → panjang mentah.
    n_right = getattr(matcher, "right_relevant", None)
    run.summary = {
        "left": len(left) - n_excluded_left,
        "right": len(right) if n_right is None else n_right,
        "cocok": c.get("cocok", 0),
        "perlu_tinjau": c.get("perlu_tinjau", 0),
        "tidak_cocok": c.get("tidak_cocok", 0),
    }
    # Mode join dari instance matcher (di-set saat match()) — hanya Panel↔Bracket
    # yang punya; disimpan di summary run agar UI/laporan bisa menjelaskan cara
    # baris dipasangkan tanpa menebak dari data.
    mode = getattr(matcher, "join_mode", None)
    if mode:
        run.summary["mode"] = mode
        # Populasi yang KALAH oleh pilihan mode: di mode ticket, baris panel tanpa
        # ticket tidak dinilai sama sekali (tak cocok, tak gagal — senyap). Dicatat
        # agar `_mode_ticket_warning` bisa menyebut angkanya di halaman batch.
        tanpa = getattr(matcher, "left_tanpa_ticket", 0) or 0
        if mode == "ticket" and tanpa:
            run.summary["panel_tanpa_ticket"] = tanpa
    if carried:
        run.summary["late_settled"] = len(late_pairs)
    if retro:
        run.summary["susulan"] = len(retro_results)
    run.save(update_fields=["summary"])
    run.late_pairs = late_pairs
    run.retro_results = retro_results
    # SEMUA uang yang terpakai pasangan hari ini (termasuk yang hasilnya milik
    # batch lain via flip/susulan) — dipakai run_batch utk B1/B2.
    run.used_right_ids = {r.right_id for r in results if r.right_id}
    return run


def _matched_money(runs):
    """Uang REAL yang benar-benar berpasangan ke baris Panel (bucket cocok + perlu_tinjau).

    Dijumlah dari sisi UANG (right) pada MatchResult PANEL_BANK yang punya left&right.
    Bucket TIDAK dikecualikan: pasangan yang DITOLAK auditor (mark_unmatched)
    bukan uang matched — tanpa ini kartu batch tetap "balanced" padahal
    reviewer menolak pasangannya. DP = money_delta>0, WD = abs(money_delta<0).
    """
    panel_bank = [r.id for r in runs if r.relation == MatchRun.Relation.PANEL_BANK]
    dp = wd = 0.0
    if panel_bank:
        results = MatchResult.objects.filter(
            run_id__in=panel_bank, left__isnull=False, right__isnull=False
        ).exclude(bucket=MatchResult.Bucket.TIDAK).select_related("right")
        for res in results:
            md = float(res.right.money_delta)
            if md > 0:
                dp += md
            elif md < 0:
                wd += -md
    return dp, wd


def _carried_qs(tokos):
    """Filter dasar carry-over "menunggu settlement" untuk banyak toko sekaligus —
    hasil no_money LAMA milik baris kredit yang masih AKTIF.
    Hanya relasi UANG (no_money); hasil no_bracket PANEL_BRACKET tidak ikut.
    Run CLI tanpa batch diabaikan (tak ada batch asal untuk konsumsi/flip)."""
    return MatchResult.objects.filter(
        bucket=MatchResult.Bucket.TIDAK, reason_code="no_money",
        left__isnull=False, left__toko__in=tokos,
        left__consumed_by_batch__isnull=True,
        run__batch__isnull=False,
        run__relation__in=[MatchRun.Relation.PANEL_BANK, MatchRun.Relation.BRACKET_BANK],
    )


def _carried_results(toko):
    """left_id → MatchResult no_money carry-over (lihat `_carried_qs`).

    `run__batch__tolerance` ikut di-select_related meski engine sendiri tak
    memakainya: `web/settlement.py` membaca `batch.tolerance.date_window_days`
    PER BARIS untuk menghitung `batas`, dan select_related membuat instance
    ReconBatch baru tiap baris (cache relasi per-instance) — tanpa ini halaman
    Settlement Tertunda jadi N+1 (di prod 439 query untuk satu toko besar).
    Jangan dibuang karena tampak tak terpakai di sini."""
    qs = _carried_qs([toko]).select_related(
        "left", "run", "run__batch", "run__batch__tolerance"
    ).order_by("id")
    return {r.left_id: r for r in qs}  # id terbesar menang (defensif bila ganda)


def pending_settlement_count(toko):
    """Jumlah baris kredit yang masih AKTIF menunggu settlement (untuk info UI).
    COUNT(DISTINCT left) di SQL — setara len(_carried_results) tapi tanpa
    materialisasi objek (halaman /tokos/ sempat ~1,5 dtk karena ini per toko)."""
    return pending_settlement_counts([toko]).get(toko.id, 0)


def pending_settlement_counts(tokos):
    """toko_id → jumlah menunggu settlement, SATU query agregat untuk semua toko."""
    rows = _carried_qs(tokos).values_list("left__toko").annotate(
        n=Count("left_id", distinct=True)
    )
    return dict(rows)


def _retro_homes(toko, recon_date, date_from, date_to, include, exclude_ids=None):
    """tx_id → ReconBatch asal untuk BARIS SUSULAN: baris aktif dalam lingkup yang
    tanggalnya < recon_date dan tanggal itu sudah punya batch harian sendiri.
    Baris carried (punya hasil no_money lama) dikecualikan — jalurnya flip, bukan
    susulan. Tanggal tanpa batch → bukan susulan (diproses batch berjalan)."""
    qs = _consume_scope(toko, date_from, date_to, include).filter(
        occurred_at__date__lt=recon_date
    )
    if exclude_ids:
        qs = qs.exclude(id__in=exclude_ids)
    rows = list(qs.values_list("id", "occurred_at"))
    if not rows:
        return {}
    dates = {dt.date() for _, dt in rows if dt}
    homes = {
        b.recon_date: b
        for b in ReconBatch.objects.filter(toko=toko, recon_date__in=dates)
    }
    return {i: homes[dt.date()] for i, dt in rows if dt and dt.date() in homes}


def _add_retro_gross(batch, rows):
    """Tambah total POTRET (panel / money_gross) batch asal dengan baris susulan —
    baris ini belum terhitung saat batch asal dijalankan. Selisih/matched dihitung
    ulang terpisah oleh refresh_batch_summary."""
    s = dict(batch.summary or {})
    for flow in ("dp", "wd"):
        f = dict(s.get(flow) or {})
        f["panel"] = float(f.get("panel") or 0)
        f["money_gross"] = float(f.get("money_gross") or 0)
        s[flow] = f
    for t in rows:
        key = t.source_type.key
        if key == "panel" and t.jenis in ("depo", "wd"):
            flow = "dp" if t.jenis == "depo" else "wd"
            s[flow]["panel"] += float(t.amount)
        elif key in MONEY_SOURCES and t.jenis != "admin":
            md = float(t.money_delta)
            if md > 0:
                s["dp"]["money_gross"] += md
            elif md < 0:
                s["wd"]["money_gross"] += -md
    batch.summary = s
    batch.save(update_fields=["summary"])


def _writeback_retro(batch, retro, retro_results, tolerance, user):
    """Tulis hasil baris susulan ke MatchRun relasi sama di batch ASALnya (buat
    run baru bila relasinya belum pernah jalan di sana) + tambah gross batch asal.
    Return set batch asal yang tersentuh (untuk refresh summary)."""
    homes = {}
    groups = {}
    for r in retro_results:
        anchor = r.left_id if r.left_id is not None else r.right_id
        home = retro[anchor]
        groups.setdefault((home.pk, r.run.relation), (home, []))[1].append(r)
    for (home_pk, relation), (home, rs) in groups.items():
        run = MatchRun.objects.filter(batch=home, relation=relation).order_by("id").first()
        if run is None:
            run = MatchRun.objects.create(
                relation=relation, tolerance=tolerance, batch=home, created_by=user
            )
        note = f"Susulan via run {batch.recon_date}"
        for r in rs:
            r.run = run
            r.reason_detail = f"{r.reason_detail} ({note})" if r.reason_detail else note
        MatchResult.objects.bulk_create(rs, batch_size=2000)
        homes[home_pk] = home
    if retro:
        txs = Transaction.objects.filter(id__in=retro).select_related("source_type")
        per_home = {}
        for t in txs:
            home = retro[t.id]
            per_home.setdefault(home.pk, (home, []))[1].append(t)
        for home_pk, (home, rows) in per_home.items():
            _add_retro_gross(home, rows)
            homes[home_pk] = home
    return set(homes.values())


def _apply_late_settlements(batch, late_pairs):
    """Flip hasil no_money LAMA di batch asalnya: bucket ikut aturan skor normal
    (cocok / perlu_tinjau name_partial), right diisi baris uang, reason asal disimpan
    di reason_detail, ditandai resolved_by_batch=batch (untuk revert saat hapus)."""
    resolved = []
    for prior, new in late_pairs:
        if prior.bucket != MatchResult.Bucket.TIDAK:
            continue  # defensif: hasil sudah dioverride manual
        prior.bucket = new.bucket
        prior.right = new.right
        prior.score = new.score
        prior.reason_detail = (
            f"Settle terlambat oleh run {batch.recon_date} — asal: {prior.reason_code}"
            + (f"; {new.reason_detail}" if new.reason_detail else "")
        )
        prior.reason_code = "late_settlement"
        prior.resolved_by_batch = batch
        prior.save(update_fields=["bucket", "right", "score", "reason_code",
                                  "reason_detail", "resolved_by_batch"])
        resolved.append(prior)
    return resolved


def refresh_batch_summary(batch):
    """Hitung ulang bagian TURUNAN summary batch dari MatchResult tersimpan:
    bucket per run, money_matched/money/selisih, buckets total. Field potret saat
    run (panel, money_gross, warnings, skipped) tidak disentuh. Idempoten — dipakai
    saat hasil batch ini di-flip late settlement maupun di-revert."""
    batch.refresh_from_db(fields=["summary"])  # jangan timpa increment gross susulan
    runs = list(batch.runs.all())
    buckets = {"cocok": 0, "perlu_tinjau": 0, "tidak_cocok": 0}
    for r in runs:
        c = Counter(r.results.values_list("bucket", flat=True))
        s = dict(r.summary or {})
        for k in buckets:
            s[k] = c.get(k, 0)
            buckets[k] += s[k]
        r.summary = s
        r.save(update_fields=["summary"])
    dp_m, wd_m = _matched_money(runs)
    s = dict(batch.summary or {})
    for flow, matched in (("dp", dp_m), ("wd", wd_m)):
        f = dict(s.get(flow) or {})
        f["money_matched"] = matched
        f["money"] = matched  # key lama (backward-compat) = versi MATCHED
        f["selisih"] = float(f.get("panel") or 0) - matched
        s[flow] = f
    s["buckets"] = buckets
    batch.summary = s
    batch.save(update_fields=["summary"])


def _late_settlement_summary(resolved):
    """Ringkasan settle terlambat per arah uang (DP/WD) dari hasil yang di-flip."""
    out = {"dp": {"count": 0, "amount": 0.0}, "wd": {"count": 0, "amount": 0.0}}
    for r in resolved:
        md = float(r.right.money_delta)
        flow = "dp" if md > 0 else "wd"
        out[flow]["count"] += 1
        out[flow]["amount"] += abs(md)
    return out


def revert_late_settlements(batch):
    """Sebelum batch dihapus: batalkan semua efek carry-over yang dilakukan batch ini.
    Flip dikembalikan ke tidak_cocok/no_money (baris kreditnya aktif lagi — kandidat
    settlement berikutnya), baris kadaluarsa diaktifkan lagi, dan summary batch asal
    dihitung ulang. Return jumlah flip yang dibatalkan.
    Catatan: delete programatik (shell/queryset.delete) MELEWATI helper ini — jalur
    resmi penghapusan adalah view hapus batch di web."""
    results = list(
        MatchResult.objects.filter(resolved_by_batch=batch).select_related("run", "run__batch")
    )
    homes = {}
    for r in results:
        r.bucket = MatchResult.Bucket.TIDAK
        r.right = None
        r.score = 0
        r.reason_code = "no_money"
        r.reason_detail = NO_MONEY_DETAIL
        r.resolved_by_batch = None
        r.save(update_fields=["bucket", "right", "score", "reason_code",
                              "reason_detail", "resolved_by_batch"])
        if r.left_id:
            Transaction.objects.filter(pk=r.left_id).update(consumed_by_batch=None)
        if r.run.batch_id:
            homes[r.run.batch_id] = r.run.batch
    # Baris kadaluarsa yang batch ini konsumsi ke batch asal → aktif lagi.
    # Filter consumed_by_batch_id=home membuatnya no-op bila batch asal sudah dihapus.
    for e in ((batch.summary or {}).get("late_settlement") or {}).get("expired", []):
        Transaction.objects.filter(pk=e["tx"], consumed_by_batch_id=e["home"])\
            .update(consumed_by_batch=None)
    for home in homes.values():
        refresh_batch_summary(home)
    return len(results)


def classify_unmatched_money(t, recon_date, window, panel_tickets, operator_names):
    """Kategori uang tanpa pasangan (satu sumber kebenaran — dipakai engine & web):
    a = histori (di luar jangkauan window pasangan), b = gateway ber-ticket yang
    tak dikenal panel, c = pindah dana internal (lawan = rekening operator),
    d = dalam periode tanpa penjelasan → layak diperiksa manusia."""
    d = t.occurred_at.date() if t.occurred_at else None
    if d is None or d < recon_date - timedelta(days=window):
        return "a"
    if t.source_type.key == "gateway" and t.ticket_no and t.ticket_no not in panel_tickets:
        return "b"
    cp = _norm_owner(t.counterparty)
    if len(cp) >= 5:  # nama terlalu pendek rawan nyangkut di nama file
        for name in operator_names:
            if name and fuzz.partial_ratio(cp, name) >= 85:
                return "c"
    return "d"


def _operator_names(toko):
    """Nama pemilik rekening operator — diambil dari nama file upload bank toko."""
    from sources.models import Upload  # impor lokal: hindari siklus

    return [
        _norm_owner(n)
        for n in Upload.objects.filter(toko=toko, source_type__key="bank")
        .values_list("original_name", flat=True)
    ]


def _bracket_overlap_warning(runs):
    """Peringatan bila cocok Panel↔Bracket sangat rendah PADAHAL kedua sisi ada data —
    indikasi file Panel & Bracket beda periode / tidak sepasang (bukan mengubah join)."""
    for r in runs:
        if r.relation != MatchRun.Relation.PANEL_BRACKET:
            continue
        s = r.summary or {}
        left, right = s.get("left", 0), s.get("right", 0)
        cocok = s.get("cocok", 0)
        if left and not right:
            # Justru kasus PALING rusak, dan dulu paling sunyi: syarat lama
            # `left and right` mematikan peringatan tepat saat sisi kanan nol —
            # mis. file FR yang cuma berisi beban admin/kategori lain, sehingga
            # tiap baris panel jadi no_bracket tanpa satu pun penjelasan.
            apa = ("baris Bracket Deposit/Withdraw" if s.get("mode") == "username"
                   else "baris Bracket ber-ticket")
            return (f"Panel↔Bracket tanpa satu pun kandidat: tidak ada {apa} "
                    "dalam rentang — periksa file FR yang diunggah.")
        if left and right:  # kedua sisi punya baris
            # Pakai sisi TERBESAR sebagai penyebut: file beda periode membuat salah
            # satu sisi (mis. bracket setelah filter tanggal) menyusut jadi ~0 baris,
            # sehingga cocok jadi porsi kecil dari sisi yang penuh.
            denom = max(left, right)
            if (cocok / denom) < 0.10:
                return (
                    f"Panel↔Bracket cocok sangat rendah ({cocok} dari {denom}) — "
                    "kemungkinan file Panel & Bracket beda periode/tidak sepasang. "
                    "Cek tanggal file."
                )
    return None


def _mode_ticket_warning(runs):
    """Mode ticket terpilih PADAHAL sebagian baris Panel tak punya ticket.

    Baris itu tidak dinilai relasi ini sama sekali — tidak cocok, tidak gagal,
    tidak muncul di mana pun. Tanpa jejak ini, satu file salah unggah bisa
    membuat sehari penuh lolos senyap."""
    for r in runs:
        if r.relation != MatchRun.Relation.PANEL_BRACKET:
            continue
        s = r.summary or {}
        n = s.get("panel_tanpa_ticket", 0)
        if s.get("mode") == "ticket" and n:
            return (f"{n} baris Panel tanpa ticket tidak dinilai relasi "
                    "Panel↔Bracket (mode ticket). Periksa file Panel yang diunggah.")
    return None


def _panel_bracket_total_warning(toko, date_from, date_to, include, exclude_tx_ids=None):
    """Cross-check AGREGAT Panel vs Bracket per arah (untuk toko tanpa join ticket,
    mis. COR): bila total DP/WD beda > 2% padahal kedua sisi ada, beri peringatan.

    `exclude_tx_ids` = himpunan yang sama dengan `_aggregate_batch` (carried +
    susulan). Baris carried masih AKTIF saat peringatan dihitung (konsumsi baru
    terjadi di langkah terakhir run) sementara pasangan Bracket-nya sudah
    dikonsumsi di batch asalnya — tanpa pengecualian ini dua hari yang
    rekonsiliasinya sempurna tetap dituduh "total beda" di hari kedua."""
    if not _inc(include, "bracket"):
        return None
    base = _date_filter(_active(_toko_filter(
        Transaction.objects.filter(is_duplicate=False), toko)), date_from, date_to)
    if exclude_tx_ids:
        base = base.exclude(id__in=exclude_tx_ids)

    def tot(key, jenis):
        return float(base.filter(source_type__key=key, jenis=jenis)
                     .aggregate(x=Sum("amount"))["x"] or 0)

    for flow, jenis in (("DP", "depo"), ("WD", "wd")):
        p, b = tot("panel", jenis), tot("bracket", jenis)
        if p > 0 and b > 0 and abs(p - b) / max(p, b) > 0.02:
            return (f"Panel↔Bracket {flow} total beda: Panel {p:,.0f} vs "
                    f"Bracket {b:,.0f} (selisih {abs(p - b):,.0f}). Cek kelengkapan file.")
    return None


def _aggregate_batch(toko, date_from, date_to, runs, skipped, include=None, exclude_tx_ids=None):
    tx = _date_filter(_active(_toko_filter(Transaction.objects.filter(is_duplicate=False), toko)), date_from, date_to)
    if exclude_tx_ids:
        # Baris carry-over: nilainya sudah tercatat di total batch ASALnya —
        # jangan menggelembungkan total batch ini.
        tx = tx.exclude(id__in=exclude_tx_ids)

    def total(qs, field):
        return float(qs.aggregate(x=Sum(field))["x"] or 0)

    panel = tx.filter(source_type__key="panel")
    # include: Panel — buang sisi yang tidak dicentang dari total.
    if include is not None:
        if not include.get("panel_dp", True):
            panel = panel.exclude(jenis="depo")
        if not include.get("panel_wd", True):
            panel = panel.exclude(jenis="wd")
    # Baris fee BCA ('admin') dikecualikan dari uang WD (bukan WD nyata).
    # Hanya sumber uang yang dicentang ikut total gross.
    money = tx.filter(source_type__key__in=_included_money_sources(include)).exclude(jenis="admin")
    dp_panel = total(panel.filter(jenis="depo"), "amount")
    dp_gross = total(money.filter(money_delta__gt=0), "money_delta")
    wd_panel = total(panel.filter(jenis="wd"), "amount")
    wd_gross = abs(total(money.filter(money_delta__lt=0), "money_delta"))

    dp_matched, wd_matched = _matched_money(runs)

    buckets = {"cocok": 0, "perlu_tinjau": 0, "tidak_cocok": 0}
    for r in runs:
        for k in buckets:
            buckets[k] += (r.summary or {}).get(k, 0)

    warnings = []
    for w in (
        _bracket_overlap_warning(runs),
        _mode_ticket_warning(runs),
        _panel_bracket_total_warning(toko, date_from, date_to, include, exclude_tx_ids),
    ):
        if w:
            warnings.append(w)

    return {
        # money_matched = uang yang berpasangan ke Panel; selisih = panel - matched.
        # 'money'/'selisih' dipertahankan (backward-compat) = versi MATCHED.
        "dp": {
            "panel": dp_panel, "money_gross": dp_gross, "money_matched": dp_matched,
            "money": dp_matched, "selisih": dp_panel - dp_matched,
        },
        "wd": {
            "panel": wd_panel, "money_gross": wd_gross, "money_matched": wd_matched,
            "money": wd_matched, "selisih": wd_panel - wd_matched,
        },
        "buckets": buckets,
        "warnings": warnings,
        "relations": [r.relation for r in runs],
        "skipped": skipped,
    }


def _inc(include, key):
    """Sumber ikut run? include=None → semua ikut (perilaku lama). Selain itu: cek toggle."""
    return include is None or include.get(key, True)


def _consume_scope(toko, date_from, date_to, include):
    """Transaksi AKTIF dalam lingkup toko+tanggal yang HANYA dari sumber yang diikutkan.
    Ini yang akan dikunci ke batch setelah sukses (tidak menyentuh sumber tak dicentang)."""
    qs = _date_filter(_active(_toko_filter(Transaction.objects.filter(is_duplicate=False), toko)), date_from, date_to)
    panel = Q()
    if _inc(include, "panel_dp"):
        panel |= Q(source_type__key="panel", jenis="depo")
    if _inc(include, "panel_wd"):
        panel |= Q(source_type__key="panel", jenis="wd")
    cond = panel
    if _inc(include, "bracket"):
        cond |= Q(source_type__key="bracket")
    money_keys = _included_money_sources(include)
    if money_keys:
        cond |= Q(source_type__key__in=money_keys)
    if not cond:
        return Transaction.objects.none()
    return qs.filter(cond)


@db_tx.atomic
def run_batch(toko, tolerance=None, date_from=None, date_to=None, user=None, include=None,
              recon_date=None):
    """Atomic: kegagalan di tengah run me-rollback SEMUANYA (termasuk baris batch),
    sehingga tanggal harian tidak terblokir constraint unik oleh batch yatim."""
    tolerance = tolerance or ToleranceProfile.objects.get(name="Default")
    if recon_date and ReconBatch.objects.filter(toko=toko, recon_date=recon_date).exists():
        raise ValueError(f"Sudah ada batch untuk {toko} tanggal {recon_date}.")
    comp = check_completeness(toko, date_from, date_to)
    batch = ReconBatch.objects.create(
        toko=toko, tolerance=tolerance, date_from=date_from, date_to=date_to,
        created_by=user, completeness=comp, recon_date=recon_date,
    )
    carried = _carried_results(toko) if recon_date else {}
    relations, skipped, skipped_detail = [], [], {}
    # PANEL_BRACKET jalan bila bracket ADA, dicentang, DAN ada baris panel DALAM
    # SCOPE tanggal run. Panel TANPA ticket (Vigor/TM Gaming, mis. COR) tidak lagi
    # memblokir relasi: matcher punya mode username. Baris CARRIED tetap
    # dikecualikan — run_batches_auto melebarkan date_from ke baris carried, dan
    # PANEL_BRACKET toh mengecualikan carried dari pencocokan, jadi baris itu
    # hanya akan menghasilkan noise.
    panel_in_scope = _date_filter(
        _active(_toko_filter(Transaction.objects.filter(
            source_type__key="panel", is_duplicate=False), toko)),
        date_from, date_to,
    ).exclude(id__in=set(carried)).exists()
    if comp["bracket"] and _inc(include, "bracket") and panel_in_scope:
        relations.append(MatchRun.Relation.PANEL_BRACKET)
    else:
        skipped.append(MatchRun.Relation.PANEL_BRACKET.value)
        # Alasan SPESIFIK (dipakai halaman batch): "data tidak ada" saja pernah
        # menyesatkan — file FR sudah masuk, yang kurang justru sisi lain.
        if not _inc(include, "bracket"):
            alasan = "sumber Bracket tidak diikutkan dalam run ini"
        elif not comp["bracket"]:
            alasan = "tidak ada baris Bracket (FR) dalam rentang tanggal"
        else:
            # Baris panel bisa ADA tapi seluruhnya carried (gerbang mengecualikan
            # baris carried) — kalimat lama menuduh file panelnya kosong.
            alasan = ("tidak ada baris Panel dalam rentang tanggal "
                      "(atau semuanya masih menunggu settlement)")
        skipped_detail[MatchRun.Relation.PANEL_BRACKET.value] = alasan
    # PANEL_BANK jalan bila ada uang (bank/gateway) yang ADA & dicentang, ATAU —
    # jaring senyap — uang DIINGINKAN (dicentang) tapi kosong di scope sementara
    # ada panel DP/WD: matcher menghasilkan no_money per baris panel sehingga
    # deposit/wd tak lenyap senyap (selisih batch selalu punya baris penjelas).
    money_present = (comp["bank"] and _inc(include, "bank")) or (comp["gateway"] and _inc(include, "gateway"))
    money_wanted = _inc(include, "bank") or _inc(include, "gateway")
    panel_present = (comp["panel_dp"] and _inc(include, "panel_dp")) or (comp["panel_wd"] and _inc(include, "panel_wd"))
    if money_present or (money_wanted and panel_present):
        relations.append(MatchRun.Relation.PANEL_BANK)
    else:
        skipped.append(MatchRun.Relation.PANEL_BANK.value)

    retro = (
        _retro_homes(toko, recon_date, date_from, date_to, include, exclude_ids=set(carried))
        if recon_date else {}
    )
    runs = [
        run_match(rel, tolerance, date_from, date_to, user=user, toko=toko, batch=batch, include=include,
                  carried=carried, retro=retro)
        for rel in relations
    ]
    late_pairs = [pair for r in runs for pair in getattr(r, "late_pairs", [])]
    resolved = _apply_late_settlements(batch, late_pairs)
    retro_results = [r for run in runs for r in getattr(run, "retro_results", [])]
    retro_homes = _writeback_retro(batch, retro, retro_results, tolerance, user)
    summary = _aggregate_batch(toko, date_from, date_to, runs, skipped, include=include,
                               exclude_tx_ids=set(carried) | set(retro))
    if skipped_detail:
        # `skipped` (daftar kode) dipertahankan apa adanya untuk kompatibilitas;
        # detail dipisah agar batch LAMA tanpa kunci ini tetap render copy lama.
        summary.setdefault("skipped_detail", {}).update(skipped_detail)
    if recon_date:
        summary["late_settlement"] = _late_settlement_summary(resolved)
        summary["retro"] = {"count": len(retro)}
    # Segarkan summary batch ASAL yang tersentuh flip / baris susulan.
    for home in {b.pk: b for b in [r.run.batch for r in resolved] + list(retro_homes)}.values():
        refresh_batch_summary(home)
    # KONSUMSI-SAAT-SUKSES: langkah TERAKHIR. Bila ada exception di atas, tidak
    # tercapai → transaksi tetap aktif (gagal = tidak dibersihkan). Hanya sumber
    # yang diikutkan yang dikunci; sumber tak dicentang tetap tersedia lain kali.
    if recon_date:
        # Rekonsiliasi harian: baris kredit no_money yang masih dalam window
        # TIDAK dikonsumsi ("menunggu settlement") — mutasinya mungkin baru
        # muncul di file hari berikutnya.
        window = tolerance.date_window_days
        resolved_ids = {r.left_id for r in resolved}
        by_home, expired = {}, []
        # 1) Carried yang settle → konsumsi ke batch ASALnya (baris milik hari itu).
        for r in resolved:
            by_home.setdefault(r.run.batch_id, []).append(r.left_id)
        # 2) Carried tak settle & sudah lewat window → kadaluarsa: konsumsi diam-diam
        #    ke batch asal (tidak_cocok-nya sudah tercatat di sana). Jejak {tx, home}
        #    disimpan agar bisa dipulihkan bila batch ini dihapus.
        for left_id, prior in carried.items():
            if left_id in resolved_ids:
                continue
            d = prior.left.occurred_at.date() if prior.left.occurred_at else None
            if not _can_still_settle(d, recon_date, window):
                by_home.setdefault(prior.run.batch_id, []).append(left_id)
                expired.append({"tx": left_id, "home": prior.run.batch_id})
        # 2b) Baris SUSULAN → konsumsi ke batch tanggal asalnya, KECUALI panel
        #     tanpa pasangan uang yang masih dalam window (tetap aktif menunggu —
        #     hasil no_money-nya sudah tertulis di batch asal, jadi run berikutnya
        #     memperlakukannya sebagai carried biasa).
        retro_waiting = set()
        if retro:
            retro_matched_money = {
                r.left_id for r in retro_results
                if r.right_id is not None and r.run.relation != MatchRun.Relation.PANEL_BRACKET
            }
            for t in Transaction.objects.filter(id__in=retro).select_related("source_type"):
                d = t.occurred_at.date() if t.occurred_at else None
                if (
                    t.source_type.key == "panel"
                    and t.id not in retro_matched_money
                    and _can_still_settle(d, recon_date, window)
                ):
                    retro_waiting.add(t.id)
                else:
                    by_home.setdefault(retro[t.id].pk, []).append(t.id)
        for home_id, ids in by_home.items():
            Transaction.objects.filter(id__in=ids).update(consumed_by_batch_id=home_id)
        summary["late_settlement"]["expired"] = expired
        # 3) Yang masih menunggu settlement tetap AKTIF: carried dalam window yang
        #    belum settle + no_money BARU batch ini yang dalam window + panel
        #    susulan yang masih dalam window.
        new_carry = MatchResult.objects.filter(
            run__batch=batch, bucket=MatchResult.Bucket.TIDAK, reason_code="no_money",
            left__isnull=False,
            left__occurred_at__date__gt=recon_date - timedelta(days=window),
        ).values_list("left_id", flat=True)
        expired_ids = {e["tx"] for e in expired}
        still_waiting = (
            (set(carried) - resolved_ids - expired_ids) | set(new_carry) | retro_waiting
        )
        # B1 — carry-over sisi UANG: baris uang bertanggal > recon_date yang tidak
        # menjadi pasangan hasil mana pun hari ini tetap AKTIF (milik run tanggalnya
        # sendiri besok). Uang lintas-hari yang BERPASANGAN tetap dikonsumsi.
        used_rights = set()
        for r_ in runs:
            used_rights |= getattr(r_, "used_right_ids", set())
        money_keys = _included_money_sources(include)
        cross_money = set(
            _consume_scope(toko, date_from, date_to, include)
            .filter(source_type__key__in=money_keys, occurred_at__date__gt=recon_date)
            .exclude(id__in=used_rights)
            .values_list("id", flat=True)
        )
        _consume_scope(toko, date_from, date_to, include)\
            .exclude(id__in=still_waiting | cross_money).update(consumed_by_batch=batch)

        # B2 — uang tanpa pasangan: klasifikasi a/b/c/d; b & d dicatat sebagai
        # hasil no_panel (bisa ditinjau/di-flag), a & c cukup dihitung.
        pb_run = next(
            (r_ for r_ in runs if r_.relation == MatchRun.Relation.PANEL_BANK), None
        )
        if pb_run is not None:
            panel_ticket_set = set(
                Transaction.objects.filter(toko=toko, source_type__key="panel")
                .exclude(ticket_no="").values_list("ticket_no", flat=True)
            )
            ops = _operator_names(toko)
            stats = {k: {"n": 0, "dp": 0.0, "wd": 0.0} for k in "abcd"}
            new_results = []
            um_qs = (
                Transaction.objects.filter(
                    consumed_by_batch=batch, source_type__key__in=money_keys
                )
                .exclude(jenis="admin").exclude(id__in=used_rights)
                .select_related("source_type")
            )
            for t in um_qs:
                k = classify_unmatched_money(t, recon_date, window, panel_ticket_set, ops)
                st = stats[k]
                st["n"] += 1
                md = float(t.money_delta)
                if md > 0:
                    st["dp"] += md
                else:
                    st["wd"] += -md
                if k in ("b", "d"):
                    new_results.append(MatchResult(
                        run=pb_run, bucket=MatchResult.Bucket.TIDAK, left=None, right=t,
                        score=0, reason_code="no_panel",
                        reason_detail=(
                            "Ticket gateway tak dikenal panel" if k == "b"
                            else "Uang dalam periode tanpa catatan panel"
                        ),
                    ))
            if new_results:
                MatchResult.objects.bulk_create(new_results, batch_size=2000)
                s_ = dict(pb_run.summary or {})
                s_["tidak_cocok"] = s_.get("tidak_cocok", 0) + len(new_results)
                pb_run.summary = s_
                pb_run.save(update_fields=["summary"])
                summary["buckets"]["tidak_cocok"] += len(new_results)
            summary["unmatched_money"] = stats
    else:
        _consume_scope(toko, date_from, date_to, include).update(consumed_by_batch=batch)
    batch.summary = summary
    batch.save(update_fields=["summary"])
    return batch


def _as_date(v):
    """str ISO / date / None → date | None (verifikasi butuh aritmetika timedelta)."""
    if v is None or v == "":
        return None
    return date.fromisoformat(v) if isinstance(v, str) else v


def _panel_dates(toko, date_from=None, date_to=None, include=None):
    """Tanggal-panel AKTIF terurut MENAIK dalam scope & include — jangkar auto-split.
    Hanya baris panel DP/WD yang diikutkan (hormati include.panel_dp/panel_wd)."""
    qs = Transaction.objects.filter(
        source_type__key="panel", is_duplicate=False, jenis__in=["depo", "wd"]
    )
    if not _inc(include, "panel_dp"):
        qs = qs.exclude(jenis="depo")
    if not _inc(include, "panel_wd"):
        qs = qs.exclude(jenis="wd")
    qs = _date_filter(_active(_toko_filter(qs, toko)), date_from, date_to)
    return sorted({dt.date() for dt in qs.values_list("occurred_at", flat=True) if dt})


def verify_panel_anchor(toko, date_from, date_to, include, window):
    """Verifikasi jangkar tanggal: uang/bracket AKTIF yang tanggalnya berada DALAM
    rentang tanggal panel harus 'tertutup' minimal satu tanggal panel dalam window.
    Return list pelanggaran (kosong = lolos). Basis PER-TANGGAL; admin/fee dikecualikan.

    PENTING: hanya memeriksa tanggal DALAM rentang panel. Uang di LUAR rentang (mis.
    statement bank sebulan penuh sedang panel cuma sebagian tanggal) BUKAN pelanggaran
    — cuma belum direkonsiliasi, dibiarkan menunggu sampai panel tanggalnya diupload.
    Tanpa panel sama sekali → tak ada yang direkon → tak ada pelanggaran.

    'Tertutup' — money (bank/gateway): ∃ panel p dengan p <= m <= p+window (searah
    engine: uang >= panel). Bracket: ∃ panel p dengan |m-p| <= window. TANGGAL YANG
    SUDAH PUNYA BATCH juga menutup dirinya sendiri: panelnya pernah diupload lalu
    dikonsumsi (karena itu tak lagi terlihat sebagai jangkar aktif), dan baris baru
    bertanggal itu — lazim dari statement bank yang berputar — memang punya jalur
    sendiri, `_retro_homes`/`_writeback_retro`, yang menulisnya balik ke batch asal.
    Penutupan lewat batch berlaku TEPAT pada tanggalnya saja, tidak melebar sewindow,
    karena penulisan-balik retro dikunci per tanggal.

    Tiap pelanggaran membawa `butuh_panel`: tanggal panel yang akan menutupnya."""
    pdates = sorted(_panel_dates(toko, date_from, date_to, include))
    if not pdates:
        return []
    pset = set(pdates)
    bqs = ReconBatch.objects.filter(recon_date__isnull=False)
    if toko is not None:
        bqs = bqs.filter(toko=toko)
    bset = set(bqs.values_list("recon_date", flat=True))
    # Rentang relevan: uang harus >= panel (searah), jadi [panel_awal .. panel_akhir+window];
    # bracket boleh mendahului panel, jadi [panel_awal-window .. panel_akhir+window].
    lo_m, hi_m = pdates[0], pdates[-1] + timedelta(days=window)
    lo_b, hi_b = pdates[0] - timedelta(days=window), pdates[-1] + timedelta(days=window)
    base = _date_filter(
        _active(_toko_filter(Transaction.objects.filter(is_duplicate=False), toko)),
        date_from, date_to,
    )
    violations = []

    def covered_money(m):
        return m in bset or any(p <= m <= p + timedelta(days=window) for p in pset)

    def covered_bracket(m):
        return m in bset or any(abs((m - p).days) <= window for p in pset)

    def butuh_money(m):
        """Tanggal panel yang akan menutup uang tanggal `m` (uang >= panel)."""
        return [m - timedelta(days=d) for d in range(window, -1, -1)]

    def butuh_bracket(m):
        return [m + timedelta(days=d) for d in range(-window, window + 1)]

    money_keys = _included_money_sources(include)
    if money_keys:
        agg = defaultdict(lambda: [0.0, 0])  # tanggal -> [gross_abs, n]
        rows = (
            base.filter(source_type__key__in=money_keys)
            .exclude(jenis="admin")
            .values_list("occurred_at", "money_delta")
        )
        for dt, md in rows:
            if dt:
                a = agg[dt.date()]
                a[0] += abs(float(md or 0))
                a[1] += 1
        for m, (gross, n) in agg.items():
            if lo_m <= m <= hi_m and not covered_money(m):
                violations.append({"date": m, "source": "uang", "amount_gross": gross,
                                   "n": n, "butuh_panel": butuh_money(m)})

    if _inc(include, "bracket"):
        bdates = defaultdict(int)
        for dt in (
            base.filter(source_type__key="bracket")
            .exclude(ticket_no="")
            .values_list("occurred_at", flat=True)
        ):
            if dt:
                bdates[dt.date()] += 1
        for m, n in bdates.items():
            if lo_b <= m <= hi_b and not covered_bracket(m):
                violations.append({"date": m, "source": "bracket", "amount_gross": 0.0,
                                   "n": n, "butuh_panel": butuh_bracket(m)})

    return sorted(violations, key=lambda v: (v["date"], v["source"]))


def run_batches_auto(toko, tolerance=None, date_from=None, date_to=None, user=None, include=None):
    """Orkestrator rekonsiliasi otomatis per tanggal: satu ReconBatch per tanggal-panel
    (panel = jangkar). Pre-flight `verify_panel_anchor` memblokir bila ada uang/bracket
    DALAM rentang panel tanpa panel penutup — TAK ada batch dibuat. Loop MENAIK memakai
    carry-over bawaan: `run_batch(date_from=lo, date_to=D, recon_date=D)`.

    `lo` = tanggal panel terawal (atau baris carried yang lebih awal, agar carry-over
    lintas-hari tetap masuk scope) — BUKAN None. Ini penting: statement bank sering
    diekspor sebulan penuh sedang panel cuma sebagian tanggal; uang SEBELUM `lo` tak
    boleh ikut dikonsumsi ke batch pertama (biar tetap menunggu sampai panelnya ada).
    `date_to=D` cegah tanggal masa depan bocor. Tanggal ber-batch dilewati (tidak raise)."""
    tolerance = tolerance or ToleranceProfile.objects.get(name="Default")
    date_from = _as_date(date_from)
    date_to = _as_date(date_to)
    window = tolerance.date_window_days

    panel_dates = _panel_dates(toko, date_from, date_to, include)
    violations = verify_panel_anchor(toko, date_from, date_to, include, window)
    if violations:
        # Jalan keluar kedua (selain upload panel yang kurang): batasi rentang mulai
        # dari tanggal panel aman TERAWAL setelah pelanggaran terakhir — baris lama
        # tetap menunggu, tanggal yang panelnya lengkap tetap bisa dijalankan.
        batas = max(v["date"] for v in violations)
        aman = [d for d in panel_dates if d > batas]
        return {
            "ok": False, "batches": [], "dates_processed": [],
            "skipped_existing": [], "violations": violations,
            "errors": [], "panel_dates": panel_dates,
            "saran_dari": aman[0] if aman else None,
        }

    # Batas bawah scope: tanggal panel terawal, diperlebar ke tanggal baris carried
    # bila lebih awal (carry-over lintas-hari harus tetap masuk scope). Uang di bawah
    # batas ini tidak ikut dikonsumsi — dibiarkan menunggu panel tanggalnya.
    lo = min(panel_dates) if panel_dates else None
    if lo is not None:
        carried_dates = [
            r.left.occurred_at.date()
            for r in _carried_results(toko).values()
            if r.left and r.left.occurred_at
        ]
        if carried_dates:
            lo = min(lo, min(carried_dates))

    batches, skipped_existing, errors = [], [], []
    for d in panel_dates:  # MENAIK — prasyarat kebenaran carry-over
        existing = ReconBatch.objects.filter(toko=toko, recon_date=d).first()
        if existing:
            skipped_existing.append({"date": d, "batch_id": existing.id})
            continue
        try:
            batch = run_batch(
                toko, tolerance, date_from=lo, date_to=d,
                user=user, include=include, recon_date=d,
            )
            batches.append(batch)
        except Exception as e:  # noqa: BLE001 - kumpulkan kegagalan per tanggal, lanjut
            errors.append({"date": d, "message": str(e)})
    return {
        "ok": True, "batches": batches,
        "dates_processed": [b.recon_date for b in batches],
        "skipped_existing": skipped_existing, "violations": [],
        "errors": errors, "panel_dates": panel_dates,
    }
