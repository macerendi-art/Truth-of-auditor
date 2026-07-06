"""Backfill player_bank/bank_title untuk baris panel/bracket yang sudah ada."""
from django.db import migrations


def forwards(apps, schema_editor):
    from transactions.bankfields import backfill_bank_fields

    Transaction = apps.get_model("transactions", "Transaction")
    backfill_bank_fields(Transaction)


class Migration(migrations.Migration):
    # Non-atomic: backfill commit per-batch (bulk_update) supaya WAL tidak menumpuk
    # dalam satu transaksi besar di prod Postgres. Idempoten → aman diulang.
    atomic = False

    dependencies = [
        ("transactions", "0004_transaction_bank_title_transaction_player_bank"),
    ]
    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
