"""Helper pencatat AuditLog — satu panggilan per aksi bermakna.

Sengaja best-effort: kegagalan mencatat tidak boleh menggagalkan aksi utamanya
(hapus/reconcile tetap jalan), tapi tetap terlihat di log server.
"""
import ipaddress
import logging

from core.models import AuditLog

logger = logging.getLogger(__name__)

# Batas `AuditLog.user_agent` (CharField) — potong, jangan biarkan header
# klien yang sangat panjang mental di INSERT.
_USER_AGENT_MAXLEN = 255


def _ip_sah(ip):
    """IP klien yang boleh masuk `AuditLog.ip`, atau None (M1, 04-09-2026).

    Kolomnya `GenericIPAddressField` = `inet` di Postgres. String XFF yang
    bukan IP (`"unknown"`, `"1.2.3.4:80"`, `"x"`) membuat INSERT-nya
    `DataError`, dan `except` di `catat` menelannya — SELURUH baris audit
    hilang diam-diam, bukan cuma IP-nya. Hari ini tak bisa dieksploitasi
    (Railway menimpa XFF), tapi di belakang proxy yang meneruskan XFF apa
    adanya (mis. nginx Contabo yang salah konfigurasi) seorang auditor bisa
    memasang `X-Forwarded-For: x` lewat ekstensi browser dan setiap
    `hapus_batch`/`review` miliknya tak pernah tercatat. Jejak lebih penting
    daripada IP-nya: yang tak valid dijatuhkan ke None, barisnya tetap ditulis.
    """
    ip = (ip or "").strip()
    if not ip:
        return None
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        logger.warning("IP klien tak valid diabaikan di audit: %r", ip[:64])
        return None


def catat(user, aksi, objek, toko=None, request=None, **detail):
    """`request` OPSIONAL (C5) — 48 titik panggil lama tetap jalan tanpa
    perubahan. Bila diberikan, IP klien + user-agent ikut direkam di kolom
    asli (bukan `detail`, supaya bisa di-index/difilter belakangan).

    Resolusi IP memakai ULANG rantai anti-spoof `web.middleware` (XFF paling
    kiri, lalu `CF-Connecting-IP` bila lewat Cloudflare) — impor LOKAL di sini
    karena `web.middleware` sendiri mengimpor `catat` di atas (hindari siklus
    impor saat startup, sama seperti pola `IPAllowlistMiddleware`).
    """
    try:
        ip = None
        user_agent = ""
        if request is not None:
            from web.middleware import resolve_client_ip  # impor lokal: hindari siklus
            ip = _ip_sah(resolve_client_ip(request))
            user_agent = (request.META.get("HTTP_USER_AGENT") or "")[:_USER_AGENT_MAXLEN]
        AuditLog.objects.create(
            user=user if getattr(user, "pk", None) else None,
            username=getattr(user, "username", "") or "",
            toko=toko, aksi=aksi, objek=str(objek)[:200], detail=detail,
            ip=ip, user_agent=user_agent,
        )
    except Exception:  # noqa: BLE001
        logger.exception("gagal mencatat audit: %s %s", aksi, objek)
