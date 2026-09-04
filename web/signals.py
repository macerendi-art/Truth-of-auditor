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

from django.contrib.auth import get_user_model
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


def _objek_login_gagal(diketik):
    """(objek, detail) audit `login_gagal` — ketikan kolom username TIDAK
    PERNAH disimpan (P4, tinjauan akhir 04-09-2026).

    Kesalahan pengguna yang sangat umum: mengetik kata sandi di kolom
    username (auto-fill meleset, tab tertukar). Django hanya menyensor kunci
    `password`; kolom username tidak dianggap rahasia — dan `AuditLog.objek`
    tampil ke semua admin di /kelola/log/, ikut cadangan harian, ikut ke
    staging, tanpa kedaluwarsa. Maka yang dicatat:

    - cocok user yang ADA (`iexact`, deterministik `order_by("id")`) →
      username KANONIK dari DB. Nilai keamanannya utuh: kita tetap tahu akun
      mana yang disasar. `iexact` (bukan `exact` ala `get_by_natural_key`)
      supaya salah kapital tetap menunjuk akunnya — yang disimpan tetap
      nilai DB, bukan ketikan;
    - tidak cocok → `"(username tidak dikenal)"` + `panjang` ketikan di
      detail. Tanpa hash: hash dari kata sandi yang salah kolom tetap
      turunan rahasia. Ini log server-side, bukan respons HTTP, jadi tak ada
      enumerasi yang bocor.
    """
    diketik = (diketik or "").strip()
    if not diketik:
        return "(tidak diketahui)", {}
    user = (
        get_user_model().objects
        .filter(username__iexact=diketik[:150])
        .order_by("id")
        .only("username")
        .first()
    )
    if user is not None:
        return user.username, {}
    return "(username tidak dikenal)", {"panjang": len(diketik)}


@receiver(user_login_failed)
def catat_login_gagal(sender, credentials=None, request=None, **kwargs):
    # `request` TIDAK SELALU dikirim Django di jalur ini — default None.
    # `credentials` bisa memuat kunci `password` (Django sudah menyensornya
    # jadi "********" sebelum signal ini dikirim, tapi JANGAN pernah ambil
    # risiko): ambil HANYA `username` percobaan, jangan simpan dict apa
    # adanya — dan `username` itu pun hanya dipakai untuk MENCARI user, tidak
    # pernah disimpan (lihat `_objek_login_gagal`).
    try:
        diketik = ""
        if isinstance(credentials, dict):
            diketik = str(credentials.get("username") or "")
        objek, detail = _objek_login_gagal(diketik)
        catat(None, "login_gagal", objek, request=request, **detail)
    except Exception:  # noqa: BLE001
        logger.exception("gagal mencatat audit login gagal")
