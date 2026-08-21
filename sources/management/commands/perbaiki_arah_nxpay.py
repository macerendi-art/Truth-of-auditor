"""Pulihkan arah baris gateway NXPay yang salah karena nama berkas DP/WD.

Parser lama menurunkan ``jenis``/``money_delta`` hanya dari ``flow`` nama file.
Staff yang menukar label DP↔WD (bukti BTS 20-08-2026) membuat ticket ``D…``
tercatat sebagai WD dan ``W…`` sebagai DP — pass 0 panel↔uang gagal total
meski ticket overlap 100%.

Pemulihan: ticket prefix ``D``/``W`` (konvensi panel Nexus) menentukan arah.
``row_hash`` tidak memuat arah, jadi unggah ulang tidak memperbaiki baris lama.

Bawaan dry-run. ``--terapkan`` menulis. Sasaran terkunci batch → henti
(hapus batch dulu — keputusan pemilik).
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction
from django.db.models import Count, Q

from sources.parsers.gateways import _nxpay_jenis
from transactions.models import Transaction


class Command(BaseCommand):
    help = "Pulihkan arah gateway NXPay dari prefix ticket D/W; dry-run bawaan."

    def add_arguments(self, parser):
        parser.add_argument("--toko", default=None, help="batasi ke satu toko (key)")
        parser.add_argument(
            "--tanggal",
            default=None,
            help="batasi ke satu posted_date (YYYY-MM-DD)",
        )
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="laporkan saja (bawaan)")
        mode.add_argument("--terapkan", action="store_true", help="tulis perubahan")

    def handle(self, *args, **opts):
        tanggal = self._parse_tanggal(opts["tanggal"])
        # Gateway NXPay: description diawali NXPAY, atau raw Payment Type ada + Ticket Number
        qs = Transaction.objects.filter(
            source_type__key="gateway",
        ).filter(
            Q(description__istartswith="NXPAY")
            | Q(raw__has_key="Ticket Number", description__icontains="NXPAY")
        ).exclude(ticket_no="")
        if opts["toko"]:
            qs = qs.filter(toko__key=opts["toko"])
        if tanggal is not None:
            qs = qs.filter(posted_date=tanggal)

        # Hanya baris yang ARAHNYA salah vs ticket
        kandidat_ids = []
        for tx in qs.only("id", "ticket_no", "jenis", "money_delta", "amount").iterator(chunk_size=500):
            want = _nxpay_jenis(tx.ticket_no, None, "")
            # skip ticket non D/W — tak bisa putuskan dari ticket
            t = (tx.ticket_no or "").strip().upper()
            if not (t.startswith("D") or t.startswith("W")):
                continue
            if tx.jenis != want:
                kandidat_ids.append(tx.id)

        qs = Transaction.objects.filter(id__in=kandidat_ids)
        for kelompok in qs.values("toko__key", "posted_date").annotate(n=Count("id")).order_by(
            "toko__key", "posted_date"
        ):
            self.stdout.write(
                f"sasaran toko={kelompok['toko__key'] or '-'} "
                f"tanggal={kelompok['posted_date'] or 'tanpa-tanggal'} n={kelompok['n']}"
            )

        terkunci = qs.filter(consumed_by_batch__isnull=False).count()
        self.stdout.write(f"salah_arah={qs.count()} terkunci_batch={terkunci}")
        if terkunci:
            self.stdout.write(self.style.ERROR(
                "DIHENTIKAN: ada sasaran terkunci batch. Hapus batch terkait dulu, "
                "lalu jalankan ulang --terapkan."
            ))
            return

        siap = []
        for tx in qs.order_by("id").iterator(chunk_size=500):
            want = _nxpay_jenis(tx.ticket_no, None, "")
            amt = abs(tx.amount or Decimal("0"))
            tx.jenis = want
            tx.money_delta = -amt if want == "wd" else amt
            siap.append(tx)

        if opts["terapkan"] and siap:
            with db_transaction.atomic():
                ids = [tx.id for tx in siap]
                terkunci_baru = (
                    Transaction.objects.select_for_update()
                    .filter(id__in=ids, consumed_by_batch__isnull=False)
                    .count()
                )
                if terkunci_baru:
                    self.stdout.write(self.style.ERROR(
                        f"DIHENTIKAN: terkunci batch={terkunci_baru} saat tulis; 0 diubah."
                    ))
                    return
                Transaction.objects.bulk_update(siap, ["jenis", "money_delta"])
            self.stdout.write(self.style.SUCCESS(f"diperbaiki={len(siap)}"))
        else:
            self.stdout.write(f"siap_diperbaiki={len(siap)} (dry-run — pakai --terapkan untuk menulis)")

    def _parse_tanggal(self, s):
        if not s:
            return None
        try:
            y, m, d = s.split("-")
            return date(int(y), int(m), int(d))
        except Exception as e:
            raise CommandError(f"tanggal tidak valid: {s}") from e
