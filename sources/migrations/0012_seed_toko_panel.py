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
    # Sentuh HANYA key yang di-seed migrasi ini (pola sama dgn unseed 0004/0007).
    # `all().update(...)` akan meratakan panel yang di-set admin lewat /kelola/toko/
    # pada toko yang tak ada hubungannya dengan migrasi ini — mundur satu migrasi
    # jadi kehilangan data konfigurasi.
    apps.get_model("sources", "Toko").objects.filter(
        key__in=VIGOR + TM_GAMING
    ).update(panel="nexus")


class Migration(migrations.Migration):

    dependencies = [
        ("sources", "0011_toko_panel"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
