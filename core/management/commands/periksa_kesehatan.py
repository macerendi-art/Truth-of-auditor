"""Pemeriksaan kesehatan operasional satu perintah.

    python manage.py periksa_kesehatan     # 0 = tak ada BAHAYA, 1 = ada BAHAYA

Kenapa perintah ini ada
=======================

`periksa_index` menjawab SATU pertanyaan (apakah index-nya jadi?). Yang
membunuh aplikasi ini di produksi bukan cuma itu — dan tiap kali pola-nya
sama: **gagal diam-diam**. Disk penuh (insiden 2026-07-04, volume 500 MB
tersumbat pg_wal), ingest berhenti tanpa ada yang sadar, tabel referensi
kosong sesudah restore (SourceType/Toko/ToleranceProfile "Default" dibuat
oleh MIGRASI DATA — DB yang di-restore separuh terlihat sehat sampai
rekonsiliasi pertama gagal), index yang tak pernah terbangun. Semuanya
tak berbunyi sampai seseorang membuka halaman yang salah.

Jadi perintah ini menyapu semua di satu tempat, memberi PENANDA STATUS per
baris, dan **keluar dengan kode ≠ 0 begitu ada satu BAHAYA** supaya bisa
dipasang di cron/runbook dan gagal dengan sendirinya.

Tiga aturan yang menentukan bentuk berkas ini
---------------------------------------------

1. **Laporan selalu utuh.** Tak ada pemeriksaan yang menghentikan yang lain;
   `CommandError` baru dilempar di AKHIR, setelah semua tercetak. Laporan
   yang putus di tengah menyembunyikan justru temuan berikutnya.

2. **Jangan pernah berpura-pura bersih.** Di luar PostgreSQL (SQLite tes &
   dev) `pg_stat_user_tables`/`pg_sequences` tak ada; pemeriksaan yang
   bersandar padanya melapor "tidak berlaku", persis seperti
   `periksa_index` — bukan OK, bukan pula galat. Pemeriksaan yang portabel
   (disk, umur batch, tabel referensi, kueri patokan) tetap jalan.

3. **Angka yang tak punya ambang jujur dilaporkan sebagai INFO.** Laju
   tumbuh dan waktu kueri patokan TIDAK diberi status: ambang waktu di
   pemeriksaan kesehatan cuma melahirkan alarm palsu (mesin sibuk, cache
   dingin), dan tak ada kapasitas resmi yang bisa dipakai menilai laju
   tumbuh. Keduanya ada supaya manusia yang membacanya, bukan supaya
   perintah ini menghakiminya.

Index hilang/invalid TIDAK diduplikasi di sini — logikanya diimpor apa
adanya dari `core.management.commands.periksa_index` (`periksa` +
`baca_katalog`). Sengaja BUKAN lewat `call_command`: perintah itu melempar
`CommandError` begitu ada temuan, dan itu akan memotong laporan ini di
tengah — melanggar aturan 1 di atas.

Laju tumbuh butuh pembanding, dan menambah tabel untuk itu tidak sepadan
(satu migrasi untuk satu angka operasional). Pembandingnya disimpan di satu
berkas JSON (`--berkas-status`, bawaannya `media/kesehatan.json` — di dalam
`media/` karena direktori itu SUDAH di-.gitignore, jadi menjalankan perintah
ini tidak mengotori `git status` dan tidak ikut terkirim oleh `railway up`,
yang membaca .gitignore untuk menentukan isi unggahan). Berkas hilang =
"belum ada pembanding" dan angka hari ini ditampilkan apa adanya; di
lingkungan yang berkasnya tidak awet (kontainer tanpa volume) itulah keadaan
normalnya, dan pemakainya cukup menunjuk `--berkas-status` ke tempat yang
awet. Kegagalan menulis berkas itu TIDAK PERNAH menggagalkan perintah — ia
alat bantu, bukan sumber kebenaran.
"""

import json
import shutil
import time
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Max

from core.management.commands.periksa_index import baca_katalog, periksa
from reconciliation.models import ReconBatch, ToleranceProfile
from sources.models import SourceType, Toko
from transactions.models import Transaction

OK, PERHATIAN, BAHAYA, INFO = "OK", "PERHATIAN", "BAHAYA", "INFO"

