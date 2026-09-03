"""Kontrol akses berbasis peran (RBAC) per Toko."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from sources.models import Toko

# Sentinel sesi mode multi-toko: `session["active_toko_id"]` yang biasanya
# berisi id numerik bisa berisi salah satu string ini. Hanya admin yang boleh
# memasangnya (lihat `web.views.set_toko`). Semua view single-toko TETAP
# menerima objek Toko nyata — `_active_toko` menerjemahkan sentinel jadi
# toko fallback di dalam lingkup mode.
SEMUA_TOKO = "all"
MODE_PUSAT = "kep_pusat"
MODE_PARTNER = "kep_partner"
# Semua sentinel multi — filter(id=sentinel) MELEDAK; harus dicegat dulu.
MULTI_TOKO_SENTINELS = frozenset({SEMUA_TOKO, MODE_PUSAT, MODE_PARTNER})
MULTI_TOKO_LABELS = {
    SEMUA_TOKO: "Semua Toko",
    MODE_PUSAT: "Toko Pusat",
    MODE_PARTNER: "Toko Partner",
}


def is_admin(user) -> bool:
    return bool(user.is_authenticated and (user.is_superuser or user.role == "admin"))


def multi_mode(request):
    """Sentinel multi-toko aktif, atau None.

    Nilai: SEMUA_TOKO / MODE_PUSAT / MODE_PARTNER. Hanya admin — pencabutan
    peran mematikan mode tanpa menyentuh sesi warisan.
    """
    user = getattr(request, "user", None)
    if not is_admin(user):
        return None
    tid = request.session.get("active_toko_id")
    return tid if tid in MULTI_TOKO_SENTINELS else None


def mode_semua(request) -> bool:
    """True bila sesi di mode multi-toko (Semua / Pusat / Partner) DAN admin.

    Nama historis \"semua\" dipertahankan: flag ini membuka dashboard gabungan,
    ceklis hutang multi-toko, bar mode, dan badge tinjau lintas toko. Lingkup
    toko di dalam mode ditentukan `scope_tokos` (bukan selalu seluruh toko).
    """
    return multi_mode(request) is not None


def tokos_for(user):
    """Queryset Toko aktif yang boleh diakses user — satu-satunya sumber kebenaran RBAC."""
    qs = Toko.objects.filter(is_active=True).order_by("name")
    if not user.is_authenticated:
        return qs.none()
    if user.is_superuser or user.role in ("admin", "supervisor"):
        return qs
    return qs.filter(assigned_users=user)


def scope_tokos(user, mode=None):
    """Queryset Toko untuk lingkup mode multi (atau seluruh RBAC bila mode=None/all).

    `mode` = nilai `multi_mode` / sentinel, atau None (= semua yang diizinkan).
    """
    qs = tokos_for(user)
    if mode == MODE_PUSAT:
        return qs.filter(kepemilikan=Toko.KEPEMILIKAN_PUSAT)
    if mode == MODE_PARTNER:
        return qs.filter(kepemilikan=Toko.KEPEMILIKAN_PARTNER)
    return qs


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


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not is_admin(request.user):
            messages.error(request, "Akses ditolak — khusus admin.")
            return redirect("dashboard")
        return view(request, *args, **kwargs)

    return wrapper


def boleh_hapus_data(user) -> bool:
    """True bila user boleh menghapus DATA KERJA (admin + supervisor).

    Cakupannya: batch rekonsiliasi dan berkas unggahan. Keputusan pemilik
    2026-09: supervisor setara admin untuk penghapusan data kerja — dua guard
    khusus supervisor yang sempat ada di v1.22.0 (hanya batch terakhir, tolak
    bila ada review manual) DICABUT atas permintaan pemilik.

    Yang TIDAK ikut, dan sengaja: menu `/kelola/` (toko, pengguna, allowlist
    IP) tetap `is_admin` — itu manajemen organisasi, bukan data kerja.

    Guard INTEGRITAS tetap berlaku untuk semua peran termasuk admin:
    `_locking_batches` tetap menolak menghapus upload yang buktinya dipakai
    hasil rekonsiliasi. Itu bukan guard peran, jadi tak ikut dicabut.
    """
    return bool(
        user.is_authenticated
        and (is_admin(user) or getattr(user, "role", "") == "supervisor")
    )


def role_required(*roles):
    """Decorator gerbang peran, pola sama `admin_required`.

    `role_required("admin", "supervisor")` meloloskan superuser dan user yang
    `role`-nya ada di daftar; selain itu ditolak dengan pesan + redirect
    dashboard. Dipakai view hapus batch yang kini dibuka untuk supervisor.
    """

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            u = request.user
            if not (u.is_superuser or getattr(u, "role", "") in roles):
                messages.error(request, "Akses ditolak — peran Anda tidak berwenang.")
                return redirect("dashboard")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
