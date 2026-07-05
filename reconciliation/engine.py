"""Engine pencocokan (rule-based & tunable).

Tiap relasi punya Matcher sendiri (pluggable lewat MATCHERS). Hasil = MatchResult
dengan bucket cocok / tidak_cocok / perlu_tinjau + reason. Toleransi dari ToleranceProfile.
"""
from collections import Counter
from datetime import timedelta

from django.db import transaction as db_tx
from django.db.models import Q, Sum
from django.utils.dateparse import parse_date
from rapidfuzz import fuzz

from sources.parsers.base import clean_name
from transactions.models import Transaction

from .models import MatchResult, MatchRun, ReconBatch, ToleranceProfile

MONEY_SOURCES = ["bank", "gateway"]

# Status gateway yang dianggap UANG SUDAH MASUK. Selain ini (UNPAID/FAILED/EXPIRED/
# PENDING) = QR belum settle → tak boleh jadi padanan uang & tak masuk gross.
SETTLED_STATUS = {"PAID", "SUCCESS", "SETTLED", "SETTLE", "SUKSES", "COMPLETED"}


def _norm_key(s):
    return (s or "").strip().upper()


def _gw_status(t):
    raw = t.raw or {}
    return _norm_key(raw.get("Payment Status") or raw.get("Status"))


def _gw_settled(t):
    """Baris gateway sudah settle (uang benar-benar masuk)? Baca status dari raw."""
    return _gw_status(t) in SETTLED_STATUS


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


def _as_date(v):
    """Koersi tanggal di titik masuk engine: web POST & CLI mengirim STRING
    'YYYY-MM-DD', tes/internal mengirim objek date, None = tanpa batas. Tanpa ini
    _widen_dto crash 'str + timedelta' saat reconcile harian dari web."""
    if v is None or hasattr(v, "toordinal"):  # date/datetime lolos apa adanya
        return v
    d = parse_date(str(v).strip())
    if d is None:
        raise ValueError(f"Format tanggal tidak dikenal: {v!r} (pakai YYYY-MM-DD)")
    return d


def _widen_dto(dto, tol):
    """Batas atas window sisi UANG diperlebar sebesar date_window_days: bank settle
    T+n (mis. Panel malam tgl 26 → mutasi bank baru masuk statement tgl 27) tetap
    jadi kandidat pada reconcile harian. Reuse date_window_days — satu knob, konsisten
    dengan gate date_ok. dto/tol None → tak diperlebar (perilaku lama)."""
    if dto and tol is not None:
        return dto + timedelta(days=tol.date_window_days)
    return dto


def _toko_filter(qs, toko):
    return qs.filter(toko=toko) if toko is not None else qs


def _active(qs):
    """Pool AKTIF = transaksi yang belum dikonsumsi batch mana pun. Transaksi yang
    sudah dipakai (consumed_by_batch terisi) tidak ikut kelengkapan/pencocokan/total."""
    return qs.filter(consumed_by_batch__isnull=True)


def check_completeness(toko, date_from=None, date_to=None, tol=None):
    date_from, date_to = _as_date(date_from), _as_date(date_to)
    base = _active(_toko_filter(Transaction.objects.filter(is_duplicate=False), toko))
    qs = _date_filter(base, date_from, date_to)
    # Sisi UANG dicek di window settlement (dto diperlebar) supaya bank T+1 terdeteksi
    # ada — kalau tidak, relasi PANEL_BANK ke-skip pada reconcile harian.
    money_qs = _date_filter(base, date_from, _widen_dto(date_to, tol))

    def has(q, **kw):
        return q.filter(**kw).exists()

    comp = {
        "panel_dp": has(qs, source_type__key="panel", jenis="depo"),
        "panel_wd": has(qs, source_type__key="panel", jenis="wd"),
        "bracket": has(qs, source_type__key="bracket"),
        "bank": has(money_qs, source_type__key="bank"),
        "gateway": has(money_qs, source_type__key="gateway"),
    }
    comp["panel"] = comp["panel_dp"] or comp["panel_wd"]
    comp["minimum_met"] = comp["panel"] and (comp["bank"] or comp["gateway"])
    return comp


