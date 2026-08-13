"""Pulihkan baris gateway yang terlanjur masuk TANPA tanggal — dari `raw`.

Saat parser tak mengenali nama kolom waktu vendor, baris tetap masuk dengan
tiket, nominal, dan username yang BENAR tapi `occurred_at`/`posted_date` NULL.
Baris begitu inert: tak terlihat oleh jendela tanggal mesin pencocokan (yang
menyaring `occurred_at__date`) maupun oleh halaman laporan (yang menyaring
`posted_date`), sehingga sisi panelnya berhenti di "Belum ada uang masuk".
Parser sekarang membaca bentuk itu, tapi perbaikan parser TIDAK retroaktif.

**Diperbaiki di tempat, bukan diunggah ulang.** `raw` menyimpan SELURUH kolom
asli berkas apa adanya, termasuk kolom waktu yang dulu tak dikenali — jadi
tanggalnya bisa dipulihkan tanpa menyentuh berkas sumbernya. Mengunggah ulang
bukan jalan keluar: `row_hash` lama dihitung saat `reference` masih kosong,
sehingga berkas yang sama akan menghasilkan hash BERBEDA dan masuk sebagai
baris baru — hari itu terhitung dua kali.

Karena itu command ini **menghitung ulang `row_hash`** dengan resep yang sama
persis dengan parser (`[ticket, ref, amount]`), dan menghitungnya dari `raw`
lewat ekspresi yang sama pula — bukan dari kolom database. Bedanya halus tapi
menentukan: `str(Decimal)` yang dibaca balik dari kolom belum tentu sama
dengan yang dihasilkan `parse_decimal` atas teks aslinya, dan hash yang meleset
satu karakter membuat unggahan ulang berikutnya lolos sebagai baris baru.

Pagarnya struktural dan sengaja sempit:

* `source_type=gateway`, KEDUA kolom waktu NULL — persis populasi yang rusak.
* `ticket_no` tak kosong. Ini yang memisahkan baris yang bisa dipulihkan dari
  6.118 baris sampah bentuk ketiga (tiket '', Rp0) yang juga tak bertanggal.
  Sampah itu TIDAK disentuh: menghapusnya keputusan pemilik data, bukan
  keputusan command ini.
* Tiket & nominal hasil hitung ulang dari `raw` WAJIB sama dengan yang
  tersimpan. Kalau meleset, barisnya bukan yang kita kira — dilewati, disebut.
* Hash baru yang bentrok dengan baris lain = salinan benarnya sudah ada.
  Dilewati, disebut; menimpanya akan melanggar constraint dan menghapus bukti.

Semua penolakan dilaporkan per sebab. Command yang MENULIS harus berisik soal
apa yang tidak ditulisnya — tidak menulis itu bisa diulang, menulis salah tidak.

Idempoten: baris yang berhasil ditulis keluar dari selektor (waktunya tak lagi
NULL), jadi menjalankannya dua kali aman.
"""
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction

from sources.parsers.base import parse_decimal, parse_dt, row_hash
from sources.parsers.gateways import QRFlyerParser
from transactions.models import Transaction

UKURAN_POTONGAN = 500


class Command(BaseCommand):
    help = ("Pulihkan tanggal/referensi baris gateway yang terlanjur masuk tanpa "
            "tanggal, dibaca dari `raw` (idempoten).")

    def add_arguments(self, parser):
        parser.add_argument("--toko", default=None, help="batasi ke satu toko (key)")
        parser.add_argument("--dry-run", action="store_true",
                            help="hitung & laporkan tanpa menulis perubahan")

    def handle(self, *args, **opts):
        qs = Transaction.objects.filter(
            source_type__key="gateway",
            occurred_at__isnull=True,
            posted_date__isnull=True,
        ).exclude(ticket_no="").order_by("id")
        if opts["toko"]:
            qs = qs.filter(toko__key=opts["toko"])

        diperiksa = diubah = 0
        lewat = {"tanpa kolom waktu di raw": 0, "isi raw tak cocok baris": 0,
                 "salinan benar sudah ada": 0}
        terakhir = 0
        while True:
            potongan = list(qs.filter(id__gt=terakhir)[:UKURAN_POTONGAN])
            if not potongan:
                break
            terakhir = potongan[-1].id
            siap = []
            for tx in potongan:
                diperiksa += 1
                hasil = self._hitung(tx)
                if isinstance(hasil, str):
                    lewat[hasil] += 1
                    continue
                siap.append((tx, hasil))

            # Bentrok hash diperiksa terhadap DB DAN terhadap sesama anggota
            # potongan ini — dua baris rusak yang identik bisa sama-sama lolos
            # cek DB lalu saling menabrak di bulk_update.
            dipakai = set()
            tulis = []
            for tx, baru in siap:
                if baru["row_hash"] in dipakai or Transaction.objects.filter(
                        source_type_id=tx.source_type_id, toko_id=tx.toko_id,
                        row_hash=baru["row_hash"]).exclude(id=tx.id).exists():
                    lewat["salinan benar sudah ada"] += 1
                    continue
                dipakai.add(baru["row_hash"])
                for k, v in baru.items():
                    setattr(tx, k, v)
                tulis.append(tx)

            if tulis and not opts["dry_run"]:
                with db_transaction.atomic():
                    Transaction.objects.bulk_update(
                        tulis,
                        ["occurred_at", "posted_date", "reference", "fee", "row_hash"],
                        batch_size=UKURAN_POTONGAN,
                    )
            diubah += len(tulis)

        tanda = " (dry-run, tidak ditulis)" if opts["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"diperiksa={diperiksa} diubah={diubah}{tanda}"))
        for sebab, n in lewat.items():
            if n:
                self.stdout.write(self.style.WARNING(f"dilewati {sebab}={n}"))

    def _hitung(self, tx):
        """Nilai pengganti dari `raw`, atau string alasan kalau tak bisa."""
        raw = tx.raw or {}
        peta = QRFlyerParser._petakan(list(raw.keys()))
        if not peta["amount"] or not peta["ticket"]:
            return "isi raw tak cocok baris"

        occurred = parse_dt(raw.get(peta["created"])) if peta["created"] else None
        settle = parse_dt(raw.get(peta["settled"])) if peta["settled"] else None
        if not (occurred or settle):
            return "tanpa kolom waktu di raw"

        # Dihitung ulang lewat ekspresi yang SAMA dengan parser, supaya hash
        # barunya identik dengan hash unggahan berikutnya atas berkas yang sama.
        ticket = str(raw.get(peta["ticket"], "") or "").strip()
        amt = abs(parse_decimal(raw.get(peta["amount"])))
        if ticket != tx.ticket_no or amt != tx.amount:
            return "isi raw tak cocok baris"

        ref = (str(raw.get(peta["ref"], "") or "").strip() if peta["ref"]
               else tx.reference)
        return {
            "occurred_at": occurred,
            "posted_date": (settle or occurred).date(),
            "reference": ref,
            "fee": parse_decimal(raw.get(peta["fee"])) if peta["fee"] else tx.fee,
            "row_hash": row_hash("qrflyer", [ticket, ref, amt]),
        }
