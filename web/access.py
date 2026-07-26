"""Kontrol akses berbasis peran (RBAC) per Toko."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from sources.models import Toko

# Sentinel sesi mode "Semua Toko": `session["active_toko_id"]` yang biasanya
# berisi id numerik bisa berisi string ini. Hanya admin yang boleh memasangnya
# (lihat `web.views.set_toko`). Semua view single-toko TETAP menerima objek Toko
# nyata — `_active_toko` menerjemahkan sentinel jadi toko fallback.
SEMUA_TOKO = "all"


def is_admin(user) -> bool:
    return bool(user.is_authenticated and (user.is_superuser or user.role == "admin"))


def mode_semua(request) -> bool:
    """True bila sesi sedang di mode Semua Toko DAN user memang admin.

    Cek peran ikut di sini supaya pencabutan hak admin langsung mematikan mode
    ini tanpa perlu menyentuh sesi yang sudah tersimpan.
    """
    return (
        request.session.get("active_toko_id") == SEMUA_TOKO
        and is_admin(request.user)
    )


def is_ip_gated(user) -> bool:
    """True bila user tunduk pada gerbang IP allowlist (`IPAllowlistMiddleware`).

    Hanya auditor & supervisor — admin/superuser SELALU dikecualikan (break-glass
    alami: admin harus selalu bisa masuk untuk membetulkan daftar allowlist itu
    sendiri, sekalipun sedang salah/kosong/mengunci semua orang lain).
    """
    return bool(
        user.is_authenticated
        and not is_admin(user)
        and getattr(user, "role", "") in ("auditor", "supervisor")
    )


def tokos_for(user):
    """Queryset Toko aktif yang boleh diakses user — satu-satunya sumber kebenaran RBAC."""
    qs = Toko.objects.filter(is_active=True).order_by("name")
    if not user.is_authenticated:
        return qs.none()
    if user.is_superuser or user.role in ("admin", "supervisor"):
        return qs
    return qs.filter(assigned_users=user)


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not is_admin(request.user):
            messages.error(request, "Akses ditolak — khusus admin.")
            return redirect("dashboard")
        return view(request, *args, **kwargs)

    return wrapper