# --- Ambang. Semuanya di satu tempat supaya bisa dibaca (dan digugat) tanpa
# membaca kodenya. Sisa disk dinilai dalam PERSEN, bukan gigabyte: volume
# produksi pernah 500 MB dan sekarang 5 GB — ambang absolut jadi basi diam-diam.
DISK_BAHAYA, DISK_PERHATIAN = 10.0, 20.0          # persen sisa
SEQ_BAHAYA, SEQ_PERHATIAN = 0.90, 0.75            # rasio last_value/max_value
BATCH_BAHAYA, BATCH_PERHATIAN = 7, 3              # hari sejak batch terakhir

# Tabel referensi yang diisi MIGRASI DATA, bukan fixture. Kosong = kelas gagal
# senyap: aplikasi naik, halaman terbuka, rekonsiliasi baru gagal belakangan.
JUDUL_REF = {
    "SourceType": "jenis sumber (panel/bracket/bank/gateway/…)",
    "Toko aktif": "merek yang boleh dikerjakan",
    'ToleranceProfile "Default"': "profil toleransi yang dipakai run harian",
}


# ---------------------------------------------------------------- penilai murni
# Semua fungsi di bawah: angka masuk, (status, nilai) keluar. Tanpa DB, tanpa
# Django — supaya ambangnya bisa diuji langsung, pola yang sama dipakai
# `web/penjaga.py` dan `periksa_index.periksa`.

def nilai_disk(total, bebas):
    """Sisa ruang disk → status + persen sisa. total 0/None → INFO."""
    if not total:
        return INFO, None
    persen = bebas / total * 100
    if persen < DISK_BAHAYA:
        return BAHAYA, persen
    if persen < DISK_PERHATIAN:
        return PERHATIAN, persen
    return OK, persen


def nilai_sequence(last_value, max_value):
    """Kedekatan sequence ke tabrakan → status + rasio.

    Semua sequence proyek ini `bigint` (DEFAULT_AUTO_FIELD = BigAutoField),
    jadi rasionya praktis nol dan pemeriksaan ini hampir selalu OK. Ia tetap
    ada karena satu kolom `int4` yang lolos (tabel perantara m2m lama, kolom
    warisan) akan meledak pada 2,1 miliar baris — dan tabel terbesar di sini
    sudah menembus 8 juta baris dengan laju ±185 rb/hari.
    """
    if last_value is None or not max_value:
        return INFO, None
    rasio = last_value / max_value
    if rasio >= SEQ_BAHAYA:
        return BAHAYA, rasio
    if rasio >= SEQ_PERHATIAN:
        return PERHATIAN, rasio
    return OK, rasio


def nilai_umur_batch(hari):
    """Umur batch terakhir satu toko (hari) → status.

    `None` = toko aktif yang BELUM PERNAH punya batch: PERHATIAN, bukan
    BAHAYA — merek yang baru di-onboard sah ada dalam keadaan ini, dan
    perintah yang keluar ≠ 0 karenanya akan diabaikan orang dalam seminggu.
    """
    if hari is None:
        return PERHATIAN
    if hari >= BATCH_BAHAYA:
        return BAHAYA
    if hari >= BATCH_PERHATIAN:
        return PERHATIAN
    return OK


def nilai_ref(jumlah):
    """Isi tabel referensi → status. Kosong = BAHAYA, tanpa gradasi."""
    return BAHAYA if not jumlah else OK


def laju_tumbuh(sebelum, sekarang):
    """Selisih ukuran DB antara dua potret → dict, atau None bila tak layak.

    `sebelum`/`sekarang` = {"tanggal": "YYYY-MM-DD", "ukuran_db": int}.
    Dua potret di hari yang SAMA (atau mundur) tidak menghasilkan laju —
    membaginya dengan 0 hari melahirkan angka fantasi.
    """
    if not sebelum:
        return None
    try:
        d0 = date.fromisoformat(sebelum["tanggal"])
        d1 = date.fromisoformat(sekarang["tanggal"])
        b0, b1 = int(sebelum["ukuran_db"]), int(sekarang["ukuran_db"])
    except (KeyError, TypeError, ValueError):
        return None
    hari = (d1 - d0).days
    if hari <= 0:
        return None
    return {"hari": hari, "delta": b1 - b0, "per_hari": (b1 - b0) / hari,
            "dari": d0, "sampai": d1}


def ukuran(nbytes):
    """Byte → teks pendek berbahasa manusia ('1,4 GB'). Koma desimal id."""
    if nbytes is None:
        return "—"
    tanda = "-" if nbytes < 0 else ""
    n = float(abs(nbytes))
    for satuan in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or satuan == "TB":
            return f"{tanda}{n:.1f} {satuan}".replace(".", ",")
        n /= 1024


