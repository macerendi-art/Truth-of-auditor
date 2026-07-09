"""Panel admin: kelola pengguna & toko, hapus data. Semua view digate admin_required."""
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from core.audit import catat
from reconciliation.engine import revert_late_settlements
from reconciliation.models import MatchResult, ReconBatch
from sources.models import Toko, Upload
from transactions.models import Transaction
from web.access import admin_required
from web.views import _active_toko


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
        if not kode or not kode.isalnum():
            messages.error(request, "Kode toko wajib huruf/angka tanpa spasi.")
        elif Toko.objects.filter(key=kode.lower()).exists():
            messages.error(request, f"Toko {kode.upper()} sudah ada.")
        else:
            Toko.objects.create(key=kode.lower(), name=kode.upper())
            messages.success(request, f"Toko {kode.upper()} ditambahkan.")
        return redirect("kelola_toko")
    if request.method == "POST" and request.POST.get("action") == "toggle":
        tid = request.POST.get("toko_id", "")
        if not tid.isdecimal():
            messages.error(request, "ID toko tidak valid.")
            return redirect("kelola_toko")
        t = get_object_or_404(Toko, pk=tid)
        t.is_active = not t.is_active
        t.save(update_fields=["is_active"])
        messages.success(request, f"Toko {t.name} {'diaktifkan' if t.is_active else 'dinonaktifkan'}.")
        return redirect("kelola_toko")
    tokos = Toko.objects.annotate(
        n_tx=Count("transaction", distinct=True),
        n_up=Count("upload", distinct=True),
    ).order_by("name")
    return render(request, "web/kelola/toko.html", {"tokos": tokos})


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
            messages.success(request, f"User {username} ({role}) dibuat.")
        return redirect("kelola_user")
    users = User.objects.prefetch_related("allowed_tokos").order_by("username")
    return render(request, "web/kelola/users.html", {
        "users": users,
        "tokos": Toko.objects.filter(is_active=True).order_by("name"),
        "roles": User.Role.choices,
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
            messages.success(request, f"Password {target.username} di-reset.")
            return redirect("kelola_user")
    elif action == "toggle":
        if target == request.user:
            messages.error(request, "Tidak bisa menonaktifkan akunmu sendiri.")
        else:
            target.is_active = not target.is_active
            target.save(update_fields=["is_active"])
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
    })


@admin_required
def delete_upload(request, pk):
    up = get_object_or_404(Upload, pk=pk)
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


@admin_required
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
        for up in ups:
            if _locking_batches(up):
                dilewati.append(up.original_name or f"Upload #{up.pk}")
                continue
            n_tx += up.transactions.count()
            if up.file:
                up.file.delete(save=False)
            up.delete()
            n_file += 1
        if n_file:
            catat(request.user, "hapus_upload_massal", f"{n_file} file",
                  toko=active, n_file=n_file, n_tx=n_tx)
            messages.success(request, f"{n_file} file dihapus — {n_tx} transaksi ikut terhapus.")
        if dilewati:
            messages.error(
                request,
                f"{len(dilewati)} file dilewati karena dipakai hasil rekonsiliasi: "
                f"{', '.join(dilewati)}. Hapus batch terkait dulu.",
            )
    return redirect("upload")


@admin_required
def delete_batch(request, pk):
    batch = get_object_or_404(ReconBatch, pk=pk)
    if request.method == "POST":
        no = ReconBatch.objects.filter(toko=batch.toko, id__lte=batch.id).count()
        n_runs = batch.runs.count()
        toko = batch.toko
        with transaction.atomic():
            # Batalkan dulu settle terlambat yang dilakukan batch ini di batch lain,
            # baru hapus — baris kredit terkait kembali "menunggu settlement".
            n_reverted = revert_late_settlements(batch)
            batch.delete()
        catat(request.user, "hapus_batch", f"Batch #{no}", toko=toko,
              batch_pk=pk, n_runs=n_runs)
        msg = f"Batch #{no} dihapus — {n_runs} run ikut terhapus. Transaksi tetap utuh."
        if n_reverted:
            msg += f" {n_reverted} settle terlambat dikembalikan ke tidak cocok."
        messages.success(request, msg)
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
            messages.success(request, f"Pengguna {username} dihapus permanen.")
    return redirect("kelola_user")
