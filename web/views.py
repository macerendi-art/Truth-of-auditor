from datetime import date as date_cls

from django.contrib import messages
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from reconciliation.engine import (
    MATCHERS,
    check_completeness,
    pending_settlement_count,
    run_batch,
    run_match,
)
from reconciliation.models import MatchResult, MatchRun, ReconBatch, ReviewAction, ToleranceProfile
from sources.detect import detect_source
from sources.management.commands.ingest import detect_flow
from sources.models import SourceType, Upload
from sources.services import PARSERS, ingest, is_encrypted_xlsx
from transactions.models import Transaction, specific_source_label
from web.access import tokos_for

BUCKET_META = {
    "cocok": {"label": "Cocok", "cls": "ok"},
    "perlu_tinjau": {"label": "Perlu Ditinjau", "cls": "warn"},
    "tidak_cocok": {"label": "Tidak Cocok", "cls": "bad"},
}

TX_EXPORT_LIMIT = 100_000

REL_LABELS = {
    MatchRun.Relation.PANEL_BRACKET.value: ("Panel", "Bracket"),
    MatchRun.Relation.PANEL_BANK.value: ("Panel", "Bank/Gateway"),
    MatchRun.Relation.BRACKET_BANK.value: ("Bracket", "Bank/Gateway"),
    MatchRun.Relation.SALDO.value: ("Kiri", "Kanan"),
}


def _apply_sort(request, qs, allowed, default_order, default_active=None):
    """Sort server-side ber-whitelist. `allowed`={ui_key: orm_field}.
    `default_order`=list field ORM saat sort tak valid. `default_active`=(ui_key,dir)
    untuk menandai kolom default aktif. Return (qs, sort_key, direction)."""
    sort = request.GET.get("sort", "")
    direction = request.GET.get("dir", "")
    if sort not in allowed:
        if default_active and default_active[0] in allowed:
            sort, direction = default_active
        else:
            return qs.order_by(*default_order), "", ""
    if direction not in ("asc", "desc"):
        direction = "asc"
    prefix = "" if direction == "asc" else "-"
    return qs.order_by(f"{prefix}{allowed[sort]}", "id"), sort, direction


def csrf_failure(request, reason=""):
    """Token CSRF basi (tab lama / setelah redeploy) — jangan 403 mentah.

    Logout: risiko CSRF-nya sepele (paling banter dipaksa keluar), jadi
    selesaikan saja logout-nya. Selain itu: halaman ramah + link masuk.
    """
    if request.path == reverse("logout"):
        auth_logout(request)
        return redirect("login")
    return render(request, "web/csrf_failure.html", status=403)


def _active_toko(request):
    allowed = tokos_for(request.user)
    tid = request.session.get("active_toko_id")
    t = allowed.filter(id=tid).first() if tid else None
    return t or allowed.first()


@login_required
def set_toko(request):
    if request.method == "POST":
        tid = request.POST.get("toko_id", "")
        if tid.isdecimal() and tokos_for(request.user).filter(id=tid).exists():
            request.session["active_toko_id"] = int(tid)
    nxt = request.POST.get("next")
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(nxt)
    return redirect("dashboard")


