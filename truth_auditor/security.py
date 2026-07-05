"""Resolusi konfigurasi keamanan yang harus fail-safe.

Dipisah dari settings.py supaya bisa diuji unit tanpa reload modul settings.
"""
from django.core.exceptions import ImproperlyConfigured

# Hanya untuk pengembangan lokal (DEBUG=True). Produksi wajib env SECRET_KEY.
_DEV_FALLBACK = "django-insecure-dev-only-wb5cb68!r##d-ht+w%ahp=(1ot)$o$p-rz"


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
