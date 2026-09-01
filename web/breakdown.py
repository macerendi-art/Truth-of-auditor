"""Breakdown Bracket (FR) harian — agregasi per FR Account.

Meniru "Control Bracket Transaction (Harian)" (referensi user) dengan hitungan
bertanda yang benar: baris per FR Account (`raw["Bank"]`), pivot per kategori
asli FR (`raw["Kategori"]`), saldo awal/akhir dari `balance_after` (saldo
berjalan per akun, urut `(raw["Jam"], id)` = urutan file), dan

    Selisih Kontrol = saldo_akhir − (saldo_awal + Σ money_delta)

yang idealnya 0 — nilai ≠ 0 berarti mutasi FR tidak konsisten dengan saldo
berjalannya (sinyal audit, bukan angka penyeimbang seperti "Akuran").

Semua baris bracket ikut dihitung (termasuk fee `jenis="admin"` dan baris yang
sudah di-consume batch): ini view data, bukan matching. Tanpa migrasi — kolom
diambil query-time dari JSON `raw`, jadi berlaku retroaktif untuk data lama.
"""
from collections import Counter
from datetime import date
from decimal import Decimal

from django.db import connection
from django.db.models import Count, Max, Min, Q, Sum, TextField
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast

from sources.models import SourceType
from transactions.models import Transaction

# Urutan kanonik kolom kategori (slug lower → label tampilan). Hanya kategori
# yang MUNCUL pada hari itu yang jadi kolom; slug di luar daftar (kategori baru
# dari FR) ditambahkan di ujung secara alfabetis — tidak ada data tersembunyi.
KATEGORI_KANONIK = [
    ("deposit", "Deposit"),
    ("pending dp", "Pending DP"),
    ("withdrawal", "Withdrawal"),
    ("bonus", "Bonus"),
    ("adjustment", "Adjustment"),
    ("sesama cm", "Sesama CM"),
    ("beban admin bank", "Beban Admin Bank"),
    ("beban admin qris", "Beban Admin QRIS"),
    ("biaya transaksi", "Biaya Transaksi"),
    ("beban other expense", "Beban Other Expense"),
    ("beban mistake cs", "Beban Mistake CS"),
    ("expense", "Expense"),
    ("hutang", "Hutang"),
    ("piutang", "Piutang"),
]
_KANONIK_LABEL = dict(KATEGORI_KANONIK)
_KANONIK_URUT = {slug: i for i, (slug, _) in enumerate(KATEGORI_KANONIK)}

# Peran akun (bagian terakhir "A | B | PERAN") → urutan tampilan,
# mengikuti referensi: rekening DP, rekening WD, QRIS, lalu lainnya.
_URUT_PERAN = {"DEPOSIT": 0, "WITHDRAW": 1, "WITHDRAWAL": 1, "DEPOSIT / WITHDRAW": 2}

NOL = Decimal("0")


def _slug_kategori(value):
    s = " ".join(str(value or "").split()).lower()
    if not s:
        return "(tanpa kategori)"
    if s == "withdraw":  # varian ejaan FR
        return "withdrawal"
    return s


def _saldo_batas(items):
    """(saldo_awal, saldo_akhir) akun dari baris ber-balance — kebal acak urutan.

    FR nyata mengacak urutan baris DI DALAM menit yang sama, jadi baris
    pertama/terakhir menurut (Jam, id) belum tentu ujung rantai saldo. Pada
    rantai yang konsisten, tepat SATU pre-balance (balance − delta) tidak
    pernah muncul sebagai balance baris lain (= saldo awal) dan tepat satu
    balance tidak pernah menjadi pre-balance baris lain (= saldo akhir),
    apa pun urutannya. Bila kandidat tidak tunggal (rantai putus = anomali
    FR asli), jatuh kembali ke urutan (Jam, id) agar selisihnya justru
    muncul di kolom kontrol.
    """
    bals, pres = Counter(), Counter()
    for _jam, _pk, delta, balance, _slug in items:
        if balance is not None:
            bals[balance] += 1
            pres[balance - delta] += 1
    if not bals:
        return None, None
    awal = list((pres - bals).elements())
    akhir = list((bals - pres).elements())
    if len(awal) == 1 and len(akhir) == 1:
        return awal[0], akhir[0]
    first = next(t for t in items if t[3] is not None)
    last = next(t for t in reversed(items) if t[3] is not None)
    return first[3] - first[2], last[3]


