import os
import zipfile
from datetime import date, timedelta

from django.contrib import messages
from django.core.files.base import ContentFile
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db.models import Count, Max, Min, Q, Sum
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from reconciliation.engine import (
    MATCHERS,
    MONEY_SOURCES,
    check_completeness,
    rematch_batch,
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

REL_LABELS = {
    MatchRun.Relation.PANEL_BRACKET.value: ("Panel", "Bracket"),
    MatchRun.Relation.PANEL_BANK.value: ("Panel", "Bank/Gateway"),
    MatchRun.Relation.BRACKET_BANK.value: ("Bracket", "Bank/Gateway"),
    MatchRun.Relation.SALDO.value: ("Kiri", "Kanan"),
}


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


def _dashboard_health(toko):
    """KPI kesehatan audit: agregat ringan dari summary 30 batch terakhir.

    Menjawab tiga pertanyaan ritual harian saat mendarat: (a) ada selisih
    terbuka? (b) berapa hari belum direkonsiliasi? (c) berapa batch masih
    punya ekor tidak_cocok yang menunggu uang susulan."""
    recent = list(ReconBatch.objects.filter(toko=toko).order_by("-id")[:30])
    selisih_total, ekor = 0, 0
    buckets = {"cocok": 0, "perlu_tinjau": 0, "tidak_cocok": 0}
    for b in recent:
        s = b.summary or {}
        selisih_total += abs((s.get("dp") or {}).get("selisih") or 0)
        selisih_total += abs((s.get("wd") or {}).get("selisih") or 0)
        bk = s.get("buckets") or {}
        if (bk.get("tidak_cocok") or 0) > 0:
            ekor += 1
        for k in buckets:
            buckets[k] += bk.get(k) or 0
    today = date.today()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    per_day = dict.fromkeys(days, 0)
    for b in recent:
        if b.date_to in per_day:
            s = b.summary or {}
            per_day[b.date_to] += abs((s.get("dp") or {}).get("selisih") or 0)
            per_day[b.date_to] += abs((s.get("wd") or {}).get("selisih") or 0)
    saran = _saran_tanggal(toko)
    return {
        "selisih_terbuka": selisih_total,
        "ekor_terbuka": ekor,
        "buckets_agg": buckets,
        "selisih_trend": [per_day[d] for d in days],
        "saran_tanggal": saran,
        "hari_tertunda": max((today - saran).days + 1, 0) if saran else 0,
    }


@login_required
def dashboard(request):
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
    ctx = {
        "active_toko": active,
        "tx_total": tx.count(),
        "upload_total": uploads.count(),
        "run_total": runs.count(),
        "by_source": by_source,
        "uploads": uploads.select_related("source_type").order_by("-id")[:8],
        "runs": runs.order_by("-id")[:8],
        "health": _dashboard_health(active),
    }
    return render(request, "web/dashboard.html", ctx)


def _rematch_candidates(toko, money_uploads):
    """Setelah upload sumber UANG: batch lama yang berpotensi ditutup mutasi baru
    (ekor malam T+1 / statement BNI bulanan). Kandidat: toko sama, punya baris
    tidak_cocok, window overlap rentang tanggal transaksi baru
    (batch.date_from <= max & batch.date_to >= min-1hari).

    Urut TERTUA dulu — auto re-match memberi hari lebih awal pilihan pertama atas
    uang yang sama. Kembalikan list (batch, nomor_per_toko), maks 10.
    """
    if not money_uploads:
        return []
    agg = Transaction.objects.filter(upload__in=money_uploads).aggregate(
        lo=Min("occurred_at"), hi=Max("occurred_at")
    )
    lo, hi = agg["lo"], agg["hi"]
    if lo is None or hi is None:
        return []
    hi_d = hi.date()
    lo_slack = lo.date() - timedelta(days=1)  # aproksimasi window toleransi 1 hari

    recent = ReconBatch.objects.filter(toko=toko).order_by("-id")[:30]
    hits = []
    for b in sorted(recent, key=lambda b: b.id):
        if (b.summary or {}).get("buckets", {}).get("tidak_cocok", 0) <= 0:
            continue
        # Tanpa batas tanggal (None) = seluruh rentang → selalu overlap.
        if b.date_from is not None and b.date_from > hi_d:
            continue
        if b.date_to is not None and b.date_to < lo_slack:
            continue
        no = ReconBatch.objects.filter(toko=toko, id__lte=b.id).count()
        hits.append((b, no))
        if len(hits) == 10:
            break
    return hits


def _selisih_abs(batch):
    """Total |selisih| DP+WD dari summary batch — angka delta kartu penyembuhan."""
    s = batch.summary or {}
    return abs((s.get("dp") or {}).get("selisih") or 0) + abs((s.get("wd") or {}).get("selisih") or 0)


def _auto_rematch(toko, money_uploads, user=None):
    """Re-match otomatis batch kandidat setelah upload sumber uang — tanpa klik.

    Kembalikan list dict terstruktur per batch (delta selisih before→after)
    untuk kartu laporan penyembuhan. Batch tanpa baris terpasang tidak
    dilaporkan (anti-noise); error per-batch dilaporkan tapi tidak
    menggagalkan upload (file sudah ter-ingest)."""
    out = []
    for batch, no in _rematch_candidates(toko, money_uploads):
        before = _selisih_abs(batch)
        try:
            stats = rematch_batch(batch, user=user)
        except Exception as e:  # noqa: BLE001 - upload jangan ikut gagal
            out.append({"level": "error", "batch_pk": batch.pk, "batch_no": no, "error": str(e)})
            continue
        if stats["terpasang"]:
            batch.refresh_from_db()
            out.append({
                "level": "success", "batch_pk": batch.pk, "batch_no": no,
                "terpasang": stats["terpasang"], "cocok": stats["cocok"],
                "perlu_tinjau": stats["perlu_tinjau"],
                "selisih_before": before, "selisih_after": _selisih_abs(batch),
            })
    return out


# Upload folder/zip: hanya ekstensi yang punya parser; sisanya junk OS/temp.
_UPLOAD_EXTS = {".xlsx", ".xls", ".csv", ".pdf"}
_ZIP_MAX_FILES = 200
_ZIP_MAX_BYTES = 200 * 1024 * 1024


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


def _saran_tanggal(toko):
    """Saran tanggal reconcile berikutnya: hari setelah window batch terakhir; bila
    belum ada batch berjendela, tanggal transaksi AKTIF tertua (data yang belum
    direkonsiliasi). None = tanpa saran (form dibiarkan kosong)."""
    last = (
        ReconBatch.objects.filter(toko=toko, date_to__isnull=False)
        .order_by("-date_to", "-id")
        .first()
    )
    if last:
        return last.date_to + timedelta(days=1)
    lo = Transaction.objects.filter(
        toko=toko, is_duplicate=False, consumed_by_batch__isnull=True
    ).aggregate(lo=Min("occurred_at"))["lo"]
    return lo.date() if lo else None


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
        money_uploads = []  # upload sumber uang → cek batch lama yg bisa di-re-match
        for i, (path_rel, key, flow) in enumerate(zip(staged, keys, flows)):
            if not path_rel.startswith("staging/") or ".." in path_rel:
                n_err += 1
                continue
            if key not in PARSERS:
                n_err += 1
                continue
            try:
                up, _created, _dup = ingest(
                    key, default_storage.path(path_rel), flow=flow,
                    user=request.user, toko=active, provider=provider,
                    password=(passwords[i] if i < len(passwords) else ""),
                )
                if up.source_type.key in MONEY_SOURCES:
                    money_uploads.append(up)
                n_ok += 1
            except Exception as e:  # noqa: BLE001 - tampilkan error parse ke user
                messages.error(request, f"{path_rel}: {e}")
                n_err += 1
            finally:
                if default_storage.exists(path_rel):
                    default_storage.delete(path_rel)
        messages.success(request, f"{n_ok} file diproses, {n_err} gagal.")
        # Auto re-match: mutasi susulan langsung dipasangkan ke batch lama yang
        # punya baris tidak_cocok (ekor malam T+1 / statement bulanan) — tanpa klik.
        # Hasil sukses di-stash ke session (pola PRG) → dirender sekali sebagai
        # kartu penyembuhan; error tetap lewat flash.
        healing = _auto_rematch(active, money_uploads, user=request.user)
        for h in healing:
            if h["level"] == "error":
                messages.error(request, f"Re-match otomatis Batch #{h['batch_no']} gagal: {h['error']}")
        sukses = [h for h in healing if h["level"] == "success"]
        if sukses:
            request.session["healing_report"] = sukses
        return redirect("upload")
    if request.method == "POST" and request.POST.get("action") == "analyze":
        preview = []
        dilewati = 0
        for f in request.FILES.getlist("files"):
            if f.name.lower().endswith(".zip"):
                isi, n_skip, err = _extract_zip(f)
                dilewati += n_skip
                if err:
                    messages.error(request, f"{f.name}: {err}")
                    continue
                for nama, data in isi:
                    preview.append(_analyze_file(nama, ContentFile(data)))
                continue
            if _is_junk_name(f.name):
                dilewati += 1
                continue
            preview.append(_analyze_file(f.name, f))
        if dilewati:
            messages.info(
                request,
                f"{dilewati} file dilewati (tersembunyi / bukan xlsx·xls·csv·pdf).",
            )
        return render(request, "web/upload.html", {
            "preview": preview, "parsers": sorted(PARSERS.keys()),
            "flows": ["", "dp", "wd"], "active_toko": active,
            "n_siap": sum(1 for p in preview if not p["needs_confirm"] and not p["needs_password"]),
            "n_cek": sum(1 for p in preview if p["needs_confirm"]),
            "n_pwd": sum(1 for p in preview if p["needs_password"]),
            "uploads": Upload.objects.filter(toko=active).select_related("source_type").order_by("-id")[:20],
            "healing": request.session.pop("healing_report", None),
        })
    return render(request, "web/upload.html", {
        "parsers": sorted(PARSERS.keys()), "active_toko": active,
        "uploads": Upload.objects.filter(toko=active).select_related("source_type").order_by("-id")[:20],
        "healing": request.session.pop("healing_report", None),
    })


@login_required
def transactions(request):
    active = _active_toko(request)
    if active is None:
        return render(request, "web/no_toko.html")
    qs = (
        Transaction.objects.filter(toko=active)
        .select_related("source_type", "account", "upload", "upload__account")
        .order_by("-occurred_at")
    )
    src = request.GET.get("source", "")
    jenis = request.GET.get("jenis", "")
    q = request.GET.get("q", "").strip()
    bank = request.GET.get("bank", "").strip()
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
    }
    return render(request, "web/transactions.html", ctx)


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
        batch = run_batch(
            active, tol,
            request.POST.get("date_from") or None,
            request.POST.get("date_to") or None,
            user=request.user,
            include=include,
        )
        no = ReconBatch.objects.filter(toko=active).count()
        messages.success(request, f"Rekonsiliasi selesai (Batch #{no}).")
        return redirect("batch_detail", pk=batch.pk)

    df = request.GET.get("date_from") or None
    dt = request.GET.get("date_to") or None
    # Saran tanggal: tanpa param eksplisit, prefill hari berikutnya yang belum
    # direkonsiliasi — cegah footgun "tanggal kosong = telan semua data".
    tanggal_disarankan = False
    if df is None and dt is None:
        saran = _saran_tanggal(active)
        if saran:
            df = dt = saran.isoformat()
            tanggal_disarankan = True
    bank = request.GET.get("bank", "")
    if bank not in ("bank", "gateway"):
        bank = ""  # nilai tak dikenal → perlakukan sebagai "semua sumber"
    # Nomor dihitung dari SEMUA batch toko dulu (posisi asli), BARU difilter —
    # supaya nomor batch tidak berubah saat filter sumber uang aktif.
    all_batches = list(ReconBatch.objects.filter(toko=active).order_by("-id"))
    total = len(all_batches)
    for i, b in enumerate(all_batches):
        b.no = total - i
        # Triple bucket ternormalisasi utk bucket-bar (summary lama bisa tanpa buckets).
        bk = (b.summary or {}).get("buckets") or {}
        b.bk = {
            "cocok": bk.get("cocok") or 0,
            "perlu_tinjau": bk.get("perlu_tinjau") or 0,
            "tidak_cocok": bk.get("tidak_cocok") or 0,
        }
        b.bk["total"] = b.bk["cocok"] + b.bk["perlu_tinjau"] + b.bk["tidak_cocok"]
    if bank:
        all_batches = [b for b in all_batches if (b.completeness or {}).get(bank)]
    batches = all_batches[:20]
    ctx = {
        "active_toko": active,
        "completeness": check_completeness(active, df, dt),
        "tolerances": ToleranceProfile.objects.all(),
        "batches": batches,
        "bank": bank,
        "date_from": df or "", "date_to": dt or "",
        "tanggal_disarankan": tanggal_disarankan,
    }
    return render(request, "web/reconcile.html", ctx)


