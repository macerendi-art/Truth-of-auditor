"""Panel admin: kelola pengguna & toko, hapus data. Semua view digate admin_required."""
import ipaddress

from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from core.audit import catat
from core.models import AuditLog
from reconciliation.engine import revert_late_settlements
from reconciliation.models import MatchResult, ReconBatch, ReviewAction
from sources.models import Toko, Upload
from transactions.models import Transaction
from web.access import admin_required, role_required, tokos_for
from web.models import AllowedIP
from web.views import _active_toko, _parse_date


# Halaman admin di berkas ini BEBAS TOKO: isinya daftar user, daftar seluruh
# toko, allowlist IP, dan log lintas-toko — tak satu pun angka di layar milik
# toko aktif. Karena itu bar mode Semua Toko ("halaman ini menampilkan <toko>")
# harus DIAM di sini: ia mengklaim atribusi yang tidak ada, dan di /kelola/toko/
# malah bertolak belakang dengan tabelnya sendiri yang memuat semua toko.
# `semua_toko_page` adalah penanda yang sama yang dipakai dashboard gabungan
# (lihat app_base.html) — hanya menyembunyikan BAR, pemilih toko tetap ada.
BEBAS_TOKO = {"semua_toko_page": True}


def _batch_no(batch):
    """Nomor batch per-toko posisional (bukan pk) — konsisten dgn view lain."""
    return ReconBatch.objects.filter(toko=batch.toko, id__lte=batch.id).count()


def _locking_batches(upload):
    """Batch yang buktinya bergantung pada upload ini.

    Menghapus upload meng-cascade transaksinya → MatchResult (left/right CASCADE)
    ikut mati, tapi ReconBatch/MatchRun selamat dengan summary basi ("Balanced ✓"
    palsu). Dua jejak dependensi: (a) transaksi direferensi MatchResult sebagai
    left ATAU right, (b) transaksi dikonsumsi batch (membentuk gross-nya).
    Kembalikan daftar batch terdampak (unik, urut id) utk diblokir + dilaporkan.
    """
    batch_ids = set(
        MatchResult.objects.filter(Q(left__upload=upload) | Q(right__upload=upload))
        .exclude(run__batch__isnull=True)
        .values_list("run__batch", flat=True)
    )
    batch_ids |= set(
        upload.transactions.filter(consumed_by_batch__isnull=False)
        .values_list("consumed_by_batch", flat=True)
    )
    return list(ReconBatch.objects.filter(id__in=batch_ids).order_by("id"))


VALID_ROLES = ("admin", "supervisor", "auditor")
PANEL_LABELS = dict(Toko.PANEL_CHOICES)
KEPEMILIKAN_LABELS = dict(Toko.KEPEMILIKAN_CHOICES)


def _toko_id_sah(tid):
    """id Toko kiriman form yang aman dikirim ke query pk.

    `isdecimal()` saja tidak cukup: "9"*11 lolos, lalu Postgres membalas
    NumericValueOutOfRange/DataError (500) alih-alih 404 yang rapi. Batas
    panjangnya sama dengan `web.views.set_toko` (≤10 digit) — sebanyak itu
    sudah jauh di luar akal untuk pk Toko.
    """
    return tid.isdecimal() and len(tid) <= 10


def _password_error(password, user=None):
    """Pesan gabungan validator password Django (terlokalisasi id) — None bila lolos.
    Mencakup panjang minimum, password umum, semua-angka, mirip atribut user."""
    try:
        validate_password(password, user=user)
    except ValidationError as e:
        return " ".join(e.messages)
    return None