def _pecah_akun(account):
    """'BANK BRI | YOGA | WITHDRAW' → ('BANK BRI — YOGA', 'WITHDRAW');
    'QRIS HOKI | DEPOSIT / WITHDRAW' → ('QRIS HOKI', 'DEPOSIT / WITHDRAW')."""
    parts = [p.strip() for p in account.split("|") if p.strip()]
    if len(parts) >= 2:
        return " — ".join(parts[:-1]), " ".join(parts[-1].upper().split())
    return account, ""


def _apply_koreksi(toko, tanggal, accounts, slugs_muncul):
    """Timpa nilai sel dengan `FRKoreksi` lalu hitung ulang turunannya.

    Data mentah tak disentuh — hanya dict tampilan. Mutasi = Σ kategori
    (setara Σ delta mentah karena tiap baris FR masuk tepat satu kategori),
    jadi setelah sel kategori diganti, mutasi/deposit/withdraw/net/selisih
    dihitung ulang dari nilai terkoreksi. Koreksi pada akun yang tak hadir
    pada tanggal itu diabaikan (sel tampilan tidak ada).
    """
    from web.models import FRKoreksi  # impor lokal: hindari siklus saat startup

    per_acc = {}
    for k in FRKoreksi.objects.filter(
        toko=toko, tanggal=tanggal
    ).select_related("dibuat_oleh"):
        per_acc.setdefault(k.account, []).append(k)
    if not per_acc:
        return
    for acc in accounts:
        daftar = per_acc.get(acc["account"])
        if not daftar:
            continue
        info = {}
        for k in daftar:
            if k.kolom in ("saldo_awal", "saldo_akhir"):
                asli = acc[k.kolom]
                acc[k.kolom] = k.nilai
            else:
                asli = acc["kategori"].get(k.kolom)
                acc["kategori"][k.kolom] = k.nilai
                slugs_muncul.add(k.kolom)
            info[k.kolom] = {
                "asli": asli, "nilai": k.nilai,
                "alasan": k.get_alasan_display() if k.alasan else "",
                "catatan": k.catatan,
                "oleh": getattr(k.dibuat_oleh, "username", "") or "",
                "waktu": k.updated_at,
            }
        acc["koreksi"] = info
        acc["mutasi"] = sum(acc["kategori"].values(), NOL)
        acc["deposit"] = acc["kategori"].get("deposit", NOL)
        acc["withdraw"] = abs(acc["kategori"].get("withdrawal", NOL))
        acc["net"] = acc["deposit"] - acc["withdraw"]
        acc["selisih"] = None
        if acc["saldo_awal"] is not None and acc["saldo_akhir"] is not None:
            acc["selisih"] = acc["saldo_akhir"] - (acc["saldo_awal"] + acc["mutasi"])


def _norm_akun(bank):
    return str(bank or "").strip() or "(Tanpa Akun)"


def _sql_bank():
    """Ekspresi SQL mentah utk `raw["Bank"]` — per vendor.

    Postgres: WAJIB persis sama dgn kompilasi `KeyTextTransform("Bank","raw")`
    pada index ekspresi `tx_fr_bank_posted_idx` (transactions/models.py), kalau
    tidak planner menolak index-nya dan loose scan di `_saldo_carry` berubah
    jadi O(#akun × sejarah). SQLite (tes & dev, DB kecil): bentuk sederhana —
    index-match tidak penting di sana.
    """
    if connection.vendor == "postgresql":
        return "(raw ->> 'Bank')"
    return "JSON_EXTRACT(raw, '$.\"Bank\"')"


def _sql_st_bracket():
    """Sub-select id SourceType 'bracket' — inline supaya tidak menambah query
    (tes memaku `_saldo_carry` = tepat 2 query; jangan di-hoist ke Python)."""
    return f"(SELECT id FROM {SourceType._meta.db_table} WHERE key = 'bracket')"