# Jam mulai "malam" untuk heuristik ekor T+1: transaksi >= jam ini di hari
# terakhir window kemungkinan settle besok (file mutasinya belum terupload).
_JAM_EKOR = 17


def _pending_t1(result, date_to):
    """True bila baris tidak_cocok ini kemungkinan EKOR T+1 (bukan selisih nyata):
    no_money + transaksi malam di hari terakhir window → uangnya baru datang di
    file besok, tertutup auto re-match."""
    return bool(
        date_to
        and result.bucket == MatchResult.Bucket.TIDAK
        and result.reason_code == "no_money"
        and result.left_id
        and result.left.occurred_at.date() == date_to
        and result.left.occurred_at.hour >= _JAM_EKOR
    )


@login_required
def batch_detail(request, pk):
    batch = get_object_or_404(ReconBatch, pk=pk, toko__in=tokos_for(request.user))
    batch_no = ReconBatch.objects.filter(toko=batch.toko, id__lte=batch.id).count()
    s = batch.summary or {}
    # Triple bucket ternormalisasi utk bucket-bar (summary lama bisa tanpa buckets).
    raw_bk = s.get("buckets") or {}
    bk = {
        "cocok": raw_bk.get("cocok") or 0,
        "perlu_tinjau": raw_bk.get("perlu_tinjau") or 0,
        "tidak_cocok": raw_bk.get("tidak_cocok") or 0,
    }
    bk["total"] = bk["cocok"] + bk["perlu_tinjau"] + bk["tidak_cocok"]
    pending_t1 = 0
    if batch.date_to:
        pending_t1 = MatchResult.objects.filter(
            run__batch=batch, bucket=MatchResult.Bucket.TIDAK, reason_code="no_money",
            left__occurred_at__date=batch.date_to, left__occurred_at__hour__gte=_JAM_EKOR,
        ).count()
    return render(request, "web/batch_detail.html", {
        "batch": batch, "batch_no": batch_no, "s": s, "bk": bk, "runs": batch.runs.all(),
        "healing": request.session.pop("healing_report", None),
        "pending_t1": pending_t1,
    })


