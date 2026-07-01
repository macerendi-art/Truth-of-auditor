from django.db import migrations

PROFILES = [
    # name, date_window_days, amount_abs_tol, amount_pct_tol, fuzzy_threshold
    ("Default", 1, 0, 0, 85),
    ("Ketat", 0, 0, 0, 90),
    ("Longgar", 2, 10000, 0, 75),
]


def seed(apps, schema_editor):
    TP = apps.get_model("reconciliation", "ToleranceProfile")
    for name, dw, ab, pct, fz in PROFILES:
        TP.objects.get_or_create(
            name=name,
            defaults=dict(
                date_window_days=dw, amount_abs_tol=ab, amount_pct_tol=pct, fuzzy_threshold=fz
            ),
        )


def unseed(apps, schema_editor):
    TP = apps.get_model("reconciliation", "ToleranceProfile")
    TP.objects.filter(name__in=[p[0] for p in PROFILES]).delete()


class Migration(migrations.Migration):
    dependencies = [("reconciliation", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
