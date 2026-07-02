from django.db import migrations


def backfill(apps, schema_editor):
    Toko = apps.get_model("sources", "Toko")
    Upload = apps.get_model("sources", "Upload")
    Transaction = apps.get_model("transactions", "Transaction")
    lbs = Toko.objects.filter(key="lbs").first()
    if not lbs:
        return
    Upload.objects.filter(toko__isnull=True).update(toko=lbs)
    Transaction.objects.filter(toko__isnull=True).update(toko=lbs)


class Migration(migrations.Migration):

    dependencies = [
        ("sources", "0005_account_toko_upload_provider_upload_toko"),
        ("transactions", "0002_transaction_toko"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
