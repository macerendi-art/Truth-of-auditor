from django.core.management.base import BaseCommand, CommandError

from reconciliation.engine import MATCHERS, run_match
from reconciliation.models import MatchRun, ToleranceProfile


class Command(BaseCommand):
    help = "Jalankan pencocokan untuk satu relasi (panel_bracket / panel_bank)."

    def add_arguments(self, parser):
        parser.add_argument("relation", choices=[r.value for r in MatchRun.Relation])
        parser.add_argument("--from", dest="dfrom", default=None, help="YYYY-MM-DD (occurred_at)")
        parser.add_argument("--to", dest="dto", default=None, help="YYYY-MM-DD (occurred_at)")
        parser.add_argument("--tolerance", default="Default")

    def handle(self, *args, **o):
        if o["relation"] not in MATCHERS:
            raise CommandError(
                f"Relasi '{o['relation']}' belum didukung. Tersedia: "
                + ", ".join(str(k) for k in MATCHERS)
            )
        try:
            tol = ToleranceProfile.objects.get(name=o["tolerance"])
        except ToleranceProfile.DoesNotExist:
            raise CommandError(f"ToleranceProfile '{o['tolerance']}' tidak ada")
        run = run_match(o["relation"], tol, o["dfrom"], o["dto"])
        s = run.summary
        self.stdout.write(
            self.style.SUCCESS(
                f"MatchRun #{run.pk} [{o['relation']}]: cocok={s['cocok']} "
                f"perlu_tinjau={s['perlu_tinjau']} tidak_cocok={s['tidak_cocok']} "
                f"(left={s['left']} right={s['right']})"
            )
        )