@login_required
def dashboard(request):
    """Kokpit harian auditor: status hari, kalender rekon, tren selisih,
    daftar kerja — bukan sekadar statistik."""
    from datetime import timedelta

    from reconciliation.engine import check_completeness, pending_settlement_count

    active = _active_toko(request)
    if active is None:
        return render(request, "web/no_toko.html")
    tx = Transaction.objects.filter(toko=active)
    uploads = Upload.objects.filter(toko=active)
    runs = MatchRun.objects.filter(batch__toko=active)
    by_source = list(
        tx.values("source_type__name", "source_type__key")
        .annotate(n=Count("id"))
        .order_by("-n")
    )

    batches = list(
        ReconBatch.objects.filter(toko=active, recon_date__isnull=False)
        .order_by("recon_date")
    )
    by_date = {b.recon_date: b for b in batches}
    total_b = ReconBatch.objects.filter(toko=active).count()

    def selisih(b):
        s = b.summary or {}
        dp = abs((s.get("dp") or {}).get("selisih") or 0)
        wd = abs((s.get("wd") or {}).get("selisih") or 0)
        return dp + wd

    # --- kalender 14 hari terakhir (anchor: recon terakhir atau hari ini) ---
    today = date_cls.today()
    anchor = max(batches[-1].recon_date, today) if batches else today
    kal = []
    for i in range(13, -1, -1):
        d = anchor - timedelta(days=i)
        b = by_date.get(d)
        if b is None:
            st = ""
        else:
            tot = selisih(b)
            st = "ok" if tot == 0 else ("warn" if tot < 10_000_000 else "bad")
        kal.append({
            "d": d, "batch": b, "st": st, "today": d == today,
            "no": (ReconBatch.objects.filter(toko=active, id__lte=b.id).count() if b else None),
        })

    # --- tren selisih 14 batch terakhir (bar SVG dihitung di sini) ---
    tren_src = batches[-14:]
    mx = max((selisih(b) for b in tren_src), default=0) or 1
    tren = []
    for b in tren_src:
        s = b.summary or {}
        dp = abs((s.get("dp") or {}).get("selisih") or 0)
        wd = abs((s.get("wd") or {}).get("selisih") or 0)
        tren.append({
            "b": b, "dp": dp, "wd": wd,
            "hdp": round(100 * dp / mx), "hwd": round(100 * wd / mx),
        })

    # --- kartu status ---
    last = batches[-1] if batches else None
    last_no = total_b if last else None
    last_sel = selisih(last) if last else 0
    pending = pending_settlement_count(active)
    um_d = {}
    if last is not None:
        um = (last.summary or {}).get("unmatched_money") or {}
        um_d = um.get("d") or {}

    comp = check_completeness(active)
    next_date = (last.recon_date + timedelta(days=1)) if last else today

    ctx = {
        "active_toko": active,
        "tx_total": tx.count(),
        "upload_total": uploads.count(),
        "run_total": runs.count(),
        "by_source": by_source,
        "uploads": uploads.select_related("source_type").order_by("-id")[:6],
        "runs": runs.select_related("batch").order_by("-id")[:6],
        "kal": kal,
        "tren": tren,
        "last": last, "last_no": last_no, "last_sel": last_sel,
        "pending": pending,
        "um_d": um_d,
        "comp": comp,
        "next_date": next_date,
    }
    return render(request, "web/dashboard.html", ctx)


@login_required
def upload(request):
    active = _active_toko(request)
    if active is None:
        return render(request, "web/no_toko.html")
    if request.method == "POST" and request.POST.get("action") == "commit":
        staged = request.POST.getlist("staged")
        keys = request.POST.getlist("parser_key")
        flows = request.POST.getlist("flow")
        passwords = request.POST.getlist("password")
        provider = request.POST.get("provider", "")
        n_ok = n_err = 0
        for i, (path_rel, key, flow) in enumerate(zip(staged, keys, flows)):
            if not path_rel.startswith("staging/") or ".." in path_rel:
                n_err += 1
                continue
            if key not in PARSERS:
                n_err += 1
                continue
            try:
                ingest(
                    key, default_storage.path(path_rel), flow=flow,
                    user=request.user, toko=active, provider=provider,
                    password=(passwords[i] if i < len(passwords) else ""),
                )
                n_ok += 1
            except Exception as e:  # noqa: BLE001 - tampilkan error parse ke user
                messages.error(request, f"{path_rel}: {e}")
                n_err += 1
            finally:
                if default_storage.exists(path_rel):
                    default_storage.delete(path_rel)
        messages.success(request, f"{n_ok} file diproses, {n_err} gagal.")
        return redirect("upload")
    if request.method == "POST" and request.POST.get("action") == "analyze":
        preview = []
        for f in request.FILES.getlist("files"):
            saved = default_storage.save(f"staging/{f.name}", f)
            needs_password = is_encrypted_xlsx(default_storage.path(saved))
            cands = detect_source(default_storage.path(saved), f.name)
            top = cands[0] if cands else None
            parser_key = top["parser_key"] if top else ""
            if not parser_key and needs_password:
                parser_key = "mandiri"
            preview.append({
                "name": f.name,
                "staged": saved,
                "parser_key": parser_key,
                "confidence": round(top["confidence"] * 100) if top else 0,
                "needs_confirm": (top is None) or top["confidence"] < 0.8,
                "needs_password": needs_password,
                "flow": detect_flow(f.name),
            })
        return render(request, "web/upload.html", {
            "preview": preview, "parsers": sorted(PARSERS.keys()),
            "flows": ["", "dp", "wd"], "active_toko": active,
            "uploads": Upload.objects.filter(toko=active).select_related("source_type").order_by("-id")[:20],
        })
    from reconciliation.engine import check_completeness

    return render(request, "web/upload.html", {
        "parsers": sorted(PARSERS.keys()), "active_toko": active,
        "uploads": Upload.objects.filter(toko=active).select_related("source_type").order_by("-id")[:20],
        "comp": check_completeness(active),
    })