@admin_required
def kelola_toko(request):
    if request.method == "POST" and request.POST.get("action") == "create":
        kode = request.POST.get("kode", "").strip()
        panel = request.POST.get("panel", "")
        kepemilikan = request.POST.get("kepemilikan", "")
        if not kode or not kode.isalnum():
            messages.error(request, "Kode toko wajib huruf/angka tanpa spasi.")
        elif Toko.objects.filter(key=kode.lower()).exists():
            messages.error(request, f"Toko {kode.upper()} sudah ada.")
        elif panel not in PANEL_LABELS:
            messages.error(request, "Pilih panel toko (Nexus/Vigor/TM Gaming).")
        elif kepemilikan not in KEPEMILIKAN_LABELS:
            messages.error(request, "Pilih kepemilikan toko (Pusat/Partner).")
        else:
            t = Toko.objects.create(
                key=kode.lower(), name=kode.upper(),
                panel=panel, kepemilikan=kepemilikan,
            )
            catat(
                request.user, "buat_toko", t.name, toko=t,
                panel=PANEL_LABELS[panel],
                kepemilikan=KEPEMILIKAN_LABELS[kepemilikan],
            )
            messages.success(request, f"Toko {kode.upper()} ditambahkan.")
        return redirect("kelola_toko")
    if request.method == "POST" and request.POST.get("action") == "toggle":
        tid = request.POST.get("toko_id", "")
        if not _toko_id_sah(tid):
            messages.error(request, "ID toko tidak valid.")
            return redirect("kelola_toko")
        t = get_object_or_404(Toko, pk=tid)
        t.is_active = not t.is_active
        t.save(update_fields=["is_active"])
        catat(request.user, "aktifkan_toko" if t.is_active else "nonaktifkan_toko",
              t.name, toko=t)
        messages.success(request, f"Toko {t.name} {'diaktifkan' if t.is_active else 'dinonaktifkan'}.")
        return redirect("kelola_toko")
    if request.method == "POST" and request.POST.get("action") == "rename":
        tid = request.POST.get("toko_id", "")
        nama_baru = (request.POST.get("nama_baru") or "").strip()[:100]
        if not _toko_id_sah(tid):
            messages.error(request, "ID toko tidak valid.")
            return redirect("kelola_toko")
        if not nama_baru:
            messages.error(request, "Nama baru wajib diisi.")
            return redirect("kelola_toko")
        t = get_object_or_404(Toko, pk=tid)
        nama_lama = t.name
        if nama_baru != nama_lama:
            t.name = nama_baru
            t.save(update_fields=["name"])
            catat(request.user, "ubah_nama_toko", f"{nama_lama} → {nama_baru}",
                  toko=t, nama_lama=nama_lama, nama_baru=nama_baru)
            messages.success(request, f"Nama toko {nama_lama} diganti menjadi {nama_baru}.")
        return redirect("kelola_toko")
    if request.method == "POST" and request.POST.get("action") == "panel":
        tid = request.POST.get("toko_id", "")
        panel_baru = request.POST.get("panel", "")
        if not _toko_id_sah(tid):
            messages.error(request, "ID toko tidak valid.")
            return redirect("kelola_toko")
        if panel_baru not in PANEL_LABELS:
            messages.error(request, "Pilih panel toko (Nexus/Vigor/TM Gaming).")
            return redirect("kelola_toko")
        t = get_object_or_404(Toko, pk=tid)
        panel_lama = t.panel
        if panel_baru != panel_lama:
            t.panel = panel_baru
            t.save(update_fields=["panel"])
            catat(request.user, "ubah_panel_toko",
                  f"{t.name}: {PANEL_LABELS[panel_lama]} → {PANEL_LABELS[panel_baru]}", toko=t)
            messages.success(
                request, f"Panel toko {t.name} diganti menjadi {PANEL_LABELS[panel_baru]}.")
        return redirect("kelola_toko")
    if request.method == "POST" and request.POST.get("action") == "kepemilikan":
        tid = request.POST.get("toko_id", "")
        kep_baru = request.POST.get("kepemilikan", "")
        if not _toko_id_sah(tid):
            messages.error(request, "ID toko tidak valid.")
            return redirect("kelola_toko")
        if kep_baru not in KEPEMILIKAN_LABELS:
            messages.error(request, "Pilih kepemilikan toko (Pusat/Partner).")
            return redirect("kelola_toko")
        t = get_object_or_404(Toko, pk=tid)
        kep_lama = t.kepemilikan
        if kep_baru != kep_lama:
            t.kepemilikan = kep_baru
            t.save(update_fields=["kepemilikan"])
            catat(
                request.user, "ubah_kepemilikan_toko",
                f"{t.name}: {KEPEMILIKAN_LABELS[kep_lama]} → {KEPEMILIKAN_LABELS[kep_baru]}",
                toko=t,
            )
            messages.success(
                request,
                f"Kepemilikan toko {t.name} diganti menjadi {KEPEMILIKAN_LABELS[kep_baru]}.",
            )
        return redirect("kelola_toko")
    # Jumlah per toko WAJIB dua query agregat terpisah — annotate ganda
    # Count(distinct) atas dua relasi meledakkan join Toko×Transaction×Upload
    # (497rb tx × ratusan upload): terukur 29,8 dtk di prod = halaman putih.
    tx_counts = dict(Transaction.objects.values_list("toko").annotate(n=Count("id")))
    up_counts = dict(Upload.objects.values_list("toko").annotate(n=Count("id")))
    semua = list(Toko.objects.order_by("name"))
    for t in semua:
        t.n_tx = tx_counts.get(t.id, 0)
        t.n_up = up_counts.get(t.id, 0)

    # Ringkasan matriks silang: baris Pusat/Partner × kolom Panel + TOTAL.
    # Dihitung dari list `semua` — 0 query ekstra.
    from collections import Counter

    n_aktif = sum(1 for t in semua if t.is_active)
    cell = Counter((t.kepemilikan, t.panel) for t in semua)
    panel_keys = [k for k, _ in Toko.PANEL_CHOICES]
    # Header kolom uppercase sesuai mockup (NEXUS / VIGOR / TMGAMING).
    _PANEL_HDR = {
        Toko.PANEL_NEXUS: "NEXUS",
        Toko.PANEL_VIGOR: "VIGOR",
        Toko.PANEL_TMG: "TMGAMING",
    }
    headers = [_PANEL_HDR.get(k, lab.upper()) for k, lab in Toko.PANEL_CHOICES]
    rows = []
    for kep_key, kep_lab in Toko.KEPEMILIKAN_CHOICES:
        cells = [cell.get((kep_key, pk), 0) for pk in panel_keys]
        rows.append({
            "key": kep_key,
            "label": kep_lab.upper(),  # PUSAT / PARTNER
            "cells": cells,
            "total": sum(cells),
        })
    col_totals = [sum(r["cells"][i] for r in rows) for i in range(len(panel_keys))]
    ringkasan = {
        "total": len(semua),
        "aktif": n_aktif,
        "nonaktif": len(semua) - n_aktif,
        "headers": headers,
        "panel_keys": panel_keys,
        "rows": rows,
        "col_totals": col_totals,
        "grand_total": sum(col_totals),
    }

    # Filter daftar (?kep= / ?panel=) — nilai di luar pilihan diabaikan.
    f_kep = (request.GET.get("kep") or "").strip()
    f_panel = (request.GET.get("panel") or "").strip()
    if f_kep not in KEPEMILIKAN_LABELS:
        f_kep = ""
    if f_panel not in PANEL_LABELS:
        f_panel = ""
    tokos = semua
    if f_kep:
        tokos = [t for t in tokos if t.kepemilikan == f_kep]
    if f_panel:
        tokos = [t for t in tokos if t.panel == f_panel]

    return render(request, "web/kelola/toko.html", {
        "tokos": tokos,
        "n_semua": len(semua),
        "ringkasan": ringkasan,
        "f_kep": f_kep,
        "f_panel": f_panel,
        "panel_choices": Toko.PANEL_CHOICES,
        "kepemilikan_choices": Toko.KEPEMILIKAN_CHOICES,
        **BEBAS_TOKO,
    })


