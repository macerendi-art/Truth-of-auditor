"""Model layer web: koreksi tampilan sel FR (overlay — data asli tak tersentuh)."""
from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class FRKoreksi(TimeStampedModel):
    """Koreksi satu sel tabel Control Bracket (FR) — timpa TAMPILAN saja.

    Nilai asli hasil agregasi `web.breakdown` TIDAK diubah; koreksi
    ditumpangkan saat render (dan total/selisih dihitung ulang darinya).
    Kunci sel = (toko, tanggal, account, kolom): `account` = label mentah
    `raw["Bank"]`, `kolom` = slug kategori atau `saldo_awal`/`saldo_akhir`.
    Edit ulang memperbarui baris yang sama — riwayat nilai ada di AuditLog.
    """

    ALASAN_KOREKSI = [
        ("cutoff_mutation", "Cutoff Mutation"),
        ("mistake_cs", "Mistake CS"),
        ("biaya_admin_bank", "Biaya Admin Bank"),
        ("biaya_admin_qris", "Biaya Admin QRIS"),
        ("dana_pending", "Dana Pending"),
        ("cm_pindah_dana", "Sesama CM (Pindah Dana)"),
        ("cm_naik_tampung", "Sesama CM (Naik Tampung)"),
        ("cm_turun_tampung", "Sesama CM (Turun Tampung)"),
        ("bank_title_beda", "Bank Title Tidak Sesuai"),
        ("lainnya", "Lainnya"),
    ]

    toko = models.ForeignKey(
        "sources.Toko", on_delete=models.CASCADE, related_name="fr_koreksi")
    tanggal = models.DateField()
    account = models.CharField(max_length=255)
    kolom = models.CharField(max_length=64)
    nilai = models.DecimalField(max_digits=18, decimal_places=2)
    alasan = models.CharField(max_length=32, choices=ALASAN_KOREKSI, blank=True)
    catatan = models.TextField(blank=True)
    dibuat_oleh = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="fr_koreksi")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["toko", "tanggal", "account", "kolom"],
                name="uniq_fr_koreksi_sel"),
        ]

    def __str__(self):
        return f"{self.tanggal} {self.account} [{self.kolom}] = {self.nilai}"
