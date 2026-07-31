"""Backfill label "QRIS" untuk baris panel COR rail QRIS yang lama.

Ekspor rail QRIS tak punya kolom bank tujuan, jadi `bank_title` baris-baris ini
kosong: sel tabel/ekspor "—", chip filter bank kosong, dan kartu "Metode
Pembayaran" dashboard menggolongkannya "Lainnya". Parser sekarang mensintesis
labelnya (lihat CORPanelQRISParser), tapi itu tidak retroaktif — command ini
mengisi baris yang sudah terlanjur diingest.

Nilai yang ditulis SAMA PERSIS dengan parser: kolom `bank_title` = "QRIS", dan
`raw["Bank Title"]` = "QRIS||" — bentuk triplet panel "KODE|NAMA|NOREK" dengan
segmen NAMA & NOREK kosong, karena rail QRIS memang tak punya pemilik maupun
nomor rekening tujuan. Segmen tengah yang kosong itu load-bearing: engine
`_expected_owner` membaca segmen TENGAH `raw["Bank Title"]` dan jatuh ke seluruh
string bila tak ada "|", jadi label telanjang "QRIS" akan dibacanya sebagai nama
pemilik rekening. Kolom DAN raw sama-sama diisi supaya backfill_bank_fields —
yang menurunkan kolom dari raw — tidak mengembalikan kolom jadi kosong.

Selektor `description__startswith="QRIS "` mengasingkan rail QRIS COR, TAPI
bukan jaminan mutlak: parser panel Nexus menulis `description` dari kolom
Remarks yang isinya teks bebas, jadi baris Nexus ber-Remarks awalan "QRIS " dan
`bank_title` kosong ikut tersapu. Jalankan dengan `--toko <toko COR>` bila ada
keraguan. Catatan lain: `__startswith` bersifat case-INsensitive di SQLite tapi
case-sensitive di Postgres (produksi) — hitungan bisa berbeda antara dev & prod.
Parser QRIS lain berawalan sama ("QRIS COR ...", "QRIS WD ...") tapi bersumber
`gateway`, jadi sudah tersaring `source_type__key="panel"`.

Idempoten: setelah jalan pertama `bank_title` tak lagi kosong, jadi selektor
tak menemukan apa-apa.
"""
from django.core.management.base import BaseCommand

from transactions.models import Transaction

# Baris yang sudah ditulis KELUAR dari selektor (bank_title tak lagi kosong),
# jadi mengambil potongan pertama berulang kali menyapu habis tanpa LIMIT/OFFSET
# yang bisa melewati baris. Dipotong supaya puncak memori terbatas: backfill
# historis bisa puluhan ribu baris dan tiap baris membawa JSON `raw`.
UKURAN_POTONGAN = 500


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

        if opts["dry_run"]:
            # Wajib keluar lebih awal: tanpa menulis, tak ada baris yang keluar
            # dari selektor sehingga loop potongan di bawah takkan pernah habis.
            n = qs.count()
            self.stdout.write(self.style.SUCCESS(
                f"diperiksa={n} diubah={n} (dry-run, tidak ditulis)"))
            return

        diubah = 0
        while True:
            potongan = list(qs[:UKURAN_POTONGAN])
            if not potongan:
                break
            for tx in potongan:
                tx.bank_title = "QRIS"
                tx.raw = {**(tx.raw or {}), "Bank Title": "QRIS||"}
            Transaction.objects.bulk_update(
                potongan, ["bank_title", "raw"], batch_size=UKURAN_POTONGAN)
            diubah += len(potongan)

        # diperiksa == diubah: selektor sudah menjamin setiap baris terpilih
        # berubah. Formatnya disamakan dgn backfill_oth_bank agar konsisten.
        self.stdout.write(
            self.style.SUCCESS(f"diperiksa={diubah} diubah={diubah}")
        )
