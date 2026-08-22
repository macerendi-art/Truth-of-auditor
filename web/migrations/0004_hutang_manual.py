# Generated manually for HutangManual overlay

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("web", "0003_allowed_ip"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="HutangManual",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("periode", models.DateField(help_text="tanggal 1 bulan bersangkutan")),
                ("field", models.CharField(choices=[("hutang", "Hutang"), ("piutang", "Piutang")], max_length=16)),
                ("nilai", models.DecimalField(decimal_places=2, max_digits=18)),
                ("tanggal", models.DateField(help_text="tanggal acuan isian manual")),
                ("catatan", models.TextField(blank=True)),
                ("dibuat_oleh", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="hutang_manual", to=settings.AUTH_USER_MODEL)),
                ("toko", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="hutang_manual", to="sources.toko")),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddConstraint(
            model_name="hutangmanual",
            constraint=models.UniqueConstraint(
                fields=("toko", "periode", "field"), name="uniq_hutang_manual"),
        ),
    ]