@admin_required
def kelola_user(request):
    User = get_user_model()
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        nama = request.POST.get("nama", "").strip()
        role = request.POST.get("role", "auditor")
        toko_ids = request.POST.getlist("tokos")
        # user=... hanya untuk cek kemiripan atribut (username/nama) — tidak disimpan.
        pw_err = _password_error(password, user=User(username=username, first_name=nama))
        err = None
        if not username:
            err = "Username wajib diisi."
        elif User.objects.filter(username=username).exists():
            err = f"Username {username} sudah dipakai."
        elif pw_err:
            err = pw_err
        elif role not in VALID_ROLES:
            err = "Role tidak dikenal."
        elif role == "auditor" and not toko_ids:
            err = "Auditor wajib ditugaskan minimal 1 toko."
        if err:
            messages.error(request, err)
        else:
            u = User.objects.create_user(
                username=username, password=password, first_name=nama, role=role,
                must_change_password=True,  # wajib ganti password sementara saat login pertama
            )
            if role == "auditor":
                u.allowed_tokos.set(Toko.objects.filter(id__in=toko_ids, is_active=True))
            catat(request.user, "buat_user", username, role=role)
            messages.success(request, f"User {username} ({role}) dibuat.")
        return redirect("kelola_user")
    users = User.objects.prefetch_related("allowed_tokos").order_by("username")
    return render(request, "web/kelola/users.html", {
        "users": users,
        "tokos": Toko.objects.filter(is_active=True).order_by("name"),
        "roles": User.Role.choices,
        **BEBAS_TOKO,
    })


