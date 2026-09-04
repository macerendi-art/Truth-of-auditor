"""Model penguncian percobaan login (C4) — satu baris per (username, IP).

KENAPA TABEL DB, BUKAN CACHE: `truth_auditor/settings.py` tidak mendefinisikan
`CACHES` sama sekali, jadi cache Django yang aktif adalah default
`LocMemCache` — penyimpanan PER PROSES. Produksi berjalan
`gunicorn --workers 4 --threads 8` (lihat CLAUDE.md bagian Performa): 4 proses
worker artinya 4 instance LocMem terpisah, sehingga ambang N percobaan yang
dimaksud sebenarnya jadi N×4 lintas proses — pembatas yang bocor 4×. Tabel DB
dibagi oleh SEMUA proses lewat koneksi Postgres yang sama, jadi hitungan
benar-benar global. Diverifikasi LANGSUNG (bukan diasumsikan): tidak ada
`CACHES`, tidak ada Redis, tidak ada dependensi cache bersama di
`requirements.txt` — lihat laporan gelombang ini untuk detail pemeriksaan.
"""
from django.db import models

from core.models import TimeStampedModel


class LoginAttempt(TimeStampedModel):
    """Penghitung kegagalan login berturut-turut untuk satu (username, IP).

    `username` BUKAN ketikan pengguna, melainkan KUNCI hasil
    `loginguard.throttle.kunci_username` (P4): username kanonik lowercase
    dari DB bila cocok user yang ada, selain itu `"?" + sha256[:40]` dari
    ketikan ternormalisasi. Kolom username form login sering diisi kata
    sandi (auto-fill meleset), dan tabel ini tampil di admin, ikut cadangan
    dan staging — ketikan mentah tidak boleh pernah mendarat di sini.
    Penguncian tetap tak bisa dihindari lewat kapitalisasi (kunci dipetakan
    dari bentuk `strip().lower()`). `ip` HASIL NORMALISASI
    juga (dipotong 45 karakter, panjang maksimum representasi IPv6 — pola
    yang sama dipakai `web.middleware.IPAllowlistMiddleware`).

    `fail_count` = kegagalan beruntun sejak reset terakhir (login benar,
    kunci kedaluwarsa, atau pemulihan lewat `manage.py buka_kunci_login`).
    `locked_until` NULL = tidak terkunci; terisi & > sekarang = autentikasi
    (username, ip) ini ditolak APA PUN sandinya (lihat
    `loginguard.backends.LockoutBackend`) sampai waktu itu lewat.

    Sengaja dikunci per (username, IP) — BUKAN per-IP saja: beberapa
    auditor/supervisor bisa berbagi satu IP kantor (di belakang
    `web.models.AllowedIP`), jadi mengunci per-IP akan menjadikan satu
    percobaan jahat sebagai penolakan-layanan bagi kantor itu. Juga BUKAN
    per-username saja: itu akan membiarkan satu username disasar dari
    banyak IP berbeda tanpa pernah terkunci di satu pun (kuncinya sebenarnya
    per pasangan, bukan gabungan).
    """

    username = models.CharField(max_length=150)
    ip = models.CharField(max_length=45, blank=True)
    fail_count = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["username", "ip"], name="uniq_loginattempt_username_ip"
            ),
        ]

    def __str__(self):
        status = "terkunci" if self.locked_until else "aktif"
        return f"{self.username}@{self.ip or '(tanpa-ip)'} gagal={self.fail_count} ({status})"
