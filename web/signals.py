"""Signal receiver: tandai sesi untuk tampilkan pop-up pengingat toko setelah
login, serta jejak audit login/logout/gagal-login (C6).

`User.last_login` cuma satu kolom yang ditimpa tiap login — bukan riwayat.
Ketiga receiver di bawah menulis satu `AuditLog` per kejadian lewat
`core.audit.catat()`, yang sudah best-effort (self try/except) — tapi tiap
receiver di sini TETAP dibungkus try/except sendiri karena kode sebelum
`catat()` (mis. membaca `credentials`) juga tidak boleh menggagalkan alur
login/logout kalau ada yang tak terduga.
"""
import logging

from django.contrib.auth.signals import (
    user_logged_in, user_logged_out, user_login_failed,
)
from django.dispatch import receiver

from core.audit import catat

logger = logging.getLogger(__name__)


@receiver(user_logged_in)
def tandai_pengingat_toko(sender, request, user, **kwargs):
    request.session["show_toko_reminder"] = True


@receiver(user_logged_in)
def catat_login(sender, request, user, **kwargs):
    try:
        catat(user, "login", getattr(user, "username", "") or "", request=request)
    except Exception:  # noqa: BLE001 — audit tak boleh menggagalkan login
        logger.exception("gagal mencatat audit login")


@receiver(user_logged_out)
def catat_logout(sender, request, user, **kwargs):
    # `user` bisa None (mis. sesi anonim yang memanggil logout).
    try:
        username = getattr(user, "username", "") or ""
        catat(user, "logout", username or "(anonim)", request=request)
    except Exception:  # noqa: BLE001
        logger.exception("gagal mencatat audit logout")


@receiver(user_login_failed)
def catat_login_gagal(sender, credentials=None, request=None, **kwargs):
    # `request` TIDAK SELALU dikirim Django di jalur ini — default None.
    # `credentials` bisa memuat kunci `password` (Django sudah menyensornya
    # jadi "********" sebelum signal ini dikirim, tapi JANGAN pernah ambil
    # risiko): ambil HANYA `username` percobaan, jangan simpan dict apa adanya.
    try:
        username = ""
        if isinstance(credentials, dict):
            username = str(credentials.get("username") or "")[:150]
        catat(None, "login_gagal", username or "(tidak diketahui)", request=request)
    except Exception:  # noqa: BLE001
        logger.exception("gagal mencatat audit login gagal")
