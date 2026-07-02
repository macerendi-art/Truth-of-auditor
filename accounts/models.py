from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Anggota tim audit. Akun dibuat admin (tanpa signup publik)."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        SUPERVISOR = "supervisor", "Supervisor"
        AUDITOR = "auditor", "Auditor"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.AUDITOR)
    allowed_tokos = models.ManyToManyField(
        "sources.Toko",
        blank=True,
        related_name="assigned_users",
        help_text="Toko yang boleh diakses (hanya relevan untuk auditor)",
    )

    def __str__(self):
        return self.username
