# Riset D6 — kenapa toko pasif membayar mahal di `/rekening/` (2026-09-04)

Status: **RISET SELESAI DENGAN CELAH JUJUR** — kode diperiksa tuntas dan satu
cacat konkret ditemukan + dibuktikan lewat SQL yang benar-benar dihasilkan,
tapi arah pasti "kenapa k25 (lebih kecil) lebih lambat dari mxw (lebih besar)"
**tidak bisa dipastikan tanpa `EXPLAIN ANALYZE` di Postgres produksi**, yang
dilarang brief ini. Bagian "Yang tidak bisa disimpulkan" di bawah jujur soal
batas itu — jangan baca ringkasan saja.

## Bukti butir & dugaan awal

Dari `docs/daftar-perbaikan-2026-09-03.md` baris D6: **k25 `/rekening/` 3,0 dtk
vs mxw `/rekening/` 1,2 dtk — padahal k25 6× lebih kecil**, dengan dugaan awal
tercatat "datanya dingin di cache karena tak disentuh trafik".

## Skala & keterbatasan lingkungan (baca sebelum menilai temuan di bawah)

- DB lokal cuma punya `k25`/`lbs` — **tidak ada `mxw`** sama sekali, jadi
  perbandingan k25-vs-mxw dari brief **tak bisa direproduksi lokal**.
- DB lokal SQLite, produksi Postgres — rencana kueri, index, dan statistik
  planner-nya berbeda MENDASAR. Bagian di bawah yang mengutip SQL yang
  benar-benar dieksekusi (`django_datetime_cast_date(...)`) itu FAKTA
  struktural (bentuk SQL yang dihasilkan ORM SAMA di kedua vendor — Django
  mengkompilasi lookup `__date` ke fungsi/cast basis-data manapun), BUKAN
  angka waktu — tak ada satu pun angka detik/ms dari Postgres di dokumen ini.
- Brief melarang SSH ke VPS, `railway`, atau menyentuh produksi. **Riset ini
  murni pembacaan kode + investigasi lewat ORM lokal (`.query`, SQL yang
  ditangkap) — tidak ada `EXPLAIN ANALYZE` sungguhan yang dijalankan.**
- Karena itu, laporan ini punya batas yang jujur dicatat, bukan diagram
  angka yang seolah-olah terukur.

## Metodologi membedakan cache vs pola-salah (sesuai instruksi brief)

Cache dingin membaik pada jalan kedua; pola query yang salah TIDAK. Preseden
persis ada di daftar yang sama, **D1** (`/mutasi-bank/?upload=<id>`): **"46 dtk
dingin / 37 dtk panas ... Tidak membaik saat dipanaskan → polanya yang salah,
bukan cache."** Perhatikan angkanya: 46→37 dtk memang sedikit membaik (±20%,
konsisten dengan SEBAGIAN halaman terbantu cache OS/`shared_buffers`), tapi
tetap dalam orde puluhan detik — jadi "membaik" tidak otomatis berarti "cache
adalah penyebab utama"; kesimpulan D1 memakai skala perbaikannya (kecil,
tidak proporsional) bukan cuma arahnya.

**Riset ini tidak bisa menjalankan uji itu** (tidak ada akses produksi). Yang
bisa dilakukan: (a) baca kode utk menentukan APAKAH mekanisme yang sama
("ORDER BY kolom global membuat toko pasif memindai jauh") secara STRUKTURAL
ada di `/rekening/`, dan (b) bila tidak persis sama, cari cacat lain yang
SECARA MEKANISME serupa (cache-insensitive) yang benar-benar ada di kode
SAAT INI. Kedua langkah itu di bawah.

## Temuan 1 — mekanisme literal D1/memo lama TIDAK ada di `rekening_breakdown` (modul)

