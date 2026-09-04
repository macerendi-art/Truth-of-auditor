"""Pemulihan NON-HTTP (C4, persyaratan butir 2): buka kunci percobaan login
tanpa lewat halaman web sama sekali — jalan pulih utama bila SEMUA akun
(termasuk admin) kebetulan terkunci bersamaan, karena command ini bicara
langsung ke DB lewat ORM, tidak melalui middleware/gerbang HTTP apa pun.

Pemakaian (lokal):
    python manage.py buka_kunci_login <username>   # satu username, semua IP
    python manage.py buka_kunci_login --semua       # SEMUA kunci, semua user

Pemakaian (produksi, Railway — pola sama seperti reset password admin di
`dev-admin-login.md`):
    railway ssh -s web "/opt/venv/bin/python manage.py buka_kunci_login <username>"
"""
from django.core.management.base import BaseCommand, CommandError

from loginguard.throttle import buka_kunci


class Command(BaseCommand):
    help = (
        "Buka kunci percobaan login (C4) untuk satu username (semua IP) "
        "atau semua username sekaligus — pemulihan darurat, non-HTTP."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "username", nargs="?", default=None,
            help="Username yang mau dibuka kuncinya (menghapus baris di semua IP).",
        )
        parser.add_argument(
            "--semua", action="store_true",
            help="Buka SEMUA kunci untuk SEMUA username (darurat total).",
        )

    def handle(self, *args, **options):
        username = options["username"]
        semua = options["semua"]
        if not username and not semua:
            raise CommandError(
                "Sebutkan <username>, atau pakai --semua untuk membuka semua kunci."
            )
        if username and semua:
            raise CommandError(
                "Pilih salah satu: <username> ATAU --semua, bukan keduanya."
            )
        jumlah = buka_kunci(username=None if semua else username)
        if semua:
            self.stdout.write(self.style.SUCCESS(
                f"Semua kunci login dibuka ({jumlah} baris dihapus)."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Kunci login untuk '{username}' dibuka ({jumlah} baris dihapus)."
            ))