@login_required
def transactions(request):
    active = _active_toko(request)
    if active is None:
        return render(request, "web/no_toko.html")
    qs = (
        Transaction.objects.filter(toko=active)
        .select_related("source_type", "account", "upload", "upload__account")
    )
    src = request.GET.get("source", "")
    jenis = request.GET.get("jenis", "")
    q = request.GET.get("q", "").strip()
    bank = request.GET.get("bank", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    if src:
        qs = qs.filter(source_type__key=src)
    if jenis:
        qs = qs.filter(jenis=jenis)
    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(ticket_no__icontains=q)
            | Q(reference__icontains=q)
            | Q(counterparty__icontains=q)
        )
    try:
        if date_from:
            qs = qs.filter(occurred_at__date__gte=date_cls.fromisoformat(date_from))
    except ValueError:
        date_from = ""
    try:
        if date_to:
            qs = qs.filter(occurred_at__date__lte=date_cls.fromisoformat(date_to))
    except ValueError:
        date_to = ""

    # Tombol filter per-bank: label diturunkan dari data upload toko ini
    # (account.provider / provider / nama file) — bukan daftar hardcode.
    bank_options = []
    if src in ("bank", "gateway"):
        ups = Upload.objects.filter(toko=active, source_type__key=src).select_related("account")
        label_by_upload = {
            u.id: specific_source_label(src, account=u.account, upload=u) for u in ups
        }
        fallback = src.capitalize()
        bank_options = sorted({lbl for lbl in label_by_upload.values() if lbl and lbl != fallback})
        if bank:
            qs = qs.filter(
                upload_id__in=[uid for uid, lbl in label_by_upload.items() if lbl == bank]
            )
    else:
        bank = ""

    qs, sort, sort_dir = _apply_sort(
        request, qs,
        allowed={
            "waktu": "occurred_at", "amount": "amount", "delta": "money_delta",
            "sumber": "source_type__key", "jenis": "jenis",
        },
        default_order=["-occurred_at", "id"],
        default_active=("waktu", "desc"),
    )

    if request.GET.get("export"):
        n = qs.count()
        if n > TX_EXPORT_LIMIT:
            messages.error(
                request,
                f"{n:,} baris terlalu banyak untuk diekspor — persempit filter dulu "
                f"(maks {TX_EXPORT_LIMIT:,}).",
            )
            # buang param export agar redirect tidak memicu export lagi (loop)
            redir = request.GET.copy()
            redir.pop("export", None)
            return redirect(f"{reverse('transactions')}?{redir.urlencode()}")
        return _export_transactions(qs, active)

    params = request.GET.copy()
    for k in ("sort", "dir", "page"):
        params.pop(k, None)
    qbase = params.urlencode()
    params_page = request.GET.copy()
    params_page.pop("page", None)
    qpage = params_page.urlencode()

    page = Paginator(qs, 40).get_page(request.GET.get("page"))

    # Ticket/Username/Nama Lengkap sisi uang: ambil dari pasangan panel/bracket
    # hasil rekonsiliasi — hanya untuk baris halaman ini (tanpa join tabel penuh).
    txs = list(page.object_list)
    page.object_list = txs
    money_ids = [t.id for t in txs if t.source_type.key in ("bank", "gateway")]
    best = {}
    if money_ids:
        results = (
            MatchResult.objects.filter(right_id__in=money_ids, left__isnull=False)
            .exclude(bucket=MatchResult.Bucket.TIDAK)
            .select_related("left")
        )
        for r in results:
            # cocok > skor tertinggi > run terbaru
            rank = (r.bucket == MatchResult.Bucket.COCOK, r.score or 0, r.run_id, r.id)
            if r.right_id not in best or rank > best[r.right_id][0]:
                best[r.right_id] = (rank, r.left)
    for t in txs:
        t.is_money = t.source_type.key in ("bank", "gateway")
        t.matched_panel = best.get(t.id, (None, None))[1]

    ctx = {
        "page": page,
        "sources": SourceType.objects.all(),
        "jenis_choices": Transaction.Jenis.choices,
        "src": src,
        "jenis": jenis,
        "q": q,
        "bank": bank,
        "bank_options": bank_options,
        "total": page.paginator.count,
        "date_from": date_from, "date_to": date_to,
        "sort": sort, "dir": sort_dir,
        "qbase": qbase, "qpage": qpage,
    }
    return render(request, "web/transactions.html", ctx)


