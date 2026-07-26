"""Model layer web: overlay tampilan (koreksi sel FR, isian manual Rekap Bulanan).

Semua model di sini bersifat OVERLAY: `Transaction` hasil ingest tidak pernah
diubah — nilai koreksi/isian ditumpangkan saat render.
"""
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


class RekapManual(TimeStampedModel):
    """Isian manual satu baris Rekap Bulanan — menimpa nilai otomatis.

    Kunci baris = (toko, periode, field): `periode` SELALU tanggal 1 bulan
    bersangkutan, `field` = slug baris di registry `web.rekap.FIELDS`.
    Sengaja TANPA `choices=` (pola `ReviewAction.alasan`): daftar baris hidup
    di `web/rekap.py` dan boleh berubah tanpa migrasi — validasi slug dilakukan
    di view saat menyimpan. Baris `kind="computed"` tak pernah dibaca dari sini
    (rumus tak boleh ditimpa); riwayat nilai ada di `core.AuditLog`.
    """

    toko = models.ForeignKey(
        "sources.Toko", on_delete=models.CASCADE, related_name="rekap_manual")
    periode = models.DateField(help_text="tanggal 1 bulan bersangkutan")
    field = models.CharField(max_length=64, help_text="slug baris web.rekap.FIELDS")
    nilai = models.DecimalField(max_digits=18, decimal_places=2)
    catatan = models.TextField(blank=True)
    dibuat_oleh = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="rekap_manual")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["toko", "periode", "field"], name="uniq_rekap_manual"),
        ]

    def __str__(self):
        return f"{self.periode:%Y-%m} {self.field} = {self.nilai}"


class RekapPenyebab(TimeStampedModel):
    """Satu baris daftar "Penyebab" selisih Rekap Bulanan (label bebas + nilai).

    Bukan overlay atas baris registry: jumlahnya dinamis per bulan, ditotal
    jadi baris `penyebab_total` (dan ikut `different`). Urutan tampilan
    ditentukan `urutan` — bukan waktu input.
    """

    toko = models.ForeignKey(
        "sources.Toko", on_delete=models.CASCADE, related_name="rekap_penyebab")
    periode = models.DateField(help_text="tanggal 1 bulan bersangkutan")
    label = models.CharField(max_length=100)
    nilai = models.DecimalField(max_digits=18, decimal_places=2)
    urutan = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["urutan", "id"]

    def __str__(self):
        return f"{self.periode:%Y-%m} {self.label} = {self.nilai}"