@admin_required
def kelola_user_edit(request, pk):
    User = get_user_model()
    target = get_object_or_404(User, pk=pk)
    action = request.POST.get("action", "") if request.method == "POST" else ""

    if action == "save":
        nama = request.POST.get("nama", "").strip()
        role = request.POST.get("role", target.role)
        toko_ids = request.POST.getlist("tokos")
        if role not in VALID_ROLES:
            messages.error(request, "Role tidak dikenal.")
        elif target == request.user and role != "admin":
            messages.error(request, "Tidak bisa menurunkan role akunmu sendiri.")
        elif role == "auditor" and not toko_ids:
            messages.error(request, "Auditor wajib ditugaskan minimal 1 toko.")
        else:
            target.first_name = nama
            target.role = role
            target.save(update_fields=["first_name", "role"])
            target.allowed_tokos.set(
                Toko.objects.filter(id__in=toko_ids, is_active=True) if role == "auditor" else []
            )
            catat(request.user, "ubah_user", target.username, role=role)
            messages.success(request, f"User {target.username} diperbarui.")
            return redirect("kelola_user")
    elif action == "reset_password":
        pw = request.POST.get("password", "")
        pw_err = _password_error(pw, user=target)
        if pw_err:
            messages.error(request, pw_err)
        else:
            target.set_password(pw)
            # reset oleh admin = password sementara → wajib ganti; kecuali admin
            # me-reset password DIRINYA SENDIRI (dia memilih passwordnya sendiri).
            target.must_change_password = target != request.user
            target.save()
            if target == request.user:
                update_session_auth_hash(request, target)
            catat(request.user, "reset_password", target.username)
            messages.success(request, f"Password {target.username} di-reset.")
            return redirect("kelola_user")
    elif action == "toggle":
        if target == request.user:
            messages.error(request, "Tidak bisa menonaktifkan akunmu sendiri.")
        else:
            target.is_active = not target.is_active
            target.save(update_fields=["is_active"])
            catat(request.user,
                  "aktifkan_user" if target.is_active else "nonaktifkan_user",
                  target.username)
            messages.success(
                request,
                f"User {target.username} {'diaktifkan' if target.is_active else 'dinonaktifkan'}.",
            )
        return redirect("kelola_user")

    return render(request, "web/kelola/user_edit.html", {
        "target": target,
        "tokos": Toko.objects.filter(is_active=True).order_by("name"),
        "roles": User.Role.choices,
        "target_toko_ids": set(target.allowed_tokos.values_list("id", flat=True)),
        **BEBAS_TOKO,
    })