@login_required
@require_POST
def rematch(request, pk):
    """Re-match batch: pasangkan mutasi uang susulan ke baris tidak_cocok batch ini
    (ekor malam T+1 / statement BNI bulanan) — tanpa hapus batch."""
    batch = get_object_or_404(ReconBatch, pk=pk, toko__in=tokos_for(request.user))
    before = _selisih_abs(batch)
    stats = rematch_batch(batch, user=request.user)
    if stats["terpasang"]:
        batch.refresh_from_db()
        no = ReconBatch.objects.filter(toko=batch.toko, id__lte=batch.id).count()
        # Kartu penyembuhan yang sama dgn auto re-match — stash session, render sekali.
        request.session["healing_report"] = [{
            "level": "success", "batch_pk": batch.pk, "batch_no": no,
            "terpasang": stats["terpasang"], "cocok": stats["cocok"],
            "perlu_tinjau": stats["perlu_tinjau"],
            "selisih_before": before, "selisih_after": _selisih_abs(batch),
        }]
    else:
        messages.info(request, "Tidak ada baris baru yang bisa dipasangkan.")
    return redirect("batch_detail", pk=batch.pk)


@login_required
def run_detail(request, pk):
    import collections

    from django.db.models.fields.json import KeyTextTransform

    run = get_object_or_404(MatchRun, pk=pk, batch__toko__in=tokos_for(request.user))
    qs = MatchResult.objects.filter(run=run).select_related("left", "right").order_by("bucket", "-score")
    bucket = request.GET.get("bucket", "")
    if bucket:
        qs = qs.filter(bucket=bucket)

    # Daftar chip channel/sumber dibangun dari qs SETELAH filter bucket tapi SEBELUM
    # filter channel — segmen pertama Player Bank sisi Panel ("DANA|nama|nomor").
    # Kunci JSON "Player Bank" mengandung spasi → tak bisa jadi alias values_list
    # langsung, jadi anotasi lewat KeyTextTransform dgn alias aman (jalan di
    # sqlite JSON1 & Postgres JSONB).
    counter = collections.Counter()
    pb_values = qs.annotate(
        _player_bank=KeyTextTransform("Player Bank", "left__raw")
    ).values_list("_player_bank", flat=True)
    for v in pb_values:
        if not v:
            continue
        name = str(v).split("|")[0].strip().upper()
        if name:
            counter[name] += 1
    channels = counter.most_common()  # [(nama, count), ...] urut count desc

    # Filter channel diterapkan SETELAH bucket; normalisasi ke upper + istartswith
    # supaya kapitalisasi tersimpan tak berpengaruh.
    channel = request.GET.get("channel", "").strip().upper()
    if channel:
        qs = qs.filter(**{"left__raw__Player Bank__istartswith": channel + "|"})

    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    # Tandai kemungkinan ekor T+1 (transaksi malam hari terakhir window) supaya
    # auditor bisa membedakan "menunggu mutasi besok" dari selisih nyata.
    dto = run.date_to or (run.batch.date_to if run.batch else None)
    for r in page:
        r.pending_t1 = _pending_t1(r, dto)
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
        "channels": channels, "channel": channel,
    }
    # Request htmx (filter tab / pager) → cukup fragmen tabel, tanpa shell.
    if request.headers.get("HX-Request"):
        return render(request, "web/_run_table.html", ctx)
    return render(request, "web/run_detail.html", ctx)


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
    r.bucket = buckets[action]
    r.reason_code = "manual_override"
    r.save(update_fields=["bucket", "reason_code"])
    ReviewAction.objects.create(result=r, action=action, reason=reason, reviewer=request.user)
    return render(request, "web/_result_row.html", {"r": r, "bucket_meta": BUCKET_META})


