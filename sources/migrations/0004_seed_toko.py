from django.db import migrations


def seed(apps, schema_editor):
    Toko = apps.get_model("sources", "Toko")
    for key, name in [("lbs", "LBS"), ("slo", "SLO")]:
        Toko.objects.get_or_create(key=key, defaults={"name": name})


def unseed(apps, schema_editor):
    apps.get_model("sources", "Toko").objects.filter(key__in=["lbs", "slo"]).delete()


class Migration(migrations.Migration):
    dependencies = [("sources", "0003_toko")]
    operations = [migrations.RunPython(seed, unseed)]
