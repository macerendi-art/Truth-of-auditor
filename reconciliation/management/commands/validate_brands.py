"""Fase 0 — buktikan match-rate pada file nyata SEBELUM integrasi UI.

Contoh:
  python manage.py validate_brands --dir "~/Downloads/Telegram Desktop/COR/01" --toko g25 --flow-from-name
"""
import os
from django.core.management.base import BaseCommand

from reconciliation.engine import run_batches_auto
from reconciliation.models import MatchResult
from sources import services
from sources.detect import detect_source
from sources.models import Toko


def format_rate(n, d):
    return f"{n}/{d} ({100 * n / d:.1f}%)" if d else f"{n}/0 (n/a)"


def _flow(name):
    low = name.lower()
    if "withdraw" in low or "_wd" in low or " wd" in low or low.startswith("wd"):
        return "wd"
    if "deposit" in low or "_dp" in low or " dp" in low or low.startswith("dp"):
        return "dp"
    return ""


class Command(BaseCommand):
    help = "Ingest folder + rekonsiliasi otomatis + laporan match-rate (Fase 0)."

    def add_arguments(self, parser):
        parser.add_argument("--dir", required=True)
        parser.add_argument("--toko", required=True)
        parser.add_argument("--flow-from-name", action="store_true")

    def handle(self, *args, **opts):
        toko = Toko.objects.get(key=opts["toko"])
        folder = os.path.expanduser(opts["dir"])
        ingested = 0
        for fn in sorted(os.listdir(folder)):
            path = os.path.join(folder, fn)
            if not os.path.isfile(path):
                continue
            ranked = detect_source(path, fn)
            if not ranked:
                self.stdout.write(f"  ? skip (tak terdeteksi): {fn}")
                continue
            key = ranked[0]["parser_key"]
            flow = _flow(fn) if opts["flow_from_name"] else ""
            try:
                _, created, dup = services.ingest(key, path, flow=flow, toko=toko)
                ingested += created
                self.stdout.write(f"  + {key:16s} {created:5d} baris  ({fn})")
            except Exception as e:  # noqa: BLE001
                self.stdout.write(f"  ! GAGAL {key} {fn}: {e}")
        self.stdout.write(f"Total transaksi ter-ingest: {ingested}")

        res = run_batches_auto(toko)
        self.stdout.write(f"\nrun_batches_auto ok={res['ok']} "
                          f"batch={len(res.get('batches', []))} "
                          f"violations={len(res.get('violations', []))}")
        for b in res.get("batches", []):
            c = MatchResult.objects.filter(run__batch=b, left__isnull=False)
            total = c.count()
            cocok = c.filter(bucket=MatchResult.Bucket.COCOK).count()
            tinjau = c.filter(bucket=MatchResult.Bucket.TINJAU).count()
            tidak = c.filter(bucket=MatchResult.Bucket.TIDAK).count()
            self.stdout.write(
                f"  {b.recon_date}: cocok {format_rate(cocok, total)} | "
                f"tinjau {tinjau} | tidak {tidak}")