@admin_required
def kelola_log(request):
    """Log audit lintas-toko: siapa melakukan apa, kapan — dengan filter & search."""
    logs = AuditLog.objects.select_related("user", "toko").order_by("-id")
    q = request.GET.get("q", "").strip()
    aksi = request.GET.get("aksi", "").strip()
    user_id = request.GET.get("user", "").strip()
    toko_id = request.GET.get("toko", "").strip()
    dfrom = _parse_date(request.GET.get("from", ""))
    dto = _parse_date(request.GET.get("to", ""))
    if q:
        logs = logs.filter(
            Q(objek__icontains=q) | Q(username__icontains=q) | Q(aksi__icontains=q)
        )
    if aksi:
        logs = logs.filter(aksi=aksi)
    if user_id.isdecimal():
        logs = logs.filter(user_id=user_id)
    if toko_id.isdecimal():
        logs = logs.filter(toko_id=toko_id)
    if dfrom:
        logs = logs.filter(created_at__date__gte=dfrom)
    if dto:
        logs = logs.filter(created_at__date__lte=dto)
    page = Paginator(logs, 40).get_page(request.GET.get("page"))
    return render(request, "web/kelola/log.html", {
        "page": page,
        "aksi_list": AuditLog.objects.order_by("aksi")
                    .values_list("aksi", flat=True).distinct(),
        "users": get_user_model().objects.order_by("username"),
        "tokos": Toko.objects.order_by("name"),
        "f": {"q": q, "aksi": aksi, "user": user_id, "toko": toko_id,
              "from": request.GET.get("from", ""), "to": request.GET.get("to", "")},
        **BEBAS_TOKO,
    })


@role_required("admin", "supervisor")
def delete_upload(request, pk):
    # Scope toko: guard struktural yang sama dengan delete_batch — hari ini
    # supervisor memang melihat semua toko, tapi peran ber-scope di masa depan
    # tidak boleh bisa menyentuh upload yang tak terlihat olehnya.
    up = get_object_or_404(Upload, pk=pk, toko__in=tokos_for(request.user))
    if request.method == "POST":
        name = up.original_name or f"Upload #{up.pk}"
        # Guard integritas (F1): upload yang buktinya dipakai hasil rekon tak boleh
        # hilang — hapus batch-nya dulu (tanpa file ini hasilnya memang tak sah).
        locked = _locking_batches(up)
        if locked:
            n_tx = up.transactions.count()
            nomor = ", ".join(f"#{_batch_no(b)}" for b in locked)
            messages.error(
                request,
                f"{name} tidak bisa dihapus — {n_tx} transaksinya dipakai Batch {nomor}. "
                f"Hapus batch itu dulu (tanpa file ini hasilnya tidak sah).",
            )
            return redirect("upload")
        n_tx = up.transactions.count()
        toko = up.toko
        if up.file:
            up.file.delete(save=False)
        up.delete()
        catat(request.user, "hapus_upload", name, toko=toko, upload_pk=pk, n_tx=n_tx)
        messages.success(request, f"{name} dihapus — {n_tx} transaksi ikut terhapus.")
    return redirect("upload")


