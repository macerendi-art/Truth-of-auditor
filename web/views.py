import os
import zipfile
from datetime import date as date_cls

from django.contrib import messages
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db.models import BooleanField, Count, Exists, ExpressionWrapper, OuterRef, Q, Sum
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from reconciliation.engine import (
    MATCHERS,
    _panel_dates,
    check_completeness,
    pending_settlement_count,
    run_batch,
    run_batches_auto,
    run_match,
)
from core.audit import catat
from core.models import AuditLog
from reconciliation.models import MatchResult, MatchRun, ReconBatch, ReviewAction, ToleranceProfile
from sources.detect import detect_source
from sources.management.commands.ingest import detect_flow
from sources.models import SourceType, Upload
from sources.services import PARSERS, ingest, is_encrypted_xlsx
from transactions.models import Transaction, specific_source_label
from web.access import tokos_for
from web.templatetags.web_extras import reason_label

BUCKET_META = {
    "cocok": {"label": "Cocok", "cls": "ok"},
    "perlu_tinjau": {"label": "Perlu Ditinjau", "cls": "warn"},
    "tidak_cocok": {"label": "Tidak Cocok", "cls": "bad"},
}

TX_EXPORT_LIMIT = 100_000

REL_LABELS = {
    MatchRun.Relation.PANEL_BRACKET.value: ("Panel", "Bracket"),
    MatchRun.Relation.PANEL_BANK.value: ("Panel", "Mutasi Bank"),
    MatchRun.Relation.BRACKET_BANK.value: ("Bracket", "Mutasi Bank"),
    MatchRun.Relation.SALDO.value: ("Kiri", "Kanan"),
}

