"""Backfill player_bank/bank_title dari raw untuk baris kredit (panel/bracket).

Dipakai oleh migrasi data & bisa dipanggil ulang (idempoten). Menerima model
Transaction (bisa model historis dari migrasi) agar aman lintas state.

Diproses per-chunk PK (bukan cursor server-side yang dijeda oleh write) supaya
aman di Postgres saat migrasi non-atomic — tiap batch commit sendiri, jadi WAL
tidak menumpuk dalam satu transaksi raksasa (lihat insiden pg_wal penuh).
"""
from sources.parsers.base import derive_bank_fields


def backfill_bank_fields(Transaction, *, batch_size=2000):
    """Isi player_bank/bank_title baris panel/bracket. Kembalikan jumlah yang berubah."""
    ids = list(
        Transaction.objects.filter(source_type__key__in=("panel", "bracket"))
        .values_list("id", flat=True)
    )
    changed = 0
    for i in range(0, len(ids), batch_size):
        rows = list(
            Transaction.objects.filter(id__in=ids[i : i + batch_size])
            .select_related("source_type")
            .only("id", "raw", "player_bank", "bank_title", "source_type__key")
        )
        buf = []
        for t in rows:
            pb, bt = derive_bank_fields(t.source_type.key, t.raw)
            if (pb, bt) != (t.player_bank, t.bank_title):
                t.player_bank, t.bank_title = pb, bt
                buf.append(t)
        if buf:
            Transaction.objects.bulk_update(buf, ["player_bank", "bank_title"])
            changed += len(buf)
    return changed
