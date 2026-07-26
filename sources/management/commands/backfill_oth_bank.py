"""Backfill `bank_title` baris panel lama: kode operator "OTH" -> bank asli.

Untuk baris yang sudah diingest SEBELUM fix parser COR (lihat resolve_oth_bank
di sources/parsers/cor.py). Tidak menyentuh `raw` (byte-identik) — hanya
menghitung ulang `bank_title` dari segmen nama di tengah `raw["Bank Title"]`
("KODE|NAMA|NOREK"). Idempoten: baris yang berhasil diurai tak lagi
bank_title=="OTH" pada run berikutnya, jadi jalan ulang = 0 perubahan.
"""
from django.core.management.base import BaseCommand

from sources.parsers.cor import resolve_oth_bank
from transactions.models import Transaction


class Command(BaseCommand):
    help = 'Urai ulang bank_title=="OTH" baris panel jadi bank asli (idempoten).'

    def add_arguments(self, parser):
        parser.add_argument("--toko", default=None, help="batasi ke satu toko (key)")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="hitung & laporkan tanpa menulis perubahan"
        )

    def handle(self, *args, **opts):
        qs = Transaction.objects.filter(source_type__key="panel", bank_title="OTH")
        if opts["toko"]:
            qs = qs.filter(toko__key=opts["toko"])

        diperiksa = diubah = dilewati = 0
        to_update = []
        for tx in qs.iterator():
            diperiksa += 1
            bank_title_raw = str((tx.raw or {}).get("Bank Title", ""))
            nama = bank_title_raw.split("|")[1] if "|" in bank_title_raw else ""
            baru = resolve_oth_bank(tx.bank_title, nama)
            if baru != tx.bank_title:
                tx.bank_title = baru
                to_update.append(tx)
                diubah += 1
            else:
                dilewati += 1

        if to_update and not opts["dry_run"]:
            # batch_size: satu backfill historis bisa puluhan ribu baris — jangan
            # jadi satu UPDATE..CASE raksasa (plafon variabel SQLite rendah).
            Transaction.objects.bulk_update(to_update, ["bank_title"], batch_size=500)

        suffix = " (dry-run, tidak ditulis)" if opts["dry_run"] else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"diperiksa={diperiksa} diubah={diubah} dilewati={dilewati}{suffix}"
            )
        )
