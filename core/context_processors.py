"""Context processor versi — badge kecil di sidebar & footer login.

Sengaja O(1) dan tanpa query DB: `core.version.RILIS` adalah konstanta modul,
jadi ini aman dipasang global di SEMUA template termasuk halaman login.
"""

from core import version as _v


def versi(request):
    return {
        "app_versi": _v.versi(),
        "app_rilis": _v.rilis_terbaru(),
    }
