"""Engine pencocokan (rule-based & tunable).

Tiap relasi punya Matcher sendiri (pluggable lewat MATCHERS). Hasil = MatchResult
dengan bucket cocok / tidak_cocok / perlu_tinjau + reason. Toleransi dari ToleranceProfile.
"""
from collections import Counter

from django.db import transaction as db_tx
from django.db.models import Sum
from rapidfuzz import fuzz

from sources.parsers.base import clean_name
from transactions.models import Transaction

from .models import MatchResult, MatchRun, ReconBatch, ToleranceProfile

MONEY_SOURCES = ["bank", "gateway"]


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


def check_completeness(toko, date_from=None, date_to=None):
    qs = _toko_filter(Transaction.objects.filter(is_duplicate=False), toko)
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
    """Join via Ticket Number (kuat). Cek kecocokan nominal."""

    def sides(self, dfrom, dto, toko=None):
        left = _date_filter(
            _toko_filter(Transaction.objects.filter(source_type__key="panel", is_duplicate=False), toko), dfrom, dto
        )
        right = _date_filter(
            _toko_filter(Transaction.objects.filter(source_type__key="bracket", is_duplicate=False).exclude(ticket_no=""), toko),
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

    def sides(self, dfrom, dto, toko=None):
        left = _date_filter(
            _toko_filter(
                Transaction.objects.filter(source_type__key=self.left_key, is_duplicate=False).filter(jenis__in=["depo", "wd"]),
                toko,
            ),
            dfrom, dto,
        )
        right = _date_filter(
            _toko_filter(
                Transaction.objects.filter(source_type__key__in=MONEY_SOURCES, is_duplicate=False).exclude(jenis="admin"),
                toko,
            ),
            dfrom, dto,
        )
        return list(left), list(right)

    def match(self, run, left, right):
        tol = run.tolerance
        bidx = {}
        for b in right:
            bidx.setdefault(int(abs(b.money_delta)), []).append(b)
        used, out = set(), []
        for p in left:
            best, best_s = None, -1
            for b in bidx.get(int(abs(p.money_delta)), []):
                if b.id in used:
                    continue
                if (p.money_delta > 0) != (b.money_delta > 0):
                    continue  # arah uang harus sama
                if not date_ok(p.occurred_at, b.occurred_at, tol):
                    continue
                if p.username and b.username:
                    s = 100.0 if p.username.lower() == b.username.lower() else 40.0
                    if p.counterparty and b.counterparty:
                        s = max(s, _name_score(p.counterparty, b.counterparty))
                else:
                    s = _name_score(p.counterparty, b.counterparty)
                if s > best_s:
                    best, best_s = b, s
            if best is not None and best_s >= tol.fuzzy_threshold:
                used.add(best.id)
                out.append(MatchResult(run=run, bucket=MatchResult.Bucket.COCOK, left=p, right=best,
                                       score=best_s, reason_code="amount+date+name"))
            elif best is not None:
                used.add(best.id)
                out.append(MatchResult(run=run, bucket=MatchResult.Bucket.TINJAU, left=p, right=best,
                                       score=best_s, reason_code="weak_name",
                                       reason_detail=f"nominal+tanggal cocok, nama lemah (score {best_s:.0f})"))
            else:
                out.append(MatchResult(run=run, bucket=MatchResult.Bucket.TIDAK, left=p, right=None,
                                       score=0, reason_code="no_money",
                                       reason_detail="Tak ada padanan nominal+tanggal di Bank/Gateway"))
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


def run_match(relation, tolerance=None, date_from=None, date_to=None, user=None, toko=None, batch=None):
    tolerance = tolerance or ToleranceProfile.objects.get(name="Default")
    matcher = MATCHERS[relation]()
    run = MatchRun.objects.create(
        relation=relation, tolerance=tolerance, date_from=date_from, date_to=date_to,
        created_by=user, batch=batch,
    )
    left, right = matcher.sides(date_from, date_to, toko)
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


def _aggregate_batch(toko, date_from, date_to, runs, skipped):
    tx = _date_filter(_toko_filter(Transaction.objects.filter(is_duplicate=False), toko), date_from, date_to)

    def total(qs, field):
        return float(qs.aggregate(x=Sum(field))["x"] or 0)

    panel = tx.filter(source_type__key="panel")
    # Baris fee BCA ('admin') dikecualikan dari uang WD (bukan WD nyata).
    money = tx.filter(source_type__key__in=MONEY_SOURCES).exclude(jenis="admin")
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


def run_batch(toko, tolerance=None, date_from=None, date_to=None, user=None):
    tolerance = tolerance or ToleranceProfile.objects.get(name="Default")
    comp = check_completeness(toko, date_from, date_to)
    batch = ReconBatch.objects.create(
        toko=toko, tolerance=tolerance, date_from=date_from, date_to=date_to,
        created_by=user, completeness=comp,
    )
    relations, skipped = [], []
    if comp["bracket"]:
        relations.append(MatchRun.Relation.PANEL_BRACKET)
    else:
        skipped.append(MatchRun.Relation.PANEL_BRACKET.value)
    if comp["bank"] or comp["gateway"]:
        relations.append(MatchRun.Relation.PANEL_BANK)
    else:
        skipped.append(MatchRun.Relation.PANEL_BANK.value)

    runs = [
        run_match(rel, tolerance, date_from, date_to, user=user, toko=toko, batch=batch)
        for rel in relations
    ]
    batch.summary = _aggregate_batch(toko, date_from, date_to, runs, skipped)
    batch.save(update_fields=["summary"])
    return batch