# Label kolom nominal per relasi: kiri selalu kredit; kanan = Saldo Bank utk relasi
# uang, tetap Kredit/Koin utk panel<->bracket.
REL_AMOUNT_LABELS = {
    MatchRun.Relation.PANEL_BRACKET.value: ("Kredit/Koin", "Kredit/Koin"),
    MatchRun.Relation.PANEL_BANK.value: ("Kredit/Koin", "Saldo Bank"),
    MatchRun.Relation.BRACKET_BANK.value: ("Kredit/Koin", "Saldo Bank"),
    MatchRun.Relation.SALDO.value: ("Nominal", "Nominal"),
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

    # --- tren selisih 30 hari kalender terakhir (bar DP/WD + garis total) ---
    tren_cutoff = anchor - timedelta(days=29)
    tren_src = [b for b in batches if b.recon_date and b.recon_date >= tren_cutoff]
    mx = max((selisih(b) for b in tren_src), default=0) or 1
    tren = []
    for b in tren_src:
        s = b.summary or {}
        dp = abs((s.get("dp") or {}).get("selisih") or 0)
        wd = abs((s.get("wd") or {}).get("selisih") or 0)
        tren.append({
            "b": b, "dp": dp, "wd": wd,
            "hdp": round(100 * dp / mx), "hwd": round(100 * wd / mx),
            "tot": dp + wd, "htot": round(100 * (dp + wd) / mx),
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


# Upload folder/zip: hanya ekstensi yang punya parser; sisanya junk OS/temp.
_UPLOAD_EXTS = {".xlsx", ".xls", ".csv", ".pdf"}
_ZIP_MAX_FILES = 200
_ZIP_MAX_BYTES = 200 * 1024 * 1024
# Cap ukuran: per-file dan total satu request analyze — volume staging jangan
# bisa dipenuhi satu upload liar (export mutasi riil terbesar masih < 20MB).
_FILE_MAX_BYTES = 50 * 1024 * 1024
_REQ_MAX_BYTES = 300 * 1024 * 1024


def _is_junk_name(name):
    """File yang tak layak dianalisis: dotfile/.DS_Store, lock Office (~$),
    artefak __MACOSX, atau ekstensi tanpa parser. Berlaku untuk upload langsung,
    isi folder (webkitdirectory), dan isi zip."""
    path = str(name).replace("\\", "/")
    if "__MACOSX" in path:
        return True
    base = os.path.basename(path)
    if not base or base.startswith(".") or base.startswith("~$"):
        return True
    return os.path.splitext(base)[1].lower() not in _UPLOAD_EXTS


def _extract_zip(f):
    """Ekstrak arsip zip upload → (list[(nama, bytes)], n_dilewati, error|None).
    Guard: jumlah file & total ukuran terkompresi-buka (anti zip-bomb); zip
    berpassword/rusak → error berpesan jelas. xlsx TIDAK lewat sini (dicek
    berdasarkan ekstensi .zip, bukan magic PK — xlsx juga arsip zip)."""
    try:
        zf = zipfile.ZipFile(f)
    except zipfile.BadZipFile:
        return [], 0, "bukan file zip yang valid"
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > _ZIP_MAX_FILES:
        return [], 0, f"terlalu banyak file di dalam zip (>{_ZIP_MAX_FILES})"
    if sum(i.file_size for i in infos) > _ZIP_MAX_BYTES:
        return [], 0, "isi zip terlalu besar (>200MB)"
    out, dilewati = [], 0
    for i in infos:
        if _is_junk_name(i.filename):
            dilewati += 1
            continue
        try:
            data = zf.read(i)
        except RuntimeError:
            return [], 0, "zip berpassword tidak didukung — ekstrak dulu lalu upload isinya"
        out.append((os.path.basename(i.filename.replace("\\", "/")), data))
    return out, dilewati, None


# File staging lebih tua dari ini = yatim (analyze tanpa commit) → disapu.
_STAGING_TTL = 24 * 3600


def _sweep_staging():
    """Bersihkan file staging yatim. Dipanggil tiap analyze — murah (satu
    listdir), dan berjalan tepat saat volume dipakai lagi."""
    import time

    try:
        _dirs, files = default_storage.listdir("staging")
    except FileNotFoundError:
        return
    batas = time.time() - _STAGING_TTL
    for nama in files:
        rel = f"staging/{nama}"
        try:
            if os.path.getmtime(default_storage.path(rel)) < batas:
                default_storage.delete(rel)
        except OSError:
            continue


def _analyze_file(name, fileobj):
    """Satu file → baris preview (simpan ke staging + deteksi parser).
    Dipakai upload langsung maupun hasil ekstrak zip."""
    saved = default_storage.save(f"staging/{name}", fileobj)
    needs_password = is_encrypted_xlsx(default_storage.path(saved))
    cands = detect_source(default_storage.path(saved), name)
    top = cands[0] if cands else None
    parser_key = top["parser_key"] if top else ""
    if not parser_key and needs_password:
        parser_key = "mandiri"
    return {
        "name": name,
        "staged": saved,
        "parser_key": parser_key,
        "confidence": round(top["confidence"] * 100) if top else 0,
        "needs_confirm": (top is None) or top["confidence"] < 0.8,
        "needs_password": needs_password,
        "flow": detect_flow(name),
    }


def _uploads_for(toko, limit=20):
    """Riwayat upload toko, dianotasi `locked` (buktinya dipakai hasil rekon:
    direferensi MatchResult left/right ATAU dikonsumsi batch). Tombol Hapus
    per-baris dinonaktifkan; server (`_locking_batches`) tetap penjaga terakhir."""
    ref = MatchResult.objects.filter(
        Q(left__upload=OuterRef("pk")) | Q(right__upload=OuterRef("pk"))
    )
    consumed = Transaction.objects.filter(
        upload=OuterRef("pk"), consumed_by_batch__isnull=False
    )
    return (
        Upload.objects.filter(toko=toko)
        .select_related("source_type")
        .annotate(locked=ExpressionWrapper(
            Exists(ref) | Exists(consumed), output_field=BooleanField(),
        ))
        .order_by("-id")[:limit]
    )


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
        _sweep_staging()
        uploaded = request.FILES.getlist("files")
        if sum(f.size for f in uploaded) > _REQ_MAX_BYTES:
            messages.error(request, "Total upload melebihi 300MB — pecah jadi beberapa kali.")
            uploaded = []
        preview, dilewati, diekstrak = [], 0, 0
        for f in uploaded:
            if f.size > _FILE_MAX_BYTES:
                messages.error(request, f"{f.name}: melebihi 50MB per file, dilewati.")
                dilewati += 1
                continue
            if f.name.lower().endswith(".zip"):
                isi, n_lewat, err = _extract_zip(f)
                if err:
                    messages.error(request, f"{f.name}: {err}")
                    continue
                dilewati += n_lewat
                for nama, data in isi:
                    preview.append(_analyze_file(nama, ContentFile(data)))
                    diekstrak += 1
                continue
            if _is_junk_name(f.name):
                dilewati += 1
                continue
            preview.append(_analyze_file(f.name, f))
        if dilewati or diekstrak:
            messages.info(
                request,
                f"{len(preview)} file dianalisa, {dilewati} dilewati"
                + (f", {diekstrak} diekstrak dari zip" if diekstrak else "")
                + ".",
            )
        return render(request, "web/upload.html", {
            "preview": preview, "parsers": sorted(PARSERS.keys()),
            "flows": ["", "dp", "wd"], "active_toko": active,
            "uploads": _uploads_for(active),
        })
    from reconciliation.engine import check_completeness

    return render(request, "web/upload.html", {
        "parsers": sorted(PARSERS.keys()), "active_toko": active,
        "uploads": _uploads_for(active),
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
        cond = (
            Q(username__icontains=q)
            | Q(ticket_no__icontains=q)
            | Q(reference__icontains=q)
            | Q(counterparty__icontains=q)
        )
        # Angka (boleh berformat "50.000" / "50,000") → cari juga nominal persis.
        digits = q.replace(".", "").replace(",", "")
        if digits.isdigit():
            cond |= Q(amount=digits)
        qs = qs.filter(cond)
    carry = request.GET.get("carry") == "1"
    if carry:
        from reconciliation.engine import _carried_results

        qs = qs.filter(id__in=list(_carried_results(active).keys()))
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
    # Basis untuk tombol cepat Deposit/Withdraw: pertahankan filter lain,
    # tapi buang jenis/sort/dir/page agar tombol yang mengatur jenis.
    params_flt = request.GET.copy()
    for k in ("jenis", "sort", "dir", "page"):
        params_flt.pop(k, None)
    qflt = params_flt.urlencode()

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
        "qbase": qbase, "qpage": qpage, "qflt": qflt,
        "carry": carry,
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
        "Waktu", "Sumber", "Jenis", "Nominal", "Δ Uang", "Ticket",
        "Username", "Nama Lengkap", "Nama di Bank",
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
        # Checkbox inc_* per baris kelengkapan = sumber yang DIIKUTKAN. Tidak ada
        # → tidak dicentang → tidak dicocokkan & tidak dikonsumsi.
        include = {
            "panel_dp": "inc_panel_dp" in request.POST,
            "panel_wd": "inc_panel_wd" in request.POST,
            "bracket": "inc_bracket" in request.POST,
            "bank": "inc_bank" in request.POST,
            "gateway": "inc_gateway" in request.POST,
        }
        # Auto-split: satu batch per tanggal-panel. Panel jadi jangkar; run ditolak
        # bila ada uang/bracket tanpa panel penutup dalam window (verify_panel_anchor).
        res = run_batches_auto(
            active, tol,
            request.POST.get("date_from") or None,
            request.POST.get("date_to") or None,
            user=request.user, include=include,
        )
        if not res["ok"]:
            rows = format_html_join(
                "", "<br>&bull; {} — {} ({} baris)",
                ((v["date"].strftime("%d/%m/%Y"), v["source"], v["n"]) for v in res["violations"]),
            )
            messages.error(request, format_html(
                "Rekonsiliasi ditolak: ada tanggal ber-uang/bracket tanpa panel penutup. "
                "Upload panel tanggal terkait dulu, lalu jalankan lagi:{}", rows,
            ))
            return redirect("reconcile")
        for er in res["errors"]:
            messages.error(request, f"{er['date'].strftime('%d/%m/%Y')}: {er['message']}")
        batches, skipped = res["batches"], res["skipped_existing"]
        for b in batches:
            no = ReconBatch.objects.filter(toko=active, id__lte=b.id).count()
            catat(request.user, "reconcile", f"Batch #{no}", toko=active, batch_pk=b.pk)
        if len(batches) == 1 and not skipped:
            no = ReconBatch.objects.filter(toko=active).count()
            messages.success(request, f"Rekonsiliasi selesai (Batch #{no}).")
            return redirect("batch_detail", pk=batches[0].pk)
        if batches:
            rentang = (
                f"{batches[0].recon_date.strftime('%d/%m')}–"
                f"{batches[-1].recon_date.strftime('%d/%m/%Y')}"
                if len(batches) > 1 else batches[0].recon_date.strftime("%d/%m/%Y")
            )
            msg = f"{len(batches)} batch dibuat ({rentang})."
            if skipped:
                msg += f" {len(skipped)} tanggal dilewati (sudah ada batch)."
            messages.success(request, msg)
        elif skipped:
            messages.info(
                request,
                f"Semua {len(skipped)} tanggal sudah punya batch — tak ada yang baru dibuat.",
            )
        else:
            messages.info(request, "Tidak ada tanggal panel untuk diproses. Upload panel dulu.")
        return redirect("reconcile")

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
    # Preview auto-split: tanggal-panel yang akan diproses (tiap tanggal = satu batch).
    panel_dates = _panel_dates(active, df, dt, None)
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
        "panel_dates": panel_dates,
        "panel_dates_count": len(panel_dates),
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

    # Ringkasan per sumber uang (dihitung on-the-fly; batch lama otomatis kebagian).
    from django.db.models import Exists, OuterRef

    from transactions.models import specific_source_label

    paired_q = MatchResult.objects.filter(left__isnull=False, right_id=OuterRef("id"))
    money_rows = (
        Transaction.objects.filter(
            consumed_by_batch=batch, source_type__key__in=["bank", "gateway"]
        )
        .exclude(jenis="admin")
        .annotate(berpasangan=Exists(paired_q))
        .select_related("source_type", "upload", "upload__account")
    )
    agg = {}
    for t in money_rows:
        label = specific_source_label(
            t.source_type.key,
            account=t.upload.account if t.upload else None,
            upload=t.upload,
        )
        row = agg.setdefault(
            label, {"label": label, "n": 0, "dp": 0.0, "wd": 0.0, "paired": 0, "unpaired": 0}
        )
        row["n"] += 1
        md = float(t.money_delta)
        if md > 0:
            row["dp"] += md
        elif md < 0:
            row["wd"] += -md
        if t.berpasangan:
            row["paired"] += 1
        else:
            row["unpaired"] += 1
    per_bank = sorted(agg.values(), key=lambda r: r["label"])

    # Deteksi cangkang (F1-B): summary mengklaim hasil tapi MatchResult sudah tak
    # ada (bukti terhapus → cascade). Batch begini tak bisa diverifikasi.
    bkt = (batch.summary or {}).get("buckets", {})
    claimed = sum(v for v in bkt.values() if isinstance(v, (int, float)))
    is_hollow = claimed > 0 and not MatchResult.objects.filter(run__batch=batch).exists()
    riwayat = list(
        AuditLog.objects.filter(detail__batch_pk=batch.pk).select_related("user")[:20]
    )

    return render(request, "web/batch_detail.html", {
        "batch": batch, "batch_no": batch_no, "s": batch.summary or {}, "runs": batch.runs.all(),
        "resolved_here": resolved_here, "settled_elsewhere": settled_elsewhere,
        "per_bank": per_bank, "is_hollow": is_hollow, "riwayat": riwayat,
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

    # Sort in-memory (rows sudah list, kategori dihitung pasca-query).
    from datetime import datetime as _dt

    sort = request.GET.get("sort", "")
    sort_dir = request.GET.get("dir", "")
    if sort == "nominal":
        rows.sort(key=lambda t: abs(float(t.money_delta)), reverse=(sort_dir == "desc"))
    elif sort == "tanggal":
        rows.sort(key=lambda t: (t.occurred_at or _dt.min), reverse=(sort_dir == "desc"))
    else:
        sort, sort_dir = "tanggal", "asc"  # default: tanggal naik
        rows.sort(key=lambda t: (t.occurred_at or _dt.min))

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
        "kartu": kartu, "kat": kat, "sort": sort, "dir": sort_dir,
    })


@login_required
def run_detail(request, pk):
    run = get_object_or_404(MatchRun, pk=pk, batch__toko__in=tokos_for(request.user))
    base = MatchResult.objects.filter(run=run).select_related("left", "right")

    # Kartu status: 'Tidak Cocok' (masih ada baris kredit / no_money) dipisah dari
    # 'Tidak Ada di Panel' (orphan uang tanpa kredit / no_panel) — dihitung live.
    TIDAK = MatchResult.Bucket.TIDAK
    n_tidak_cocok = base.filter(bucket=TIDAK, left__isnull=False).count()
    n_tidak_ada_panel = base.filter(bucket=TIDAK, left__isnull=True).count()

    qs = base
    bucket = request.GET.get("bucket", "")
    if bucket == "tidak_cocok":
        qs = qs.filter(bucket=TIDAK, left__isnull=False)
    elif bucket == "tidak_ada_panel":
        qs = qs.filter(bucket=TIDAK, left__isnull=True)
    elif bucket:
        qs = qs.filter(bucket=bucket)

    # Filter arus Deposit/Withdraw: pakai jenis sisi kiri; hasil tanpa kiri
    # (mis. no_panel) dinilai dari sisi uangnya.
    flow = request.GET.get("flow", "")
    if flow not in ("depo", "wd"):
        flow = ""
    if flow:
        qs = qs.filter(Q(left__jenis=flow) | Q(left__isnull=True, right__jenis=flow))

    # Chip filter per alasan — dihitung DALAM bucket+flow terpilih supaya angkanya jujur.
    reasons = list(
        qs.values("reason_code").annotate(n=Count("id")).order_by("-n")
    )
    reason = request.GET.get("reason", "")
    if reason:
        qs = qs.filter(reason_code=reason)

    # Chip filter bank pemain (dalam bucket+flow+alasan). Kosong/orphan dikecualikan.
    banks = [
        {"code": r["left__player_bank"], "n": r["n"]}
        for r in qs.filter(left__player_bank__gt="")
        .values("left__player_bank").annotate(n=Count("id")).order_by("-n")
    ]
    bank = request.GET.get("bank", "")
    if bank:
        qs = qs.filter(left__player_bank=bank)

    # Chip filter bank title / tujuan (dalam bucket+flow+alasan+bank).
    btitles = [
        {"code": r["left__bank_title"], "n": r["n"]}
        for r in qs.filter(left__bank_title__gt="")
        .values("left__bank_title").annotate(n=Count("id")).order_by("-n")
    ]
    btitle = request.GET.get("btitle", "")
    if btitle:
        qs = qs.filter(left__bank_title=btitle)

    # Ringkasan total pada set terfilter penuh (sebelum paginasi).
    totals = qs.aggregate(
        kredit=Sum("left__amount"), saldo=Sum("right__amount"), n=Count("id")
    )

    qs, sort, sort_dir = _apply_sort(
        request, qs,
        allowed={"amount": "left__amount", "skor": "score", "waktu": "left__occurred_at"},
        default_order=["bucket", "-score", "id"],
    )
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    left_label, right_label = REL_LABELS.get(run.relation, ("Kiri", "Kanan"))
    left_amt_label, right_amt_label = REL_AMOUNT_LABELS.get(
        run.relation, ("Kredit/Koin", "Saldo Bank")
    )
    orphan_label = f"Tidak Ada di {left_label}"
    # Nomor batch per-toko (posisi urut, bukan pk global) — konsisten dgn batch_detail.
    batch = run.batch
    batch_no = (
        ReconBatch.objects.filter(toko=batch.toko, id__lte=batch.id).count() if batch else None
    )
    # Cangkang (F1-B): summary run mengklaim hasil tapi MatchResult sudah tak ada.
    rs = run.summary or {}
    claimed = sum(v for v in rs.values() if isinstance(v, (int, float)))
    is_hollow = claimed > 0 and not MatchResult.objects.filter(run=run).exists()
    ctx = {
        "run": run, "page": page, "bucket": bucket, "bucket_meta": BUCKET_META,
        "left_label": left_label, "right_label": right_label,
        "left_amt_label": left_amt_label, "right_amt_label": right_amt_label,
        "orphan_label": orphan_label,
        "n_tidak_cocok": n_tidak_cocok, "n_tidak_ada_panel": n_tidak_ada_panel,
        "batch": batch, "batch_no": batch_no,
        "reasons": reasons, "reason": reason, "flow": flow,
        "banks": banks, "bank": bank, "btitles": btitles, "btitle": btitle,
        "totals": totals,
        "sort": sort, "dir": sort_dir, "is_hollow": is_hollow,
    }
    return render(request, "web/run_detail.html", ctx)


@login_required
def review_queue(request):
    """Antrean semua hasil perlu-tinjau toko aktif, lintas batch/run."""
    active = _active_toko(request)
    if active is None:
        return render(request, "web/no_toko.html")
    qs = (
        MatchResult.objects.filter(
            run__batch__toko=active, bucket=MatchResult.Bucket.TINJAU
        )
        .select_related("left", "right", "run", "run__batch")
        .order_by("-run__batch__recon_date", "-score", "id")
    )
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    # nomor batch per-toko untuk tiap hasil di halaman ini
    for r in page.object_list:
        b = r.run.batch
        r.home_no = (
            ReconBatch.objects.filter(toko=active, id__lte=b.id).count() if b else None
        )
    return render(request, "web/review_queue.html", {
        "page": page, "active_toko": active,
    })


@login_required
def toko_overview(request):
    """Ringkasan lintas toko (scoped RBAC): status rekon terakhir, selisih,
    antrean tinjau, menunggu settlement, uang periksa D."""
    from reconciliation.engine import pending_settlement_count

    tokos = tokos_for(request.user)
    rows = []
    for t in tokos:
        last = (
            ReconBatch.objects.filter(toko=t, recon_date__isnull=False)
            .order_by("recon_date")
            .last()
        )
        s = (last.summary or {}) if last else {}
        dp = abs((s.get("dp") or {}).get("selisih") or 0)
        wd = abs((s.get("wd") or {}).get("selisih") or 0)
        total = dp + wd
        st = "" if last is None else ("ok" if total == 0 else ("warn" if total < 10_000_000 else "bad"))
        tinjau = MatchResult.objects.filter(
            run__batch__toko=t, bucket=MatchResult.Bucket.TINJAU
        ).count()
        um = (s.get("unmatched_money") or {}).get("d") or {}
        rows.append({
            "toko": t, "last": last, "selisih": total, "status": st,
            "tinjau": tinjau, "pending": pending_settlement_count(t),
            "uang_d": um.get("n") or 0,
            "has_batch": last is not None,
        })
    # selisih terbesar dulu; toko tanpa batch di bawah
    rows.sort(key=lambda r: (r["has_batch"], r["selisih"]), reverse=True)
    return render(request, "web/toko_overview.html", {"rows": rows})


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
    if rows:
        catat(request.user, "review_massal", f"{len(rows)} hasil",
              toko=run.batch.toko if run.batch else None,
              run_pk=run.pk, n=len(rows), action=action)
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
    catat(request.user, "review", f"Result #{r.pk}",
          toko=r.run.batch.toko if r.run.batch else None, result_pk=r.pk, action=action)
    show_run_col = request.POST.get("show_run_col") == "1"
    if show_run_col and r.run.batch:
        r.home_no = ReconBatch.objects.filter(
            toko=r.run.batch.toko, id__lte=r.run.batch_id
        ).count()
    return render(request, "web/_result_row.html", {
        "r": r, "bucket_meta": BUCKET_META, "show_run_col": show_run_col,
    })


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
    headers = ["Status", f"{L} Ticket", f"{L} Nominal", f"{L} Username", f"{L} Nama Lengkap",
               f"{L} Player Bank", f"{L} Bank Title", f"{L} Handler", f"{L} Waktu",
               R, f"{R} Sumber", f"{R} Nominal", f"{R} Waktu", "Skor", "Alasan", "Detail"]
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
            reason_label(r.reason_code),
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