# ------------------------------------------------------------------- perintah

class Command(BaseCommand):
    help = ("Pemeriksaan kesehatan operasional (ukuran DB, disk, index, baris, "
            "umur batch, sequence, tabel referensi). Keluar 1 bila ada BAHAYA.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--berkas-status", default=None,
            help="Berkas JSON potret sebelumnya (bawaan: media/kesehatan.json).")
        parser.add_argument(
            "--tanpa-simpan", action="store_true",
            help="Jangan tulis potret hari ini (mis. saat menjalankan dari cron pemeriksa).")

    # -- penulis laporan --------------------------------------------------
    def _mulai(self):
        self.temuan = []          # [(status, teks)] — hanya yang != OK/INFO ditally
        self.jumlah = {OK: 0, PERHATIAN: 0, BAHAYA: 0, INFO: 0}

    def _judul(self, teks):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(teks))

    def _lapor(self, status, teks):
        self.jumlah[status] += 1
        gaya = {OK: self.style.SUCCESS, PERHATIAN: self.style.WARNING,
                BAHAYA: self.style.ERROR, INFO: self.style.HTTP_INFO}[status]
        self.stdout.write(f"  {gaya(f'{status:9}')} {teks}")

    # -- pemeriksaan ------------------------------------------------------
    def _ukuran_db(self):
        """Ukuran DB dalam byte, lintas-vendor. None = tak bisa diukur."""
        if connection.vendor == "postgresql":
            with connection.cursor() as cur:
                cur.execute("SELECT pg_database_size(current_database())")
                return cur.fetchone()[0]
        if connection.vendor == "sqlite":
            berkas = Path(connection.settings_dict["NAME"])
            # ":memory:" dan basis data tes in-memory tak punya berkas.
            return berkas.stat().st_size if berkas.is_file() else None
        return None

    def _bagian_ukuran(self, potret_lama, potret_baru):
        self._judul("Ukuran basis data & laju tumbuh")
        besar = potret_baru["ukuran_db"]
        if besar is None:
            # SQLite in-memory (DB tes) dan vendor lain: ukurannya memang tak
            # ada. Bagian ini TIDAK berhenti — laju tumbuh tetap dilaporkan,
            # supaya satu angka yang hilang tak menelan bagian di bawahnya.
            self._lapor(INFO, f"Ukuran sekarang: tidak terbaca untuk vendor "
                              f"'{connection.vendor}' pada basis data ini.")
        else:
            self._lapor(INFO, f"Ukuran sekarang: {ukuran(besar)} "
                              f"({connection.vendor}, {potret_baru['tanggal']}).")
        laju = laju_tumbuh(potret_lama, potret_baru)
        if laju is None:
            self._lapor(INFO, "Laju tumbuh: belum ada pembanding — potret hari "
                              "ini disimpan, jalankan lagi besok.")
            return
        self._lapor(INFO,
                    f"Laju tumbuh: {ukuran(laju['delta'])} dalam {laju['hari']} hari "
                    f"({laju['dari']} → {laju['sampai']}) = "
                    f"{ukuran(laju['per_hari'])}/hari.")

    def _bagian_disk(self):
        self._judul("Ruang disk")
        # Diukur di direktori tempat perintah ini BERJALAN. Di Railway,
        # volume Postgres adalah service lain — jangan mengaku mengukurnya.
        jalur = Path(settings.BASE_DIR)
        try:
            total, dipakai, bebas = shutil.disk_usage(jalur)
        except OSError as e:
            self._lapor(INFO, f"Tidak terbaca ({e}).")
            return
        status, persen = nilai_disk(total, bebas)
        self._lapor(status,
                    f"Sisa {persen:.1f}".replace(".", ",")
                    + f"% ({ukuran(bebas)} dari {ukuran(total)}) "
                    f"di {jalur} — volume tempat PERINTAH ini berjalan, belum "
                    f"tentu volume basis data.")

    def _bagian_index(self):
        self._judul("Index (hilang / invalid)")
        if connection.vendor != "postgresql":
            self._lapor(INFO, f"Tidak berlaku: basis data '{connection.vendor}', "
                              "bukan postgresql — `pg_index` tak ada dan index "
                              "invalid bukan konsep di sini.")
            return
        tabel = Transaction._meta.db_table
        diharapkan = [i.name for i in Transaction._meta.indexes]
        katalog = baca_katalog(connection, tabel)
        hasil = periksa(diharapkan, katalog)
        if not hasil:
            self._lapor(OK, f"{tabel}: {len(katalog)} index ada, "
                            f"{len(diharapkan)} diwajibkan model — bersih.")
            return
        for t in hasil:
            self._lapor(BAHAYA, f"{t['status'].upper()} — {t['nama']} "
                                "(rincian & perintah pemulihan: manage.py periksa_index)")

    def _bagian_baris(self):
        self._judul("Tabel terbesar")
        if connection.vendor != "postgresql":
            self._lapor(INFO, f"Tidak berlaku: perkiraan baris diambil dari "
                              f"`pg_stat_user_tables`, tak ada di "
                              f"'{connection.vendor}'. COUNT(*) sengaja TIDAK "
                              "dipakai — di tabel 8 juta baris ia sendiri yang "
                              "jadi masalah.")
            return
        with connection.cursor() as cur:
            cur.execute(
                "SELECT relname, n_live_tup, pg_total_relation_size(relid) "
                "  FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 5")
            baris = cur.fetchall()
        for nama, tup, besar in baris:
            jml = f"{tup:,}".replace(",", ".")   # pemisah ribuan gaya Indonesia
            self._lapor(INFO, f"{nama}: ±{jml} baris, {ukuran(besar)}")

    def _bagian_batch(self):
        self._judul("Umur batch terakhir per toko (tanda ingest berhenti)")
        hari_ini = date.today()
        tokos = list(Toko.objects.filter(is_active=True).order_by("key"))
        if not tokos:
            self._lapor(INFO, "Tak ada toko aktif — lihat bagian tabel referensi.")
            return
        # Satu query untuk semua toko: recon_date terakhir per toko.
        terakhir = dict(
            ReconBatch.objects.filter(toko__in=tokos, recon_date__isnull=False)
            .values_list("toko_id")
            .annotate(t=Max("recon_date"))
            .values_list("toko_id", "t")
        )
        for t in tokos:
            tgl = terakhir.get(t.id)
            hari = None if tgl is None else (hari_ini - tgl).days
            status = nilai_umur_batch(hari)
            if hari is None:
                self._lapor(status, f"{t.key}: belum pernah ada batch bertanggal.")
            else:
                self._lapor(status, f"{t.key}: batch terakhir {tgl} "
                                    f"({hari} hari lalu).")

    def _bagian_sequence(self):
        self._judul("Sequence mendekati tabrakan")
        if connection.vendor != "postgresql":
            self._lapor(INFO, f"Tidak berlaku: `pg_sequences` tak ada di "
                              f"'{connection.vendor}'.")
            return
        with connection.cursor() as cur:
            cur.execute(
                "SELECT sequencename, data_type::text, last_value, max_value "
                "  FROM pg_sequences WHERE schemaname = 'public' "
                "   AND last_value IS NOT NULL")
            baris = cur.fetchall()
        if not baris:
            self._lapor(INFO, "Belum ada sequence yang pernah dipakai.")
            return
        dinilai = [(nama, tipe, *nilai_sequence(last, maks))
                   for nama, tipe, last, maks in baris]
        buruk = [d for d in dinilai if d[2] in (PERHATIAN, BAHAYA)]
        for nama, tipe, status, rasio in buruk:
            self._lapor(status, f"{nama} ({tipe}) terpakai "
                                + f"{rasio:.1%}".replace(".", ",")
                                + " dari rentangnya — ubah kolomnya ke bigint.")
        if not buruk:
            # `rasio is None` mustahil di sini (kueri sudah menyaring
            # last_value NOT NULL), tapi baris ringkasan ini memformat angka —
            # satu None akan melempar TypeError dan menelan bagian di bawahnya.
            terukur = [d for d in dinilai if d[3] is not None]
            if not terukur:
                self._lapor(INFO, f"{len(dinilai)} sequence, rasionya tak terukur.")
                return
            paling = max(terukur, key=lambda d: d[3])
            rasio = f"{paling[3]:.6%}".replace(".", ",")   # koma desimal id
            self._lapor(OK, f"{len(terukur)} sequence, tertinggi {paling[0]} "
                            f"({paling[1]}) di {rasio} dari rentangnya.")

    def _bagian_referensi(self):
        self._judul("Tabel referensi (diisi migrasi data — kosong = gagal senyap)")
        isi = {
            "SourceType": SourceType.objects.count(),
            "Toko aktif": Toko.objects.filter(is_active=True).count(),
            'ToleranceProfile "Default"':
                ToleranceProfile.objects.filter(name="Default").count(),
        }
        for nama, jumlah in isi.items():
            status = nilai_ref(jumlah)
            if status == OK:
                self._lapor(OK, f"{nama}: {jumlah} baris.")
            else:
                self._lapor(BAHAYA, f"{nama}: KOSONG — {JUDUL_REF[nama]}. "
                                    "Dibuat oleh migrasi data; DB hasil restore "
                                    "separuh terlihat sehat sampai rekonsiliasi "
                                    "pertama gagal. Jalankan `migrate`.")

    def _bagian_patokan(self):
        self._judul("Kueri patokan")
        # Sengaja berbentuk sama dengan pemakai `tx_toko_src_posted_idx`:
        # kesetaraan (toko, source_type) + rentang tanggal. TANPA status —
        # ambang waktu di pemeriksaan kesehatan cuma melahirkan alarm palsu.
        batch = (ReconBatch.objects.filter(recon_date__isnull=False)
                 .order_by("-recon_date", "-id").first())
        st = SourceType.objects.filter(key=SourceType.BRACKET).first()
        if batch is None or batch.toko_id is None or st is None:
            self._lapor(INFO, "Dilewati: belum ada batch bertanggal / SourceType "
                              "bracket untuk dijadikan patokan.")
            return
        mulai = time.monotonic()
        n = Transaction.objects.filter(
            toko_id=batch.toko_id, source_type_id=st.id,
            posted_date=batch.recon_date).count()
        ms = (time.monotonic() - mulai) * 1000
        self._lapor(INFO, f"COUNT bracket toko #{batch.toko_id} pada "
                          f"{batch.recon_date}: {n} baris dalam {ms:.0f} ms "
                          "(informatif, bukan ambang).")

    # -- potret -----------------------------------------------------------
    def _jalur_status(self, opts):
        if opts.get("berkas_status"):
            return Path(opts["berkas_status"])
        return Path(settings.BASE_DIR) / "media" / "kesehatan.json"

    def _baca_potret(self, jalur):
        try:
            with open(jalur, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            # Berkas hilang/rusak bukan kegagalan: ia cuma pembanding.
            return None

    def _tulis_potret(self, jalur, potret):
        try:
            jalur.parent.mkdir(parents=True, exist_ok=True)
            with open(jalur, "w", encoding="utf-8") as f:
                json.dump(potret, f, ensure_ascii=False, indent=2)
            return None
        except OSError as e:
            return str(e)

    # -- orkestrasi -------------------------------------------------------
    def handle(self, *args, **opts):
        self._mulai()
        jalur = self._jalur_status(opts)
        lama = self._baca_potret(jalur)
        baru = {"tanggal": date.today().isoformat(), "ukuran_db": self._ukuran_db()}

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"PEMERIKSAAN KESEHATAN — {date.today()} — basis data "
            f"'{connection.vendor}'"))

        self._bagian_ukuran(lama, baru)
        self._bagian_disk()
        self._bagian_index()
        self._bagian_baris()
        self._bagian_batch()
        self._bagian_sequence()
        self._bagian_referensi()
        self._bagian_patokan()

        if not opts.get("tanpa_simpan"):
            galat = self._tulis_potret(jalur, baru)
            self._judul("Potret")
            if galat:
                self._lapor(INFO, f"Gagal menyimpan potret ke {jalur} ({galat}) — "
                                  "laju tumbuh tak akan terhitung lain kali. "
                                  "Tidak menggagalkan pemeriksaan.")
            else:
                self._lapor(INFO, f"Potret hari ini disimpan ke {jalur}.")

        self._judul("Ringkasan")
        self.stdout.write(
            f"  {self.jumlah[BAHAYA]} BAHAYA · {self.jumlah[PERHATIAN]} PERHATIAN "
            f"· {self.jumlah[OK]} OK · {self.jumlah[INFO]} INFO")
        if self.jumlah[BAHAYA]:
            raise CommandError(
                f"{self.jumlah[BAHAYA]} temuan BAHAYA — lihat baris bertanda "
                "BAHAYA di atas. Aplikasi mungkin masih menyala; yang rusak "
                "adalah hal yang tidak berbunyi sendiri.")
        if self.jumlah[PERHATIAN]:
            self.stdout.write(self.style.WARNING(
                "  Ada PERHATIAN — belum menggagalkan, tapi jangan dibiarkan "
                "menumpuk."))
        else:
            self.stdout.write(self.style.SUCCESS("  Tak ada temuan."))
