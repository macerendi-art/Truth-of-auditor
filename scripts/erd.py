"""Bangkitkan ERD (mermaid) dari model Django — OFFLINE, tanpa menyentuh database.

`apps.get_models()` dan `Model._meta` hanya membaca kelas Python: tidak ada koneksi
yang dibuka, tidak ada query, tidak ada `migrate`. Karena itu skrip ini aman
dijalankan dari checkout mana pun tanpa DATABASE_URL — settings jatuh ke SQLite
tapi tak pernah menyambung, jadi jebakan J1 (diam-diam menulis ke SQLite) tidak
berlaku di sini.

    python scripts/erd.py > docs/migrasi/erd-mermaid.md
"""

import os
import sys
from pathlib import Path

# `python scripts/erd.py` menaruh scripts/ di sys.path[0], BUKAN akar proyek, jadi
# `import truth_auditor.settings` gagal. Sisipkan akarnya sendiri supaya skrip ini
# bisa dijalankan langsung dari mana saja tanpa PYTHONPATH atau `manage.py shell`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "truth_auditor.settings")
django.setup()

from django.apps import apps  # noqa: E402  (wajib setelah django.setup())

APPS = {"core", "accounts", "sources", "transactions", "reconciliation", "web"}

# Kolom yang ikut digambar. Sisanya disembunyikan supaya diagram tetap terbaca —
# ERD ini alat baca manusia saat migrasi, bukan dump skema (itu tugas gerbang.sql).
PENTING = {
    "id", "toko", "source_type", "upload", "account", "posted_date", "occurred_at",
    "amount", "credit_delta", "money_delta", "row_hash", "ticket_no", "reference",
    "username", "jenis", "is_duplicate", "consumed_by_batch", "resolved_by_batch",
    "superseded_by", "bucket", "reason_code", "recon_date", "run", "left", "right",
    "batch", "tolerance", "nilai", "tanggal", "cidr", "aksi", "periode", "field",
    "alasan", "raw", "status", "relation", "kategori",
}

entitas, relasi = [], []
for model in apps.get_models():
    if model._meta.app_label not in APPS:
        continue
    tabel = model._meta.db_table
    baris = [f"  {tabel} {{"]
    for f in model._meta.get_fields():
        if f.auto_created and not f.concrete:  # buang relasi balik
            continue
        tipe = f.get_internal_type().replace("Field", "")  # mermaid menolak spasi
        if f.many_to_many:
            lawan = f.related_model._meta.db_table
            relasi.append(f'  {tabel} }}o--o{{ {lawan} : "{f.name} M2M"')
            baris.append(f"    M2M {f.name}")
            continue
        if f.is_relation and f.related_model is not None:
            on_delete = getattr(
                getattr(f.remote_field, "on_delete", None), "__name__", "?"
            ).upper()
            lawan = f.related_model._meta.db_table
            relasi.append(f'  {lawan} ||--o{{ {tabel} : "{f.name} {on_delete}"')
            baris.append(f"    {tipe} {f.name} FK")
            continue
        if f.name in PENTING or f.primary_key or getattr(f, "unique", False):
            kunci = "PK" if f.primary_key else ("UK" if getattr(f, "unique", False) else "")
            baris.append(f"    {tipe} {f.name} {kunci}".rstrip())
    baris.append("  }")
    entitas.append("\n".join(baris))

print("```mermaid")
print("erDiagram")
print("\n".join(entitas))
print("\n".join(sorted(set(relasi))))
print("```")
