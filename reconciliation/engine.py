"""Engine pencocokan (rule-based & tunable).

Tiap relasi punya Matcher sendiri (pluggable lewat MATCHERS). Hasil = MatchResult
dengan bucket cocok / tidak_cocok / perlu_tinjau + reason. Toleransi dari ToleranceProfile.
"""
from collections import Counter
from datetime import timedelta

from django.db import transaction as db_tx
from django.db.models import Q, Sum
from rapidfuzz import fuzz

from sources.parsers.base import clean_name
from transactions.models import Transaction

from .models import MatchResult, MatchRun, ReconBatch, ToleranceProfile

MONEY_SOURCES = ["bank", "gateway"]

# Detail baku hasil no_money — juga dipakai untuk MENGEMBALIKAN hasil yang
# di-flip late settlement, jadi string ini harus tetap satu sumber kebenaran.
NO_MONEY_DETAIL = "Tak ada padanan nominal+tanggal di Bank/Gateway"


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
    """Join via Ticket Number (kuat). Cek kecocokan nominal."""

    def sides(self, dfrom, dto, toko=None, include=None):
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
                                       reason_detail=NO_MONEY_DETAIL))
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
    run.summary = {
        "left": len(left) - n_excluded_left, "right": len(right),
        "cocok": c.get("cocok", 0),
        "perlu_tinjau": c.get("perlu_tinjau", 0),
        "tidak_cocok": c.get("tidak_cocok", 0),
    }
    if carried:
        run.summary["late_settled"] = len(late_pairs)
    if retro:
        run.summary["susulan"] = len(retro_results)
    run.save(update_fields=["summary"])
    run.late_pairs = late_pairs
    run.retro_results = retro_results
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


def _carried_results(toko):
    """left_id → MatchResult no_money LAMA (dari batch lain) milik baris kredit yang
    masih AKTIF — carry-over "menunggu settlement" dari run harian sebelumnya.
    Hanya relasi UANG (no_money); hasil no_bracket PANEL_BRACKET tidak ikut.
    Run CLI tanpa batch diabaikan (tak ada batch asal untuk konsumsi/flip)."""
    qs = (
        MatchResult.objects.filter(
            bucket=MatchResult.Bucket.TIDAK, reason_code="no_money",
            left__isnull=False, left__toko=toko,
            left__consumed_by_batch__isnull=True,
            run__batch__isnull=False,
            run__relation__in=[MatchRun.Relation.PANEL_BANK, MatchRun.Relation.BRACKET_BANK],
        )
        .select_related("left", "run", "run__batch")
        .order_by("id")
    )
    return {r.left_id: r for r in qs}  # id terbesar menang (defensif bila ganda)


def pending_settlement_count(toko):
    """Jumlah baris kredit yang masih AKTIF menunggu settlement (untuk info UI)."""
    return len(_carried_results(toko))


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
    (cocok / perlu_tinjau weak_name), right diisi baris uang, reason asal disimpan
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

    carried = _carried_results(toko) if recon_date else {}
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
        _consume_scope(toko, date_from, date_to, include)\
            .exclude(id__in=still_waiting).update(consumed_by_batch=batch)
    else:
        _consume_scope(toko, date_from, date_to, include).update(consumed_by_batch=batch)
    batch.summary = summary
    batch.save(update_fields=["summary"])
    return batch