class PanelBracketMatcher:
    """Join via Ticket Number (kuat). Cek kecocokan nominal."""

    def sides(self, dfrom, dto, toko=None, include=None, tol=None):
        # Bracket join via ticket (tak ada lag settlement) → tol diabaikan.
        left = Transaction.objects.filter(source_type__key="panel", is_duplicate=False)
        # include: hilangkan sisi Panel yang tidak dicentang (depo/wd) bila diberikan.
        if include is not None:
            if not include.get("panel_dp", True):
                left = left.exclude(jenis="depo")
            if not include.get("panel_wd", True):
                left = left.exclude(jenis="wd")
        left = _date_filter(_active(_toko_filter(left, toko)), dfrom, dto)
        right = _date_filter(
            _active(_toko_filter(
                Transaction.objects.filter(source_type__key="bracket", is_duplicate=False).exclude(ticket_no=""), toko
            )),
            dfrom, dto,
        )
        return list(left), list(right)

    def match(self, run, left, right):
        tol = run.tolerance
        bidx = {}
        for b in right:
            bidx.setdefault(b.ticket_no, []).append(b)
        used, out = set(), []
        for p in left:
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


class _MoneyMatcher:
    """Cocokkan sisi kredit (Panel/Bracket) ke sisi UANG (Bank/Gateway):
    blocking by nominal, lalu tanggal-terarah + username/fuzzy nama."""

    left_key = "panel"

    def sides(self, dfrom, dto, toko=None, include=None, tol=None):
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

        # right: hanya sumber UANG yang dicentang (bank dan/atau gateway). Window
        # atas diperlebar (settlement T+n) supaya bank pending yang masuk hari
        # berikutnya tetap jadi kandidat; jarak pair tetap digate date_ok.
        money_keys = _included_money_sources(include)
        right = _date_filter(
            _active(_toko_filter(
                Transaction.objects.filter(source_type__key__in=money_keys, is_duplicate=False).exclude(jenis="admin"),
                toko,
            )),
            dfrom, _widen_dto(dto, tol),
        )
        return list(left), list(right)

    def match(self, run, left, right):
        tol = run.tolerance
        # --- Pisahkan pool sisi UANG per sumber ---
        # GATEWAY (QR) punya kunci eksak immutable (TXN ID = ticket_no, Client Reference
        # = reference) yang sama dengan sisi kredit → cocokkan EKSAK, kebal T+1 & kebal
        # deposit berulang. BANK tak punya kunci → tetap fuzzy (nominal+tanggal+nama).
        gw_all_ticket = {}   # semua gateway (incl belum settle) — deteksi "ini txn QR"
        gw_ticket = {}       # gateway SETTLED, index by ticket_no
        gw_ref = {}          # gateway SETTLED, index by reference
        gw_settled = []      # untuk emit orphan (uang QR masuk tanpa deposit Panel)
        bank_by_amt = {}     # bank, blocking by nominal (fuzzy)
        for b in right:
            if b.source_type.key == "gateway":
                k = _norm_key(b.ticket_no)
                if k:
                    gw_all_ticket.setdefault(k, []).append(b)
                if _gw_settled(b):
                    gw_settled.append(b)
                    if k:
                        gw_ticket.setdefault(k, []).append(b)
                    r = _norm_key(b.reference)
                    if r:
                        gw_ref.setdefault(r, []).append(b)
            else:
                bank_by_amt.setdefault(int(abs(b.money_delta)), []).append(b)

        used, out = set(), []
        for p in left:
            # ===== Pass 1: gateway kunci EKSAK (TXN ID → Client Reference) =====
            tk, rf = _norm_key(p.ticket_no), _norm_key(p.reference)
            keytype = "gateway_ticket"
            cand = [b for b in gw_ticket.get(tk, []) if b.id not in used] if tk else []
            if not cand and rf:
                cand = [b for b in gw_ref.get(rf, []) if b.id not in used]
                keytype = "gateway_reference"
            if cand:
                if len(cand) >= 2:  # kunci tak unik → jangan tebak, auditor pilih
                    ids = ", ".join(f"#{b.id}" for b in cand)
                    out.append(MatchResult(run=run, bucket=MatchResult.Bucket.TINJAU, left=p, right=None,
                                           score=0, reason_code="gateway_key_ambiguous",
                                           reason_detail=f"{len(cand)} baris gateway kunci sama: {ids}"))
                    continue
                b = cand[0]
                used.add(b.id)
                ok, diff = amount_ok(p.amount, b.amount, tol)
                if ok:
                    out.append(MatchResult(run=run, bucket=MatchResult.Bucket.COCOK, left=p, right=b,
                                           score=100, reason_code=keytype))
                else:  # kunci cocok tapi nominal beda → TERMINAL (jangan jatuh ke bank)
                    out.append(MatchResult(run=run, bucket=MatchResult.Bucket.TINJAU, left=p, right=b,
                                           score=60, reason_code="gateway_amount_mismatch",
                                           reason_detail=f"selisih {diff}: Panel {p.amount} vs Gateway {b.amount}"))
                continue
            if tk and tk in gw_all_ticket:
                # Ticket QR ADA tapi tak ada yang settle (UNPAID/FAILED) → uang tak masuk.
                # TERMINAL: jangan jatuh ke bank fuzzy (nanti nyasar ke uang orang lain).
                out.append(MatchResult(run=run, bucket=MatchResult.Bucket.TIDAK, left=p, right=None,
                                       score=0, reason_code="gateway_unpaid",
                                       reason_detail=f"QR {p.ticket_no} belum settle (uang belum masuk)"))
                continue

            # ===== Pass 2: bank FUZZY (hanya panel yang belum kena gateway) =====
            # Nomor tujuan (dest_account) = KUNCI KUAT WD, analog TXN ID gateway: kalau
            # panel & bank sama-sama punya nomor tujuan dan cocok (sudah ternormalisasi
            # di parser → cukup bandingkan eksak), skor 100 & tandai dest — menang atas
            # kecocokan nama. Kalau nomor tak ada / beda → jatuh ke skor nama biasa.
            scored = []
            for b in bank_by_amt.get(int(abs(p.money_delta)), []):
                if b.id in used:
                    continue
                if (p.money_delta > 0) != (b.money_delta > 0):
                    continue  # arah uang harus sama
                if not date_ok(p.occurred_at, b.occurred_at, tol):
                    continue
                is_dest = bool(p.dest_account and b.dest_account and p.dest_account == b.dest_account)
                if is_dest:
                    s = 100.0
                elif p.username and b.username:
                    s = 100.0 if p.username.lower() == b.username.lower() else 40.0
                    if p.counterparty and b.counterparty:
                        s = max(s, _name_score(p.counterparty, b.counterparty))
                else:
                    s = _name_score(p.counterparty, b.counterparty)
                scored.append((s, b, is_dest))
            if scored:
                best_s = max(s for s, _, _ in scored)
                # Pada skor seri, kandidat dest-match diprioritaskan (kunci kuat menang
                # atas kecocokan nama yang kebetulan sama-sama 100).
                best, best_is_dest = next(
                    ((b, d) for s, b, d in scored if s == best_s and d),
                    next((b, d) for s, b, d in scored if s == best_s),
                )
            else:
                best, best_s, best_is_dest = None, -1, False
            # Ambigu SEJATI: >=2 kandidat SERI di skor tertinggi DAN lolos ambang DAN
            # ber-IDENTITAS BERBEDA → tinjau, JANGAN konsumsi (auditor pilih). Deposit
            # berulang oleh user SAMA BUKAN ambigu → pasangkan greedy 1-1. Untuk baris
            # dest-match, identitas = NOMOR TUJUAN (nomor sama = identitas sama, walau
            # nama kosong) → jangan dianggap ambigu.
            tied = [(b, d) for s, b, d in scored if s == best_s]
            tied_idents = {
                b.dest_account if d
                else ((b.username or "").strip().lower() or (b.counterparty or "").strip().lower())
                for b, d in tied
            }
            ambiguous = len(tied) >= 2 and len(tied_idents) >= 2
            match_reason = "bank_dest" if best_is_dest else "amount+date+name"
            if best is not None and best_s >= tol.fuzzy_threshold and ambiguous:
                names = ", ".join(f"#{b.id} {b.counterparty or b.username or '-'}" for b, _ in tied)
                out.append(MatchResult(run=run, bucket=MatchResult.Bucket.TINJAU, left=p, right=None,
                                       score=best_s, reason_code="ambiguous_multi",
                                       reason_detail=f"{len(tied)} kandidat seri (skor {best_s:.0f}): {names}"))
            elif best is not None and best_s >= tol.fuzzy_threshold:
                used.add(best.id)
                out.append(MatchResult(run=run, bucket=MatchResult.Bucket.COCOK, left=p, right=best,
                                       score=best_s, reason_code=match_reason))
            elif best is not None:
                used.add(best.id)
                out.append(MatchResult(run=run, bucket=MatchResult.Bucket.TINJAU, left=p, right=best,
                                       score=best_s, reason_code="weak_name",
                                       reason_detail=f"nominal+tanggal cocok, nama lemah (score {best_s:.0f})"))
            else:
                out.append(MatchResult(run=run, bucket=MatchResult.Bucket.TIDAK, left=p, right=None,
                                       score=0, reason_code="no_money",
                                       reason_detail="Tak ada padanan nominal+tanggal di Bank/Gateway"))

        # ===== Orphan: uang QR SETTLE tanpa deposit Panel (uang masuk, tak ada record) =====
        # Sinyal audit paling penting. Hanya yang SETTLED — UNPAID tak dihitung uang.
        # HANYA dalam window run [from,to]: pool right dilebarkan T+n untuk PAIRING,
        # tapi uang QR bertanggal D+1 tanpa panel itu milik batch besok — bukan
        # orphan hari ini (kalau ikut dicap, batch hari ini mencuri uang besok).
        dto = _as_date(run.date_to)
        for b in gw_settled:
            if b.id not in used:
                if dto is not None and b.occurred_at.date() > dto:
                    continue
                out.append(MatchResult(run=run, bucket=MatchResult.Bucket.TIDAK, left=None, right=b,
                                       score=0, reason_code="gateway_no_panel",
                                       reason_detail="Uang QR settle tanpa deposit Panel"))
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


