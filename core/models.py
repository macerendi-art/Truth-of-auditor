from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base: timestamp created/updated untuk semua model."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AuditLog(TimeStampedModel):
    """Jejak aksi bermakna: siapa melakukan apa, kapan, pada objek apa.

    FK sengaja SET_NULL — riwayat harus tetap hidup setelah user/toko dihapus
    (justru saat itulah jejak paling dibutuhkan). Konteks objek disimpan di
    `objek` (label human) + `detail` (JSON: batch_pk, result_pk, dst) sehingga
    tidak ikut terhapus cascade bersama objeknya.
    """

    user = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    # Snapshot identitas pelaku — FK di atas SET_NULL saat user dihapus,
    # justru saat itulah "siapa" paling dibutuhkan.
    username = models.CharField(max_length=150, blank=True, default="")
    toko = models.ForeignKey(
        "sources.Toko", on_delete=models.SET_NULL, null=True, blank=True
    )
    aksi = models.CharField(max_length=40)
    objek = models.CharField(max_length=200, blank=True)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["toko", "aksi"])]

    def __str__(self):
        return f"{self.aksi} {self.objek} oleh {self.user}"