@role_required("admin", "supervisor")
def bulk_delete_uploads(request):
    """Hapus banyak upload sekaligus dari Riwayat Upload — dibatasi ke TOKO AKTIF
    (persis daftar yang dirender). Yang terkunci guard integritas dilewati &
    dilaporkan, bukan dihapus diam-diam."""
    if request.method == "POST":
        active = _active_toko(request)
        ids = [i for i in request.POST.getlist("upload_ids") if i.isdecimal()]
        ups = list(Upload.objects.filter(pk__in=ids, toko=active)) if active else []
        n_file = n_tx = 0
        dilewati = []
        terhapus = []
        for up in ups:
            if _locking_batches(up):
                dilewati.append(up.original_name or f"Upload #{up.pk}")
                continue
            nama = up.original_name or f"Upload #{up.pk}"
            n_tx += up.transactions.count()
            if up.file:
                up.file.delete(save=False)
            up.delete()
            n_file += 1
            terhapus.append(nama)
        if n_file:
            catat(request.user, "hapus_upload_massal", f"{n_file} file",
                  toko=active, n_file=n_file, n_tx=n_tx,
                  files=", ".join(terhapus)[:1000])
            messages.success(request, f"{n_file} file dihapus — {n_tx} transaksi ikut terhapus.")
        if dilewati:
            messages.error(
                request,
                f"{len(dilewati)} file dilewati karena dipakai hasil rekonsiliasi: "
                f"{', '.join(dilewati)}. Hapus batch terkait dulu.",
            )
    # Kembali ke halaman riwayat asal (digit-only → aman dari open redirect);
    # halaman yang jadi kosong usai hapus di-clamp get_page ke halaman terakhir.
    page = request.POST.get("page", "")
    if page.isdigit():
        return redirect(f"{reverse('upload')}?page={page}")
    return redirect("upload")


def _hitung_review_batch(batch):
    """Jumlah keputusan review manual yang bergantung pada batch ini (M3).

    Dua jejak: (a) ReviewAction pada hasil di dalam batch, (b) MatchResult di
    batch LAIN yang di-override manual dan `resolved_by_batch` menunjuk ke sini
    (override mengunci baris kredit ke batch asalnya — lihat CLAUDE.md).
    """
    n_review = ReviewAction.objects.filter(result__run__batch=batch).count()
    n_override = MatchResult.objects.filter(
        resolved_by_batch=batch, reason_code="manual_override"
    ).count()
    return n_review, n_override


@role_required("admin", "supervisor")
def delete_batch(request, pk):
    # Scope toko (M2): supervisor/admin memang melihat semua toko, tapi guard
    # struktural ini melindungi bila kelak ada peran lain yang lolos decorator.
    batch = get_object_or_404(ReconBatch, pk=pk, toko__in=tokos_for(request.user))
    if request.method == "POST":
        no = _batch_no(batch)
        n_runs = batch.runs.count()
        toko = batch.toko
        recon_date = batch.recon_date.isoformat() if batch.recon_date else ""
        buckets = (batch.summary or {}).get("buckets", {})
        n_review, n_override = _hitung_review_batch(batch)
        with transaction.atomic():
            # Batalkan dulu settle terlambat yang dilakukan batch ini di batch lain,
            # baru hapus — baris kredit terkait kembali "menunggu settlement".
            n_reverted = revert_late_settlements(batch)
            batch.delete()
        # M5: snapshot dicatat SEBELUM data hilang dari memori — jejak audit
        # harus bisa menjawab "batch tanggal berapa, isinya apa" tanpa batch-nya.
        catat(request.user, "hapus_batch", f"Batch #{no}", toko=toko,
              batch_pk=pk, n_runs=n_runs, recon_date=recon_date,
              cocok=buckets.get("cocok"), tinjau=buckets.get("perlu_tinjau"),
              tidak_cocok=buckets.get("tidak_cocok"),
              n_review=n_review + n_override)
        msg = f"Batch #{no} dihapus — {n_runs} run ikut terhapus. Transaksi tetap utuh."
        if n_reverted:
            msg += f" {n_reverted} settle terlambat dikembalikan ke tidak cocok."
        messages.success(request, msg)
    return redirect("reconcile")


