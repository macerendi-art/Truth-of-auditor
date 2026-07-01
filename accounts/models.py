from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Anggota tim audit. Akun dibuat admin (tanpa signup publik)."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        AUDITOR = "auditor", "Auditor"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.AUDITOR)

    def __str__(self):
        return self.username
