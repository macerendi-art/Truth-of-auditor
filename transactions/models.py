import re

from django.db import models
from django.db.models.fields.json import KeyTextTransform

from core.models import TimeStampedModel

# Regex kategori Hutang/Piutang — SATU SUMBER untuk predikat index parsial
# `tx_hutang_piutang_idx` di bawah. `web/hutang.py` (di luar wewenang tulis
# migrasi ini) memakai literal yang SAMA lewat
# `KeyTextTransform("Kategori", "raw").iregex` — kedua sisi WAJIB tetap identik
# byte-per-byte (dikunci tes `transactions/tests_index.py`
# `D2KategoriIndexTests`), karena `predicate_implied_by` Postgres membuktikan
# kecocokan index parsial lewat kesetaraan STRUKTURAL klausa, bukan makna
# semantiknya — satu karakter melenceng berarti index diam-diam tak terpakai
# tanpa error apa pun. Follow-up yang disarankan (di luar wewenang tugas ini):
# `web/hutang.py` sebaiknya mengimpor konstanta ini alih-alih menyalin literal.
KATEGORI_HUTANG_PIUTANG_REGEX = r"^\s*(hutang|piutang)\s*$"

# Peta token -> label sumber spesifik. Kunci = huruf/angka saja (tanpa spasi),
# dicocokkan per-token utuh dari nama file / provider — BUKAN substring, dan
# TIDAK PERNAH menebak dari teks counterparty.
SPECIFIC_SOURCE_LABELS = {
    "BCA": "BCA",
    "BRI": "BRI",
    "BNI": "BNI",
    "MANDIRI": "MANDIRI",
    "CIMB": "CIMB",
    "PERMATA": "PERMATA",
    "DANAMON": "DANAMON",
    "SEABANK": "SEABANK",
    "JAGO": "JAGO",
    "DANA": "DANA",
    "OVO": "OVO",
    "GOPAY": "GOPAY",
    "LINKAJA": "LINKAJA",
    "SHOPEEPAY": "SHOPEEPAY",
    "QRIS": "QRIS",
    "NXPAY": "NXPAY",
    "QRFLYER": "QR FLYER",
    # varian penamaan MUL: "... DP QRIS FLYER.xlsx" — pasangan token QRIS+FLYER
    # harus menang atas token tunggal "QRIS" agar tidak jadi akun QRIS anonim
    "QRISFLYER": "QR FLYER",
}

_MONEY_KEYS = ("bank", "gateway")


def _normalize_provider(value):
    """'QRFLYER'/'qr flyer' -> 'QR FLYER'; provider tak dikenal tetap dipakai apa adanya."""
    compact = re.sub(r"[^A-Z0-9]+", "", (value or "").upper())
    if not compact:
        return ""
    return SPECIFIC_SOURCE_LABELS.get(compact, (value or "").strip().upper())


def provider_from_filename(name):
    """Ambil token bank/gateway dari nama file upload.

    Contoh nyata: '27_JUNI_2026_WD_BCA_HENDI.pdf' -> 'BCA',
    'MUTASI DP QR FLYER OKE25 27-06.xlsx' -> 'QR FLYER'. Tidak dikenal -> ''.
    """
    tokens = [t for t in re.split(r"[^A-Z0-9]+", (name or "").upper()) if t]
    for i, tok in enumerate(tokens):
        if i + 1 < len(tokens):  # token dua kata, mis. 'QR' + 'FLYER'
            pair = tok + tokens[i + 1]
            if pair in SPECIFIC_SOURCE_LABELS:
                return SPECIFIC_SOURCE_LABELS[pair]
        if tok in SPECIFIC_SOURCE_LABELS:
            return SPECIFIC_SOURCE_LABELS[tok]
    return ""


# Token nama file yang BUKAN nama pemilik rekening (label alur/dokumen + ekstensi).
# Nama bulan ikut dibuang (nama file sering memuat tanggal: '27_JUNI_2026_...').
_OWNER_STOPWORDS = frozenset({
    "DP", "WD", "MUTASI", "REKENING", "REK", "TRANSAKSI", "HISTORI", "PANEL",
    "TGL", "QR", "FLYER", "CSV", "PDF", "XLSX", "XLS",
    "JANUARI", "FEBRUARI", "MARET", "APRIL", "MEI", "JUNI", "JULI", "AGUSTUS",
    "SEPTEMBER", "OKTOBER", "NOVEMBER", "DESEMBER",
    "JAN", "FEB", "MAR", "APR", "JUN", "JUL", "AGU", "AGT", "SEP", "OKT", "NOV", "DES",
})


