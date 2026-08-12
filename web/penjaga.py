"""Penjaga kesalahan upload — MEMPERINGATKAN, tidak pernah menghalangi.

Tiga pemeriksaan yang jalan sekali tepat setelah sebuah file selesai di-ingest,
menangkap salah-tarik di detik terjadinya alih-alih lewat tumpukan merah
berhari-hari kemudian:

1. **Tanggal isi vs tanggal di nama file** — file bernama ``01-08-2026`` yang
   isinya 30/06–01/07 pernah menarik batas bawah rentang panel mundur sebulan
   dan membuat seluruh mutasi Juli diprotes gerbang panel-penutup.
2. **Jumlah baris vs kebiasaan** — file gateway 9.156 baris pada aliran yang
   kebiasaannya 615–714 baris/hari. Kebiasaan dihitung PER ALIRAN (berkas
   berulang yang sama), bukan per jenis sumber — lihat `kunci_aliran`.
3. **Irisan kode transaksi dengan panel** — file gateway yang tak satu pun
   kode transaksinya dikenal panel hari itu; pada kasus nyata seluruh 9.156
   barisnya milik merchant lain dan melahirkan 9.618 baris "uang tanpa panel".
   Pemeriksaan ini BERJANGKAR: ia hanya boleh menuduh bila panel dengan ARAH
   YANG SAMA (DP/WD) untuk tanggal berkas itu sudah ada. Sebelum itu penjaga
   diam, karena satu kiriman berisi belasan berkas dua arah dan urutannya
   sembarang. Yang dijamin persis sebatas itu — bukan "urutan unggah tak
   pernah mengubah putusan". Sisa lubangnya jujur disebut: pada toko yang
   panel se-arahnya terpecah beberapa berkas di hari yang sama (Vigor/TMG:
   "PANEL DP" sisi bank ±140 baris DAN "PANEL QRIS DP" ±6.900 baris), berkas
   panel se-arah MANA PUN sudah membuka jangkar, jadi berkas gateway yang
   pasangannya belum masuk masih bisa dituduh. Arah salahnya aman —
   peringatan muncul terlalu dini, tak pernah tertelan — dan jalur ini toh
   hanya memperingatkan.

**Kenapa hanya peringatan.** Ketiganya menyimpulkan dari kebiasaan, dan
kebiasaan itu belum ada pada brand baru, merchant baru, atau hari pertama
sebuah sumber dipakai. Memblokir berarti satu ambang yang salah kalibrasi bisa
membuat toko tak bisa bekerja sama sekali sampai kodenya diperbaiki — harga
yang jauh lebih mahal daripada satu peringatan yang terlewat dibaca. Tiap
pemeriksaan juga DIAM saat buktinya tipis (riwayat terlalu pendek, panel
pembanding belum ada, file terlalu kecil): lebih baik lewat daripada salah
tuduh, karena penjaga yang sering salah akan diabaikan orang.

Fungsi pemeriksanya sengaja MURNI (masukan berupa angka/himpunan, bukan
queryset) supaya kalibrasi ambangnya bisa diuji tanpa menyentuh basis data;
hanya `periksa_upload` yang berbicara dengan DB.
"""
import logging
import re
import statistics
from datetime import date, timedelta

from django.db.models import Max, Min

from transactions.models import Transaction

log = logging.getLogger(__name__)

#: Toleransi jarak tanggal nama-file vs isi. 1 hari menutup pola sah yang paling
#: lazim: panel tanggal D memuat request D-1 larut malam yang di-approve tanggal D.
TOLERANSI_TANGGAL = 1

#: Volume: butuh minimal sekian upload sebelumnya DARI ALIRAN YANG SAMA sebelum
#: berani bicara, dan kebiasaan itu sendiri harus cukup besar — sumber
#: bervolume kecil (WD QRIS ±25 baris) berayun 3-4 kali lipat secara wajar.
MIN_RIWAYAT = 5
MIN_BIASA = 20
LIPAT_VOLUME = 4

#: Berapa upload terakhir (satu sumber, satu toko) yang disisir untuk mencari
#: 10 tetangga se-aliran. SLO mengunggah ±4 berkas panel dan belasan berkas bank
#: per hari, jadi 120 menutup sekitar dua pekan — cukup dalam, tetap satu query.
JENDELA_SISIR = 120