@role_required("admin", "supervisor")
def bulk_delete_batches(request):
    """Hapus banyak batch sekaligus dari Riwayat Batch (checkbox).

    Pola sama bulk_delete_uploads: admin + supervisor SETARA (dua guard khusus
    supervisor dari v1.22.0 dicabut atas keputusan pemilik), dibatasi toko
    aktif, transaksi tetap utuh, settle terlambat di-revert per batch.
    """
    if request.method == "POST":
        active = _active_toko(request)
        if active is None:
            # FAIL-CLOSED (M1): tanpa toko aktif filter toko tidak bisa
            # dipasang — melanjutkan berarti penghapusan lintas-toko.
            messages.error(request, "Toko aktif tidak ditemukan — tidak ada batch yang dihapus.")
            return redirect("reconcile")
        ids = [i for i in request.POST.getlist("batch_ids") if str(i).isdecimal()]
        qs = ReconBatch.objects.filter(pk__in=ids, toko=active).select_related("toko")
        # Urut TERBARU dulu: guard "hanya batch terakhir" (M4) dievaluasi di
        # dalam transaksi yang sama, jadi ekor berurutan (23 lalu 22) bisa
        # terhapus bersih — urutan lama-dulu menolak 22 karena 23 masih ada.
        batches = list(qs.order_by(F("recon_date").desc(nulls_last=True), "-id"))
        n_batch = n_runs = n_reverted = n_review_hilang = 0
        labels = []
        with transaction.atomic():
            for batch in batches:
                no = _batch_no(batch)
                n_review, n_override = _hitung_review_batch(batch)
                n_review_hilang += n_review + n_override
                n_runs += batch.runs.count()
                n_reverted += revert_late_settlements(batch)
                tgl = batch.recon_date.strftime("%d/%m/%Y") if batch.recon_date else "—"
                labels.append(f"#{no} ({tgl})")
                batch.delete()
                n_batch += 1
        if n_batch:
            # `n_review` dicatat karena sejak guard v1.22.0 dicabut, batch
            # ber-review manual BOLEH dihapus — angka ini satu-satunya jejak
            # yang tersisa bahwa keputusan itu pernah ada (ReviewAction ikut
            # mati lewat cascade run → result → action).
            catat(
                request.user, "hapus_batch_massal", f"{n_batch} batch",
                toko=active, n_batch=n_batch, n_runs=n_runs,
                n_review=n_review_hilang,
                batches=", ".join(labels)[:1000],
            )
            msg = (
                f"{n_batch} batch dihapus — {n_runs} run ikut terhapus. "
                "Transaksi tetap utuh."
            )
            if n_reverted:
                msg += f" {n_reverted} settle terlambat dikembalikan ke tidak cocok."
            messages.success(request, msg)
        elif ids:
            messages.info(request, "Tidak ada batch terpilih yang bisa dihapus.")
    # Kembali ke filter bulan/sumber yang sama (hanya token aman)
    q = []
    bulan = (request.POST.get("bulan") or "").strip()
    bank = (request.POST.get("bank") or "").strip()
    if bulan and len(bulan) == 7 and bulan[4] == "-" and bulan[:4].isdigit() and bulan[5:].isdigit():
        q.append(f"bulan={bulan}")
    if bank in ("bank", "gateway"):
        q.append(f"bank={bank}")
    if q:
        return redirect(f"{reverse('reconcile')}?{'&'.join(q)}")
    return redirect("reconcile")


@admin_required
def delete_toko(request, pk):
    t = get_object_or_404(Toko, pk=pk)
    if request.method == "POST":
        name = t.name
        with transaction.atomic():
            n_tx = Transaction.objects.filter(toko=t).count()
            n_up = Upload.objects.filter(toko=t).count()
            n_batch = ReconBatch.objects.filter(toko=t).count()
            # Hapus file fisik tiap upload sebelum baris DB-nya hilang.
            for up in Upload.objects.filter(toko=t):
                if up.file:
                    up.file.delete(save=False)
            # Bongkar dependen PROTECT dulu, baru toko-nya (belt-and-suspenders).
            ReconBatch.objects.filter(toko=t).delete()
            Upload.objects.filter(toko=t).delete()
            Transaction.objects.filter(toko=t).delete()
            t.delete()
        catat(request.user, "hapus_toko", name, n_tx=n_tx, n_up=n_up, n_batch=n_batch)
        messages.success(
            request,
            f"Toko {name} dihapus permanen — {n_tx} transaksi, {n_up} upload, {n_batch} batch ikut terhapus.",
        )
    return redirect("kelola_toko")