def _tanggal(v):
    """Raw cursor SQLite mengembalikan DATE sebagai teks ISO; Postgres objek date."""
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def _saldo_carry(toko, dari):
    """account(ternormalisasi) → saldo penutup pada hari-berbaris TERBARU < `dari`.

    (1) loose index scan REKURSIF (WITH RECURSIVE): enumerasi akun distinct +
    `MAX(posted_date)` per akun untuk baris `posted_date < dari` — tiap langkah
    rekursi = satu index seek di index ekspresi `tx_fr_bank_posted_idx`
    (toko, source_type, raw->>'Bank', posted_date), jadi biayanya
    O(#akun × log N) dan TIDAK tumbuh dengan umur data. Versi lama (agregat
    `Max(posted_date)` grouped) memindai seluruh sejarah bracket toko
    pra-`dari` — terukur di g25 (VPS salinan produksi) 608 ms pada 15 hari
    sejarah → 1.605 ms pada 52 hari, tumbuh selamanya: utang struktural yang
    dipatahkan di sini. Loose scan dipilih ALIH-ALIH tabel snapshot saldo:
    snapshot butuh mekanisme invalidasi saat data lama berubah (retro
    write-back, hapus batch, hapus lewat admin) dan mekanisme itu bisa salah
    diam-diam — loose scan selalu menghitung dari data hidup, tak ada yang
    bisa basi.
    (2) penutup per (akun, tanggal-penutup) via hitungan-bertanda per HARI
    (`_ujung_saldo_hari` — bukan memindahkan satu hari penuh baris ke Python);
    rantai harian yang putus/ambigu jatuh ke fetch baris (akun, hari) itu
    saja + `_saldo_batas` asli, jadi hasilnya identik dgn versi lama. Akun
    dorman bersaldo-lama tetap ikut (tak ada batas lookback). Biaya (2)
    terikat kerja per-hari-penutup (agregat per-hari + fallback akun
    ber-rantai-putus di hari itu) — BUKAN umur data: terukur datar pada
    kedalaman sejarah 30/52/82 hari.

    Varian ejaan mentah (spasi tepi) yang menormal ke akun sama: dipakai
    tanggal TERBESAR — versi lama menimpa dict tanpa urutan tentu
    (nondeterministik); max deterministik dan superset benar.
    """
    tabel = Transaction._meta.db_table
    bank = _sql_bank()
    syarat = f"toko_id = %s AND source_type_id = {_sql_st_bracket()} AND posted_date < %s"
    sql = f"""
        WITH RECURSIVE akun(b) AS (
            SELECT (SELECT {bank} FROM {tabel}
                     WHERE {syarat} AND {bank} IS NOT NULL
                     ORDER BY {bank} LIMIT 1)
            UNION ALL
            SELECT (SELECT {bank} FROM {tabel}
                     WHERE {syarat} AND {bank} > akun.b
                     ORDER BY {bank} LIMIT 1)
              FROM akun WHERE akun.b IS NOT NULL
        )
        SELECT akun.b,
               (SELECT MAX(posted_date) FROM {tabel}
                 WHERE {syarat} AND {bank} = akun.b)
          FROM akun WHERE akun.b IS NOT NULL
        UNION ALL
        SELECT NULL,
               (SELECT posted_date FROM {tabel}
                 WHERE {syarat} AND {bank} IS NULL
                 ORDER BY {bank} DESC, posted_date DESC
                 LIMIT 1)
    """
    # Cabang NULL sengaja BUKAN MAX(posted_date): transformasi min/max membuat
    # planner memilih index (toko, src, posted_date) mundur + Filter bank IS
    # NULL — dan karena baris ber-bank-NULL nyaris tak ada, ia menyaring
    # SELURUH sejarah (terukur 517 rb baris / 747 ms di g25). ORDER BY
    # ({bank} DESC, posted_date DESC) LIMIT 1 hanya bisa dilayani index
    # ekspresi tx_fr_bank_posted_idx → seek langsung, hasilnya identik
    # (semua baris cabang ini ber-bank NULL, jadi urutan bank konstan).
    with connection.cursor() as cur:
        cur.execute(sql, [toko.pk, dari] * 4)
        hasil = cur.fetchall()

    per_acc_date = {}  # account_norm → tanggal-penutup
    varian = {}        # account_norm → himpunan nilai mentah raw["Bank"]
    for b, d in hasil:
        d = _tanggal(d)
        acc = _norm_akun(b)
        varian.setdefault(acc, set()).add(b)
        if d is None:
            continue  # akun tanpa baris pra-`dari` (baris NULL-probe kosong)
        if per_acc_date.get(acc) is None or d > per_acc_date[acc]:
            per_acc_date[acc] = d
    if not per_acc_date:
        return {}

    # Penutup per (akun, hari-penutup) lewat hitungan-bertanda per HARI —
    # bukan memindahkan satu hari penuh baris ke Python (terukur ±0,5 dtk/hari
    # di g25). Rantai harian yang putus/ambigu jatuh ke fetch baris (akun,
    # hari) ITU SAJA + `_saldo_batas` asli — semantik lama dipertahankan.
    hitung = _ujung_saldo_hari(toko, sorted(set(per_acc_date.values())))
    carry, fallback = {}, {}
    for acc, d in per_acc_date.items():
        t = _tepi_dari_hitungan(hitung.get((acc, d), {}))
        if t is not None:
            carry[acc] = t[1]
        else:
            fallback[acc] = d
    if fallback:
        banks, perlu_null = set(), False
        for acc in fallback:
            for v in varian.get(acc, ()):
                if v is None:
                    perlu_null = True
                else:
                    banks.add(v)
        cond = Q(b_txt__in=sorted(banks)) if banks else Q(pk__in=[])
        if perlu_null:
            cond = cond | Q(b_txt__isnull=True)
        rows = (
            Transaction.objects.filter(
                toko=toko, source_type__key="bracket",
                posted_date__in=sorted(set(fallback.values())),
            )
            .annotate(
                b_txt=Cast(KeyTextTransform("Bank", "raw"), TextField()),
                fr_jam=KeyTextTransform("Jam", "raw"),
            )
            .filter(cond)
            .values_list("posted_date", "id", "money_delta", "balance_after", "b_txt", "fr_jam")
        )
        by = {}  # (account_norm, posted_date) → items untuk _saldo_batas
        for pd, pk, delta, bal, bank_v, jam in rows:
            by.setdefault((_norm_akun(bank_v), pd), []).append(
                (f"{pd}T{jam or ''}", pk, delta or NOL, bal, None)
            )
        for acc, d in fallback.items():
            items = by.get((acc, d))
            if not items:
                continue
            items.sort(key=lambda t: (t[0], t[1]))
            _awal, akhir = _saldo_batas(items)
            if akhir is not None:
                carry[acc] = akhir
    return carry


