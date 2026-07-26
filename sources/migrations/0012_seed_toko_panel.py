from django.db import migrations

# Pengelompokan panel client per key toko seed (0007). Toko lain (termasuk
# yang dibuat setelah migrasi ini) tetap default "nexus" — mayoritas brand.
VIGOR = ["slo"]
TM_GAMING = ["w25", "g25"]


def seed(apps, schema_editor):
    Toko = apps.get_model("sources", "Toko")
    Toko.objects.filter(key__in=VIGOR).update(panel="vigor")
    Toko.objects.filter(key__in=TM_GAMING).update(panel="tm_gaming")


def unseed(apps, schema_editor):
    apps.get_model("sources", "Toko").objects.all().update(panel="nexus")


class Migration(migrations.Migration):

    dependencies = [
        ("sources", "0011_toko_panel"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