def _export_transactions(qs, active):
    import io
    from datetime import datetime as _dt

    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font

    rows = list(qs)
    money_ids = [t.id for t in rows if t.source_type.key in ("bank", "gateway")]
    best = {}
    if money_ids:
        results = (
            MatchResult.objects.filter(right_id__in=money_ids, left__isnull=False)
            .exclude(bucket=MatchResult.Bucket.TIDAK)
            .select_related("left")
        )
        for r in results:
            rank = (r.bucket == MatchResult.Bucket.COCOK, r.score or 0, r.run_id, r.id)
            if r.right_id not in best or rank > best[r.right_id][0]:
                best[r.right_id] = (rank, r.left)

    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Transaksi")
    bold = Font(bold=True)

    def hcell(v):
        c = WriteOnlyCell(ws, value=v)
        c.font = bold
        return c

    ws.append([hcell(h) for h in [
        "Waktu", "Sumber", "Jenis", "Amount", "Δ Uang", "Ticket",
        "Username", "Nama Lengkap", "Counterparty",
    ]])
    for t in rows:
        mp = best.get(t.id, (None, None))[1]
        is_money = t.source_type.key in ("bank", "gateway")
        ticket = t.ticket_no or (f"≈ {mp.ticket_no}" if mp and mp.ticket_no else "")
        username = t.username or (f"≈ {mp.username}" if mp and mp.username else "")
        if is_money:
            nama = f"≈ {mp.counterparty}" if mp and mp.counterparty else ""
        else:
            nama = t.counterparty or ""
        ws.append([
            t.occurred_at.strftime("%d/%m/%Y %H:%M") if t.occurred_at else "",
            t.source_label,
            t.get_jenis_display(),
            float(t.amount),
            float(t.money_delta),
            ticket, username, nama, t.counterparty or "",
        ])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    fname = f"transaksi_{active.name}_{_dt.now():%Y%m%d-%H%M}.xlsx"
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp


@login_required
def reconcile(request):
    active = _active_toko(request)
    if active is None:
        return render(request, "web/no_toko.html")
    if request.method == "POST":
        tol = get_object_or_404(ToleranceProfile, name=request.POST.get("tolerance", "Default"))
        # Rekonsiliasi harian: satu run = satu tanggal. Tanggal wajib diisi.
        try:
            recon_date = date_cls.fromisoformat((request.POST.get("recon_date") or "").strip())
        except ValueError:
            recon_date = None
        if recon_date is None:
            messages.error(request, "Tanggal rekonsiliasi wajib diisi.")
            return redirect("reconcile")
        existing = ReconBatch.objects.filter(toko=active, recon_date=recon_date).first()
        if existing:
            no = ReconBatch.objects.filter(toko=active, id__lte=existing.id).count()
            messages.error(request, format_html(
                'Rekonsiliasi {} tanggal {} sudah ada: <a href="{}">Batch #{}</a>. '
                "Hapus batch itu dulu (tombol Hapus Laporan) bila ingin mengulang tanggal ini.",
                active.name, recon_date.strftime("%d/%m/%Y"),
                reverse("batch_detail", args=[existing.pk]), no,
            ))
            return redirect("reconcile")
        # Checkbox inc_* per baris kelengkapan = sumber yang DIIKUTKAN. Tidak ada
        # → tidak dicentang → tidak dicocokkan & tidak dikonsumsi.
        include = {
            "panel_dp": "inc_panel_dp" in request.POST,
            "panel_wd": "inc_panel_wd" in request.POST,
            "bracket": "inc_bracket" in request.POST,
            "bank": "inc_bank" in request.POST,
            "gateway": "inc_gateway" in request.POST,
        }
        try:
            batch = run_batch(
                active, tol,
                request.POST.get("date_from") or None,
                request.POST.get("date_to") or None,
                user=request.user,
                include=include,
                recon_date=recon_date,
            )
        except ValueError as e:  # backstop guard engine (race dua tab)
            messages.error(request, str(e))
            return redirect("reconcile")
        no = ReconBatch.objects.filter(toko=active).count()
        messages.success(request, f"Rekonsiliasi selesai (Batch #{no}).")
        return redirect("batch_detail", pk=batch.pk)

    df = request.GET.get("date_from") or None
    dt = request.GET.get("date_to") or None
    bank = request.GET.get("bank", "")
    if bank not in ("bank", "gateway"):
        bank = ""  # nilai tak dikenal → perlakukan sebagai "semua sumber"
    # Nomor dihitung dari SEMUA batch toko dulu (posisi asli), BARU difilter —
    # supaya nomor batch tidak berubah saat filter sumber uang aktif.
    all_batches = list(ReconBatch.objects.filter(toko=active).order_by("-id"))
    total = len(all_batches)
    for i, b in enumerate(all_batches):
        b.no = total - i
    if bank:
        all_batches = [b for b in all_batches if (b.completeness or {}).get(bank)]
    batches = all_batches[:20]
    comp = check_completeness(active, df, dt)
    comp_keys = ["panel_dp", "panel_wd", "bracket", "bank", "gateway"]
    comp_ready = sum(1 for k in comp_keys if comp.get(k))
    ctx = {
        "active_toko": active,
        "completeness": comp,
        "comp_ready": comp_ready,
        "comp_total": len(comp_keys),
        "comp_pct": round(100 * comp_ready / len(comp_keys)),
        "tolerances": ToleranceProfile.objects.all(),
        "batches": batches,
        "bank": bank,
        "date_from": df or "", "date_to": dt or "",
        "recon_date": date_cls.today().isoformat(),
        "pending_settlement": pending_settlement_count(active),
    }
    return render(request, "web/reconcile.html", ctx)


