from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from reconciliation.engine import MATCHERS, run_match
from reconciliation.models import MatchResult, MatchRun, ReviewAction, ToleranceProfile
from sources.management.commands.ingest import detect_flow
from sources.models import SourceType, Toko, Upload
from sources.services import PARSERS, ingest
from transactions.models import Transaction

BUCKET_META = {
    "cocok": {"label": "Cocok", "cls": "ok"},
    "perlu_tinjau": {"label": "Perlu Ditinjau", "cls": "warn"},
    "tidak_cocok": {"label": "Tidak Cocok", "cls": "bad"},
}


def _active_toko(request):
    tid = request.session.get("active_toko_id")
    t = Toko.objects.filter(id=tid, is_active=True).first() if tid else None
    return t or Toko.objects.filter(is_active=True).order_by("name").first()


@login_required
def set_toko(request):
    if request.method == "POST":
        tid = request.POST.get("toko_id")
        if tid and Toko.objects.filter(id=tid, is_active=True).exists():
            request.session["active_toko_id"] = int(tid)
    return redirect(request.POST.get("next") or "dashboard")


@login_required
def dashboard(request):
    by_source = list(
        Transaction.objects.values("source_type__name", "source_type__key")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    ctx = {
        "tx_total": Transaction.objects.count(),
        "upload_total": Upload.objects.count(),
        "run_total": MatchRun.objects.count(),
        "by_source": by_source,
        "uploads": Upload.objects.select_related("source_type").order_by("-id")[:8],
        "runs": MatchRun.objects.order_by("-id")[:8],
    }
    return render(request, "web/dashboard.html", ctx)


@login_required
def upload(request):
    if request.method == "POST":
        f = request.FILES.get("file")
        parser_key = request.POST.get("parser_key")
        flow = request.POST.get("flow") or (detect_flow(f.name) if f else "")
        if not f or parser_key not in PARSERS:
            messages.error(request, "Pilih file dan jenis parser yang valid.")
        else:
            try:
                saved = default_storage.save(f"uploads/{f.name}", f)
                up, created, dup = ingest(
                    parser_key, default_storage.path(saved), flow=flow, user=request.user
                )
                messages.success(
                    request, f"{f.name}: {created} transaksi dibuat, {dup} duplikat (Upload #{up.pk})."
                )
            except Exception as e:  # noqa: BLE001 - tampilkan error parse ke user
                messages.error(request, f"Gagal parse: {e}")
        return redirect("upload")
    return render(request, "web/upload.html", {"parsers": sorted(PARSERS.keys())})


@login_required
def transactions(request):
    qs = Transaction.objects.select_related("source_type").order_by("-occurred_at")
    src = request.GET.get("source", "")
    jenis = request.GET.get("jenis", "")
    q = request.GET.get("q", "").strip()
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
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    ctx = {
        "page": page,
        "sources": SourceType.objects.all(),
        "jenis_choices": Transaction.Jenis.choices,
        "src": src,
        "jenis": jenis,
        "q": q,
        "total": qs.count(),
    }
    return render(request, "web/transactions.html", ctx)


@login_required
def reconcile(request):
    if request.method == "POST":
        rel = request.POST.get("relation")
        if rel not in MATCHERS:
            messages.error(request, "Relasi tidak didukung.")
            return redirect("reconcile")
        tol = ToleranceProfile.objects.get(name=request.POST.get("tolerance", "Default"))
        run = run_match(
            rel,
            tol,
            request.POST.get("date_from") or None,
            request.POST.get("date_to") or None,
            user=request.user,
        )
        messages.success(request, f"Rekonsiliasi selesai (Run #{run.pk}).")
        return redirect("run_detail", pk=run.pk)
    ctx = {
        "relations": [(r.value, r.label) for r in MatchRun.Relation if r.value in MATCHERS],
        "tolerances": ToleranceProfile.objects.all(),
        "runs": MatchRun.objects.order_by("-id")[:20],
    }
    return render(request, "web/reconcile.html", ctx)


@login_required
def run_detail(request, pk):
    run = get_object_or_404(MatchRun, pk=pk)
    qs = MatchResult.objects.filter(run=run).select_related("left", "right").order_by("bucket", "-score")
    bucket = request.GET.get("bucket", "")
    if bucket:
        qs = qs.filter(bucket=bucket)
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    ctx = {"run": run, "page": page, "bucket": bucket, "bucket_meta": BUCKET_META}
    return render(request, "web/run_detail.html", ctx)


@login_required
def review(request, pk):
    r = get_object_or_404(MatchResult, pk=pk)
    action = request.POST.get("action", "")
    reason = request.POST.get("reason", "")
    if action == "mark_matched":
        r.bucket = MatchResult.Bucket.COCOK
    elif action == "mark_review":
        r.bucket = MatchResult.Bucket.TINJAU
    elif action == "mark_unmatched":
        r.bucket = MatchResult.Bucket.TIDAK
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

    run = get_object_or_404(MatchRun, pk=pk)
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
    headers = ["Bucket", "Panel Ticket", "Panel Amount", "Panel User", "Panel Waktu",
               "Kanan", "Kanan Sumber", "Kanan Amount", "Kanan Waktu", "Skor", "Alasan", "Detail"]
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