def _desimal(v):
    """Nilai numeric dari raw cursor → Decimal (Postgres sudah Decimal;
    SQLite mengembalikan float — sudah di-ROUND(…,2) di SQL, jadi `str()`
    memberi representasi desimal 2-digit yang tepat)."""
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _ujung_saldo(toko, dari, sampai):
    """account(ternormalisasi) → {nilai: hitungan-bertanda ≠ 0} utk rentang.

    Versi SQL dari inti `_saldo_batas`: multiset `(pres − bals)` /
    `(bals − pres)` bersifat LINIER pada hitungan bertanda, jadi cukup satu
    UNION ALL — tiap baris ber-balance menyumbang `(bank, balance −
    COALESCE(delta,0), +1)` dan `(bank, balance, −1)` — lalu GROUP BY
    (bank, nilai) HAVING SUM ≠ 0. Rantai konsisten menyisakan tepat dua baris
    per akun (pembuka +1, penutup −1) untuk SEBERAPA pun panjang rentangnya;
    nilai yang saling-hapus tidak pernah menyeberang ke Python. `ROUND(…,2)`
    identitas di Postgres (kolomnya numeric ber-skala 2) dan meredam artefak
    float SQLite — artefak yang lolos paling-paling membuat rantai tampak
    putus → jatuh ke `_saldo_fallback` yang menjalankan `_saldo_batas` asli,
    jadi hasil akhirnya tetap identik.
    """
    hasil = _ujung_saldo_sql(
        "posted_date BETWEEN %s AND %s", [toko.pk, dari, sampai], toko
    )
    per_acc = {}
    for b, _pd, val, net in hasil:
        d = per_acc.setdefault(_norm_akun(b), {})
        v = _desimal(val)
        d[v] = d.get(v, 0) + int(net)
    # varian ejaan mentah yang menormal ke akun sama bisa saling-hapus di Python
    return {acc: {v: c for v, c in d.items() if c} for acc, d in per_acc.items()}


def _ujung_saldo_hari(toko, hari):
    """(account, tanggal) → hitungan-bertanda per HARI — utk `_saldo_carry`
    langkah (2): menentukan saldo penutup tiap (akun, hari-penutup) tanpa
    memindahkan satu hari penuh baris ke Python. Mekanisme identik dengan
    `_ujung_saldo`, hanya grup-nya ditambah `posted_date`."""
    if not hari:
        return {}
    ph = ", ".join(["%s"] * len(hari))
    hasil = _ujung_saldo_sql(
        f"posted_date IN ({ph})", [toko.pk, *hari], toko, per_hari=True
    )
    per = {}
    for b, pd, val, net in hasil:
        d = per.setdefault((_norm_akun(b), _tanggal(pd)), {})
        v = _desimal(val)
        d[v] = d.get(v, 0) + int(net)
    return {k: {v: c for v, c in d.items() if c} for k, d in per.items()}