@login_required
def batch_detail(request, pk):
    batch = get_object_or_404(ReconBatch, pk=pk, toko__in=tokos_for(request.user))
    batch_no = ReconBatch.objects.filter(toko=batch.toko, id__lte=batch.id).count()
    # Settle terlambat dua arah — dari queryset LIVE (bukan summary JSON) supaya
    # otomatis kosong bila batch pasangannya sudah dihapus.
    resolved_here = list(
        MatchResult.objects.filter(resolved_by_batch=batch)
        .select_related("left", "right", "run__batch")
    )
    for r in resolved_here:  # nomor batch asal (konvensi nomor per-toko)
        r.home_no = ReconBatch.objects.filter(
            toko=batch.toko, id__lte=r.run.batch_id
        ).count()
    settled_elsewhere = list(
        MatchResult.objects.filter(run__batch=batch, resolved_by_batch__isnull=False)
        .select_related("resolved_by_batch", "left", "right")
    )
    return render(request, "web/batch_detail.html", {
        "batch": batch, "batch_no": batch_no, "s": batch.summary or {}, "runs": batch.runs.all(),
        "resolved_here": resolved_here, "settled_elsewhere": settled_elsewhere,
    })


KATEGORI_UANG = {
    "a": ("Histori", "di luar periode rekonsiliasi"),
    "b": ("Ticket asing", "ticket gateway tak dikenal panel"),
    "c": ("Internal", "pindah dana antar rekening operator"),
    "d": ("Periksa", "dalam periode tanpa catatan panel"),
}


