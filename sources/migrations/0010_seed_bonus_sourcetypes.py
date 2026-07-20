from django.db import migrations, models


def seed(apps, schema_editor):
    SourceType = apps.get_model("sources", "SourceType")
    SourceType.objects.get_or_create(
        key="panel_bonus", defaults={"name": "Panel Bonus", "is_money_source": False})
    SourceType.objects.get_or_create(
        key="bracket_bonus", defaults={"name": "Bracket Bonus", "is_money_source": False})


def unseed(apps, schema_editor):
    apps.get_model("sources", "SourceType").objects.filter(
        key__in=["panel_bonus", "bracket_bonus"]).delete()


class Migration(migrations.Migration):
    dependencies = [("sources", "0009_upload_duplicate_transactions")]
    operations = [
        migrations.AlterField(
            model_name="sourcetype", name="key",
            field=models.CharField(choices=[
                ("panel", "Panel"), ("bracket", "Bracket"), ("bank", "Bank"),
                ("gateway", "Gateway"), ("panel_bonus", "Panel Bonus"),
                ("bracket_bonus", "Bracket Bonus"),
            ], max_length=20, unique=True),
        ),
        migrations.RunPython(seed, unseed),
    ]
