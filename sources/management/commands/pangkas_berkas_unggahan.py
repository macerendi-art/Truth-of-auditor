"""Hapus salinan berkas asli unggahan yang lebih tua dari N hari.

**Alat ini sengaja TIDAK BERSENJATA.** Ia tidak dipasang di penjadwal mana pun
dan tidak melakukan apa pun tanpa dipanggil dengan `--hari N` yang eksplisit;
tanpa `--terapkan` ia hanya melapor. Retensi yang dipilih pemilik (2026-09-05)
adalah **simpan selamanya** — sejalan dengan aturan proyek "jangan pernah hapus
data produksi". Perintah ini ada supaya kalau suatu saat volume media perlu
dipangkas, tindakannya sudah teruji dan terukur, bukan diimprovisasi lewat `rm`
di dalam kontainer yang membuat baris `Upload` menunjuk berkas hantu.

Yang dihapus HANYA berkasnya. Baris `Upload`, `Transaction`, tautan
`duplicate_transactions`, dan penanda "ketiban" tidak disentuh sama sekali —
seluruh metadata rekonsiliasi tetap utuh, yang hilang cuma kemampuan mengunduh
berkas mentahnya (view unduh menjawab 404, sama seperti baris lama sebelum
fitur ini ada).

Proyeksi ukuran, diukur dari ekspor NYATA (samples/ OKE25, 3 hari penuh):
±5,6 MB/hari/toko × 16 toko aktif ≈ 90 MB/hari ≈ 2,7 GB/bulan ≈ 32 GB/tahun.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from sources.models import Upload


class Command(BaseCommand):
    help = (
        "Hapus salinan berkas asli unggahan yang lebih tua dari --hari N "
        "(baris Upload & transaksinya TIDAK dihapus); dry-run secara bawaan."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--hari", type=int, default=None,
            help="usia minimum berkas (hari) yang boleh dipangkas — WAJIB diisi",
        )
        parser.add_argument("--toko", default=None, help="batasi ke satu toko (key)")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true",
                          help="hitung dan laporkan tanpa menghapus (perilaku bawaan)")
        mode.add_argument("--terapkan", action="store_true",
                          help="benar-benar hapus berkasnya")

    def handle(self, *args, **opts):
        hari = opts["hari"]
        if hari is None:
            raise CommandError(
                "--hari WAJIB diisi. Perintah ini tidak punya nilai bawaan dengan "
                "sengaja: retensi yang berlaku adalah 'simpan selamanya', jadi "
                "setiap pemangkasan harus jadi keputusan sadar. Contoh: "
                "--hari 365 --dry-run"
            )
        if hari < 1:
            raise CommandError("--hari harus >= 1.")

        batas = timezone.now() - timedelta(days=hari)
        qs = Upload.objects.exclude(file="").filter(created_at__lt=batas)
        if opts["toko"]:
            qs = qs.filter(toko__key=opts["toko"])
        qs = qs.order_by("id")

        terapkan = opts["terapkan"]
        n = byte = gagal = 0
        for up in qs.iterator():
            try:
                ukuran = up.file.size
            except (OSError, ValueError):
                # Berkas sudah lenyap dari disk (mis. deploy sebelum volume
                # terpasang). Kolomnya tetap dibersihkan supaya view unduh
                # berhenti menjanjikan berkas yang tidak ada.
                ukuran = 0
            n += 1
            byte += ukuran
            if terapkan:
                try:
                    up.file.delete(save=True)
                except OSError as e:
                    gagal += 1
                    self.stderr.write(f"GAGAL Upload #{up.pk} ({up.original_name}): {e}")

        mb = byte / 1048576
        awalan = "DIHAPUS" if terapkan else "AKAN DIHAPUS (dry-run)"
        self.stdout.write(
            f"{awalan}: {n} berkas, {mb:.1f} MB — unggahan lebih tua dari "
            f"{hari} hari (sebelum {batas:%Y-%m-%d %H:%M})"
            + (f", toko={opts['toko']}" if opts["toko"] else "")
        )
        if gagal:
            self.stdout.write(self.style.WARNING(f"{gagal} berkas gagal dihapus — lihat pesan di atas."))
        if n and not terapkan:
            self.stdout.write("Tambahkan --terapkan untuk benar-benar menghapus.")
        self.stdout.write(
            "Baris Upload, transaksi, tautan dedup, dan penanda ketiban TIDAK disentuh."
        )