@login_required
def batch_uang(request, pk):
    """Uang tanpa pasangan milik satu batch — daftar live berkategori a/b/c/d.
    Baris b/d juga punya MatchResult no_panel (bisa ditinjau di halaman run);
    halaman ini adalah ikhtisar + filter + export."""
    from django.db.models import Exists, OuterRef

    from reconciliation.engine import _operator_names, classify_unmatched_money

    batch = get_object_or_404(ReconBatch, pk=pk, toko__in=tokos_for(request.user))
    batch_no = ReconBatch.objects.filter(toko=batch.toko, id__lte=batch.id).count()
    paired = MatchResult.objects.filter(left__isnull=False, right_id=OuterRef("id"))
    rows = list(
        Transaction.objects.filter(
            consumed_by_batch=batch, source_type__key__in=["bank", "gateway"]
        )
        .exclude(jenis="admin")
        .annotate(berpasangan=Exists(paired))
        .filter(berpasangan=False)
        .select_related("source_type", "upload")
        .order_by("occurred_at", "id")
    )
    recon_date = batch.recon_date
    window = batch.tolerance.date_window_days
    if recon_date:
        panel_tickets = set(
            Transaction.objects.filter(toko=batch.toko, source_type__key="panel")
            .exclude(ticket_no="").values_list("ticket_no", flat=True)
        )
        ops = _operator_names(batch.toko)
        for t in rows:
            t.kategori = classify_unmatched_money(t, recon_date, window, panel_tickets, ops)
    else:  # batch lama tanpa tanggal harian — tak bisa diklasifikasi
        for t in rows:
            t.kategori = "d"
    stats = {k: {"n": 0, "amt": 0.0} for k in KATEGORI_UANG}
    for t in rows:
        stats[t.kategori]["n"] += 1
        stats[t.kategori]["amt"] += abs(float(t.money_delta))
    kat = request.GET.get("k", "")
    if kat in KATEGORI_UANG:
        rows = [t for t in rows if t.kategori == kat]

    if request.GET.get("export"):
        import io

        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook()
        ws = wb.active
        ws.title = "Uang tanpa pasangan"
        ws.append(["Kategori", "Tanggal", "Sumber", "File/Rekening", "Ticket",
                   "Username", "Pengirim/Penerima", "Nominal"])
        for c in ws[1]:
            c.font = Font(bold=True)
        for t in rows:
            ws.append([
                t.kategori.upper(),
                t.occurred_at.strftime("%d/%m/%Y %H:%M") if t.occurred_at else "",
                t.source_type.key,
                t.upload.original_name if t.upload else "",
                t.ticket_no, t.username, t.counterparty,
                float(t.money_delta),
            ])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        resp = HttpResponse(
            buf.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = (
            f'attachment; filename="uang_tanpa_pasangan_batch{batch.pk}.xlsx"'
        )
        return resp

    page = Paginator(rows, 40).get_page(request.GET.get("page"))
    kartu = [
        {"key": k, "label": KATEGORI_UANG[k][0], "desc": KATEGORI_UANG[k][1],
         "n": stats[k]["n"], "amt": stats[k]["amt"]}
        for k in KATEGORI_UANG
    ]
    return render(request, "web/batch_uang.html", {
        "batch": batch, "batch_no": batch_no, "page": page,
        "kartu": kartu, "kat": kat,
    })


@login_required
def run_detail(request, pk):
    run = get_object_or_404(MatchRun, pk=pk, batch__toko__in=tokos_for(request.user))
    qs = MatchResult.objects.filter(run=run).select_related("left", "right").order_by("bucket", "-score")
    bucket = request.GET.get("bucket", "")
    if bucket:
        qs = qs.filter(bucket=bucket)
    # Chip filter per alasan — dihitung DALAM bucket terpilih supaya angkanya jujur.
    reasons = list(
        qs.values("reason_code").annotate(n=Count("id")).order_by("-n")
    )
    reason = request.GET.get("reason", "")
    if reason:
        qs = qs.filter(reason_code=reason)
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    left_label, right_label = REL_LABELS.get(run.relation, ("Kiri", "Kanan"))
    # Nomor batch per-toko (posisi urut, bukan pk global) — konsisten dgn batch_detail.
    batch = run.batch
    batch_no = (
        ReconBatch.objects.filter(toko=batch.toko, id__lte=batch.id).count() if batch else None
    )
    ctx = {
        "run": run, "page": page, "bucket": bucket, "bucket_meta": BUCKET_META,
        "left_label": left_label, "right_label": right_label,
        "batch": batch, "batch_no": batch_no,
        "reasons": reasons, "reason": reason,
    }
    return render(request, "web/run_detail.html", ctx)


@login_required
@require_POST
def bulk_review(request, pk):
    """Setujui / tandai-tinjau banyak hasil sekaligus (per halaman terfilter).
    Setiap baris tetap tercatat ReviewAction-nya sendiri — jejak audit utuh."""
    run = get_object_or_404(MatchRun, pk=pk, batch__toko__in=tokos_for(request.user))
    action = request.POST.get("action", "")
    buckets = {"mark_matched": MatchResult.Bucket.COCOK,
               "mark_review": MatchResult.Bucket.TINJAU}
    if action not in buckets:
        return HttpResponseBadRequest("Aksi tidak dikenal.")
    ids = [i for i in request.POST.getlist("result_ids") if i.isdigit()]
    rows = list(MatchResult.objects.filter(run=run, id__in=ids))
    for r in rows:
        r.bucket = buckets[action]
        r.reason_code = "manual_override"
        r.save(update_fields=["bucket", "reason_code"])
        ReviewAction.objects.create(
            result=r, action=action, reason="bulk", reviewer=request.user
        )
    messages.success(request, f"{len(rows)} hasil diperbarui.")
    nxt = request.POST.get("next") or reverse("run_detail", args=[run.pk])
    if not url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        nxt = reverse("run_detail", args=[run.pk])
    return redirect(nxt)


@login_required
@require_POST
def review(request, pk):
    r = get_object_or_404(MatchResult, pk=pk, run__batch__toko__in=tokos_for(request.user))
    action = request.POST.get("action", "")
    reason = request.POST.get("reason", "")
    buckets = {
        "mark_matched": MatchResult.Bucket.COCOK,
        "mark_review": MatchResult.Bucket.TINJAU,
        "mark_unmatched": MatchResult.Bucket.TIDAK,
    }
    if action not in buckets:
        return HttpResponseBadRequest("Aksi tidak dikenal.")
    # Catatan: override pada hasil no_money yang barisnya masih AKTIF (menunggu
    # settlement) mengeluarkannya dari carry-over — baris itu akan diperlakukan
    # sebagai baris baru di run berikutnya. Follow-up kecil bila jadi masalah:
    # konsumsi baris ke batch asalnya saat di-override.
    r.bucket = buckets[action]
    r.reason_code = "manual_override"
    r.save(update_fields=["bucket", "reason_code"])
    ReviewAction.objects.create(result=r, action=action, reason=reason, reviewer=request.user)
    return render(request, "web/_result_row.html", {"r": r, "bucket_meta": BUCKET_META})


@login_required
def export_run(request, pk):
    import io

    from django.http import HttpResponse
    from openpyxl import Workbook
    from openpyxl.styles import Font

    run = get_object_or_404(MatchRun, pk=pk, batch__toko__in=tokos_for(request.user))
    wb = Workbook()
    ws = wb.active
    ws.title = "Ringkasan"
    s = run.summary or {}
    for label, val in [
        ("Rekonsiliasi", run.get_relation_display()),
        ("Run", f"#{run.pk}"),
        ("Toleransi", f"{run.tolerance.name} (±{run.tolerance.date_window_days} hari)"),
        ("Tanggal", run.created_at.strftime("%d/%m/%Y %H:%M")),
        ("", ""),
        ("Cocok", s.get("cocok", 0)),
        ("Perlu Ditinjau", s.get("perlu_tinjau", 0)),
        ("Tidak Cocok", s.get("tidak_cocok", 0)),
    ]:
        ws.append([label, val])
    for row in ws["A"]:
        row.font = Font(bold=True)

    d = wb.create_sheet("Hasil")
    L, R = REL_LABELS.get(run.relation, ("Kiri", "Kanan"))
    headers = ["Bucket", f"{L} Ticket", f"{L} Amount", f"{L} User", f"{L} Nama Lengkap",
               f"{L} Player Bank", f"{L} Bank Title", f"{L} Handler", f"{L} Waktu",
               R, f"{R} Sumber", f"{R} Amount", f"{R} Waktu", "Skor", "Alasan", "Detail"]
    d.append(headers)
    for c in d[1]:
        c.font = Font(bold=True)
    qs = run.results.select_related("left", "right", "left__source_type", "right__source_type")
    for r in qs.iterator():
        left, right = r.left, r.right
        d.append([
            r.get_bucket_display(),
            left.ticket_no if left else "",
            float(left.amount) if left else "",
            left.username if left else "",
            left.counterparty if left else "",
            (left.raw or {}).get("Player Bank", "") if left else "",
            (left.raw or {}).get("Bank Title", "") if left else "",
            (left.raw or {}).get("Handler", "") if left else "",
            left.occurred_at.strftime("%d/%m %H:%M") if left and left.occurred_at else "",
            (right.ticket_no or right.counterparty) if right else "",
            right.source_type.key if right else "",
            float(right.amount) if right else "",
            right.occurred_at.strftime("%d/%m %H:%M") if right and right.occurred_at else "",
            round(r.score or 0),
            r.reason_code,
            r.reason_detail,
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="rekonsiliasi_run{run.pk}.xlsx"'
    return resp
