"""Inti harness sidik-jari (E3) — dipakai `sidik_jari.py`, `bandingkan.py`,
`ukur_kandidat.py`, `sintetik_elite.py`. TIDAK dimaksudkan dijalankan langsung.

KONTRAK (lihat docs/riset-money-phones-2026-09-04.md untuk latar lengkap):
  - Harness ini HANYA MEMBACA. Ia memanggil `matcher.sides()` + `matcher.match()`
    langsung (bukan `reconciliation.engine.run_batch`), jadi tidak ada
    `ReconBatch`/`MatchRun`/`MatchResult` yang pernah ditulis ke DB — `run` yang
    dibuat di sini TAK PERNAH `.save()`, dan `MatchResult` yang dikembalikan
    `match()` TAK PERNAH `.save()`/`bulk_create()`. Ini disengaja: harness harus
    aman dijalankan berulang kali tanpa mengubah data APA PUN, termasuk data
    dev lokal yang dipakai bersama agen lain.
  - Karena bypass `run_batch`, harness TIDAK mereplikasi orkestrasi batch harian
    (carried/retro/consumed_by_batch/completeness-gate). Itu keputusan sadar:
    kontrak determinisme CLAUDE.md bicara soal keputusan PASANGAN matcher
    (`left_id, right_id, bucket, reason_code, score`), bukan orkestrasi batch —
    fingerprint per-relasi sudah cukup untuk menjawab "apakah kode baru mengubah
    keputusan pencocokan", tanpa ikut menyeret status "batch mana sudah ada"
    yang tak relevan buat pertanyaan itu.

CARA PAKAI (lihat juga docstring `sidik_jari.py`):
    import sys; sys.path.insert(0, "scripts/harness")
    import inti
    inti.boot_django("/path/ke/salinan.sqlite3")   # SEBELUM impor apa pun yg baca settings
    from reconciliation import engine
    rows = inti.hitung_baris(engine, "panel_bank", "k25", date(2026,6,1), date(2026,6,28))
    baris = inti.urutkan_kanonik(inti.sidik_jari_baris("panel_bank", rows))
"""
import importlib
import os
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)


def boot_django(db_path):
    """Nyalakan Django dengan DATABASE_URL menunjuk `db_path` (file sqlite).

    WAJIB dipanggil PALING AWAL di setiap skrip — sebelum `import django` /
    `import reconciliation.engine` / apa pun yang membaca `django.conf.settings`
    — karena `truth_auditor/settings.py` membaca `os.environ["DATABASE_URL"]`
    sekali saat modul itu pertama kali diimpor. `db_path` semestinya SELALU
    berupa SALINAN sekali-pakai (lihat `docs/riset-money-phones-2026-09-04.md`
    bagian "DB & lingkungan") — skrip di paket ini sendiri tak pernah menulis,
    tapi tetap: jangan arahkan ke db.sqlite3 dev yang dipakai bersama sesi lain.
    """
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "truth_auditor.settings")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    import django
    django.setup()


def boot_django_tanpa_db():
    """Nyalakan Django TANPA menunjuk file DB apa pun — dipakai `sintetik_elite.py`,
    yang hanya membangun objek `Transaction`/`MatchRun`/`ToleranceProfile` TAK
    TERSIMPAN di memori dan tak pernah menjalankan satu query pun. Django tetap
    perlu `django.setup()` untuk app-registry (impor model), tapi koneksi DB
    default (sqlite lokal, entah ada atau tidak) tak pernah benar-benar dibuka."""
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "truth_auditor.settings")
    import django
    django.setup()


def muat_toleransi_default():
    from reconciliation.models import ToleranceProfile
    return ToleranceProfile.objects.get(name="Default")


def resolve_toko(key):
    from sources.models import Toko
    # `.only("id", "key")`: sengaja tak menyeleksi seluruh kolom Toko — pada
    # salinan DB yang belum ter-`migrate` penuh kolom `panel`/`kepemilikan`
    # bisa hilang (schema drift), dan matcher tak pernah membaca field itu.
    return Toko.objects.only("id", "key").get(key=key)


