"""Detail FR/Bracket — baris-baris di balik tiap sel Control Bracket.

`/bracket/` menjawab "berapa"; halaman ini menjawab "isinya apa saja". Permintaan
aslinya persis begitu: sel Adjustment sebuah rekening tertulis −450.000, dan
yang ingin diketahui adalah tiga baris apa yang menyusunnya.

**Satu sifat yang menentukan segalanya: rincian ini WAJIB menjumlah balik persis
ke sel di `/bracket/`.** Kalau meleset sedikit pun, halaman ini lebih berbahaya
daripada tidak ada — orang akan menyandarkan keputusan pada angka yang salah.
Karena itu modul ini:

* memakai queryset yang SAMA PERSIS dengan `bracket_breakdown` — `posted_date`
  (bukan `occurred_at`), TANPA `is_duplicate=False`, TANPA membuang
  `jenis="admin"`, dan TANPA menyaring baris yang sudah dikonsumsi batch. Ketiga
  penyaring itu lazim di modul lain aplikasi ini; membiarkannya bocor ke sini
  akan membuat angkanya meleset diam-diam;
* MENGIMPOR `_norm_akun` dan `_slug_kategori` dari `web.breakdown`, tidak pernah
  menyalinnya. Kunci sel adalah hasil normalisasi Python itu ("Withdraw" dan
  "Withdrawal" satu sel; spasi ganda pada nama akun dirapikan), sehingga
  penyaringan juga dilakukan di Python — perbandingan langsung di SQL akan
  kehilangan baris berejaan varian, dan `KeyTextTransform` di WHERE menuntut
  `Cast` (lihat CLAUDE.md);
* melaporkan koreksi `FRKoreksi` alih-alih menyembunyikannya: sel yang dikoreksi
  manual memang tidak sama dengan jumlah baris aslinya, dan itu harus terbaca
  sebagai catatan, bukan sebagai selisih misterius. Sama seperti `/bracket/`,
  koreksi hanya berlaku pada mode satu hari.

Query-time murni, tanpa migrasi — berlaku surut untuk seluruh data lama.
"""
from django.db.models.fields.json import KeyTextTransform

from transactions.models import Transaction
from web.breakdown import (
    KATEGORI_KANONIK,
    NOL,
    _norm_akun,
    _pecah_akun,
    _slug_kategori,
)

_KANONIK_LABEL = dict(KATEGORI_KANONIK)
_KANONIK_URUT = {slug: i for i, (slug, _) in enumerate(KATEGORI_KANONIK)}


def label_kategori(slug):
    """Slug → label tampilan; kategori baru dari FR tampil apa adanya."""
    return _KANONIK_LABEL.get(slug, slug.title())


def _urut_kategori(slug):
    return (_KANONIK_URUT.get(slug, len(_KANONIK_URUT)), slug)


def _koreksi_sel(toko, tanggal, akun, kolom):
    """Koreksi manual pada satu sel, bila ada. None = sel apa adanya."""
    from web.models import FRKoreksi  # impor lokal: hindari siklus saat startup

    k = (
        FRKoreksi.objects.filter(toko=toko, tanggal=tanggal, account=akun, kolom=kolom)
        .select_related("dibuat_oleh")
        .first()
    )
    if not k:
        return None
    return {
        "nilai": k.nilai,
        "alasan": k.get_alasan_display() if k.alasan else "",
        "catatan": k.catatan,
        "oleh": getattr(k.dibuat_oleh, "username", "") or "",
        "waktu": k.updated_at,
    }


def detail_fr(toko, dari, sampai=None, akun="", kategori="", q=""):
    """Baris FR mentah untuk `posted_date ∈ [dari, sampai]`, tersaring.

    `akun` = label `raw["Bank"]` seperti tampil di `/bracket/`; `kategori` = slug
    kategori (mis. ``"adjustment"``); `q` = cari bebas pada keterangan, member,
    dan username. Argumen kosong berarti "semua".

    {"baris": [...], "total": Decimal, "jumlah": int,
     "akun_pilihan": [...], "kategori_pilihan": [...], "koreksi": dict|None,
     "dari": date, "sampai": date, "akun": str, "kategori": str, "q": str}
    """
    if sampai is None:
        sampai = dari
    if dari > sampai:
        dari, sampai = sampai, dari

    # Penyaring sengaja seminimal breakdown — lihat docstring modul.
    rows = (
        Transaction.objects.filter(
            toko=toko, source_type__key="bracket", posted_date__range=(dari, sampai)
        )
        .annotate(
            fr_bank=KeyTextTransform("Bank", "raw"),
            fr_kategori=KeyTextTransform("Kategori", "raw"),
            fr_jam=KeyTextTransform("Jam", "raw"),
        )
        .values_list(
            "id", "posted_date", "money_delta", "balance_after",
            "fr_bank", "fr_kategori", "fr_jam",
            "counterparty", "username", "description",
        )
    )

    akun_pilih = _norm_akun(akun) if akun else ""
    kategori_pilih = kategori or ""
    cari = " ".join(str(q or "").split()).lower()

    baris, total, akun_n, kategori_n = [], NOL, {}, {}
    for (pk, pd, delta, saldo, bank, kat, jam,
         member, username, keterangan) in rows:
        account = _norm_akun(bank)
        slug = _slug_kategori(kat)
        # Pilihan filter dihitung dari SELURUH baris in-range, bukan dari hasil
        # tersaring — kalau tidak, memilih satu akun akan melenyapkan akun lain
        # dari daftarnya dan pemakai terkunci pada pilihannya sendiri.
        akun_n[account] = akun_n.get(account, 0) + 1
        kategori_n[slug] = kategori_n.get(slug, 0) + 1

        if akun_pilih and account != akun_pilih:
            continue
        if kategori_pilih and slug != kategori_pilih:
            continue
        if cari and cari not in " ".join(
            filter(None, [str(keterangan or ""), str(member or ""), str(username or "")])
        ).lower():
            continue

        delta = delta or NOL
        total += delta
        nama, peran = _pecah_akun(account)
        baris.append({
            "id": pk,
            "tanggal": pd,
            "jam": jam or "",
            "account": account,
            "name": nama,
            "role": peran,
            "kategori_slug": slug,
            "kategori_label": label_kategori(slug),
            "member": member or "",
            "username": username or "",
            "keterangan": keterangan or "",
            "nominal": delta,
            "saldo": saldo,
        })

    # Kronologi yang sama dengan rantai saldo di breakdown: (tanggal T jam, id).
    baris.sort(key=lambda b: (f"{b['tanggal']}T{b['jam']}", b["id"]))

    koreksi = None
    if akun_pilih and kategori_pilih and dari == sampai:
        koreksi = _koreksi_sel(toko, dari, akun_pilih, kategori_pilih)

    return {
        "baris": baris,
        "total": total,
        "jumlah": len(baris),
        "akun_pilihan": [
            {"account": a, "n": n, "name": _pecah_akun(a)[0], "role": _pecah_akun(a)[1]}
            for a, n in sorted(akun_n.items(), key=lambda kv: kv[0])
        ],
        "kategori_pilihan": [
            {"slug": s, "label": label_kategori(s), "n": n}
            for s, n in sorted(kategori_n.items(), key=lambda kv: _urut_kategori(kv[0]))
        ],
        "koreksi": koreksi,
        "dari": dari,
        "sampai": sampai,
        "akun": akun_pilih,
        "kategori": kategori_pilih,
        "q": q or "",
    }
