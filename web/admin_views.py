"""Panel admin: kelola pengguna & toko, hapus data. Semua view digate admin_required."""
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from sources.models import Toko
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
        t = get_object_or_404(Toko, pk=request.POST.get("toko_id"))
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
    return render(request, "web/kelola/user_edit.html", {
        "target": target,
        "tokos": Toko.objects.filter(is_active=True).order_by("name"),
        "roles": User.Role.choices,
        "target_toko_ids": set(target.allowed_tokos.values_list("id", flat=True)),
    })