def buat_run_sementara(relation, tolerance, dfrom, dto):
    """`MatchRun` TAK TERSIMPAN — cukup untuk `matcher.match()` (ia hanya
    membaca `run.tolerance`, lalu meneruskan `run` apa adanya ke `MatchResult(
    run=run, ...)` yang JUGA tak pernah disimpan). Tak ada `.save()` di sini —
    itulah yang membuat seluruh harness murni baca."""
    from reconciliation.models import MatchRun
    return MatchRun(relation=relation, tolerance=tolerance, date_from=dfrom, date_to=dto)


def hitung_baris(engine, relation_key, toko_key, dfrom, dto, include=None):
    """Jalankan SATU matcher relasi langsung (bypass `run_batch`), kembalikan
    list `MatchResult` TAK TERSIMPAN apa adanya (urutan asli dari `match()`,
    BELUM dikanonikalkan — pemanggil yang memutuskan mau apa dgn urutan itu)."""
    from reconciliation.models import MatchRun
    relation = MatchRun.Relation(relation_key)
    matcher = engine.MATCHERS[relation]()
    toko = resolve_toko(toko_key)
    tol = muat_toleransi_default()
    left, right = matcher.sides(dfrom, dto, toko, include=include)
    run = buat_run_sementara(relation, tol, dfrom, dto)
    return matcher.match(run, left, right)


def sidik_jari_baris(relation_key, rows):
    """list[MatchResult tak-tersimpan] -> list[tuple sidik-jari kanonik].

    Tuple: (relation_key, left_id, right_id, bucket, reason_code, score_str).
    `left_id`/`right_id` diganti -1 saat None (NULL) supaya seluruh tuple bisa
    di-sort tanpa membandingkan None dgn int (TypeError di Python 3), dan agar
    format teks tak pernah menaruh 'None' pada berkas keluaran.
    """
    out = []
    for r in rows:
        lid = r.left_id if r.left_id is not None else -1
        rid = r.right_id if r.right_id is not None else -1
        out.append((relation_key, lid, rid, r.bucket, r.reason_code, f"{float(r.score):.4f}"))
    return out


def urutkan_kanonik(baris):
    """Urutan TAMPILAN kanonik untuk perbandingan berkas — BUKAN urutan
    komputasi matcher (yang determinismenya diatur `sides()`/kunci sort
    internal engine, tak disentuh di sini sama sekali). Mengurutkan baris
    OUTPUT demi diff yang stabil bukan pelanggaran kontrak determinisme:
    pasangan yang terbentuk sudah final sebelum baris ini dipanggil."""
    return sorted(baris, key=lambda t: (t[0], t[1], t[2]))


def tulis_sidik_jari(path, meta, baris):
    # Prefiks metadata `#meta:` (BEDA dari komentar biasa `# ...`) sengaja
    # dipisah: komentar bebas boleh mengandung '=' (mis. penjelasan kode)
    # tanpa disalahtafsir sbg pasangan key=value oleh `baca_sidik_jari`.
    with open(path, "w") as f:
        f.write("# sidik-jari rekonsiliasi (harness E3 -- scripts/harness)\n")
        for k, v in meta.items():
            f.write(f"#meta:{k}={v}\n")
        f.write("# kolom: relation|left_id|right_id|bucket|reason_code|score\n")
        f.write("# left_id/right_id senilai -1 berarti NULL (mis. no_panel/no_money)\n")
        for relation_key, lid, rid, bucket, reason, score in baris:
            f.write(f"{relation_key}|{lid}|{rid}|{bucket}|{reason}|{score}\n")


def baca_sidik_jari(path):
    meta, baris = {}, []
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith("#meta:"):
                k, _, v = line[len("#meta:"):].partition("=")
                meta[k] = v
                continue
            if line.startswith("#"):
                continue
            relation_key, lid, rid, bucket, reason, score = line.split("|")
            baris.append((relation_key, int(lid), int(rid), bucket, reason, score))
    return meta, baris


def muat_patch(dotted):
    """dotted = 'modul.path:fungsi' -> impor modul, kembalikan fungsinya.
    Fungsi itu dipanggil sbg `fungsi(engine_module)` dan diharapkan melakukan
    monkeypatch IN-MEMORY pada `engine_module` (lihat `patch_lewati_name_score.py`).
    """
    mod_name, _, func_name = dotted.partition(":")
    mod = importlib.import_module(mod_name)
    return getattr(mod, func_name)
