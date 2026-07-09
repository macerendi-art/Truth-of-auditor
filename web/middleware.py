"""Middleware gerbang: paksa user ber-flag must_change_password ke halaman ganti password."""
from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """Selama flag menyala, semua halaman selain allowlist dialihkan ke
    halaman ganti password — tidak bisa di-bypass dengan mengetik URL langsung.

    Allowlist: halaman ganti password itu sendiri (hindari loop), logout
    (user harus bisa keluar), dan aset statis/media (agar CSS/font halaman termuat).
    Harus dipasang SETELAH AuthenticationMiddleware (butuh request.user).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "must_change_password", False):
            path = request.path
            allowed = (reverse("ganti_password"), reverse("logout"))
            asset_prefixes = tuple(p for p in (settings.STATIC_URL, settings.MEDIA_URL) if p)
            if path not in allowed and not path.lstrip("/").startswith(asset_prefixes):
                return redirect("ganti_password")
        return self.get_response(request)