def _ujung_saldo_sql(syarat_tanggal, params, toko, per_hari=False):
    """Eksekusi SQL hitungan-bertanda; baris (b, posted_date|None, val, net)."""
    tabel = Transaction._meta.db_table
    bank = _sql_bank()
    kol_pd = "posted_date" if per_hari else "NULL"
    syarat = (
        f"toko_id = %s AND source_type_id = {_sql_st_bracket()} "
        f"AND {syarat_tanggal} AND balance_after IS NOT NULL"
    )
    sql = f"""
        SELECT b, pd, val, SUM(s) FROM (
            SELECT {bank} AS b, {kol_pd} AS pd,
                   ROUND(balance_after - COALESCE(money_delta, 0), 2) AS val,
                   1 AS s
              FROM {tabel} WHERE {syarat}
            UNION ALL
            SELECT {bank}, {kol_pd}, ROUND(balance_after, 2), -1
              FROM {tabel} WHERE {syarat}
        ) u GROUP BY b, pd, val HAVING SUM(s) <> 0
    """
    with connection.cursor() as cur:
        cur.execute(sql, list(params) + list(params))
        return cur.fetchall()


def _tepi_dari_hitungan(hitung):
    """(saldo_awal, saldo_akhir) bila hitungan bertanda memutuskan TUNGGAL.

    Setara uji `len(awal) == 1 and len(akhir) == 1` di `_saldo_batas` — pada
    MULTIPLISITAS, bukan jumlah entri: {a:+2, b:−1, c:−1} wajib fallback.
    None = rantai putus/ambigu → pemanggil jatuh ke `_saldo_fallback`.
    """
    pos = [(v, c) for v, c in hitung.items() if c > 0]
    neg = [(v, c) for v, c in hitung.items() if c < 0]
    if len(pos) == 1 and pos[0][1] == 1 and len(neg) == 1 and neg[0][1] == -1:
        return pos[0][0], neg[0][0]
    return None


def _saldo_fallback(toko, varian_per_akun, hari_per_akun):
    """Akun ber-rantai putus → semantik fallback `_saldo_batas` (urut
    komposit (tanggalTjam, id), lewati balance NULL): saldo_awal = pre-balance
    baris PERTAMA, saldo_akhir = balance baris TERAKHIR — byte-identik dgn
    versi materialisasi lama.

    Kuncinya: kunci komposit berawalan tanggal ISO, jadi baris pertama pasti
    ada di hari ber-balance PALING AWAL akun itu dan baris terakhir di hari
    PALING AKHIR (`hari_per_akun`, dari Min/Max ber-FILTER di query grup) —
    cukup fetch dua hari itu, bukan seluruh rentang (akun QRIS churn tinggi
    bisa ratusan ribu baris sebulan; fetch penuh terukur 2,5 dtk di g25).
    Satu query utk semua akun fallback sekaligus. `varian_per_akun`:
    acc_norm → himpunan nilai mentah `raw["Bank"]` (dari grup kategori) —
    filter SQL pakai nilai mentah, normalisasi tetap urusan Python (aturan
    yang sama dgn web/detail_fr.py)."""
    banks, perlu_null, hari = set(), False, set()
    for acc, varian in varian_per_akun.items():
        for v in varian:
            if v is None:
                perlu_null = True
            else:
                banks.add(v)
        d_min, d_max = hari_per_akun[acc]
        hari.update({d_min, d_max})
    cond = Q(b_txt__in=sorted(banks)) if banks else Q(pk__in=[])
    if perlu_null:
        cond = cond | Q(b_txt__isnull=True)
    rows = (
        Transaction.objects.filter(
            toko=toko, source_type__key="bracket", posted_date__in=sorted(hari)
        )
        .annotate(
            b_txt=Cast(KeyTextTransform("Bank", "raw"), TextField()),
            fr_jam=KeyTextTransform("Jam", "raw"),
        )
        .filter(cond)
        .values_list("posted_date", "id", "money_delta", "balance_after", "b_txt", "fr_jam")
    )
    per = {}
    for pd, pk, delta, bal, bankv, jam in rows:
        if bal is None:
            continue  # sama dgn skip `t[3] is not None` di _saldo_batas
        per.setdefault(_norm_akun(bankv), []).append(
            (f"{pd}T{jam or ''}", pk, delta or NOL, bal)
        )
    hasil = {}
    for acc in varian_per_akun:
        items = per.get(acc)
        if not items:
            hasil[acc] = (None, None)  # defensif; n_bal>0 menjamin tak terjadi
            continue
        first = min(items, key=lambda t: (t[0], t[1]))
        last = max(items, key=lambda t: (t[0], t[1]))
        hasil[acc] = (first[3] - first[2], last[3])
    return hasil