def run_match(relation, tolerance=None, date_from=None, date_to=None, user=None, toko=None, batch=None, include=None):
    date_from, date_to = _as_date(date_from), _as_date(date_to)
    tolerance = tolerance or ToleranceProfile.objects.get(name="Default")
    matcher = MATCHERS[relation]()
    run = MatchRun.objects.create(
        relation=relation, tolerance=tolerance, date_from=date_from, date_to=date_to,
        created_by=user, batch=batch,
    )
    left, right = matcher.sides(date_from, date_to, toko, include=include, tol=tolerance)
    results = matcher.match(run, left, right)
    with db_tx.atomic():
        MatchResult.objects.bulk_create(results, batch_size=2000)
    c = Counter(r.bucket for r in results)
    run.summary = {
        "left": len(left), "right": len(right),
        "cocok": c.get("cocok", 0),
        "perlu_tinjau": c.get("perlu_tinjau", 0),
        "tidak_cocok": c.get("tidak_cocok", 0),
    }
    run.save(update_fields=["summary"])
    return run


def _matched_money(runs):
    """Uang REAL yang benar-benar berpasangan ke baris Panel (bucket cocok + perlu_tinjau).

    Dijumlah dari sisi UANG (right) pada MatchResult PANEL_BANK yang punya left&right.
    DP = money_delta>0, WD = abs(money_delta<0). Tidak menjalankan ulang matching.
    """
    panel_bank = [r.id for r in runs if r.relation == MatchRun.Relation.PANEL_BANK]
    dp = wd = 0.0
    if panel_bank:
        results = MatchResult.objects.filter(
            run_id__in=panel_bank, left__isnull=False, right__isnull=False
        ).select_related("right")
        for res in results:
            md = float(res.right.money_delta)
            if md > 0:
                dp += md
            elif md < 0:
                wd += -md
    return dp, wd


