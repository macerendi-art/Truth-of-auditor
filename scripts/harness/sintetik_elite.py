#!/usr/bin/env python
"""Reproduksi SINTETIK dari rezim "Anomali matcher 25-08-2026" (CLAUDE.md),
dipakai HANYA karena DB lokal (db.sqlite3 dev) tak punya satu baris pun dari
rezim itu (toko Vigor/TM Gaming g25/w25/cah dgn gateway QRIS ELITE -- lokal
cuma py k25/lbs, panel "nexus" mode ticket).

ANGKA DI SKRIP INI SINTETIK -- BUKAN PRODUKSI, BUKAN PERKIRAAN PRODUKSI.
Dibuat untuk MENGUJI METODOLOGI harness pada BENTUK data yang mirip anomali
(banyak "nomor HP" palsu dari ID/VENDOR ID ELITE, panel tanpa ticket/reference
sehingga seluruh baris jatuh ke pass 1 identitas), pada SKALA yang jauh lebih
kecil dari kejadian produksi (4.969.497 pasangan) supaya tetap murah dijalankan
di laptop. Jangan pernah mengutip angka `--n`/waktu di sini seolah itu
proyeksi produksi.

TIDAK MENYENTUH DATABASE SAMA SEKALI -- `boot_django_tanpa_db()` hanya
menyalakan app-registry Django (perlu utk impor model), lalu seluruh objek
`Transaction`/`ToleranceProfile`/`MatchRun` dibangun TAK TERSIMPAN di memori
dan `_MoneyMatcher.match()` dipanggil langsung (bypass `sides()`, yang
memang butuh DB nyata dan tak relevan buat pertanyaan skrip ini: "pada
BENTUK data begini, apa efek patch_lewati_name_score?").

CARA PAKAI
    /path/ke/.venv/bin/python scripts/harness/sintetik_elite.py --n 300 --ulang 5
"""
import argparse
import statistics
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inti  # noqa: E402
import patch_lewati_name_score as patch_mod  # noqa: E402


def _bangun_data(engine, n):
    from transactions.models import Transaction
    from sources.models import SourceType, Upload

    panel_st = SourceType(key="panel")
    gw_st = SourceType(key="gateway")
    # `Transaction.upload` TIDAK nullable (null=False) -- mengoper `upload=None`
    # tetap memicu `RelatedObjectDoesNotExist` saat diakses (perilaku Django utk
    # FK wajib). Satu Upload TAK TERSIMPAN dipakai bersama semua baris gateway
    # (owners dict di match() mengelompokkan per upload_id -- berbagi satu id
    # sengaja, hasilnya netral utk pertanyaan skrip ini).
    upload_sintetik = Upload(pk=1, source_type=gw_st, original_name="sintetik_elite.csv")

    left, right = [], []
    for i in range(n):
        left.append(Transaction(
            pk=800_000 + i,
            source_type=panel_st, upload=upload_sintetik,
            ticket_no="", reference="",
            username=f"eliteuser{i:04d}",
            counterparty=f"Nama Panel {i}",
            money_delta=Decimal("500000"), credit_delta=Decimal("-500000"),
            amount=Decimal("500000"),
            occurred_at=datetime(2026, 8, 25, 10, 0, 0),
            jenis="depo",
            raw={"Player Bank": f"BANK|OWNER|8{i:08d}"},  # 9-digit, prefix '8' -- disjoint dari ID/VENDOR ID
            bank_title="",
        ))
    for j in range(n):
        right.append(Transaction(
            pk=900_000 + j,
            source_type=gw_st, upload=upload_sintetik,
            ticket_no="", reference="",
            username=f"eliteuser{j:04d}",  # sama dgn left[j] -> SATU-SATUNYA pasangan "benar" per j
            counterparty=f"Nama Gateway {j}",
            money_delta=Decimal("500000"), credit_delta=Decimal("0"),
            amount=Decimal("500000"),
            occurred_at=datetime(2026, 8, 25, 10, 5, 0),
            jenis="depo",
            # ELITE: kolom ID / VENDOR ID 9-digit dipanen _money_phones sbg "HP" palsu --
            # persis mekanisme yg dicatat CLAUDE.md (7.775/8.284 baris ELITE ber-2 "phones").
            raw={"ID": f"1{j:08d}", "VENDOR ID": f"2{j:08d}"},
            description="",
        ))
    return left, right


def _jalankan(engine, left, right, ulang):
    from reconciliation.models import MatchRun, ToleranceProfile

    tol = ToleranceProfile(
        name="Default (sintetik, tak tersimpan)",
        date_window_days=1, amount_abs_tol=Decimal("0"),
        amount_pct_tol=Decimal("0"), fuzzy_threshold=85,
    )
    waktu, fp_terakhir = [], None
    for _ in range(ulang):
        run = MatchRun(relation=MatchRun.Relation.PANEL_BANK, tolerance=tol)
        matcher = engine.PanelBankMatcher()
        t0 = time.perf_counter()
        rows = matcher.match(run, left, right)
        t1 = time.perf_counter()
        waktu.append(t1 - t0)
        fp_terakhir = inti.urutkan_kanonik(inti.sidik_jari_baris("panel_bank", rows))
    return waktu, fp_terakhir


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=300, help="jumlah baris panel = jumlah baris gateway (N x N pasangan dievaluasi pass 1)")
    ap.add_argument("--ulang", type=int, default=5)
    args = ap.parse_args(argv)

    inti.boot_django_tanpa_db()
    from reconciliation import engine

    left, right = _bangun_data(engine, args.n)
    n_pasangan = args.n * args.n

    print(f"# SINTETIK -- n={args.n} (={n_pasangan} pasangan dievaluasi pass 1, "
          f"vs 4.969.497 pasangan pada insiden produksi 25-08-2026 -- skala JAUH lebih kecil)")
    print(f"# ulang={args.ulang}")

    w_base, fp_base = _jalankan(engine, left, right, args.ulang)
    asli = patch_mod.terapkan(engine)
    w_patch, fp_patch = _jalankan(engine, left, right, args.ulang)
    patch_mod.pulihkan(engine, asli)

    identik = fp_base == fp_patch
    print(f"\nn_baris_hasil={len(fp_base)} fingerprint_identik={identik}")
    if not identik:
        a = {(r[1], r[2]): r for r in fp_base}
        b = {(r[1], r[2]): r for r in fp_patch}
        beda = [k for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
        print(f"!!! {len(beda)} baris berbeda:")
        for k in beda[:20]:
            print("   ", k, "baseline=", a.get(k), "patch=", b.get(k))

    mb, mp = statistics.median(w_base), statistics.median(w_patch)
    print(f"baseline  median={mb*1000:.3f}ms  semua(ms)={[f'{x*1000:.3f}' for x in w_base]}")
    print(f"patch     median={mp*1000:.3f}ms  semua(ms)={[f'{x*1000:.3f}' for x in w_patch]}")
    if mp > 0:
        print(f"speedup median baseline/patch = {mb/mp:.3f}x")
    print(f"\nCatatan: patch HANYA menghemat panggilan _name_score pada baris yang username-nya "
          f"PERSIS SAMA (di sini: {args.n} dari {n_pasangan} pasangan, ~{100*args.n/n_pasangan:.2f}%) -- "
          f"TIDAK menyentuh _phone_match/_money_phones, yang menurut profil produksi 25-08-2026 "
          f"justru biaya UTAMA pada rezim ini. Speedup di atas mengukur PERSIS batas itu, bukan "
          f"proyeksi perbaikan bottleneck yang sebenarnya.")
    return 0 if identik else 1


if __name__ == "__main__":
    raise SystemExit(main())