def bracket_breakdown(toko, dari, sampai=None, dengan_koreksi=True):
    """Agregasi bracket `toko` untuk `posted_date ∈ [dari, sampai]` → dict view.

    Rentang [dari, sampai] (default `sampai=dari` = perilaku 1-hari). Untuk tiap
    akun: `saldo_awal` = saldo penutup (dari−1) bila ada (carry-forward), jika
    tidak pembukaan rantai in-range; `saldo_akhir` = penutup baris hari TERBARU
    ≤ sampai. Akun tanpa baris in-range tapi masih bersaldo (carry ≠ 0) tetap
    tampil sebagai baris carry murni (mutasi 0); yang carry == 0 disembunyikan.
    Koreksi FR (`FRKoreksi`) hanya berlaku pada tampilan 1 hari (`dari == sampai`).

    {"accounts": [per akun], "kolom": [(slug, label) yang muncul],
     "total": agregat lintas akun, "count": jumlah baris in-range,
     "dari": date, "sampai": date}
    """
    if sampai is None:
        sampai = dari
    if dari > sampai:
        dari, sampai = sampai, dari

    # Agregasi di SQL, bukan materialisasi baris ke Python (pola yang sama
    # dgn arah web/rekening.py): satu query grouped (Bank, Kategori) utk sel
    # kategori/mutasi/trx/count, satu query `_ujung_saldo` utk ujung rantai
    # saldo. Yang menyeberang ke Python hanya #grup (puluhan), bukan #baris
    # (ratusan ribu utk rentang sebulan).
    grup = list(
        Transaction.objects.filter(
            toko=toko, source_type__key="bracket", posted_date__range=(dari, sampai)
        )
        .annotate(
            fr_bank=KeyTextTransform("Bank", "raw"),
            fr_kategori=KeyTextTransform("Kategori", "raw"),
        )
        .values("fr_bank", "fr_kategori")
        .annotate(
            v=Sum("money_delta"), n=Count("id"), n_bal=Count("balance_after"),
            # hari ber-balance paling awal/akhir per grup — modal _saldo_fallback
            # utk fetch dua hari saja (bukan seluruh rentang); satu pass yang sama
            d_min=Min("posted_date", filter=Q(balance_after__isnull=False)),
            d_max=Max("posted_date", filter=Q(balance_after__isnull=False)),
        )
    )

    count = 0
    per_akun = {}  # acc → {"kategori": {slug: Σdelta}, "trx", "n_bal", "varian", "hari"}
    for g in grup:
        acc = _norm_akun(g["fr_bank"])
        slug = _slug_kategori(g["fr_kategori"])
        sel = per_akun.setdefault(
            acc, {"kategori": {}, "trx": 0, "n_bal": 0, "varian": set(),
                  "hari": [None, None]}
        )
        # `or NOL` menelan Decimal("0.00") (falsy) dan menggantinya dengan NOL
        # ber-skala 0, sehingga sel yang deltanya saling meniadakan berubah
        # dari "0.00" jadi "0". Nilainya sama, tapi tak perlu berbeda.
        v = NOL if g["v"] is None else g["v"]
        sel["kategori"][slug] = sel["kategori"].get(slug, NOL) + v
        if slug in ("deposit", "withdrawal"):
            sel["trx"] += g["n"]
        sel["n_bal"] += g["n_bal"]
        sel["varian"].add(g["fr_bank"])
        if g["d_min"] is not None and (sel["hari"][0] is None or g["d_min"] < sel["hari"][0]):
            sel["hari"][0] = g["d_min"]
        if g["d_max"] is not None and (sel["hari"][1] is None or g["d_max"] > sel["hari"][1]):
            sel["hari"][1] = g["d_max"]
        count += g["n"]

    # ujung rantai saldo per akun: jalur cepat hitungan-bertanda; rantai
    # putus/ambigu → _saldo_fallback (semantik fallback _saldo_batas asli)
    hitung = _ujung_saldo(toko, dari, sampai) if per_akun else {}
    tepi, akun_fallback, hari_fallback = {}, {}, {}
    for account, sel in per_akun.items():
        if sel["n_bal"] == 0:
            tepi[account] = (None, None)  # akun tanpa satu pun balance
            continue
        t = _tepi_dari_hitungan(hitung.get(account, {}))
        if t is None:
            akun_fallback[account] = sel["varian"]
            hari_fallback[account] = tuple(sel["hari"])
        else:
            tepi[account] = t
    if akun_fallback:
        tepi.update(_saldo_fallback(toko, akun_fallback, hari_fallback))

    carry = _saldo_carry(toko, dari)  # account_norm → penutup (dari−1)

    accounts, slugs_muncul, seen = [], set(), set()
    for account, sel in per_akun.items():
        kategori_sum = sel["kategori"]
        mutasi = sum(kategori_sum.values(), NOL)
        trx = sel["trx"]
        deposit = kategori_sum.get("deposit", NOL)
        withdraw = kategori_sum.get("withdrawal", NOL)
        chain_awal, saldo_akhir = tepi[account]
        # utamakan penutup (dari−1) sebagai saldo awal; fallback pembukaan rantai
        saldo_awal = carry.get(account, chain_awal)
        withdraw = abs(withdraw)
        selisih = None
        if saldo_awal is not None and saldo_akhir is not None:
            selisih = saldo_akhir - (saldo_awal + mutasi)
        slugs_muncul.update(kategori_sum)
        name, role = _pecah_akun(account)
        seen.add(account)
        accounts.append({
            "account": account, "name": name, "role": role,
            "saldo_awal": saldo_awal, "saldo_akhir": saldo_akhir,
            "mutasi": mutasi, "selisih": selisih, "kategori": kategori_sum,
            "deposit": deposit, "withdraw": withdraw,
            "net": deposit - withdraw, "trx": trx,
            "koreksi": {},
        })

    # akun dorman: tak ada baris in-range tapi masih bersaldo (carry ≠ 0)
    for account, closing in carry.items():
        if account in seen or closing is None or closing == NOL:
            continue  # sudah tampil, atau saldo nol → disembunyikan
        name, role = _pecah_akun(account)
        accounts.append({
            "account": account, "name": name, "role": role,
            "saldo_awal": closing, "saldo_akhir": closing,
            "mutasi": NOL, "selisih": NOL, "kategori": {},
            "deposit": NOL, "withdraw": NOL, "net": NOL, "trx": 0,
            "koreksi": {},
        })

    if dengan_koreksi and dari == sampai:
        _apply_koreksi(toko, dari, accounts, slugs_muncul)

    accounts.sort(key=lambda a: (_URUT_PERAN.get(a["role"], 3), a["name"], a["account"]))

    kolom = [(slug, label) for slug, label in KATEGORI_KANONIK if slug in slugs_muncul]
    kolom += [
        (slug, slug.title())
        for slug in sorted(slugs_muncul - set(_KANONIK_URUT))
    ]

    total = {
        "kategori": {}, "mutasi": NOL, "deposit": NOL, "withdraw": NOL,
        "net": NOL, "trx": 0, "saldo_awal": None, "saldo_akhir": None, "selisih": None,
    }
    for acc in accounts:
        for slug, val in acc["kategori"].items():
            total["kategori"][slug] = total["kategori"].get(slug, NOL) + val
        total["mutasi"] += acc["mutasi"]
        total["deposit"] += acc["deposit"]
        total["withdraw"] += acc["withdraw"]
        total["net"] += acc["net"]
        total["trx"] += acc["trx"]
        for key in ("saldo_awal", "saldo_akhir", "selisih"):
            if acc[key] is not None:
                total[key] = (total[key] or NOL) + acc[key]

    return {
        "accounts": accounts,
        "kolom": kolom,
        "total": total,
        "count": count,
        "dari": dari,
        "sampai": sampai,
    }