def _bracket_overlap_warning(runs):
    """Peringatan bila cocok Panel↔Bracket sangat rendah PADAHAL kedua sisi ada data —
    indikasi file Panel & Bracket beda periode / tidak sepasang (bukan mengubah join)."""
    for r in runs:
        if r.relation != MatchRun.Relation.PANEL_BRACKET:
            continue
        s = r.summary or {}
        left, right = s.get("left", 0), s.get("right", 0)
        cocok = s.get("cocok", 0)
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


def _batch_active(qs, batch):
    """Pool 'aktif' untuk agregasi batch. Saat run asli (batch belum konsumsi) sama
    dengan _active. Saat re-match (batch sudah konsumsi barisnya sendiri) baris milik
    batch INI tetap ikut — kalau tidak, gross-nya kolaps ke ~0. Baris yang dikonsumsi
    batch LAIN tetap dikecualikan."""
    if batch is None:
        return _active(qs)
    return qs.filter(Q(consumed_by_batch__isnull=True) | Q(consumed_by_batch=batch))


def _aggregate_batch(toko, date_from, date_to, runs, skipped, include=None, batch=None):
    tx = _date_filter(_batch_active(_toko_filter(Transaction.objects.filter(is_duplicate=False), toko), batch), date_from, date_to)

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
    # Gateway yang BELUM settle (UNPAID/FAILED) bukan uang masuk → keluarkan dari gross
    # supaya tak menggelembungkan angka & selisih.
    unsettled = [t.id for t in money.filter(source_type__key="gateway") if not _gw_settled(t)]
    if unsettled:
        money = money.exclude(id__in=unsettled)
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
    w = _bracket_overlap_warning(runs)
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


