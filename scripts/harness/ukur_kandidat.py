#!/usr/bin/env python
"""Bagian 2 E3 -- ukur dampak kandidat `patch_lewati_name_score.py` pada DATA
NYATA lokal (BUKAN produksi -- lihat catatan skala di bawah).

Untuk tiap relasi: jalankan matcher BASELINE (kode asli, tak dimodifikasi),
lalu matcher DENGAN PATCH (monkeypatch in-memory, reconciliation/engine.py
TAK PERNAH disentuh) pada DATA YANG SAMA PERSIS, `--ulang` kali masing-masing.
Membuktikan (a) fingerprint kedua varian IDENTIK dan (b) mengukur median
wall-time keduanya.

CARA PAKAI
    /path/ke/.venv/bin/python scripts/harness/ukur_kandidat.py \\
        --db /tmp/salinan.sqlite3 --toko k25 \\
        --dari 2026-06-01 --sampai 2026-06-28 \\
        --relations panel_bank --ulang 7

CATATAN SKALA -- WAJIB dibaca sebelum mengutip angka dari skrip ini:
    DB lokal (`db.sqlite3` dev, 71.584 baris Transaction) HANYA berisi toko
    `k25`/`lbs`, keduanya panel "nexus" bermode TICKET (anchor ticket/reference
    gateway kuat, per CLAUDE.md). Anomali 25-08-2026 yang memicu riset ini
    terjadi pada toko Vigor/TM Gaming (g25/w25/cah) memakai QRIS ELITE MODE
    USERNAME -- REZIM ITU TIDAK ADA SAMA SEKALI di data lokal. Angka dari
    skrip ini HANYA mewakili rezim Nexus/ticket-mode (yang menurut CLAUDE.md
    justru rezim yang REGRESI pada varian optimasi lain yang ditolak).
    Untuk rezim ELITE, lihat `sintetik_elite.py` (data SINTETIK, dilabeli
    jelas, dibuat justru karena rezim itu tak terwakili di sini).
"""
import argparse
import datetime as dt
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inti  # noqa: E402
import patch_lewati_name_score as patch_mod  # noqa: E402


def satu_pengukuran(engine, relation_key, toko_key, dfrom, dto, ulang):
    waktu, fp_terakhir = [], None
    for _ in range(ulang):
        t0 = time.perf_counter()
        rows = inti.hitung_baris(engine, relation_key, toko_key, dfrom, dto)
        t1 = time.perf_counter()
        waktu.append(t1 - t0)
        fp_terakhir = inti.urutkan_kanonik(inti.sidik_jari_baris(relation_key, rows))
    return waktu, fp_terakhir


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--toko", required=True)
    ap.add_argument("--dari", required=True)
    ap.add_argument("--sampai", required=True)
    ap.add_argument("--relations", default="panel_bank")
    ap.add_argument("--ulang", type=int, default=5)
    args = ap.parse_args(argv)

    inti.boot_django(args.db)
    from reconciliation import engine

    dfrom = dt.date.fromisoformat(args.dari)
    dto = dt.date.fromisoformat(args.sampai)

    print(f"# db={args.db}")
    print(f"# toko={args.toko} dari={args.dari} sampai={args.sampai} "
          f"relations={args.relations} ulang={args.ulang}")

    semua_identik = True
    for relation_key in [r.strip() for r in args.relations.split(",") if r.strip()]:
        w_base, fp_base = satu_pengukuran(engine, relation_key, args.toko, dfrom, dto, args.ulang)
        asli = patch_mod.terapkan(engine)
        w_patch, fp_patch = satu_pengukuran(engine, relation_key, args.toko, dfrom, dto, args.ulang)
        patch_mod.pulihkan(engine, asli)

        identik = fp_base == fp_patch
        semua_identik = semua_identik and identik
        print(f"\n== {relation_key} ==")
        print(f"n_baris={len(fp_base)} fingerprint_identik={identik}")
        if not identik:
            a = {(r[1], r[2]): r for r in fp_base}
            b = {(r[1], r[2]): r for r in fp_patch}
            beda = [k for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
            print(f"!!! {len(beda)} baris berbeda -- kandidat TIDAK setara pada data ini:")
            for k in beda[:20]:
                print("   ", k, "baseline=", a.get(k), "patch=", b.get(k))
        mb, mp = statistics.median(w_base), statistics.median(w_patch)
        print(f"baseline  median={mb*1000:.3f}ms  semua(ms)={[f'{x*1000:.3f}' for x in w_base]}")
        print(f"patch     median={mp*1000:.3f}ms  semua(ms)={[f'{x*1000:.3f}' for x in w_patch]}")
        if mp > 0:
            print(f"speedup median baseline/patch = {mb/mp:.3f}x")

    print(f"\nSEMUA RELASI FINGERPRINT IDENTIK: {semua_identik}")
    return 0 if semua_identik else 1


if __name__ == "__main__":
    raise SystemExit(main())