#: Irisan kunci: butuh sekian kode transaksi sebelum disebut pola, dan berbunyi
#: di bawah sekian persen. Hari normal berada di ~100% (kalibrasi W25 03–04/08:
#: 710 dan 704 pasangan dari ±700 baris), jadi 10% sangat longgar.
MIN_KUNCI = 20
AMBANG_IRISAN = 0.10

# Tanggal di nama file. Urutan pola = urutan keyakinan; pola pertama yang
# menghasilkan kecocokan dipakai, sisanya tidak diperiksa lagi.
_POLA_ISO = re.compile(r"(?<!\d)(\d{4})[-_/.](\d{1,2})[-_/.](\d{1,2})(?!\d)")
_POLA_LENGKAP = re.compile(r"(?<!\d)(\d{1,2})[-_/.](\d{1,2})[-_/.](\d{4})(?!\d)")
# Tanpa tahun: WAJIB dua digit di kedua sisi. Bentuk satu digit ("1-2") terlalu
# sering muncul di potongan nama rekening/cabang dan cuma melahirkan salah tuduh.
_POLA_PENDEK = re.compile(r"(?<!\d)(\d{2})[-_/.](\d{2})(?!\d)")


def _ribu(n):
    """1234567 -> '1.234.567' (pemisah ribuan Indonesia)."""
    return f"{int(n):,}".replace(",", ".")


def _sah(hari, bulan):
    return 1 <= hari <= 31 and 1 <= bulan <= 12


def kunci_aliran(nama):
    """Nama file -> identitas "laporan berulang" yang sama; None bila tak terbaca.

    Kebiasaan volume HARUS dihitung per aliran, bukan per jenis sumber. Satu
    `source_type` menampung berkas yang volumenya berbeda jauh: pada panel
    Vigor/TM Gaming, "PANEL DP SLO" (±140 baris, pasangannya bank) dan
    "PANEL QRIS DP SLO" (±6.900 baris, pasangannya berkas QRIS) sama-sama
    `panel`+`dp`; berkas bank pun terpisah per rekening. Kolam campur begitu
    bermodus-dua dan mediannya jatuh di lembah kosong di antaranya — pada data
    nyata SLO 3 Agustus 2026 median kolam campurnya 2.670, angka yang tidak
    menggambarkan satu pun dari keduanya. Lebih buruk lagi, nilainya bergeser
    mengikuti URUTAN unggah dalam satu kiriman: berkas panel-bank dinilai
    terhadap median 2.670, berkas QRIS sedetik kemudian terhadap 147. Tiga
    peringatan palsu lahir dari situ.

    Identitas aliran diambil dari kebiasaan penamaan pengunggah sendiri: buang
    tanggal dan ekstensi, sisanya jadi HIMPUNAN kata. Himpunan (bukan urutan)
    disengaja — W25 pernah berganti dari "QRIS UNOPAY DP W25" ke "W25 DP QRIS
    UNOPAY"; sebagai urutan itu dua aliran, sebagai himpunan tetap satu.
    Bila penamaannya benar-benar berubah, kolamnya memang kosong dan penjaga
    diam sampai kebiasaan baru terbentuk — gagal-aman, bukan salah tuduh.
    """
    teks = (nama or "").lower()
    teks = re.sub(r"(\.[a-z0-9]{1,5})+$", "", teks)  # ekstensi, termasuk ".xlsx.xlsx"
    for pola in (_POLA_ISO, _POLA_LENGKAP, _POLA_PENDEK):
        teks = pola.sub(" ", teks)
    token = [t for t in re.split(r"[^a-z0-9]+", teks) if t]
    # Sisa angka pendek = pecahan tanggal yang lolos; kode brand ("w25", "oke25")
    # selamat karena bercampur huruf.
    token = {t for t in token if not (t.isdigit() and len(t) <= 4)}
    return tuple(sorted(token)) or None


