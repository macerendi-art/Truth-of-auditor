#!/usr/bin/env python
"""Harness sidik-jari rekonsiliasi (E3) — prasyarat perubahan matcher yang
disebut berulang kali di CLAUDE.md ("setiap kandidat perbaikan wajib
digerbangi harness sidik-jari (left_id, right_id, bucket, reason_code, score)
atas hari nyata") tapi belum pernah dibangun sebelum sesi ini.

APA YANG DILAKUKAN
    Menjalankan matcher (`reconciliation.engine.MATCHERS`) langsung lewat
    `matcher.sides()` + `matcher.match()` (bukan `run_batch` — lihat
    `inti.py` untuk alasan bypass-nya), lalu menulis sidik jari kanonik
    (terurut deterministik, bisa di-diff) ke berkas teks.

CARA PAKAI
    Salin dulu DB yang mau diperiksa (JANGAN pernah tunjuk ke db.sqlite3 dev
    yang dipakai bersama sesi lain):
        cp db.sqlite3 /tmp/salinan.sqlite3
        # migrate salinan itu ke skema terbaru bila perlu (aman, itu SALINAN):
        DATABASE_URL=sqlite:////tmp/salinan.sqlite3 \\
            /path/ke/.venv/bin/python manage.py migrate

    Lalu, dari root repo:
        /path/ke/.venv/bin/python scripts/harness/sidik_jari.py \\
            --db /tmp/salinan.sqlite3 \\
            --toko k25 --dari 2026-06-01 --sampai 2026-06-28 \\
            --relations panel_bank,panel_bracket \\
            --out /tmp/fingerprint_a.txt

    Bandingkan dua revisi kode: checkout revisi A, jalankan di atas -> fp_a.txt;
    checkout revisi B (atau pakai `--patch modul:fungsi` utk monkeypatch
    in-memory tanpa checkout, lihat `patch_lewati_name_score.py`), jalankan
    lagi -> fp_b.txt; lalu:
        python scripts/harness/bandingkan.py fp_a.txt fp_b.txt

SYARAT YANG DIPENUHI (lihat CLAUDE.md "Urutan pencocokan WAJIB deterministik")
    - Deterministik: dua jalan atas data SAMA -> berkas IDENTIK byte-untuk-byte
      (dijamin ganda: `match()` sendiri sudah deterministik per kontrak engine,
      DAN baris keluaran di sini diurutkan kanonik sebelum ditulis).
    - Baca-saja: tak ada `.save()`/`bulk_create()` di jalur ini sama sekali
      (lihat `inti.hitung_baris`/`inti.buat_run_sementara`).
    - Bisa membandingkan dua revisi per-baris (lewat `bandingkan.py`), bukan
      cuma bilang "berbeda".
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inti  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="path ke SALINAN sqlite (bukan db.sqlite3 dev bersama)")
    ap.add_argument("--toko", required=True, help="key Toko, mis. k25")
    ap.add_argument("--dari", required=True, help="YYYY-MM-DD")
    ap.add_argument("--sampai", required=True, help="YYYY-MM-DD")
    ap.add_argument("--relations", default="panel_bank,panel_bracket,fr_bank,bracket_bank",
                     help="daftar relasi dipisah koma, subset dari MatchRun.Relation")
    ap.add_argument("--patch", default=None,
                     help="'modul:fungsi' -- monkeypatch in-memory pada modul engine "
                          "SEBELUM match() dipanggil (lihat patch_lewati_name_score.py). "
                          "Tak pernah menulis ke reconciliation/engine.py di disk.")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    inti.boot_django(args.db)
    from reconciliation import engine

    if args.patch:
        fn = inti.muat_patch(args.patch)
        fn(engine)

    dfrom = dt.date.fromisoformat(args.dari)
    dto = dt.date.fromisoformat(args.sampai)

    semua = []
    for relation_key in [r.strip() for r in args.relations.split(",") if r.strip()]:
        rows = inti.hitung_baris(engine, relation_key, args.toko, dfrom, dto)
        semua.extend(inti.sidik_jari_baris(relation_key, rows))
    semua = inti.urutkan_kanonik(semua)

    meta = {
        "db": args.db, "toko": args.toko, "dari": args.dari, "sampai": args.sampai,
        "relations": args.relations, "patch": args.patch or "(tanpa patch)",
        "n_baris": len(semua),
    }
    inti.tulis_sidik_jari(args.out, meta, semua)
    print(f"Ditulis {len(semua)} baris -> {args.out}")


if __name__ == "__main__":
    main()
