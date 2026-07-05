"""Resolusi konfigurasi keamanan yang harus fail-safe.

Dipisah dari settings.py supaya bisa diuji unit tanpa reload modul settings.
"""
from django.core.exceptions import ImproperlyConfigured

# Hanya untuk pengembangan lokal (DEBUG=True). Produksi wajib env SECRET_KEY.
_DEV_FALLBACK = "django-insecure-dev-only-wb5cb68!r##d-ht+w%ahp=(1ot)$o$p-rz"


def client_ip(request):
    """IP klien di belakang proxy Railway (utk lockout django-axes).

    REMOTE_ADDR = IP internal load balancer (berganti-ganti). Ambil hop
    TERAKHIR X-Forwarded-For: itu yang ditulis edge Railway (proxy tepercaya
    tunggal); entri kiriman penyerang berada di DEPAN dan diabaikan — spoof
    XFF tidak bisa dipakai menghindari lockout.
    """
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "")


def resolve_secret_key(env, debug):
    """SECRET_KEY dari env; produksi tanpa env = mati saat boot.

    Jalan diam-diam dengan key yang ada di repo berarti session & CSRF bisa
    dipalsukan siapa pun yang baca repo — lebih baik deploy gagal keras.
    """
    key = env.get("SECRET_KEY", "")
    if key:
        return key
    if debug:
        return _DEV_FALLBACK
    raise ImproperlyConfigured(
        "SECRET_KEY wajib di-set lewat environment variable saat DEBUG=False."
    )