def run_batch(toko, tolerance=None, date_from=None, date_to=None, user=None, include=None):
    date_from, date_to = _as_date(date_from), _as_date(date_to)
    tolerance = tolerance or ToleranceProfile.objects.get(name="Default")
    batch = ReconBatch.objects.create(
        toko=toko, tolerance=tolerance, date_from=date_from, date_to=date_to,
        created_by=user, include=include, status=ReconBatch.Status.BERJALAN,
    )
    return run_batch_into(batch, user=user)


def run_batch_into(batch, user=None):
    """Isi batch placeholder (status=berjalan) dengan hasil rekonsiliasi penuh.

    Entry point background runner: placeholder dibuat cepat di request, engine
    jalan di thread. Lock baris Toko men-serialisasi reconcile/re-match per
    toko. Gagal = isi (runs/hasil/konsumsi) rollback TOTAL, batch ditandai
    `gagal` + error_note — kegagalan terlihat, bukan cangkang setengah jadi.
    """
    try:
        with db_tx.atomic():
            toko = type(batch.toko).objects.select_for_update().get(pk=batch.toko_id)
            _run_batch_locked(
                batch, toko, batch.tolerance,
                _as_date(batch.date_from), _as_date(batch.date_to),
                user or batch.created_by, batch.include,
            )
            batch.status = ReconBatch.Status.SELESAI
            batch.save(update_fields=["status"])
    except Exception as e:  # noqa: BLE001 - tandai gagal, tetap propagate
        ReconBatch.objects.filter(pk=batch.pk).update(
            status=ReconBatch.Status.GAGAL, error_note=str(e)[:500]
        )
        raise
    return batch


def _run_batch_locked(batch, toko, tolerance, date_from, date_to, user, include):
    comp = check_completeness(toko, date_from, date_to, tol=tolerance)
    batch.completeness = comp
    batch.save(update_fields=["completeness"])
    relations, skipped = [], []
    # PANEL_BRACKET hanya jika bracket ADA dan dicentang.
    if comp["bracket"] and _inc(include, "bracket"):
        relations.append(MatchRun.Relation.PANEL_BRACKET)
    else:
        skipped.append(MatchRun.Relation.PANEL_BRACKET.value)
    # PANEL_BANK hanya jika ada sumber uang yang ADA dan dicentang.
    if (comp["bank"] and _inc(include, "bank")) or (comp["gateway"] and _inc(include, "gateway")):
        relations.append(MatchRun.Relation.PANEL_BANK)
    else:
        skipped.append(MatchRun.Relation.PANEL_BANK.value)

    runs = [
        run_match(rel, tolerance, date_from, date_to, user=user, toko=toko, batch=batch, include=include)
        for rel in relations
    ]
    batch.summary = _aggregate_batch(toko, date_from, date_to, runs, skipped, include=include, batch=batch)
    batch.save(update_fields=["summary"])
    # KONSUMSI-SAAT-SUKSES: langkah TERAKHIR. Bila ada exception di atas, tidak
    # tercapai → transaksi tetap aktif (gagal = tidak dibersihkan). Hanya sumber
    # yang diikutkan yang dikunci; sumber tak dicentang tetap tersedia lain kali.
    _consume_scope(toko, date_from, date_to, include).update(consumed_by_batch=batch)
    # Spillover T+n: baris UANG yang settle di luar [from,to] tapi BERPASANGAN ke
    # Panel di batch ini juga dikunci — kalau tidak, batch besok match ulang.
    # Orphan (tak match) TIDAK dikonsumsi → tetap tersedia untuk batch berikutnya.
    spill = list(
        MatchResult.objects.filter(
            run__batch=batch,
            left__isnull=False,  # hanya yang BERPASANGAN — orphan bukan spillover
            right__isnull=False,
            right__source_type__key__in=MONEY_SOURCES,
            right__consumed_by_batch__isnull=True,
        ).values_list("right_id", flat=True)
    )
    if spill:
        Transaction.objects.filter(id__in=spill).update(consumed_by_batch=batch)
    return batch