def owner_from_filename(name):
    """Nama pemilik rekening dari nama file upload — fallback bila header file
    tidak memuatnya (BRI). Token SETELAH token brand, buang token berdigit
    (tanggal/kode toko) + stopword. '27_JUNI_2026_WD_BRI_PANCA_SENTANA.csv'
    -> 'PANCA SENTANA'. Tak ada brand / tak tersisa token -> ''.
    """
    tokens = [t for t in re.split(r"[^A-Z0-9]+", (name or "").upper()) if t]
    brand_end = None  # indeks token pertama SETELAH token brand
    for i, tok in enumerate(tokens):
        if i + 1 < len(tokens) and tok + tokens[i + 1] in SPECIFIC_SOURCE_LABELS:
            brand_end = i + 2
            break
        if tok in SPECIFIC_SOURCE_LABELS:
            brand_end = i + 1
            break
    if brand_end is None:
        return ""
    keep = [
        t for t in tokens[brand_end:]
        if t not in _OWNER_STOPWORDS and not re.search(r"\d", t)
    ]
    return " ".join(keep)


def specific_source_label(source_key, account=None, upload=None):
    """Label sumber spesifik untuk badge Transaksi.

    Bank/gateway: account.provider > upload.account.provider > upload.provider >
    token dari upload.original_name > fallback 'Bank'/'Gateway'.
    Panel/bracket: tetap label generik ('Panel'/'Bracket').
    """
    key = (source_key or "").lower()
    if key not in _MONEY_KEYS:
        # Key ber-underscore (panel_bonus/bracket_bonus) jangan tampil mentah.
        return key.replace("_", " ").title()
    candidates = []
    if account is not None:
        candidates.append(account.provider)
    if upload is not None:
        if upload.account_id and upload.account is not None:
            candidates.append(upload.account.provider)
        candidates.append(upload.provider)
    for cand in candidates:
        label = _normalize_provider(cand)
        if label:
            return label
    if upload is not None:
        label = provider_from_filename(upload.original_name)
        if label:
            return label
    return key.capitalize()


