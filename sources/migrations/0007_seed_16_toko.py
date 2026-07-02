from django.db import migrations

KODE = [
    "AHK", "MUL", "STN", "LBS", "W25", "M25", "MXW", "HKS",
    "BWN", "LTN", "WLG", "SSN", "CTR", "SLO", "G25", "K25",
]


def seed(apps, schema_editor):
    Toko = apps.get_model("sources", "Toko")
    for k in KODE:
        Toko.objects.get_or_create(key=k.lower(), defaults={"name": k.upper()})


def unseed(apps, schema_editor):
    Toko = apps.get_model("sources", "Toko")
    keep = {"lbs", "slo"}  # seed lama (0004) tetap
    Toko.objects.filter(key__in=[k.lower() for k in KODE if k.lower() not in keep]).delete()


class Migration(migrations.Migration):
    dependencies = [("sources", "0006_backfill_toko")]
    operations = [migrations.RunPython(seed, unseed)]
