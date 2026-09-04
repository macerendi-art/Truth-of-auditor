"""Logika murni penguncian percobaan login (C4) — dipanggil dari
`loginguard.backends.LockoutBackend` dan `manage.py buka_kunci_login`.

Semua ambang dibaca dari `settings` DI DALAM tiap fungsi (bukan konstanta
modul) supaya `override_settings` di tes benar-benar berlaku, dan supaya
env bisa diubah tanpa deploy ulang (persyaratan butir 5).
"""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import LoginAttempt

# Panjang maksimum representasi IPv6 — pola sama seperti
# `web.middleware.IPAllowlistMiddleware` (baris audit `ip_blokir`).
_IP_MAXLEN = 45


def _norm_username(username):
    return (username or "").strip().lower()[:150]


def _norm_ip(ip):
    return (ip or "")[:_IP_MAXLEN]


def _enabled():
    return bool(getattr(settings, "LOGIN_LOCKOUT_ENABLED", True))


def _threshold():
    # Klem minimum 1 — ambang 0/negatif dari env yang salah ketik akan
    # mengunci semua orang pada percobaan pertama (termasuk login benar).
    return max(1, int(getattr(settings, "LOGIN_LOCKOUT_THRESHOLD", 5)))


def _lockout_minutes():
    return max(1, int(getattr(settings, "LOGIN_LOCKOUT_MINUTES", 15)))


def is_locked(username, ip) -> bool:
    """True bila (username, ip) sedang dalam masa kunci aktif.

    Kill switch `LOGIN_LOCKOUT_ENABLED=False` membuat ini SELALU False —
    jalan pulih non-HTTP kedua (selain `buka_kunci_login`): kalau fitur ini
    sendiri yang bermasalah di produksi, matikan lewat env tanpa deploy
    ulang, sama seperti pola `GEO_BLOCK_ENABLED`.
    """
    if not _enabled():
        return False
    username = _norm_username(username)
    if not username:
        return False
    ip = _norm_ip(ip)
    try:
        obj = LoginAttempt.objects.get(username=username, ip=ip)
    except LoginAttempt.DoesNotExist:
        return False
    return bool(obj.locked_until and obj.locked_until > timezone.now())


def register_failure(username, ip) -> None:
    """Tambah satu kegagalan; kunci begitu ambang tercapai.

    Bila kunci SEBELUMNYA sudah kedaluwarsa, hitungan dimulai ulang dari 0
    dulu (jendela baru) sebelum menambah kegagalan ini — satu kegagalan
    lawas dari kunci yang sudah lepas tidak boleh langsung mengunci lagi
    tanpa memenuhi ambang penuh dari awal.

    `select_for_update()` di dalam `atomic()`: mengunci baris di Postgres
    (produksi) untuk mengurangi race dua request gagal bersamaan; di SQLite
    (dev/tes) `has_select_for_update=False` membuat compiler MELEWATI klausa
    ini secara diam-diam (bukan error) — jadi aman dipakai di kedua backend.
    """
    if not _enabled():
        return
    username = _norm_username(username)
    if not username:
        return
    ip = _norm_ip(ip)
    now = timezone.now()
    with transaction.atomic():
        obj, created = LoginAttempt.objects.select_for_update().get_or_create(
            username=username, ip=ip,
        )
        if not created and obj.locked_until and obj.locked_until <= now:
            obj.fail_count = 0
            obj.locked_until = None
        obj.fail_count += 1
        if obj.fail_count >= _threshold():
            obj.locked_until = now + timedelta(minutes=_lockout_minutes())
        obj.save(update_fields=["fail_count", "locked_until", "updated_at"])


def register_success(username, ip) -> None:
    """Login benar → hapus jejak kegagalan (mulai bersih untuk pasangan ini)."""
    username = _norm_username(username)
    if not username:
        return
    ip = _norm_ip(ip)
    LoginAttempt.objects.filter(username=username, ip=ip).delete()


def buka_kunci(username=None) -> int:
    """Pemulihan NON-HTTP (dipanggil `manage.py buka_kunci_login`).

    `username=None` → hapus SEMUA baris (buka semua kunci, semua user).
    Selain itu → hapus semua baris (lintas SEMUA IP) milik username itu.
    Kembalikan jumlah baris yang dihapus (untuk pesan command).
    """
    qs = LoginAttempt.objects.all()
    if username:
        qs = qs.filter(username=_norm_username(username))
    jumlah = qs.count()
    qs.delete()
    return jumlah