def tanggal_dari_nama(nama):
    """``"06-08-2026 W25 DP.xlsx"`` -> ``(6, 8, 2026)``; tahun boleh None.

    Mengembalikan None bila tak ada tanggal yang meyakinkan ATAU bila nama file
    memuat lebih dari satu tanggal berbeda — nama berentang ("01-07 sd 31-07")
    tidak boleh ditebak, karena tebakan yang salah akan berbunyi setiap hari.
    """
    teks = nama or ""
    for pola, urut in ((_POLA_ISO, "ymd"), (_POLA_LENGKAP, "dmy"), (_POLA_PENDEK, "dm")):
        temuan = set()
        for m in pola.finditer(teks):
            a, b, c = (m.group(1), m.group(2), m.group(3) if pola is not _POLA_PENDEK else None)
            if urut == "ymd":
                hari, bulan, tahun = int(c), int(b), int(a)
            elif urut == "dmy":
                hari, bulan, tahun = int(a), int(b), int(c)
            else:
                hari, bulan, tahun = int(a), int(b), None
            if not _sah(hari, bulan):
                continue
            if tahun is not None and not 2000 <= tahun <= 2100:
                continue
            temuan.add((hari, bulan, tahun))
        if len(temuan) == 1:
            return temuan.pop()
        if temuan:
            return None  # ambigu pada tingkat keyakinan ini — jangan turun lagi
    return None


def periksa_tanggal_isi(nama, isi_dari, isi_sampai, toleransi=TOLERANSI_TANGGAL):
    """None bila wajar; dict bila tanggal di nama file jauh dari isi file.

    Tahun yang tidak tertulis di nama file diambil dari tahun isi (kedua ujungnya,
    lalu yang terdekat yang menang) — tanpa itu ekspor pergantian tahun akan
    salah tuduh setiap 1 Januari.
    """
    terbaca = tanggal_dari_nama(nama)
    if not terbaca or not isi_dari or not isi_sampai:
        return None
    hari, bulan, tahun = terbaca
    tahun_calon = [tahun] if tahun else sorted({isi_dari.year, isi_sampai.year})
    kandidat = []
    for th in tahun_calon:
        try:
            kandidat.append(date(th, bulan, hari))
        except ValueError:
            continue  # mis. 31 April
    if not kandidat:
        return None

    bawah, atas = isi_dari - timedelta(days=toleransi), isi_sampai + timedelta(days=toleransi)

    def jarak(t):
        if t < bawah:
            return (bawah - t).days
        if t > atas:
            return (t - atas).days
        return 0

    terdekat = min(kandidat, key=jarak)
    selisih = jarak(terdekat)
    if not selisih:
        return None
    return {
        "tanggal_nama": terdekat,
        "isi_dari": isi_dari,
        "isi_sampai": isi_sampai,
        "selisih_hari": selisih,
    }


def periksa_volume(baris, riwayat, minimal_riwayat=MIN_RIWAYAT,
                   minimal_biasa=MIN_BIASA, lipat=LIPAT_VOLUME):
    """None bila wajar; dict bila jumlah baris jauh dari kebiasaan.

    `riwayat` = jumlah baris upload-upload sebelumnya DARI ALIRAN YANG SAMA
    (lihat `kunci_aliran` — mencampur aliran melahirkan peringatan palsu).
    Median dipakai, bukan rata-rata: satu file salah tarik di riwayat tak
    boleh menggeser acuan sampai file salah berikutnya terlihat normal.
    """
    if baris <= 0:
        return None  # 0 baris punya jalur pesannya sendiri (parse gagal / duplikat penuh)
    riwayat = [n for n in riwayat if n > 0]
    if len(riwayat) < minimal_riwayat:
        return None
    biasa = statistics.median(riwayat)
    if biasa < minimal_biasa:
        return None
    if baris > biasa * lipat:
        arah = "atas"
    elif baris * lipat < biasa:
        arah = "bawah"
    else:
        return None
    return {"baris": baris, "biasanya": biasa, "arah": arah}


