"""Panel admin: kelola pengguna & toko, hapus data. Semua view digate admin_required."""
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from reconciliation.models import ReconBatch
from sources.models import Toko, Upload
from web.access import admin_required


VALID_ROLES = ("admin", "supervisor", "auditor")


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
        err = None
        if not username:
            err = "Username wajib diisi."
        elif User.objects.filter(username=username).exists():
            err = f"Username {username} sudah dipakai."
        elif len(password) < 8:
            err = "Password minimal 8 karakter."
        elif role not in VALID_ROLES:
            err = "Role tidak dikenal."
        elif role == "auditor" and not toko_ids:
            err = "Auditor wajib ditugaskan minimal 1 toko."
        if err:
            messages.error(request, err)
        else:
            u = User.objects.create_user(username=username, password=password, first_name=nama, role=role)
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
        if len(pw) < 8:
            messages.error(request, "Password minimal 8 karakter.")
        else:
            target.set_password(pw)
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
        n_tx = up.transactions.count()
        if up.file:
            up.file.delete(save=False)
        up.delete()
        messages.success(request, f"{name} dihapus — {n_tx} transaksi ikut terhapus.")
    return redirect("upload")


@admin_required
def delete_batch(request, pk):
    batch = get_object_or_404(ReconBatch, pk=pk)
    if request.method == "POST":
        n_runs = batch.runs.count()
        batch.delete()
        messages.success(request, f"Batch #{pk} dihapus — {n_runs} run ikut terhapus. Transaksi tetap utuh.")
    return redirect("reconcile")
