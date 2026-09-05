from django.core.management.base import BaseCommand, CommandError

from sources.flow import detect_flow
from sources.services import PARSERS, ingest


class Command(BaseCommand):
    help = "Parse & ingest satu file sumber menjadi Transaction kanonik."

    def add_arguments(self, parser):
        parser.add_argument("parser_key", help=f"salah satu: {', '.join(PARSERS)}")
        parser.add_argument("file_path")
        parser.add_argument("--flow", default=None, help="dp/wd (default: deteksi dari nama file)")
        parser.add_argument("--recon-date", default=None)
        parser.add_argument(
            "--tanpa-berkas", action="store_true",
            help="jangan simpan salinan berkas aslinya (jejak audit) — untuk uji coba/debug",
        )

    def handle(self, *args, **opts):
        flow = opts["flow"] if opts["flow"] is not None else detect_flow(opts["file_path"])
        try:
            up, created, dup = ingest(
                opts["parser_key"],
                opts["file_path"],
                recon_date=opts["recon_date"],
                flow=flow,
                # Jalur ingest PRODUKSI (membuat Upload + Transaction sungguhan),
                # jadi jejak berkas aslinya ikut disimpan seperti unggahan web.
                simpan_berkas=not opts["tanpa_berkas"],
            )
        except (ValueError, FileNotFoundError) as e:
            raise CommandError(str(e))
        self.stdout.write(
            self.style.SUCCESS(
                f"OK [{opts['parser_key']}/{flow or '-'}] {up.original_name}: "
                f"{created} dibuat, {dup} duplikat (Upload #{up.pk})"
            )
        )
