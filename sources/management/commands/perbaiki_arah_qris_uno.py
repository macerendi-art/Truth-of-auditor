"""Pulihkan arah baris QRIS UNO bentuk deposit yang salah tercatat sebagai WD.

Bug lama menurunkan arah dari substring nama berkas. Nama yang memuat ``WD DP``
memilih WD lebih dulu, padahal kolom ``BranchName``/``OrderId``/``GrandTotal``
adalah bentuk deposit dari vendor. Unggah ulang tidak memperbaiki baris lama
karena resep ``row_hash`` tidak memuat arah.

Perintah ini hanya menyasar gerbang struktural yang sempit, lalu menurunkan
nominal dan fee kembali dari ``raw``. Secara bawaan ia dry-run; penulisan hanya
terjadi dengan ``--terapkan``. Bila ada satu sasaran yang sudah dikunci batch,
seluruh operasi dihentikan agar urutan pemulihan tetap menjadi keputusan
pemilik data.
"""
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.db.models import Count

from sources.parsers.base import parse_decimal
from transactions.models import Transaction


class Command(BaseCommand):
    help = (
        "Pulihkan arah baris QRIS UNO bentuk deposit dari raw; "
        "dry-run secara bawaan."
    )

    def add_arguments(self, parser):
        parser.add_argument("--toko", default=None, help="batasi ke satu toko (key)")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--dry-run",
            action="store_true",
            help="hitung dan laporkan tanpa menulis (perilaku bawaan)",
        )
        mode.add_argument(
            "--terapkan",
            action="store_true",
            help="tulis perubahan setelah seluruh pagar lolos",
        )

    def handle(self, *args, **opts):
        qs = Transaction.objects.filter(
            source_type__key="gateway",
            raw__has_key="BranchName",
            jenis="wd",
            money_delta__lt=0,
        )
        if opts["toko"]:
            qs = qs.filter(toko__key=opts["toko"])

        for kelompok in qs.values("toko__key", "posted_date").annotate(
            n=Count("id")
        ).order_by("toko__key", "posted_date"):
            tanggal = kelompok["posted_date"] or "tanpa-tanggal"
            self.stdout.write(
                f"sasaran toko={kelompok['toko__key'] or '-'} "
                f"tanggal={tanggal} n={kelompok['n']}"
            )

        terkunci = qs.filter(consumed_by_batch__isnull=False).count()
        self.stdout.write(f"terkunci batch={terkunci}")
        if terkunci:
            self.stdout.write(self.style.ERROR(
                "DIHENTIKAN: ada sasaran yang sudah terkunci batch. "
                "Jangan mengubah atau menghapus batch otomatis; pemilik harus "
                "menentukan urutan pemulihannya."
            ))
            return

        lewat = {
            "raw tidak lengkap atau nominal tidak sah": 0,
            "isi raw tak cocok baris": 0,
        }
        diperiksa = 0
        siap = []
        for tx in qs.order_by("id").iterator(chunk_size=500):
            diperiksa += 1
            hasil = self._hitung(tx)
            if isinstance(hasil, str):
                lewat[hasil] += 1
                continue
            for bidang, nilai in hasil.items():
                setattr(tx, bidang, nilai)
            siap.append(tx)

        diubah = 0
        if opts["terapkan"] and siap:
            # Kunci dan periksa ulang di dalam transaksi: jangan sampai satu
            # baris dikonsumsi batch di antara pemeriksaan awal dan penulisan.
            with db_transaction.atomic():
                ids = [tx.id for tx in siap]
                terkunci_baru = Transaction.objects.select_for_update().filter(
                    id__in=ids,
                    consumed_by_batch__isnull=False,
                ).count()
                if terkunci_baru:
                    self.stdout.write(self.style.ERROR(
                        f"DIHENTIKAN: terkunci batch berubah menjadi {terkunci_baru} "
                        "saat penulisan; tidak ada baris diubah."
                    ))
                    return
                Transaction.objects.bulk_update(
                    siap,
                    ["jenis", "amount", "money_delta", "fee"],
                    batch_size=500,
                )
                diubah = len(siap)

        mode = "diterapkan" if opts["terapkan"] else "dry-run, tidak ditulis"
        self.stdout.write(self.style.SUCCESS(
            f"diperiksa={diperiksa} siap={len(siap)} diubah={diubah} ({mode})"
        ))
        for sebab, jumlah in lewat.items():
            self.stdout.write(self.style.WARNING(f"dilewati {sebab}={jumlah}"))

    @staticmethod
    def _hitung(tx):
        """Nilai arah benar dari ``raw``, atau alasan penolakan."""
        raw = tx.raw or {}
        gross_raw = raw.get("GrandTotal")
        net_raw = raw.get("BranchNominal")
        if gross_raw in (None, "") or net_raw in (None, ""):
            return "raw tidak lengkap atau nominal tidak sah"
        gross = parse_decimal(gross_raw)
        net = parse_decimal(net_raw)
        if gross <= 0 or net <= 0 or net > gross:
            return "raw tidak lengkap atau nominal tidak sah"
        if tx.amount != gross or abs(tx.money_delta) != gross:
            return "isi raw tak cocok baris"
        return {
            "jenis": "depo",
            "amount": gross,
            "money_delta": gross,
            "fee": gross - net,
        }