def rematch_batch(batch, user=None):
    """Pasangkan mutasi UANG susulan ke baris tidak_cocok batch LAMA — tanpa hapus batch.

    Kasus: ekor malam T+1 (bank/gateway lag semalam) & statement BNI bulanan. Baris
    Panel tidak_cocok di batch lama dipasangkan ke pool uang AKTIF di window yang SAMA
    dengan run asli; yang berpasangan dikonsumsi ke batch INI; summary/selisih dihitung
    ulang. TIDAK mencuri baris yang dikonsumsi batch lain. Idempoten. PANEL_BANK saja.
    Lihat docs/superpowers/specs/rematch-batch.md.
    """
    n_targets = n_paired = n_cocok = n_tinjau = 0
    with db_tx.atomic():
        # Lock per-toko yang sama dengan run_batch — re-match & reconcile
        # bersamaan pada satu toko tak boleh berebut pool uang aktif.
        type(batch.toko).objects.select_for_update().get(pk=batch.toko_id)
        for run in batch.runs.filter(relation=MatchRun.Relation.PANEL_BANK):
            matcher = MATCHERS[run.relation]()
            # Target = baris tidak_cocok yang PUNYA sisi kiri (skip orphan/gateway_no_panel).
            targets = list(
                run.results.filter(bucket=MatchResult.Bucket.TIDAK, left__isnull=False)
                .select_related("left")
            )
            n_targets += len(targets)
            if not targets:
                continue
            left_txs = [t.left for t in targets]
            by_left = {}
            for t in targets:
                by_left.setdefault(t.left_id, []).append(t)

            # Pool kandidat = uang AKTIF di window run asli (widen sama), hormati include.
            _, right_pool = matcher.sides(
                batch.date_from, batch.date_to, batch.toko,
                include=batch.include, tol=batch.tolerance,
            )
            # Matcher jalan pakai run yang ADA (bukan run baru). Hasil ini SCRATCH —
            # jangan bulk_create; kita hanya baca verdict-nya untuk update in-place.
            fresh = matcher.match(run, left_txs, right_pool)
            by_left_fresh = {f.left_id: f for f in fresh if f.left_id is not None}

            to_consume = []
            for left_id, tgt_list in by_left.items():
                f = by_left_fresh.get(left_id)
                if f is None:
                    continue
                paired = f.right is not None
                changed = paired or f.bucket != MatchResult.Bucket.TIDAK
                if not changed:
                    # Masih tidak_cocok/no_money → jangan churn reason_detail.
                    continue
                for tgt in tgt_list:
                    tgt.bucket = f.bucket
                    tgt.right = f.right
                    tgt.score = f.score
                    tgt.reason_code = f.reason_code
                    tgt.reason_detail = (f.reason_detail or "") + " (re-match)"
                    tgt.save(update_fields=["bucket", "right", "score", "reason_code", "reason_detail"])
                    if f.right is not None:
                        to_consume.append(f.right_id)
                        n_paired += 1
                        if f.bucket == MatchResult.Bucket.COCOK:
                            n_cocok += 1
                        elif f.bucket == MatchResult.Bucket.TINJAU:
                            n_tinjau += 1

            if to_consume:
                # Pool aktif-saja → tak ada konflik; tetap guard isnull utk keamanan race.
                Transaction.objects.filter(
                    id__in=to_consume, consumed_by_batch__isnull=True
                ).update(consumed_by_batch=batch)

            # Recompute hitungan bucket per-run dari MatchResult aktual (left/right pool
            # historis dibiarkan apa adanya).
            c = Counter(
                run.results.values_list("bucket", flat=True)
            )
            s = run.summary or {}
            s["cocok"] = c.get("cocok", 0)
            s["perlu_tinjau"] = c.get("perlu_tinjau", 0)
            s["tidak_cocok"] = c.get("tidak_cocok", 0)
            run.summary = s
            run.save(update_fields=["summary"])

        # Recompute summary batch — pakai batch-param supaya baris yang DIKONSUMSI batch
        # ini tetap masuk gross (jangan kolaps ke 0).
        batch.summary = _aggregate_batch(
            batch.toko, batch.date_from, batch.date_to,
            runs=list(batch.runs.all()),
            skipped=(batch.summary or {}).get("skipped", []),
            include=batch.include, batch=batch,
        )
        batch.save(update_fields=["summary"])

    return {
        "diperiksa": n_targets,
        "terpasang": n_paired,
        "cocok": n_cocok,
        "perlu_tinjau": n_tinjau,
    }