Catatan memori proyek (`insight-lambat-per-toko-upload-id.md`, ditulis
01-09-2026) mencatat mekanisme yang lebih baik dari cache dingin: `ORDER BY
upload_id DESC, id ASC LIMIT 50` pada `/mutasi-bank/` (`web/views.py::
bank_mutations`, `.order_by("-upload_id", "id")` di baris 2262) memaksa
Postgres memindai index `upload_id` GLOBAL dari puncak, membuang baris toko
lain satu per satu — toko yang unggahan terakhirnya LAMA (upload_id kecil
relatif ke puncak global) membayar paling mahal, **meski total datanya
kecil**. Fix-nya `tx_toko_upload_id_idx (toko, upload, id)` (`transactions/
models.py` baris 252-255, komentarnya secara eksplisit menamai halaman itu
sbg pemakai) — sudah dipasang.

**Diperiksa: apakah `web/rekening.py::rekening_breakdown` (fungsi agregator,
BUKAN view — lihat Temuan 2 utk bedanya) punya pola `ORDER BY kolom-global +
LIMIT` yang sama?** Dibaca penuh (238 baris) — **tidak**:

- Query 1 (`agregat`, baris 130-156): `GROUP BY (source_type_id, account_id,
  upload_id)` atas SELURUH baris dalam rentang tanggal yg diminta — tanpa
  `LIMIT`/`OFFSET`, tanpa `ORDER BY` (baris 132 eksplisit `.order_by()` kosong
  justru utk MENCEGAH kolom sort bocor ke `GROUP BY`).
- Query 2 (`rantai`, baris 189-196): `.order_by("occurred_at", "id")` — juga
  TANPA `LIMIT`. Tanpa `LIMIT`, planner tak punya alasan "berhenti sedini
  mungkin dari satu ujung index global" — pola yang justru jadi akar masalah
  D1/memori lama SECARA STRUKTURAL butuh `LIMIT` (planner memilih rencana
  "pindai dari satu ujung, berhenti begitu cukup" HANYA kalau ada `LIMIT`
  yang membuat itu menguntungkan secara biaya).
- Kedua query berbasis `dasar` (baris 119-123): `toko=toko` sbg filter
  KESETARAAN pertama — cocok persis prefix index komposit `tx_toko_src_
  occurred_idx (toko, source_type, occurred_at)` (`transactions/models.py`
  baris 238-241).

**Kesimpulan Temuan 1**: pola literal dari memori lama (yang sudah diperbaiki
utk `/mutasi-bank/`) TIDAK bereplikasi di modul `rekening_breakdown`. Kalau
hipotesis brief dimaksudkan HARFIAH ("kueri yang sama persis"), itu **tidak
terbukti** dari kode saat ini.

## Temuan 2 — cacat NYATA yang berbeda bentuk tapi SATU KELUARGA, di VIEW-nya

`web/views.py::rekening_breakdown` (baris 2965-2985 — **NAMA SAMA dengan
modul `web/rekening.py::rekening_breakdown`, tapi berkas BEDA**: yang satu
view Django, satu lagi fungsi agregator murni; brief sendiri hanya menyebut
"baca web/rekening.py" — investigasi ini SENGAJA melebar ke pemanggilnya
karena di situlah cacatnya ditemukan) menghitung, di baris 2974-2976,
**TANPA SYARAT pada setiap pemuatan halaman** (bahkan saat `dari`/`sampai`
sudah eksplisit di URL):

```python
latest = Transaction.objects.filter(
    toko=active, source_type__key__in=("bank", "gateway")
).aggregate(m=Max("occurred_at__date"))["m"]
```

**Dibuktikan, bukan diasumsikan** — kueri ini dijalankan pada salinan DB lokal
(`Toko k25`, django shell, `CaptureQueriesContext`) dan SQL yang BENAR-BENAR
dihasilkan Django adalah:

```sql
SELECT MAX(django_datetime_cast_date("transactions_transaction"."occurred_at", NULL, NULL)) AS "m"
FROM "transactions_transaction"
INNER JOIN "sources_sourcetype" ON (...)
WHERE ("sources_sourcetype"."key" IN ('bank', 'gateway') AND "transactions_transaction"."toko_id" = 30)
```

