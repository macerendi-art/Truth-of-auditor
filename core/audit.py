"""Helper pencatat AuditLog — satu panggilan per aksi bermakna.

Sengaja best-effort: kegagalan mencatat tidak boleh menggagalkan aksi utamanya
(hapus/reconcile tetap jalan), tapi tetap terlihat di log server.
"""
import logging

from core.models import AuditLog

logger = logging.getLogger(__name__)


def catat(user, aksi, objek, toko=None, **detail):
    try:
        AuditLog.objects.create(
            user=user if getattr(user, "pk", None) else None,
            username=getattr(user, "username", "") or "",
            toko=toko, aksi=aksi, objek=str(objek)[:200], detail=detail,
        )
    except Exception:  # noqa: BLE001
        logger.exception("gagal mencatat audit: %s %s", aksi, objek)
