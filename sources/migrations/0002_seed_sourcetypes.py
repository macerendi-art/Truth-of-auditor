from django.db import migrations

SOURCES = [
    ("panel", "Panel", False),
    ("bracket", "Bracket", False),
    ("bank", "Bank", True),
    ("gateway", "Gateway", True),
]


def seed(apps, schema_editor):
    ST = apps.get_model("sources", "SourceType")
    for key, name, money in SOURCES:
        ST.objects.get_or_create(key=key, defaults={"name": name, "is_money_source": money})


def unseed(apps, schema_editor):
    ST = apps.get_model("sources", "SourceType")
    ST.objects.filter(key__in=[s[0] for s in SOURCES]).delete()


class Migration(migrations.Migration):
    dependencies = [("sources", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
