#!/usr/bin/env python
"""Bandingkan dua berkas sidik-jari (dari `sidik_jari.py`) baris-per-baris.

CARA PAKAI
    python scripts/harness/bandingkan.py fp_baseline.txt fp_kandidat.txt

Bukan sekadar "berbeda" -- mengelompokkan tiap ketidaksamaan ke salah satu:
    hilang   : kunci ada di baseline, tak ada lagi di kandidat
    baru     : kunci tak ada di baseline, muncul di kandidat
    berubah  : kunci ada di keduanya tapi (pasangan/bucket/reason/score) beda

KUNCI per baris = (relation, "L", left_id) bila left_id != -1 (baris kredit),
else (relation, "R", right_id) (baris `no_panel`, left=None). Kunci ini SENGAJA
bukan (left_id, right_id) pasangan penuh -- itu tak akan menangkap kasus paling
penting: kredit yang SAMA kini berpasangan dengan uang yang BERBEDA (right_id
berubah tapi left_id tetap). Mengunci ke sisi kredit (atau sisi uang bila
kredit-nya None) membuat perubahan pasangan itu justru muncul sebagai
"berubah", bukan tersembunyi sebagai satu baris hilang + satu baris baru yang
kebetulan tak pernah disandingkan.

Exit code 0 hanya bila kedua berkas identik (baris & urutan) -- dipakai
sebagai gerbang otomatis: `echo $?` setelah panggilan ini menjawab
"apakah kandidat ini aman", bukan cuma manusia yang harus membaca output.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inti  # noqa: E402


def _kunci(baris):
    relation_key, lid, rid, bucket, reason, score = baris
    if lid != -1:
        return (relation_key, "L", lid)
    return (relation_key, "R", rid)


def bandingkan(baseline, kandidat):
    a = {_kunci(b): b for b in baseline}
    b = {_kunci(b): b for b in kandidat}
    hilang = [a[k] for k in a if k not in b]
    baru = [b[k] for k in b if k not in a]
    berubah = [(a[k], b[k]) for k in a if k in b and a[k] != b[k]]
    identik = sum(1 for k in a if k in b and a[k] == b[k])
    return {"hilang": hilang, "baru": baru, "berubah": berubah, "identik": identik}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("baseline")
    ap.add_argument("kandidat")
    ap.add_argument("--maks-tampil", type=int, default=20,
                     help="maksimum baris detail ditampilkan per kategori (default 20)")
    args = ap.parse_args(argv)

    meta_a, baris_a = inti.baca_sidik_jari(args.baseline)
    meta_b, baris_b = inti.baca_sidik_jari(args.kandidat)
    hasil = bandingkan(baris_a, baris_b)

    print(f"baseline: {args.baseline}  ({len(baris_a)} baris)  meta={meta_a}")
    print(f"kandidat: {args.kandidat}  ({len(baris_b)} baris)  meta={meta_b}")
    print()
    print(f"identik={hasil['identik']}  hilang={len(hasil['hilang'])}  "
          f"baru={len(hasil['baru'])}  berubah={len(hasil['berubah'])}")

    def _cetak(judul, daftar, formatter):
        if not daftar:
            return
        print(f"\n-- {judul} ({len(daftar)}) --")
        for item in daftar[: args.maks_tampil]:
            print("  " + formatter(item))
        if len(daftar) > args.maks_tampil:
            print(f"  ... {len(daftar) - args.maks_tampil} lagi tak ditampilkan")

    _cetak("HILANG (ada di baseline, tak ada di kandidat)", hasil["hilang"],
           lambda r: f"{r[0]} left={r[1]} right={r[2]} bucket={r[3]} reason={r[4]} score={r[5]}")
    _cetak("BARU (tak ada di baseline, muncul di kandidat)", hasil["baru"],
           lambda r: f"{r[0]} left={r[1]} right={r[2]} bucket={r[3]} reason={r[4]} score={r[5]}")
    _cetak("BERUBAH (kunci sama, isi beda)", hasil["berubah"],
           lambda pair: f"{pair[0][0]} left={pair[0][1]}  "
                        f"baseline(right={pair[0][2]},bucket={pair[0][3]},reason={pair[0][4]},score={pair[0][5]})  "
                        f"-> kandidat(right={pair[1][2]},bucket={pair[1][3]},reason={pair[1][4]},score={pair[1][5]})")

    identik_penuh = not hasil["hilang"] and not hasil["baru"] and not hasil["berubah"]
    print()
    print("FINGERPRINT IDENTIK -- kandidat aman (per data ini)." if identik_penuh
          else "FINGERPRINT BERBEDA -- kandidat MENGUBAH hasil, jangan diterapkan tanpa kalibrasi ulang.")
    return 0 if identik_penuh else 1


if __name__ == "__main__":
    raise SystemExit(main())
