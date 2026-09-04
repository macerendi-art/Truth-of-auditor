"""Logika murni penguncian percobaan login (C4) — dipanggil dari
`loginguard.backends.LockoutBackend` dan `manage.py buka_kunci_login`.

Semua ambang dibaca dari `settings` DI DALAM tiap fungsi (bukan konstanta
modul) supaya `override_settings` di tes benar-benar berlaku, dan supaya
env bisa diubah tanpa deploy ulang (persyaratan butir 5).
"""
import hashlib
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.utils import timezone

from .models import LoginAttempt

logger = logging.getLogger(__name__)

# Panjang maksimum representasi IPv6 — pola sama seperti
# `web.middleware.IPAllowlistMiddleware` (baris audit `ip_blokir`).
_IP_MAXLEN = 45

# P5(b): baris `LoginAttempt` yang tak disentuh selama ini DAN tidak sedang
# mengunci dianggap mati dan boleh dibuang. 24 jam >> LOGIN_LOCKOUT_MINUTES
# (15 menit bawaan); kunci yang masih aktif TIDAK PERNAH ikut dibuang apa pun
# umurnya (syarat `locked_until` di `bersihkan_kedaluwarsa`).
RETENSI_BARIS = timedelta(hours=24)


def _norm_username(username):
    return (username or "").strip().lower()[:150]


def kunci_username(username):
    """Kunci baris `LoginAttempt` untuk sebuah username yang DIKETIK (P4).

    Nilai kolom username dari form login TIDAK PERNAH disimpan apa adanya:
    kesalahan paling umum pengguna adalah mengetik kata sandi di kolom
    username (auto-fill meleset, tab tertukar), dan tabel ini tampil di
    Django admin, ikut cadangan harian, dan ikut ke staging. Maka:

    - cocok dengan user yang ADA (`iexact` — `_norm_username` sudah
      lowercase, dan penguncian tak boleh bisa dihindari lewat kapitalisasi)
      → username KANONIK dari DB (lowercase; nilai DB, bukan ketikan);
    - tidak cocok → `"?" + sha256(ketikan ternormalisasi)[:40]`. Tetap
      deterministik, jadi penguncian username-tak-dikenal TETAP bekerja
      persis seperti username asli (non-leak: "terkunci" tidak jadi oracle
      keberadaan akun) tanpa satu byte ketikan pun menyentuh DB. Awalan `?`
      tidak mungkin bertabrakan dengan username asli — validator username
      Django hanya mengizinkan huruf/angka/`@.+-_`.

    SENGAJA tidak idempoten: `kunci_username(kunci_username(x))` ≠
    `kunci_username(x)`. Selalu berikan username MENTAH ke fungsi-fungsi di
    modul ini, jangan kunci yang sudah dipetakan. Bila dua user berbeda hanya
    kapitalisasi (Django mengizinkannya), keduanya berbagi satu kunci —
    diterima, konservatif, bukan celah.
    """
    norm = _norm_username(username)
    if not norm:
        return ""
    user = (
        get_user_model().objects
        .filter(username__iexact=norm)
        .order_by("id")
        .only("username")
        .first()
    )
    if user is not None:
        return (user.username or "").lower()[:150]
    return "?" + hashlib.sha256(norm.encode("utf-8")).hexdigest()[:40]


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
    username = kunci_username(username)
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
    username = kunci_username(username)
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
    """Login benar → hapus jejak kegagalan (mulai bersih untuk pasangan ini).

    Sekalian membuang baris kedaluwarsa SELURUH tabel (P5(b), oportunistik):
    login benar jarang (puluhan per hari), jadi satu DELETE tambahan di sini
    murah, sementara tabel tak pernah menumpuk tanpa batas walau tak ada
    cron yang menulis ke produksi. Dibungkus try/except — pembersihan tak
    boleh menggagalkan login yang sudah benar.
    """
    username = kunci_username(username)
    if not username:
        return
    ip = _norm_ip(ip)
    LoginAttempt.objects.filter(username=username, ip=ip).delete()
    try:
        bersihkan_kedaluwarsa()
    except Exception:  # noqa: BLE001 — pembersihan tak boleh menggagalkan login
        logger.exception("gagal membersihkan LoginAttempt kedaluwarsa")


def bersihkan_kedaluwarsa(now=None) -> int:
    """Buang baris yang sudah MATI: tak disentuh > `RETENSI_BARIS` DAN tidak
    sedang mengunci (`locked_until` kosong atau sudah lewat). Kunci aktif
    tidak pernah ikut terbuang apa pun umurnya. Kembalikan jumlah baris.

    Ada karena `register_failure` membuat satu baris per (username, IP) dan
    hanya `register_success` pasangan itu sendiri yang menghapusnya —
    penyerang yang merotasi username tak pernah login benar, jadi barisnya
    tak pernah hilang sendiri (P5).
    """
    now = now or timezone.now()
    batas = now - RETENSI_BARIS
    qs = LoginAttempt.objects.filter(updated_at__lt=batas).filter(
        models.Q(locked_until__isnull=True) | models.Q(locked_until__lt=now)
    )
    jumlah, _ = qs.delete()
    return jumlah


def buka_kunci(username=None) -> int:
    """Pemulihan NON-HTTP (dipanggil `manage.py buka_kunci_login`).

    `username=None` → hapus SEMUA baris (buka semua kunci, semua user).
    Selain itu → hapus semua baris (lintas SEMUA IP) milik username itu.
    Kembalikan jumlah baris yang dihapus (untuk pesan command).
    """
    qs = LoginAttempt.objects.all()
    if username:
        qs = qs.filter(username=kunci_username(username))
    jumlah = qs.count()
    qs.delete()
    return jumlah