def ringkas_bracket_hari(toko, tanggal, dengan_koreksi=True):
    """Ringkasan bracket 1-hari RINGAN untuk kartu dashboard.

    Beda dengan `bracket_breakdown`: TIDAK memanggil `_saldo_carry` (scan
    seluruh sejarah toko) — tak layak dipanggil di tiap render dashboard.
    Satu query grouped `(Bank, Kategori)` via `values().annotate(Sum, Count)`
    + (opsional) satu query overlay `FRKoreksi`, sehingga dp/wd tetap TEPAT
    SAMA dengan `bracket_breakdown(toko, tanggal)["total"]["deposit"/"withdraw"]`
    — nilai deposit/withdraw sama sekali tak bergantung pada saldo carry.

    Aturan skip-akun-absen mengikuti `_apply_koreksi`: koreksi hanya berlaku
    pada akun yang punya baris bracket (kategori APA PUN) di tanggal itu —
    bukan cuma akun yang punya baris deposit/withdrawal. `n` (jumlah trx)
    selalu dari baris nyata; koreksi hanya menimpa nilai (`v`).

    {"dp": {"n", "v"}, "wd": {"n", "v"}, "net", "total_n"} atau None bila
    `toko` tak punya baris bracket pada `tanggal`.
    """
    rows = list(
        Transaction.objects.filter(
            toko=toko, source_type__key="bracket", posted_date=tanggal
        )
        .annotate(
            fr_bank=KeyTextTransform("Bank", "raw"),
            fr_kategori=KeyTextTransform("Kategori", "raw"),
        )
        .values("fr_bank", "fr_kategori")
        .annotate(v=Sum("money_delta"), n=Count("id"))
    )
    if not rows:
        return None

    per_acc = {}  # account_norm → {slug: {"v": Decimal, "n": int}}
    for r in rows:
        sel = per_acc.setdefault(_norm_akun(r["fr_bank"]), {})
        slug = _slug_kategori(r["fr_kategori"])
        cur = sel.get(slug)
        if cur is None:
            sel[slug] = {"v": r["v"] or NOL, "n": r["n"]}
        else:
            cur["v"] += r["v"] or NOL
            cur["n"] += r["n"]

    if dengan_koreksi:
        from web.models import FRKoreksi  # impor lokal: hindari siklus saat startup

        for k in FRKoreksi.objects.filter(
            toko=toko, tanggal=tanggal, kolom__in=("deposit", "withdrawal")
        ).values("account", "kolom", "nilai"):
            sel = per_acc.get(k["account"])
            if sel is None:
                continue  # akun tak hadir tanggal ini → koreksi diabaikan
            cur = sel.get(k["kolom"])
            sel[k["kolom"]] = {"v": k["nilai"], "n": cur["n"] if cur else 0}

    dp_v = wd_v = NOL
    dp_n = wd_n = 0
    for sel in per_acc.values():
        dp = sel.get("deposit")
        if dp:
            dp_v += dp["v"]
            dp_n += dp["n"]
        wd = sel.get("withdrawal")
        if wd:
            wd_v += wd["v"]
            wd_n += wd["n"]
    wd_v = abs(wd_v)

    return {
        "dp": {"n": dp_n, "v": dp_v},
        "wd": {"n": wd_n, "v": wd_v},
        "net": dp_v - wd_v,
        "total_n": dp_n + wd_n,
    }