@login_required
@require_POST
def review_bulk(request):
    """Review MASSAL — semantik sama persis dengan review per-baris (bucket +
    reason_code=manual_override + jejak ReviewAction per baris), untuk banyak
    hasil sekaligus: ratusan weak_name/hari tak mungkin diklik satu-satu."""
    action = request.POST.get("action", "")
    buckets = {
        "mark_matched": MatchResult.Bucket.COCOK,
        "mark_review": MatchResult.Bucket.TINJAU,
        "mark_unmatched": MatchResult.Bucket.TIDAK,
    }
    if action not in buckets:
        return HttpResponseBadRequest("Aksi tidak dikenal.")
    ids = request.POST.getlist("result_ids")
    results = list(
        MatchResult.objects.filter(pk__in=ids, run__batch__toko__in=tokos_for(request.user))
    )
    for r in results:
        r.bucket = buckets[action]
        r.reason_code = "manual_override"
    MatchResult.objects.bulk_update(results, ["bucket", "reason_code"], batch_size=500)
    ReviewAction.objects.bulk_create(
        [ReviewAction(result=r, action=action, reason="review massal", reviewer=request.user)
         for r in results],
        batch_size=500,
    )
    label = {"mark_matched": "cocok", "mark_review": "perlu ditinjau",
             "mark_unmatched": "tidak cocok"}[action]
    messages.success(request, f"{len(results)} baris ditandai {label}.")
    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    if results:
        return redirect("run_detail", pk=results[0].run_id)
    return redirect("reconcile")


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
