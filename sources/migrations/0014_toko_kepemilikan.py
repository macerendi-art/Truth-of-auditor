from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sources", "0013_upload_superseded_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="toko",
            name="kepemilikan",
            field=models.CharField(
                choices=[
                    ("pusat", "Pusat"),
                    ("partner", "Partner"),
                ],
                default="pusat",
                help_text="Pusat atau Partner — metadata admin, bukan input engine.",
                max_length=20,
            ),
        ),
    ]
