"""Backfill label "QRIS" untuk baris panel COR rail QRIS yang lama.

Ekspor rail QRIS tak punya kolom bank tujuan, jadi `bank_title` baris-baris ini
kosong: sel tabel/ekspor "—", chip filter bank kosong, dan kartu "Metode
Pembayaran" dashboard menggolongkannya "Lainnya". Parser sekarang mensintesis
labelnya (lihat CORPanelQRISParser), tapi itu tidak retroaktif — command ini
mengisi baris yang sudah terlanjur diingest.

Selektor aman karena hanya CORPanelQRISParser yang menulis
`description = "QRIS <transaction id>"` pada sumber `panel`; parser QRIS lain
berawalan sama ("QRIS COR ...", "QRIS WD ...") tapi bersumber `gateway`.
Kolom DAN `raw["Bank Title"]` sama-sama diisi supaya backfill_bank_fields —
yang menurunkan kolom dari raw — tidak mengembalikannya jadi kosong.
Idempoten: setelah jalan pertama `bank_title` tak lagi kosong, jadi selektor
tak menemukan apa-apa.
"""
from django.core.management.base import BaseCommand

from transactions.models import Transaction


class Command(BaseCommand):
    help = 'Isi bank_title="QRIS" untuk baris panel COR rail QRIS lama (idempoten).'

    def add_arguments(self, parser):
        parser.add_argument("--toko", default=None, help="batasi ke satu toko (key)")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="hitung & laporkan tanpa menulis perubahan"
        )

    def handle(self, *args, **opts):
        qs = Transaction.objects.filter(
            source_type__key="panel", bank_title="", description__startswith="QRIS "
        )
        if opts["toko"]:
            qs = qs.filter(toko__key=opts["toko"])

        diperiksa = 0
        to_update = []
        for tx in qs.iterator():
            diperiksa += 1
            tx.bank_title = "QRIS"
            tx.raw = {**(tx.raw or {}), "Bank Title": "QRIS"}
            to_update.append(tx)

        if to_update and not opts["dry_run"]:
            # batch_size: backfill historis bisa puluhan ribu baris — jangan jadi
            # satu UPDATE..CASE raksasa (plafon variabel SQLite rendah).
            Transaction.objects.bulk_update(
                to_update, ["bank_title", "raw"], batch_size=500)

        suffix = " (dry-run, tidak ditulis)" if opts["dry_run"] else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"diperiksa={diperiksa} diubah={len(to_update)}{suffix}"
            )
        )