def ringkas_bracket_rentang(toko, dari, sampai):
    """Ringkasan bracket RENTANG untuk kartu dashboard mode filter tanggal.

    `dari == sampai` → delegasi ke `ringkas_bracket_hari` (dengan overlay
    `FRKoreksi`) — sama dengan halaman /bracket/ 1-hari yang jadi tujuan
    kliknya. Rentang > 1 hari → agregat mentah TANPA overlay, mengikuti
    aturan `bracket_breakdown` mode rentang (koreksi hanya berlaku 1-hari),
    supaya kartu tie out persis dengan `total["deposit"/"withdraw"/"trx"]`
    halaman rentangnya. `withdraw` di-abs PER AKUN (bukan global) — persis
    cara `bracket_breakdown` menjumlah lintas akun.

    Satu query grouped `(Bank, Kategori)`; bentuk hasil sama dengan
    `ringkas_bracket_hari`, atau None bila tak ada baris bracket in-range.
    """
    if dari > sampai:
        dari, sampai = sampai, dari
    if dari == sampai:
        return ringkas_bracket_hari(toko, dari)
    rows = list(
        Transaction.objects.filter(
            toko=toko, source_type__key="bracket",
            posted_date__range=(dari, sampai),
        )
        .annotate(
            fr_bank=KeyTextTransform("Bank", "raw"),
            fr_kategori=KeyTextTransform("Kategori", "raw"),
        )
        .values("fr_bank", "fr_kategori")
        .annotate(v=Sum("money_delta"), n=Count("id"))
    )
    if not rows:
        return None

    dp_v = NOL
    dp_n = wd_n = 0
    wd_per_akun = {}  # account_norm → Σ delta withdrawal (abs belakangan)
    for r in rows:
        slug = _slug_kategori(r["fr_kategori"])
        if slug == "deposit":
            dp_v += r["v"] or NOL
            dp_n += r["n"]
        elif slug == "withdrawal":
            akun = _norm_akun(r["fr_bank"])
            wd_per_akun[akun] = wd_per_akun.get(akun, NOL) + (r["v"] or NOL)
            wd_n += r["n"]
    wd_v = sum((abs(v) for v in wd_per_akun.values()), NOL)

    return {
        "dp": {"n": dp_n, "v": dp_v},
        "wd": {"n": wd_n, "v": wd_v},
        "net": dp_v - wd_v,
        "total_n": dp_n + wd_n,
    }
