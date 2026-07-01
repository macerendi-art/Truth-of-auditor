from django.db import models

from core.models import TimeStampedModel


class Transaction(TimeStampedModel):
    """Baris transaksi kanonik dari SEMUA sumber (uang dinormalisasi ke rupiah)."""

    class Jenis(models.TextChoices):
        DEPO = "depo", "Deposit"
        WD = "wd", "Withdraw"
        BONUS = "bonus", "Bonus"
        ADMIN = "admin", "Biaya Admin"
        MISTAKE = "mistake", "Mistake"
        LAINNYA = "lainnya", "Lainnya"

    upload = models.ForeignKey(
        "sources.Upload", on_delete=models.CASCADE, related_name="transactions"
    )
    source_type = models.ForeignKey("sources.SourceType", on_delete=models.PROTECT)
    account = models.ForeignKey(
        "sources.Account", on_delete=models.SET_NULL, null=True, blank=True
    )

    occurred_at = models.DateTimeField(
        null=True, blank=True, help_text="Waktu transaksi asli"
    )
    posted_date = models.DateField(
        null=True, blank=True, help_text="Tanggal 'masuk' (statement/entry)"
    )
    jenis = models.CharField(max_length=10, choices=Jenis.choices, default=Jenis.LAINNYA)

    # Semua nilai uang dinormalisasi ke RUPIAH (Panel sudah dikali amount_scale, mis. x1000)
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    credit_delta = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    money_delta = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    fee = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    bonus = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    balance_after = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )

    # Kunci pencocokan
    ticket_no = models.CharField(max_length=64, blank=True, db_index=True)
    username = models.CharField(max_length=100, blank=True, db_index=True)
    reference = models.CharField(max_length=128, blank=True, db_index=True)
    counterparty = models.CharField(
        max_length=200, blank=True, help_text="nama pengirim/penerima di bank"
    )

    description = models.TextField(blank=True)
    raw = models.JSONField(default=dict, help_text="baris asli (telusur balik)")
    row_hash = models.CharField(
        max_length=64, db_index=True, help_text="guard idempotensi re-import"
    )
    is_duplicate = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["source_type", "occurred_at"]),
            models.Index(fields=["jenis", "amount"]),
        ]

    def __str__(self):
        return f"{self.get_jenis_display()} {self.amount}"
