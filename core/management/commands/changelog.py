"""Tulis CHANGELOG.md dari `core.version.RILIS`.

    python manage.py changelog          # tulis berkas
    python manage.py changelog --cek    # hanya periksa, keluar 1 bila melenceng

Mode `--cek` dipakai kalau mau memeriksa tanpa mengubah berkas; tes
`core.tests_version` menegakkan hal yang sama di suite.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.version import changelog_markdown, versi


def path_changelog() -> Path:
    return Path(settings.BASE_DIR) / "CHANGELOG.md"


class Command(BaseCommand):
    help = "Tulis (atau periksa) CHANGELOG.md dari daftar rilis di core/version.py"

    def add_arguments(self, parser):
        parser.add_argument(
            "--cek",
            action="store_true",
            help="Jangan tulis; keluar dengan galat bila CHANGELOG.md tidak sinkron.",
        )

    def handle(self, *args, **opts):
        target = path_changelog()
        isi = changelog_markdown()
        lama = target.read_text(encoding="utf-8") if target.exists() else None

        if opts["cek"]:
            if lama != isi:
                raise CommandError(
                    "CHANGELOG.md tidak sinkron dengan core/version.py — "
                    "jalankan `python manage.py changelog`."
                )
            self.stdout.write(self.style.SUCCESS(f"CHANGELOG.md sinkron (v{versi()})."))
            return

        if lama == isi:
            self.stdout.write(f"CHANGELOG.md sudah mutakhir (v{versi()}).")
            return

        target.write_text(isi, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"CHANGELOG.md ditulis ulang — v{versi()}."))
