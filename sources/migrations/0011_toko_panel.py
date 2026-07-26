from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sources", "0010_seed_bonus_sourcetypes"),
    ]

    operations = [
        migrations.AddField(
            model_name="toko",
            name="panel",
            field=models.CharField(
                choices=[
                    ("nexus", "Nexus"),
                    ("vigor", "Vigor"),
                    ("tm_gaming", "TM Gaming"),
                ],
                default="nexus",
                max_length=20,
            ),
        ),
    ]