def periksa_irisan_kunci(kunci_file, kunci_panel, ambang=AMBANG_IRISAN, minimum=MIN_KUNCI):
    """None bila wajar; dict bila kode transaksi file hampir tak dikenal panel.

    Diam saat panel pembanding kosong (panelnya memang belum diupload) atau saat
    file tak membawa kunci sama sekali — RafflesPay sengaja tanpa `reference`,
    dan itu bukan kesalahan.

    Kolam kosong bukan satu-satunya bentuk "panel belum diupload": kolam yang
    melebar ±1 hari bisa terisi panel KEMARIN saja, atau panel ARAH LAIN hari
    itu (tiket W… tak akan pernah memuat tiket D…). Jangkar tanggal+arahnya ada
    di `_periksa` — satu-satunya yang bicara dengan DB dan karenanya satu-satunya
    yang bisa tahu.
    """
    if len(kunci_file) < minimum or not kunci_panel:
        return None
    cocok = len(kunci_file & kunci_panel)
    rasio = cocok / len(kunci_file)
    if rasio >= ambang:
        return None
    return {"cocok": cocok, "total": len(kunci_file), "rasio": rasio}


def _isi_upload(up):
    """Baris yang MEWAKILI isi file: baris milik upload ini + baris yang di-skip
    dedup tapi ter-link padanya. Tanpa link itu, upload ulang yang hanya
    menambah sedikit baris akan terlihat seperti file mungil."""
    return Transaction.objects.filter(upload=up), up.duplicate_transactions.all()


def _rentang_tanggal(*querysets):
    lo = hi = None
    for qs in querysets:
        a = qs.aggregate(lo=Min("occurred_at"), hi=Max("occurred_at"))
        if a["lo"] and (lo is None or a["lo"] < lo):
            lo = a["lo"]
        if a["hi"] and (hi is None or a["hi"] > hi):
            hi = a["hi"]
    return (lo.date() if lo else None), (hi.date() if hi else None)


def _kunci(qs, kolom):
    return {v for v in qs.values_list(kolom, flat=True) if v}


def periksa_upload(up):
    """Jalankan ketiga pemeriksaan atas satu Upload → daftar pesan siap tampil.

    Tak pernah melempar: penjaga yang bisa menggagalkan upload lebih berbahaya
    daripada penjaga yang sesekali bungkam. Kegagalannya dicatat ke log.
    """
    try:
        return _periksa(up)
    except Exception:  # noqa: BLE001 - penjaga tak boleh menjatuhkan upload
        log.exception("Penjaga upload gagal untuk Upload #%s", getattr(up, "pk", "?"))
        return []