class Transaction(TimeStampedModel):
    """Baris transaksi kanonik dari SEMUA sumber (uang dinormalisasi ke rupiah)."""

    class Jenis(models.TextChoices):
        DEPO = "depo", "Deposit"
        WD = "wd", "Withdraw"
        BONUS = "bonus", "Bonus"
        ADMIN = "admin", "Biaya Admin"
        MISTAKE = "mistake", "Mistake"
        LAINNYA = "lainnya", "Lainnya"

    upload = models.ForeignKey(
        "sources.Upload", on_delete=models.CASCADE, related_name="transactions"
    )
    source_type = models.ForeignKey("sources.SourceType", on_delete=models.PROTECT)
    account = models.ForeignKey(
        "sources.Account", on_delete=models.SET_NULL, null=True, blank=True
    )
    toko = models.ForeignKey(
        "sources.Toko", on_delete=models.PROTECT, null=True, blank=True
    )

    occurred_at = models.DateTimeField(
        null=True, blank=True, help_text="Waktu transaksi asli"
    )
    posted_date = models.DateField(
        null=True, blank=True, help_text="Tanggal 'masuk' (statement/entry)"
    )
    jenis = models.CharField(max_length=10, choices=Jenis.choices, default=Jenis.LAINNYA)

    # Semua nilai uang dinormalisasi ke RUPIAH (Panel sudah dikali amount_scale, mis. x1000)
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    credit_delta = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    money_delta = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    fee = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    bonus = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    balance_after = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )

    # Kunci pencocokan
    ticket_no = models.CharField(max_length=64, blank=True, db_index=True)
    # `username`/`reference` TANPA index (migrasi 0011, G5 audit 04-09-2026):
    # disisir seluruh basis kode, satu-satunya pemakaian sebagai KUERI adalah
    # `icontains` (pencarian global web/views.py::transactions + search_fields
    # transactions/admin.py tanpa awalan `^`) — itu jadi `UPPER(kolom) LIKE
    # UPPER('%q%')`, btree biasa mati karena kolom terbungkus fungsi dan
    # `varchar_pattern_ops` (index `_like` yang menyertai `db_index=True` di
    # Postgres) hanya melayani `LIKE 'awalan%'` case-sensitive — tak satu pun
    # dipakai di sini. `reconciliation/engine.py` memakai kedua kolom ini
    # sebagai kunci join, TAPI selalu pada list Python yang sudah dimuat lewat
    # `sides()` (`list(qs.order_by("id"))`), tak pernah lewat `.filter(username=`
    # /`.filter(reference=` pada queryset yang masih lazy. Pembanding
    # `counterparty`/`description` sudah lama dicari `icontains` tanpa index
    # apa pun dan tak ada yang mengeluh — dua kolom ini disamakan. Total 719 MB
    # (base + `_like`, dua kolom) di produksi 8,8 juta baris. Lihat migrasi
    # 0011 untuk cara buangnya (lewat `db_index=False`, BUKAN `DROP INDEX`
    # manual) dan alasan kenapa itu TIDAK memakai pola `TambahIndexAman`
    # (0008-0010) seperti index besar lainnya.
    username = models.CharField(max_length=100, blank=True, db_index=False)
    reference = models.CharField(max_length=128, blank=True, db_index=False)
    counterparty = models.CharField(
        max_length=200, blank=True, help_text="nama pengirim/penerima di bank"
    )
    # Kode bank/dompet pemain (sisi kredit) untuk filter: player_bank dari
    # Player Bank / No. Rek Bank Member, bank_title dari Bank Title / Bank.
    # Kosong utk sumber uang (bank/gateway). Tanpa index: query selalu ter-scope run.
    player_bank = models.CharField(max_length=40, blank=True)
    bank_title = models.CharField(max_length=40, blank=True)

    description = models.TextField(blank=True)
    raw = models.JSONField(default=dict, help_text="baris asli (telusur balik)")
    row_hash = models.CharField(
        max_length=64, db_index=True, help_text="guard idempotensi re-import"
    )
    is_duplicate = models.BooleanField(default=False)
    # Setelah batch rekonsiliasi sukses, transaksi yang dipakai "dikonsumsi" (dikunci
    # ke batch itu) agar tidak masuk lagi ke kelengkapan/pencocokan run berikutnya —
    # run selanjutnya butuh upload ulang. SET_NULL: hapus batch → transaksi bebas lagi.
    consumed_by_batch = models.ForeignKey(
        "reconciliation.ReconBatch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="consumed_transactions",
        db_index=True,
    )

    class Meta:
        indexes = [
            models.Index(fields=["source_type", "occurred_at"]),
            models.Index(fields=["jenis", "amount"]),
            # Dua index komposit di bawah ini dinamai EKSPLISIT: nama itulah yang
            # dipakai runbook DDL manual di produksi (dibangun lewat psql dengan
            # CREATE INDEX CONCURRENTLY sebelum deploy — lihat core/db_ops.py).
            # Urutan kolom disengaja: `toko` + `source_type` selalu dipakai
            # sebagai KESETARAAN, tanggal sebagai RENTANG di posisi terakhir.
            # Pemakai: web/breakdown.py, web/detail_fr.py, web/biaya.py,
            # web/hutang.py, web/bonus.py, web/rekap.py.
            models.Index(
                fields=["toko", "source_type", "posted_date"],
                name="tx_toko_src_posted_idx",
            ),
            # Pemakai: web/rekening.py, web/penjaga.py,
            # reconciliation/engine.py::_date_filter.
            #
            # CATATAN AKURASI (diukur 01-09-2026): `_date_filter` menyaring
            # `occurred_at__date__gte/lte`, dan Django membungkus kolomnya jadi
            # `(occurred_at)::date` sehingga bagian TANGGAL index ini mati untuk
            # pemakai tersebut — hanya prefix (toko, source_type) yang terpakai.
            # Perbaikannya ada di sisi kode (rentang setengah-terbuka, seperti
            # yang sudah dilakukan web/rekening.py), bukan di sini.
            models.Index(
                fields=["toko", "source_type", "occurred_at"],
                name="tx_toko_src_occurred_idx",
            ),
            # --- Tiga index di bawah lahir dari profil halaman lambat pada data
            # produksi nyata (01-09-2026). Angka SEBELUM/SESUDAH ada di
            # docstring migrasi 0009; ketiganya diukur, bukan diperkirakan.
            #
            # Pemakai: web/views.py::bank_mutations (halaman Mutasi Bank).
            # Slice-nya `ORDER BY upload_id DESC, id ASC LIMIT 50`, dan tanpa
            # `toko` di depan, Postgres memindai index upload_id GLOBAL dari
            # puncak lalu membuang baris toko lain satu per satu. Toko yang
            # unggahan terakhirnya lama (upload_id kecil) membayar paling mahal:
            # k25 membuang 4,87 juta baris untuk mengambil 50.
            models.Index(
                fields=["toko", "upload", "id"],
                name="tx_toko_upload_id_idx",
            ),
            # Pemakai: reconciliation/engine.py::check_completeness (5x EXISTS
            # per render dashboard) dan web/kelengkapan.py.
            # PARSIAL: hanya baris yang masih aktif — itulah yang selalu
            # ditanyakan, dan menyempitkan index ke pecahan kecil tabel.
            # Backlog CLAUDE.md "partial index untuk 5x EXISTS" — kini terukur.
            models.Index(
                fields=["toko", "source_type", "jenis"],
                name="tx_aktif_toko_src_jenis_idx",
                condition=models.Q(consumed_by_batch__isnull=True, is_duplicate=False),
            ),
            # Pemakai: web/views.py::transactions (_apply_sort default
            # `ORDER BY occurred_at DESC, id`). Index occurred_at yang ada
            # menaruh source_type di TENGAH, dan urutan itu memblokirnya untuk
            # query yang tidak menyaring source_type.
            models.Index(
                fields=["toko", "occurred_at"],
                name="tx_toko_occurred_idx",
            ),
            # Pemakai: web/breakdown.py::_saldo_carry (loose index scan rekursif
            # — enumerasi akun FR distinct + MAX(posted_date) per akun, tiap
            # langkah CTE = satu index seek). Index EKSPRESI atas kolom JSON:
            # tanpa ini tiap langkah rekursi jadi scan sejarah penuh — jauh
            # lebih buruk dari agregat tunggal yang digantikannya. Ekspresi
            # `raw ->> 'Bank'` di SQL mentah _saldo_carry WAJIB sama dengan
            # kompilasi KeyTextTransform di sini agar planner Postgres mau
            # memakainya. Angka SEBELUM/SESUDAH: docstring migrasi 0010.
            models.Index(
                models.F("toko"),
                models.F("source_type"),
                KeyTextTransform("Bank", "raw"),
                models.F("posted_date"),
                name="tx_fr_bank_posted_idx",
            ),
            # Eskalasi dari D2 (`.superpowers/sdd/.../3b-report.md`): biaya
            # dominan `web/hutang.py::hutang_piutang` adalah SATU scan yang
            # memaksa Postgres mengekstrak `raw->>'Kategori'` lalu menjalankan
            # regex per baris bracket dalam rentang toko×tanggal — TANPA index.
            # Kolom (toko, source_type, posted_date) SUDAH tercakup
            # `tx_toko_src_posted_idx` di atas, tapi query ini SELALU juga
            # butuh `money_delta` (kolom heap biasa, tak ada di index mana
            # pun) untuk baris yang lolos filter — jadi index EKSPRESI biasa
            # ala `tx_fr_bank_posted_idx` (menaruh `raw->>'Kategori'` sebagai
            # KOLOM index) TIDAK menolong: `money_delta` memblokir Index-Only
            # Scan untuk seluruh query, dan `~*` regex tak bisa jadi Index
            # Cond pada btree biasa — jadi planner tetap harus membuka heap
            # utk SETIAP baris kandidat (toko, bracket, rentang), index atau
            # tidak. Sebaliknya: regexnya KONSTAN di kode (persis dua nilai,
            # `hutang`/`piutang`, longgar spasi+kapital) — jadi ia dipindah
            # ke PREDIKAT parsial, bukan kolom, meniru logika D4
            # (`tx_aktif_toko_src_jenis_idx`) bukan bentuk kolom
            # `tx_fr_bank_posted_idx`. Postgres membuktikan kecocokan index
            # parsial lewat `predicate_implied_by` — kesetaraan STRUKTURAL
            # klausa `raw->>'Kategori' ~* '...'` pada query vs index, bukan
            # makna. Index inilah yang hanya berisi ~2% baris bracket
            # (hutang/piutang) — heap HANYA dibuka utk baris itu, bukan
            # seluruh bracket dalam rentang.
            #
            # ⚠️ TIDAK dibuktikan dengan EXPLAIN Postgres nyata (tak ada akses
            # Postgres di lingkungan tugas ini, hanya SQLite). Yang terverifikasi
            # lokal: kompilasi SQL kondisi ini (`raw__Kategori__iregex`) IDENTIK
            # byte-per-byte dengan kompilasi filter asli `web/hutang.py`
            # (`KeyTextTransform("Kategori","raw").iregex`) — dikunci
            # `D2KategoriIndexTests` di `tests_index.py`. Risiko yang tersisa,
            # HANYA bisa diverifikasi di Postgres nyata: psycopg Django secara
            # baku melakukan bind CLIENT-SIDE (literal disisipkan sebelum
            # dikirim), jadi predikat mestinya sampai ke planner sebagai
            # literal (bukan `$1`) — TAPI kalau `EXPLAIN` menunjukkan index ini
            # TIDAK dipakai, periksa dulu `pg_stat_statements`/teks kueri
            # aktual apakah regexnya benar tersubstitusi sebagai literal, bukan
            # parameter — itulah kegagalan implikasi yang paling mungkin.
            #
            # Predikat SENGAJA TIDAK menambah `is_duplicate=False` (beda dari
            # D4/tx_aktif_toko_src_jenis_idx): `hutang_piutang()` memang tidak
            # menyaring `is_duplicate` sama sekali — predikat index harus
            # persis seketat query, menambah syarat ekstra membuat index ini
            # LEBIH SEMPIT dari yang query minta sehingga `predicate_implied_by`
            # gagal (planner tak bisa membuktikan setiap baris hasil query pasti
            # `is_duplicate=False`) dan index tak akan pernah dipilih.
            #
            # Ukuran: hanya ~2% baris bracket (rasio hutang/piutang, ASUMSI 3b,
            # BUKAN terukur produksi) × 3 kolom sempit (toko_id, source_type_id,
            # posted_date int/date) — kecil dibanding index penuh tabel. Biaya
            # tulis: regex dievaluasi tiap INSERT bracket (±185rb/hari porsi
            # bracket dari ±500rb total) HANYA utk memutuskan masuk index atau
            # tidak — evaluasi regex atas satu string pendek, murah dibanding
            # index penuh-tabel manapun di atas.
            #
            # DDL runbook (kompilasi Django di Postgres, + kata CONCURRENTLY):
            #
            #     CREATE INDEX CONCURRENTLY "tx_hutang_piutang_idx"
            #         ON "transactions_transaction" ("toko_id", "source_type_id", "posted_date")
            #         WHERE ("raw" ->> 'Kategori') ~* '^\s*(hutang|piutang)\s*$';
            #
            # Verifikasi pemakaian planner (jalankan pemilik, bentuk query
            # PERSIS `web/hutang.py::hutang_piutang` fase-1, toko+rentang nyata):
            #
            #     EXPLAIN (ANALYZE, BUFFERS)
            #     SELECT id, posted_date, money_delta,
            #            raw ->> 'Kategori' AS fr_kategori, raw ->> 'Jam' AS fr_jam
            #       FROM transactions_transaction
            #      WHERE toko_id = <id> AND source_type_id = <id bracket>
            #        AND posted_date BETWEEN <dari> AND <sampai>
            #        AND (raw ->> 'Kategori') ~* '^\s*(hutang|piutang)\s*$';
            #
            # Setelah deploy: `manage.py periksa_index`.
            models.Index(
                fields=["toko", "source_type", "posted_date"],
                name="tx_hutang_piutang_idx",
                condition=models.Q(raw__Kategori__iregex=KATEGORI_HUTANG_PIUTANG_REGEX),
            ),
        ]
        constraints = [
            # Idempotensi di DB (guard aplikasi di ingest tetap ada): dua proses
            # ingest bersamaan tak boleh menghasilkan baris kembar. Diverifikasi
            # 2026-07-07: lokal & prod 0 duplikat sebelum constraint ini masuk.
            models.UniqueConstraint(
                fields=["source_type", "toko", "row_hash"],
                name="uniq_tx_source_toko_rowhash",
            ),
            # NULL dianggap distinct oleh constraint di atas — jalur ingest tanpa
            # toko (CLI debug) dijaga constraint kondisional terpisah.
            models.UniqueConstraint(
                fields=["source_type", "row_hash"],
                condition=models.Q(toko__isnull=True),
                name="uniq_tx_source_rowhash_toko_null",
            ),
        ]

    def __str__(self):
        return f"{self.get_jenis_display()} {self.amount}"

    @property
    def source_label(self):
        """Badge sumber spesifik (BCA/BRI/NXPAY/QR FLYER/...) — read-only, tanpa migrasi."""
        return specific_source_label(
            self.source_type.key,
            account=self.account if self.account_id else None,
            upload=self.upload if self.upload_id else None,
        )

    @property
    def source_label_full(self):
        """Label sumber + pemilik rekening end user: 'BCA a/n HENDI'.

        Hanya sisi uang (bank/gateway) yang punya owner; tanpa owner ->
        sama dengan `source_label` (jangan mengarang).
        """
        label = self.source_label
        if self.source_type.key in _MONEY_KEYS and self.upload_id:
            owner = self.upload.owner_name
            if owner:
                return f"{label} a/n {owner}"
        return label
