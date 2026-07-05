from django.db import migrations

# Window 1 hari buta weekend: WD Sabtu settle Senin (T+2). Bukti staging K25
# 27-29 Jun 2026 — 27=Sabtu, uangnya baru muncul di mutasi Senin 29 dan selamanya
# tak terjangkau batch 27. Hanya pool KANDIDAT yang melebar (dan pengecekan
# kelengkapan); konsumsi in-window tetap [from,to]. Risiko salah-pasang ditahan
# floor bukti nama, kunci dest, alias historis, dan tie-break tanggal terdekat.


def widen(apps, schema_editor):
    TP = apps.get_model("reconciliation", "ToleranceProfile")
    TP.objects.filter(name="Default", date_window_days=1).update(date_window_days=2)


def narrow(apps, schema_editor):
    TP = apps.get_model("reconciliation", "ToleranceProfile")
    TP.objects.filter(name="Default", date_window_days=2).update(date_window_days=1)


class Migration(migrations.Migration):
    dependencies = [("reconciliation", "0005_reconbatch_error_note_reconbatch_status")]
    operations = [migrations.RunPython(widen, narrow)]