`django_datetime_cast_date(...)` adalah fungsi SQLite utk lookup `__date`;
di Postgres, Django mengkompilasi lookup YANG SAMA menjadi `(occurred_at)::date`
— PERSIS istilah yang sudah dipakai `transactions/models.py` sendiri utk
menjelaskan kenapa `tx_toko_src_occurred_idx` "mati" utk pemakai yang
membungkus kolomnya (baris 232-236: *"Django membungkus kolomnya jadi
`(occurred_at)::date` sehingga bagian TANGGAL index ini mati ... hanya
prefix (toko, source_type) yang terpakai"*).

**Bandingan dgn halaman TETANGGA yang punya fitur IDENTIK ("badge tanggal
terakhir")**: `bracket_breakdown`/`bracket_detail`/`export_breakdown`
(`web/views.py` baris 2399-2401, 2436-2438, 2472-2474) — tiga tempat, SEMUA
memakai:

```python
latest = Transaction.objects.filter(
    toko=active, source_type__key="bracket"
).aggregate(m=Max("posted_date"))["m"]
```

Ditangkap SQL-nya juga (metodologi sama): **`SELECT MAX("transactions_
transaction"."posted_date") ...`** — TANPA fungsi pembungkus apa pun, karena
`posted_date` sudah `DateField` mentah.

Dicek juga lewat grep: `occurred_at__date` (bentuk PERSIS yang dipakai sbg
argumen `Max()`, bukan filter `__gte/__lte`) di seluruh kode aplikasi **HANYA
muncul satu kali**, di baris 2976 ini. Artinya di antara semua "pemakai
`tx_toko_src_occurred_idx`" yang disebut komentar model, **ini satu-satunya
yang MENG-AGREGASI lewat cast** (bukan sekadar memfilter dengannya).

**⚠️ KOREKSI PENTING soal seberapa jauh perbandingan ini bisa dipercaya**
(temuan review, bukan asumsi awal dokumen ini): saya SEMPAT menyimpulkan
`Max("posted_date")` "bisa memakai jalan pintas pindai-mundur index MIN/MAX
Postgres" sedangkan `Max("occurred_at__date")` tidak, dan menyajikan itu sbg
"satu fitur, dua implementasi, satu benar satu salah". **Itu overclaim.**
Kedua kueri di atas SAMA-SAMA melewati `INNER JOIN sources_sourcetype`
(dari `source_type__key=...`) — dan jalan pintas index MIN/MAX Postgres
(`planagg.c`, `preprocess_minmax_aggregates`) setahu saya menolak query yang
BUKAN pindai satu relasi tunggal (ada JOIN = ditolak). Kalau itu benar,
**KEDUANYA** — pola /bracket/ yang saya sebut "bersih" maupun pola
/rekening/ yang saya sebut "cacat" — sama-sama TIDAK bisa memakai jalan
pintas itu, dan bedanya menciut jadi: /rekening/ tetap membayar EKSTRA per
baris (fungsi cast) dan menyaring DUA nilai `source_type` bukan satu, tapi
KEDUANYA tetap memindai seluruh baris toko yg cocok filter (bukan
pindai-mundur-satu-baris). Saya TIDAK memverifikasi klaim `planagg.c` ini
lewat sumber Postgres atau `EXPLAIN` sungguhan — hanya argumen dari ingatan.
**Jangan perlakukan pola /bracket/ sbg "terbukti cepat"** di dokumen ini;
tak satu pun keduanya diukur waktu jalannya. Bagian Rekomendasi #1 di bawah
sudah disesuaikan dgn koreksi ini.

## Kenapa Temuan 2 SENDIRI belum tentu jawaban penuh (celah jujur)

Biaya `MAX(cast(occurred_at))` di atas sebanding dgn JUMLAH BARIS bank+gateway
milik toko itu SENDIRI (dibatasi prefix kesetaraan `toko, source_type` pada
index) — BUKAN dgn seberapa jauh unggahan terakhir toko itu dari puncak
GLOBAL (mekanisme spesifik yang membuat toko *pasif* — bukan toko *kecil* —
paling menderita pada kasus lama). Kalau `k25` benar 6× LEBIH KECIL dari `mxw`
dalam baris bank/gateway juga (bukan cuma total baris), Temuan 2 **semestinya
membuat k25 LEBIH CEPAT**, bukan lebih lambat, pada bagian query ini — jadi
Temuan 2 adalah **cacat nyata yang pantas diperbaiki atas nama sendiri**,
tapi TIDAK terbukti sbg penjelasan PENUH atas ARAH spesifik "k25 > mxw".

Dua mekanisme lain yang SECARA TEORI bisa menjelaskan arah itu, keduanya
HANYA bisa dikonfirmasi via `EXPLAIN ANALYZE` produksi (tak dilakukan di
sini):

1. **Generic vs custom plan (prepared statement Postgres)**: setelah ±5
   eksekusi bentuk kueri terparameter yang sama, Postgres bisa beralih dari
   rencana "custom" (khusus nilai parameter itu) ke rencana "generic"
   (rata-rata semua nilai parameter yang pernah dilihat). Kalau rencana
   generic dioptimalkan utk toko besar/umum (`mxw`), toko kecil/jarang
   seperti `k25` bisa mendapat rencana yang justru LEBIH BURUK utk dirinya
   sendiri dibanding rencana custom yang seharusnya dia dapat.
2. **Bentuk data, bukan volume**: jumlah kombinasi `(source_type, account,
   upload)` DISTINCT pada hari/rentang yang diminta (bukan total baris) yang
   menentukan biaya `_label_kombinasi` (`web/rekening.py` baris 22-59) —
   toko dgn riwayat unggahan yang lebih "berkeping" (banyak file kecil per
   hari) membayar lebih di sini WALAU total barisnya lebih kecil.
   **Diuji lokal utk k25** (satu-satunya toko yg tersedia): SEBALIKNYA dari
   dugaan ini — k25 justru punya SEDIKIT kombinasi (10 kombinasi utk
   15.387 baris bank+gateway sebulan penuh; 2 kombinasi utk 49 baris pada
   hari teraktifnya, ≈24,5 baris/kombinasi). Ini pola "file terkonsolidasi",
   BUKAN "banyak file kecil berkeping" — jadi hipotesis ini **TIDAK didukung
   data k25 sendiri**. Tanpa angka `mxw` utk pembanding, hipotesis ini tetap
   TAK TERVERIFIKASI (bisa saja `mxw` py justru lebih fragmentif — tak
   diketahui), tapi bukti yang ada tidak mengarah ke sana; dicantumkan hanya
   sbg kemungkinan teoretis yang belum tersingkir sepenuhnya, bukan dugaan
   yang didukung.

## Halaman lain yang kemungkinan kena pola SAMA (cast `__date` mematikan index)

Ini BUKAN temuan baru — sudah tercatat sbg utang teknis di memori proyek
(*"engine.py::_date_filter memakai occurred_at__date ... 16 lokasi di kode,
terukur 37.547→17.107 buffer bila cast dibuang"*, masih terbuka). Kontribusi
riset ini: memetakan `grep occurred_at__date` ke HALAMAN kongkret yang
memakainya (di luar Temuan 2 yang sudah dibahas di atas):

| Berkas:baris | View | Bentuk |
|---|---|---|
| `web/views.py:1314,1319` | `transactions` (list "Transaksi") | filter `__gte/__lte` |
| `web/views.py:2284,2286` | `bank_mutations` (Mutasi Bank) | filter `__gte/__lte` — **terpisah** dari `.order_by("-upload_id","id")` baris 2262 yang sudah dibahas di atas (sudah dibantu index `tx_toko_upload_id_idx`) |
| `web/views.py:2125-2131` | `review_queue` (Area Pengecekan `/tinjau/`) | filter `__gte/__lte`, dua sisi (`left__.../right__...`) |
| `reconciliation/engine.py:239,241,1401,1926,1941` | `_date_filter` + pemakainya | filter — **di luar cakupan tulis riset ini** (`reconciliation/` terlarang disentuh) |
| `web/penjaga.py:359,372,373` | pemeriksaan pasca-unggah | filter — jalur peringatan, bukan halaman baca |

Semua yang berbentuk FILTER (bukan agregat `Max`) masih dibatasi prefix
kesetaraan `toko`(+`source_type`/`run__batch__toko`) pada indexnya masing2 —
jadi levelnya "membuang kesempatan index bagian tanggal utk MEMPERSEMPIT
rentang" (biaya sebanding riwayat TOKO itu dalam rentang yg diminta), beda
mekanisme dari Temuan 2 (agregat `Max` tanpa `WHERE` tanggal sama sekali —
selalu memindai SELURUH riwayat toko utk source_type itu, terlepas rentang
yg diminta pengguna). Tak satu pun di atas diperbaiki di sini (scope tulis
riset ini hanya `scripts/harness/*` + dua dokumen ini).

## Rekomendasi + risiko (tidak diterapkan — riset murni)

### 1. Perbaiki Temuan 2: `Max("occurred_at")` lalu `.date()` di Python

```python
latest_dt = Transaction.objects.filter(
    toko=active, source_type__key__in=("bank", "gateway")
).aggregate(m=Max("occurred_at"))["m"]
latest = latest_dt.date() if latest_dt else None
```

**Kenapa PERILAKUNYA provably setara** (bukan tebakan): `.date()` monoton
tak-turun — utk fungsi monoton tak-turun `f` apa pun, `f(max(x_i)) ==
max(f(x_i))` (elemen yang mencapai `max(x_i)` juga mencapai `max(f(x_i))`
karena monotonisitas). Jadi memindah `.date()` dari SEBELUM agregasi (di
SQL, membungkus kolom) ke SESUDAH agregasi (di Python, atas SATU nilai)
tidak mengubah hasil `latest` APA PUN. Ini bagian yang PASTI benar.

**Kenapa MANFAAT KECEPATANNYA belum pasti** (lihat koreksi ⚠️ di atas):
awalnya saya klaim perubahan ini membuka "jalan pintas pindai-mundur MIN/MAX"
Postgres. Itu **perlu tapi mungkin TIDAK CUKUP** — kueri ini tetap melewati
`INNER JOIN sources_sourcetype` (dari `source_type__key__in=(...)`), dan
setahu saya jalan pintas itu ditolak Postgres utk query yg bukan pindai satu
relasi tunggal. Kalau begitu, membuang cast SAJA menghasilkan kueri yang
PASTI tak lebih mahal (satu fungsi lebih sedikit per baris dicek) tapi BELUM
TENTU jadi O(log n) — bisa jadi masih O(baris toko itu). Utk benar2 membuka
jalan pintasnya, `source_type` mungkin perlu diselesaikan ke id di Python
lalu difilter `source_type_id__in=[...]` (menghilangkan JOIN) — dan bahkan itu
TIDAK DIJAMIN cukup (lihat batasan berikutnya). **Satu-satunya cara memastikan
seberapa besar manfaatnya adalah `EXPLAIN (ANALYZE, BUFFERS)` di Postgres
sungguhan**, sebelum dan sesudah, utk k25 dan mxw.

**Risiko**: rendah utk PERILAKU (perubahan bentuk kueri, bukan logika — nilai
`latest` dijamin sama). Risiko utk EKSPEKTASI KECEPATAN: sedang — jangan
menjanjikan speedup besar ke pemilik produk sebelum `EXPLAIN` mengonfirmasi;
klaim yang aman hanya "tidak lebih mahal, mungkin lebih murah". Tes yang
memaku angka/perilaku halaman `/rekening/` (bila ada) harus tetap hijau tanpa
diubah, karena nilai `latest` SAMA persis. **Belum ada
`assertNumQueries`/perf-regression test utk halaman ini** (item F2 di daftar
audit) — pantas ditambah bersamaan biar regresi serupa tertangkap otomatis.

### 2. JANGAN mengganti ke `Max("posted_date")` meniru pola `/bracket/`

Tergoda karena polanya "sudah terbukti bekerja" di 3 tempat lain — tapi
**BUKAN setara**: `posted_date` help_text-nya sendiri *"Tanggal 'masuk'
(statement/entry)"* — konsep BERBEDA dari tanggal `occurred_at` (waktu
transaksi ASLI). Untuk baris bank ini biasanya sama, tapi TIDAK dijamin utk
semua sumber gateway (mis. shift UTC→WIB ZPay, atau baris yang tanggalnya
sempat kosong lalu diperbaiki lewat `perbaiki_gateway_tanpa_tanggal` dari
`raw` — dua tanggal itu diisi dari ekspresi berbeda, tidak selalu identik).
Mengganti kolom bisa diam-diam menggeser badge "data terbaru s/d tanggal X"
DAN default rentang tanggal halaman (`sampai = ... or latest or ...`) —
perubahan PERILAKU, bukan cuma perubahan kueri. Opsi #1 di atas TIDAK
punya risiko ini karena tetap memakai kolom yang sama persis.

### 3. Sebelum menutup butir ini: minta pemegang akses produksi menjalankan

- `EXPLAIN (ANALYZE, BUFFERS)` utk KETIGA query (2 di `web/rekening.py` +
  `Max("occurred_at__date")` di view) pada `k25` DAN `mxw`, rentang tanggal
  YANG SAMA — bandingkan `buffers` per baris hasil. Bila salah satu toko
  menyentuh buffer jauh lebih banyak per baris keluaran daripada yang lain,
  itu konfirmasi mekanisme "memindai lebih dari yang seharusnya"; bila
  proporsional, arahnya bukan soal index sama sekali (kembali ke hipotesis
  #2 bentuk-data atau #1 generic-plan di atas).
- Jalankan halaman dua kali berturut-turut (metodologi D1) utk k25 —
  catat detik dingin vs panas. Membaik besar → cache berperan; tak membaik
  (pola D1) → pasti bukan cache, tapi EXPLAIN di atas tetap perlu utk tahu
  query MANA yang salah.

## Yang TIDAK bisa disimpulkan riset ini (baca sebelum bertindak)

- **Tidak terbukti** bahwa mekanisme `/rekening/`-nya PERSIS sama dgn
  memori lama `/mutasi-bank/` (ORDER BY global + LIMIT) — pola itu SECARA
  STRUKTURAL tak ada di `rekening_breakdown`. Hipotesis awal brief
  ("mekanismenya... toko pasif membayar aktivitas toko lain") benar SEBAGAI
  KELAS UMUM (cast mematikan index = keluarga masalah yang sama: query yang
  bisa memakai index tak dipakai penuh), tapi belum terbukti sbg penjelasan
  LENGKAP atas angka k25-vs-mxw yang spesifik.
- **Tidak terbukti maupun terbantahkan** bahwa hipotesis "cache dingin" itu
  100% salah — yang bisa dikatakan: (a) metodologi utk mengujinya (run dua
  kali) ADA dan sudah dipakai sukses di D1, (b) riset ini tak bisa
  menjalankannya (tanpa akses produksi), (c) SATU cacat struktural yang
  cache-insensitive (Temuan 2) memang ditemukan dan dibuktikan ada di kode,
  jadi paling tidak "murni cache dingin" BUKAN satu-satunya faktor yang
  mungkin — ada faktor cache-insensitive yang pasti nyata di sana.
- Tak ada angka detik/ms Postgres di dokumen ini — SEMUA bukti di atas
  adalah SQL yang benar-benar dihasilkan (lewat `CaptureQueriesContext` di
  DB lokal SQLite) + argumen struktural index, bukan pengukuran waktu.
- Klaim "jalan pintas pindai-mundur MIN/MAX Postgres ditolak bila ada JOIN"
  (dipakai utk mengoreksi Temuan 2 di atas) sendiri **belum diverifikasi**
  ke sumber Postgres atau `EXPLAIN` sungguhan — itu argumen dari ingatan,
  dicantumkan sbg PERINGATAN supaya rekomendasi #1 tak dijual sbg "pasti
  cepat", bukan sbg fakta yang sudah terbukti. Verifikasi keduanya (klaim
  JOIN ini, dan besaran manfaat rekomendasi #1) sama-sama menunggu
  `EXPLAIN` produksi.