def _periksa(up):
    pesan = []
    milik, terduplikat = _isi_upload(up)
    n_baris = (up.rows_parsed or 0) + (up.rows_duplicate or 0)
    isi_dari, isi_sampai = _rentang_tanggal(milik, terduplikat)
    nama = up.original_name or ""

    h = periksa_tanggal_isi(nama, isi_dari, isi_sampai)
    if h:
        rentang = h["isi_dari"].strftime("%d/%m/%Y")
        if h["isi_sampai"] != h["isi_dari"]:
            rentang += "–" + h["isi_sampai"].strftime("%d/%m/%Y")
        pesan.append(
            f'"{nama}" — tanggal di nama file ({h["tanggal_nama"]:%d/%m/%Y}) '
            f'terpaut {h["selisih_hari"]} hari dari isinya ({rentang}). '
            "Pastikan periode ekspornya benar."
        )

    # Kolam kebiasaan = 10 upload terakhir SE-ALIRAN (bukan se-jenis-sumber).
    # `flow` sengaja TIDAK ikut menyaring: arahnya sudah terbawa nama file, dan
    # deteksi flow yang meleset pada satu berkas akan memecah kolam tanpa sebab.
    aliran = kunci_aliran(up.original_name)
    riwayat = []
    if aliran:
        # NB: nama tetangga TIDAK boleh dinamai `nama` — itu variabel berkas yang
        # sedang diperiksa, dipakai dua pesan di bawah. Pernah tertimpa sekali dan
        # peringatannya menyebut nama berkas tetangga (`test_pesan_menyebut_nama_
        # berkas_yang_diperiksa` menjaganya).
        for nama_lain, parsed, dup in (
            type(up).objects
            .filter(toko=up.toko, source_type=up.source_type, status=up.PARSED)
            .exclude(pk=up.pk)
            .order_by("-id")
            .values_list("original_name", "rows_parsed", "rows_duplicate")[:JENDELA_SISIR]
        ):
            if kunci_aliran(nama_lain) == aliran:
                riwayat.append((parsed or 0) + (dup or 0))
                if len(riwayat) == 10:
                    break
    h = periksa_volume(n_baris, riwayat)
    if h:
        arah = "jauh di atas" if h["arah"] == "atas" else "jauh di bawah"
        pesan.append(
            f'"{nama}" — {_ribu(h["baris"])} baris, {arah} kebiasaan berkas ini '
            f'di toko ini (biasanya ±{_ribu(round(h["biasanya"]))}). '
            "Pastikan filenya tidak tertukar atau salah periode."
        )

    if up.source_type.key == "gateway" and isi_dari and isi_sampai:
        # Sisi panel diambil TANPA menyaring status konsumsi: panel hari itu
        # lazim sudah dikonsumsi batch, dan penjaga yang cuma melihat baris
        # aktif akan buta tepat pada kasus tersibuk. Kedua kolom kunci diambil
        # (superset) supaya beda konvensi antar-panel tak jadi salah tuduh.
        panel = Transaction.objects.filter(
            toko=up.toko, source_type__key="panel", is_duplicate=False,
        )
        # JANGKAR — panel harus punya baris pada tanggal berkas ini SENDIRI dan
        # DENGAN ARAH YANG SAMA, tanpa pelebaran. Satu kiriman berisi belasan
        # berkas dan urutannya sembarang: bila berkas gateway masuk lebih dulu,
        # kolam pembanding yang melebar ±1 hari TIDAK kosong melainkan berisi
        # panel KEMARIN, tiketnya beda semua, 0% — dan perlindungan "panelnya
        # memang belum diupload" milik `periksa_irisan_kunci` bocor lewat celah
        # itu. Kasus nyata STN 11-08-2026: 224 dari 224 kode dituduh asing,
        # padahal ke-224-nya ada di panel hari itu yang diunggah sesaat kemudian.
        #
        # Tanggal saja tidak cukup, karena satu kiriman memuat DUA arah. Pada
        # kiriman STN yang sama, "STN WD PANEL" masuk sebelum "STN DP NXPAY":
        # panel WD hari itu membuka jangkar untuk berkas DP yang tiket D…-nya
        # mustahil ada di sana, jadi tuduhan 0% lahir lagi — cuma bergeser
        # syaratnya. Berkas "WD NXPAY" hari itu lolos semata-mata karena isinya
        # 5 baris (di bawah MIN_KUNCI), bukan karena penjaganya benar.
        #
        # `flow` KOSONG (arah tak terdeteksi) sengaja kembali ke perilaku lama
        # "arah apa pun": menebak arah dari isi berkas cuma menambah sumber
        # kesalahan baru pada jalur yang toh hanya memperingatkan. Nilai `flow`
        # dipetakan, bukan dipakai langsung — sisi DP bernama "dp" di Upload
        # tetapi "depo" di Transaction.jenis.
        arah = {"dp": "depo", "wd": "wd"}.get((up.flow or "").strip().lower())
        jangkar_qs = panel.filter(
            occurred_at__date__gte=isi_dari, occurred_at__date__lte=isi_sampai
        )
        if arah:
            jangkar_qs = jangkar_qs.filter(jenis=arah)
        jangkar = jangkar_qs.exists()
        if jangkar:
            refs = _kunci(milik, "reference") | _kunci(terduplikat, "reference")
            tix = _kunci(milik, "ticket_no") | _kunci(terduplikat, "ticket_no")
            kunci_file = refs if len(refs) >= len(tix) else tix
            # Pelebaran ±1 hari tetap dipakai untuk MENGUMPULKAN pembandingnya —
            # itu benar dan disengaja: deposit larut malam D-1 lazim di-approve
            # panel tanggal D, dan sebaliknya.
            pembanding = panel.filter(
                occurred_at__date__gte=isi_dari - timedelta(days=1),
                occurred_at__date__lte=isi_sampai + timedelta(days=1),
            )
            h = periksa_irisan_kunci(
                kunci_file, _kunci(pembanding, "reference") | _kunci(pembanding, "ticket_no")
            )
            if h:
                pesan.append(
                    f'"{nama}" — {_ribu(h["total"] - h["cocok"])} dari {_ribu(h["total"])} '
                    f'kode transaksinya tidak dikenal panel tanggal itu '
                    f'({h["rasio"]:.0%} cocok, biasanya hampir 100%). '
                    "Kemungkinan file ini bukan dari akun gateway toko ini."
                )
    return pesan
