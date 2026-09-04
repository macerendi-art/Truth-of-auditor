"""Index parsial `(toko, source_type, posted_date) WHERE raw->>'Kategori' ~* '...'`.

Eskalasi dari D2 (`.superpowers/sdd/prompt-eksekusi-perbaikan-2026-09-04/3b-report.md`,
`web/hutang.py::hutang_piutang`, halaman `/hutang-piutang/`). Agen D2 mengukur
lokal (data sintetis 174k baris/29 toko/30 hari) dan menemukan biaya
dominannya BUKAN materialisasi Python (dict+sort utk baris cocok: ≤3 md utk
3.412 baris — hampir nol), melainkan SATU scan yang memaksa Postgres
mengekstrak `raw->>'Kategori'` lalu menjalankan regex per baris bracket dalam
rentang toko×tanggal — TANPA index. Angka isolasi D2 (SQLite sintetis):
`qs.count()` tanpa filter kategori 0,10 dtk vs DENGAN filter 0,15-0,31 dtk —
selisih itulah biaya ekstraksi+regex per baris yang index ini menargetkan.

KENAPA BUKAN index ekspresi ala `tx_fr_bank_posted_idx` (0010)
================================================================
Godaan pertama: tiru 0010 apa adanya — jadikan `raw->>'Kategori'` KOLOM index
(`toko, source_type, raw->>'Kategori', posted_date`). Ini SALAH untuk query
ini dan sengaja tidak dipakai:

1. Query fase-1 `hutang_piutang` SELALU juga butuh `money_delta` (kolom heap
   biasa, Decimal, tak ada di index manapun) untuk baris yang lolos filter.
   Itu artinya Postgres TAK PERNAH bisa memilih Index-Only Scan untuk query
   ini apa pun bentuk indexnya — heap wajib dibuka untuk setiap baris
   KANDIDAT yang lolos Index Cond (toko, source_type, rentang tanggal),
   terlepas apakah `Kategori` juga ada di index. Index kolom biasa cuma
   menambah lebar tanpa mengurangi baris yang dibuka.
2. `~*` (iregex, case-insensitive) bukan operator yang bisa jadi Index Cond
   pada btree biasa — tak seperti kesetaraan/rentang, regex tak bisa
   mengarahkan pencarian ke rentang daun index tertentu.

Kolom (toko, source_type, posted_date) itu sendiri SUDAH tercakup
`tx_toko_src_posted_idx` (migrasi 0007c8953c) — menambahnya lagi sebagai
index terpisah tanpa alasan baru persis pola index mati yang baru dibuang
719 MB di migrasi 0011.

DESAIN YANG DIPAKAI: regex sebagai PREDIKAT, meniru D4
=======================================================
Regex kategori itu KONSTAN di kode — persis dua nilai (`hutang`/`piutang`,
longgar kapital+spasi) — jadi predikatnya dipindah ke PARSIAL index
(`WHERE (raw->>'Kategori') ~* '...'`), meniru logika D4
(`tx_aktif_toko_src_jenis_idx`: `consumed_by_batch`/`is_duplicate` konstan di
kelima EXISTS -> predikat), BUKAN bentuk kolom `tx_fr_bank_posted_idx`.
Postgres membuktikan kecocokan index parsial lewat `predicate_implied_by`:
kesetaraan STRUKTURAL klausa `raw->>'Kategori' ~* '...'` pada QUERY vs
predikat INDEX — bukan makna semantiknya. Index ini karena itu HANYA berisi
baris bracket yang kategorinya hutang/piutang (diasumsikan ~2% dari total
bracket toko — asumsi 3b, BUKAN terukur produksi): heap HANYA dibuka untuk
baris yang memang ditampilkan halaman, bukan seluruh bracket dalam rentang.

Predikat SENGAJA TIDAK menambah `is_duplicate=False` (beda dari D4):
`hutang_piutang()` tidak menyaring `is_duplicate` sama sekali — predikat
index harus PERSIS seketat query; syarat ekstra membuat index lebih sempit
dari yang query minta, `predicate_implied_by` gagal membuktikan implikasi
dan planner tidak akan pernah memilih index ini.

VERIFIKASI YANG BENAR-BENAR DILAKUKAN (lokal, SQLite — tidak ada Postgres di
lingkungan tugas ini)
======================================================================
Dikompilasi dua cara berbeda ke SQL dan DIBANDINGKAN BYTE-PER-BYTE:
(a) `Transaction.objects.annotate(fr_kategori=KeyTextTransform("Kategori",
"raw")).filter(fr_kategori__iregex=POLA)` — bentuk PERSIS yang dipakai
`web/hutang.py::hutang_piutang` hari ini;
(b) `Transaction.objects.filter(raw__Kategori__iregex=POLA)` — bentuk yang
dipakai predikat `condition=` index ini (Django tidak menerima ekspresi
`KeyTextTransform` langsung di dalam `Q()` utk `Index.condition`, hanya
lookup path).
Keduanya menghasilkan fragmen WHERE IDENTIK di SQLite:
`(CASE WHEN JSON_TYPE(...) IN ('true','null','false') THEN JSON_TYPE(...)
ELSE JSON_EXTRACT(...) END) REGEXP '(?i)' || '^\s*(hutang|piutang)\s*$'`.
Ini menguatkan (bukan membuktikan utk Postgres) bahwa kedua jalur memakai
mesin lookup JSONField Django YANG SAMA (`KeyTransformIRegex`), jadi
mestinya berkompilasi setara juga di backend Postgres. Dikunci
`D2KategoriIndexTests` (`transactions/tests_index.py`) via
`CaptureQueriesContext` atas panggilan `hutang_piutang()` sungguhan.

⚠️ RISIKO YANG TERSISA, HANYA BISA DIVERIFIKASI DI POSTGRES NYATA:
psycopg (driver Django) secara baku melakukan bind CLIENT-SIDE (literal
disisipkan ke teks SQL sebelum dikirim ke server), jadi regexnya semestinya
sampai ke planner sebagai LITERAL (bukan parameter `$1`) — `predicate_implied_by`
butuh literal, bukan parameter, untuk membuktikan kecocokan. Kalau `EXPLAIN`
menunjukkan index ini TIDAK dipakai padahal bentuk querynya cocok, periksa
dulu `pg_stat_statements`/teks kueri aktual: apakah regexnya benar tersubstitusi
literal — itulah kegagalan implikasi yang paling mungkin, BUKAN index yang
salah bentuk.

URUTAN DEPLOY WAJIB (P2, tinjauan akhir 04-09-2026) — bukan saran
=================================================================
1. psql produksi, DI LUAR 03:00–03:30 WIB: `CREATE INDEX CONCURRENTLY
   "tx_hutang_piutang_idx" …` (DDL di bawah), lalu
   `SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;` → KOSONG.
   Jendela itu terlarang karena `pg_dump` cadangan harian memegang transaksi
   13+ menit, dan `CREATE INDEX CONCURRENTLY` MENUNGGU semua transaksi yang
   lebih tua selesai sebelum fase keduanya — walau tak memegang lock
   eksklusif, ia tetap tertahan selama dump berjalan.
2. BARU `railway up`. `TambahIndexAman` menemukan index ada & valid → no-op.
3. Sesudah naik, DARI KODE BARU (`railway ssh`): `python manage.py
   periksa_index`, lalu `EXPLAIN (ANALYZE, BUFFERS)` fase-1 `/hutang-piutang/`
   (query di bawah) — `predicate_implied_by` belum dibuktikan di Postgres
   nyata (lihat ⚠️ di atas).
4. Perbarui checkout `/opt/toa` di VPS ke commit yang di-deploy (pemantauan
   harian menjalankan `periksa_index` dari sana; lihat alasan di bawah).

Kalau langkah 1 TERLEWAT: `TambahIndexAman` membangun index INI saat boot,
atas 10,3 juta baris, mengevaluasi regex `raw->>'Kategori'` per baris — port
belum terbuka selama itu. Health-check Railway membunuh container di tengah
build → index tertinggal `indisvalid=false`, migrasi TERCATAT selesai
(core/db_ops.py). Besok 03:00 gerbang J4 cadangan menemukan index invalid →
dump DIBATALKAN (alarm hanya ke journal). Yang menangkapnya kemudian:
`periksa_index` — INVALID dideteksi LINTAS-KODE (SELURUH index tabel dibaca
dari pg_index, tak bergantung daftar `Transaction._meta.indexes` kode yang
berjalan) — dan bagian 1 skrip kesehatan (verdict cadangan GAGAL). Yang
TIDAK tertangkap dari checkout basi: index HILANG (CONCURRENTLY gagal total,
migrasi tercatat selesai, nama index tak pernah ada di pg_index) — hanya
kode yang mengenal `tx_hutang_piutang_idx` yang bisa melaporkannya. Itulah
alasan langkah 4, dan alasan skrip kesehatan kini mencatat revisi `/opt/toa`.

`atomic = False` + `TambahIndexAman`: di produksi index dibangun lebih dulu
lewat psql (CREATE INDEX CONCURRENTLY) supaya migrasi tidak menahan boot;
di SQLite (tes & dev) turun ke AddIndex biasa. Lihat core/db_ops.py.
DDL runbook (kompilasi Django di Postgres, + kata CONCURRENTLY):

    CREATE INDEX CONCURRENTLY "tx_hutang_piutang_idx"
        ON "transactions_transaction" ("toko_id", "source_type_id", "posted_date")
        WHERE ("raw" ->> 'Kategori') ~* '^\\s*(hutang|piutang)\\s*$';

Verifikasi pemakaian planner (jalankan pemilik, bentuk query PERSIS fase-1
`web/hutang.py::hutang_piutang`, toko+rentang nyata):

    EXPLAIN (ANALYZE, BUFFERS)
    SELECT id, posted_date, money_delta,
           raw ->> 'Kategori' AS fr_kategori, raw ->> 'Jam' AS fr_jam
      FROM transactions_transaction
     WHERE toko_id = <id> AND source_type_id = <id source_type 'bracket'>
       AND posted_date BETWEEN <dari> AND <sampai>
       AND (raw ->> 'Kategori') ~* '^\\s*(hutang|piutang)\\s*$';

Ukuran perkiraan: ~2% baris bracket toko (asumsi 3b, bukan terukur produksi)
x 3 kolom sempit (toko_id, source_type_id, posted_date — int/int/date) — kecil
dibanding index penuh-tabel manapun di atas. Biaya tulis: regex dievaluasi
sekali per INSERT bracket (porsi dari ±500rb baris/hari total ingest) hanya
utk memutuskan masuk index atau tidak — evaluasi satu regex atas satu string
pendek, jauh lebih murah daripada index penuh-tabel.

Setelah deploy: `manage.py periksa_index`.
"""

from django.db import migrations, models

from core.db_ops import TambahIndexAman


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("reconciliation", "0008_index_badge_tinjau"),
        ("sources", "0014_toko_kepemilikan"),
        ("transactions", "0011_buang_index_username_reference"),
    ]

    operations = [
        TambahIndexAman(
            model_name="transaction",
            index=models.Index(
                fields=["toko", "source_type", "posted_date"],
                name="tx_hutang_piutang_idx",
                condition=models.Q(
                    raw__Kategori__iregex=r"^\s*(hutang|piutang)\s*$"
                ),
            ),
        ),
    ]