@admin_required
def delete_user(request, pk):
    User = get_user_model()
    target = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        if target == request.user:
            messages.error(request, "Tidak bisa menghapus akunmu sendiri.")
        else:
            username = target.username
            target.delete()
            catat(request.user, "hapus_user", username)
            messages.success(request, f"Pengguna {username} dihapus permanen.")
    return redirect("kelola_user")


@admin_required
def kelola_ip(request):
    """Kelola allowlist IP (`web.middleware.IPAllowlistMiddleware`) — hanya
    menggerbang auditor & supervisor; admin tidak pernah terkunci dari sini."""
    if request.method == "POST" and request.POST.get("action") == "create":
        label = (request.POST.get("label") or "").strip()[:100]
        cidr_raw = (request.POST.get("cidr") or "").strip()
        if not label:
            messages.error(request, "Label wajib diisi.")
        elif not cidr_raw:
            messages.error(request, "IP/CIDR wajib diisi.")
        else:
            try:
                net = ipaddress.ip_network(cidr_raw, strict=False)
            except ValueError:
                messages.error(request, f"'{cidr_raw}' bukan IP atau CIDR yang valid.")
            else:
                if net.prefixlen == 0:
                    # /0 (0.0.0.0/0 atau ::/0) mencakup SELURUH internet — kalau
                    # lolos, entri ini sama saja mematikan gerbang untuk semua
                    # orang (fitur jadi dorman tanpa admin sadar).
                    messages.error(
                        request,
                        "Cakupan /0 tidak diizinkan — itu mematikan gembok utk semua orang.")
                else:
                    # Normalisasi: simpan bentuk kanonik jaringan (mis. "138.201.14.7/16"
                    # → "138.201.0.0/16") supaya tampilan = kebenaran, dan supaya
                    # pengecekan duplikat di bawah ini tidak lolos gara-gara notasi beda.
                    cidr = str(net)
                    if AllowedIP.objects.filter(cidr=cidr).exists():
                        messages.error(
                            request,
                            f"IP/CIDR {cidr} sudah ada di allowlist — "
                            "mungkin berstatus nonaktif (cek daftar di bawah).",
                        )
                    else:
                        entri = AllowedIP.objects.create(label=label, cidr=cidr, dibuat_oleh=request.user)
                        catat(request.user, "buat_ip_allow", entri.label, label=label, cidr=cidr)
                        messages.success(request, f"IP {cidr} ({label}) ditambahkan ke allowlist.")
        return redirect("kelola_ip")
    if request.method == "POST" and request.POST.get("action") == "toggle":
        eid = request.POST.get("ip_id", "")
        if not eid.isdecimal():
            messages.error(request, "ID entri tidak valid.")
            return redirect("kelola_ip")
        entri = get_object_or_404(AllowedIP, pk=eid)
        entri.aktif = not entri.aktif
        entri.save(update_fields=["aktif"])
        catat(request.user, "toggle_ip_allow", entri.label, label=entri.label, cidr=entri.cidr,
              aktif=entri.aktif)
        messages.success(
            request, f"IP {entri.cidr} ({entri.label}) {'diaktifkan' if entri.aktif else 'dinonaktifkan'}.")
        return redirect("kelola_ip")
    if request.method == "POST" and request.POST.get("action") == "delete":
        eid = request.POST.get("ip_id", "")
        if not eid.isdecimal():
            messages.error(request, "ID entri tidak valid.")
            return redirect("kelola_ip")
        entri = get_object_or_404(AllowedIP, pk=eid)
        label, cidr = entri.label, entri.cidr
        entri.delete()
        catat(request.user, "hapus_ip_allow", label, label=label, cidr=cidr)
        messages.success(request, f"IP {cidr} ({label}) dihapus dari allowlist.")
        return redirect("kelola_ip")
    entries = AllowedIP.objects.select_related("dibuat_oleh").order_by("-aktif", "label")
    return render(request, "web/kelola/ip.html", {"entries": entries, **BEBAS_TOKO})
