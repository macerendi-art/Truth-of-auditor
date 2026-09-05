# Keputusan — menyambungkan `Upload.file` (jejak audit berkas asli), 2026-09-05

Status: **kode SELESAI dan teruji. Manfaatnya BELUM aktif di produksi** sampai volume
Railway terpasang (butir A2). Lihat "Ketergantungan pada A2" di bawah — ini bukan
formalitas, tanpa volume berkas tetap lenyap tiap deploy.

Sumber tugas: temuan sesi A2 (`docs/runbook-media-volume-2026-09-04.md`, kini di `main`
lewat `4ca270d`) bahwa `Upload.file` tidak pernah diisi kode apa pun. Rilis: **v1.26.0**.

## Premis tugas — diverifikasi ulang, benar

Empat lapis bukti dari sesi A2 diperiksa ulang di sesi ini dan semuanya bertahan:

1. `Upload.objects.create(...)` hanya muncul di `sources/services.py:_persist_rows`
   untuk jalur produksi — sisanya seluruhnya berkas tes. Tak satu pun membawa `file=`.
2. `web/views.py` `upload()` menghapus `staging/<nama>` di blok `finally` pada request
   commit yang sama.
3. `git log --all -S 'upload_to="uploads'` atas `sources/models.py` → **satu** commit:
   `58a5c04` (initial commit). Field ini scaffold yang tak pernah disambungkan.
   `git log --all -S 'file=' -- sources/services.py` → **nol** commit.
4. Satu-satunya isi `media/uploads/` di checkout utama adalah **24 berkas `uji*.csv`**
   — residu tes (`web/tests_delete.py`, `web/tests_kelola.py` memanggil `up.file.save`
   tanpa `override_settings(MEDIA_ROOT=…)`), bukan unggahan sungguhan.

## Yang diputuskan pemilik (2026-09-05)

| Pertanyaan | Keputusan |
|---|---|
| Lanjut sekarang walau volume belum terpasang? | **Lanjut** — sikap sama dengan A2: kode siap, infra tertahan |
| Retensi | **Simpan selamanya**, plus alat pangkas manual yang **tidak dijadwalkan** |

## Penyimpangan dari rancangan awal tugas — dan alasannya

Rumusan tugas menyarankan *memindahkan* berkas staging: "`web/views.py` — commit path
TIDAK BOLEH lagi menghapus `staging/<nama>` … pindahkan ke lokasi permanen".

**Yang dikerjakan justru menyalin di dalam `ingest()`, dan `web/views.py` nyaris tak
disentuh.** Alasannya tiga, dan semuanya soal permukaan risiko:

1. **Satu jalur, bukan dua.** `ingest()` dipanggil dari tiga tempat (web, `manage.py
   ingest`, `validate_brands`). Menaruh penyimpanan di dalamnya membuat CLI ikut
   mendapat jejak audit tanpa kode tambahan; menaruhnya di view hanya melindungi web.
2. **Alur staging yang sudah teruji tidak berubah sama sekali.** `finally` yang
   menghapus staging, `_sweep_staging()`, `_STAGING_TTL`, dan seluruh tes yang
   menjaganya tetap berlaku apa adanya — yang disimpan adalah SALINAN. Semantik
   "pindah" akan membuat blok `finally` itu bercabang (hapus kalau gagal, jangan hapus
   kalau sukses) tepat di jalur yang paling ramai kasus tepinya.
3. **Berkas terenkripsi punya dua path.** Di dalam `ingest()` perbedaan `file_path`
   (asli) vs `parse_path` (hasil dekripsi sementara) terlihat jelas, sehingga yang
   tersimpan dipastikan berkas asli. Dari dalam view, perbedaan itu tak kelihatan.

Biayanya satu operasi salin per unggahan (berkas dibatasi 50 MB oleh
`_FILE_MAX_BYTES`, dan Django menyalinnya per-chunk).

## Opt-in, bukan bawaan — `simpan_berkas=False`

`services.ingest(..., simpan_berkas=False)`. Dinyalakan eksplisit oleh:

- `web/views.py` commit path (`simpan_berkas=True`)
- `sources/management/commands/ingest.py` (nyala; `--tanpa-berkas` mematikannya)

Dimatikan (bawaan) untuk `reconciliation/management/commands/validate_brands.py` dan
seluruh tes. Dua alasan konkret, bukan selera:

- **Harness kalibrasi** `validate_brands` meng-ingest satu folder ekspor nyata setiap
  kali dijalankan; berkasnya sudah ada di disk pemanggil, menyalinnya murni pemborosan.
- **Tes** memanggil `ingest()` 33 kali di 11 modul, beberapa dengan path yang **tidak
  ada** (`services.ingest("shared", "/nofile", …)` di `sources/tests_dedup.py`).
  Bawaan menyala akan membuat tes-tes itu gagal membuka berkas — dan yang lolos akan
  menumpuk residu di `media/uploads/` repo, persis 24 berkas `uji*.csv` yang sudah ada.

**Risiko yang diterima:** jalur ingest BARU (mis. rekonsiliasi async yang sedang
dirancang) tidak akan menyimpan berkas kecuali penulisnya ingat menyalakannya. Ditutup
dua arah: dua tes memaku jalur produksi yang ada
(`web/tests_unduh_berkas.JalurCommitMenyimpanTests`, `sources/tests_berkas_asli.PerintahCLITests`),
dan CLAUDE.md menyebut kontraknya.

## Penyimpanan berkas bukan operasi transaksional — dan itu ditangani

`_persist_rows` berjalan di dalam `db_tx.atomic()`, sedangkan penulisan berkas tidak
ikut rollback. Dua jalur nyata bisa meninggalkan berkas yatim:

- `_tandai_tiban` adalah statement TERAKHIR di dalam `atomic()` — kalau ia melempar,
  DB balik ke semula tapi berkasnya sudah di disk.
- `ingest()` **sengaja mengulang** `_persist_rows` sekali saat `IntegrityError`
  (balapan ingest ganda) — percobaan pertama akan meninggalkan satu berkas, kedua
  menulis satu lagi.

Karena itu berkas ditulis **setelah** `bulk_create` (kegagalan yang paling mungkin,
baris tak valid, tak pernah menyentuh disk), dan seluruh badan `_persist_rows`
dibungkus `except Exception: berkas.delete(save=False); raise`. Dua tes memaku ini:
`test_kegagalan_setelah_simpan_membersihkan_berkas` dan
`test_retry_integrityerror_tidak_menggandakan_berkas`.

## Perilaku lama yang WAJIB tidak berubah — dan buktinya

Yang paling mudah rusak diam-diam adalah `original_name`: itu **kunci pencocokan
"ketiban"** (`_tandai_tiban` mencocokkan nama, dan `_SUFIKS_STORAGE_RE` mengupas sufiks
storage hanya di sisi tersimpan). Storage Django menyanitasi nama saat menyimpan
(spasi → garis bawah) dan membubuhi sufiks acak saat bentrok — kalau nama hasil
sanitasi itu bocor ke `original_name`, perilaku dedup/tiban bergeser tanpa error.

`_simpan_berkas_asli` menulis ke `up.file` saja; kolom `original_name` diisi apa adanya
saat `Upload.objects.create(...)`, seperti sebelumnya. Dijaga
`test_original_name_tidak_ikut_disanitasi_storage`, ditambah lima tes karakterisasi di
`PerilakuLamaTidakBerubahTests` (dedup 0 baris baru pada unggah ulang identik, tautan
`duplicate_transactions`, tiban menandai, tiban TIDAK menandai saat file identik, dan
berkas file yang ketiban tidak ikut dihapus).

Bukti terkuatnya tetap suite penuh: `python manage.py test` hijau.

## Sisi "bisa diambil kembali"

Menyimpan tanpa jalan mengambil sama saja tidak menyimpan. `MEDIA_URL` **tidak bisa
dipakai**: `truth_auditor/urls.py` hanya memasangnya saat `DEBUG`, jadi di produksi tak
ada jalurnya — dan kalaupun ada, URL media tak mengenal siapa pun, sementara ekspor
mutasi bank memuat nama pemain, nomor rekening, dan nominal.

Jadi jalurnya satu view: `web/views.unduh_upload` (`/upload/<pk>/berkas/`), digerbang
`tokos_for(request.user)` — gerbang yang persis sama dengan `delete_upload`. Unggahan
tanpa toko (jalur CLI) tak bisa di-scope siapa pun sehingga 404 dengan sendirinya.
Baris lama tanpa berkas dan berkas yang lenyap dari disk menjawab **404, bukan 500** —
halaman riwayat harus tetap bisa dibuka.

Di UI: ikon unduh kecil di sebelah nama berkas pada Riwayat Upload, **hanya** untuk
baris yang benar-benar punya berkas.

## Ukuran volume — angka nyata, bukan proyeksi kosong

Runbook A2 meninggalkan rumus tanpa isi karena tak punya ekspor nyata. Sesi ini
menemukannya: `samples/SAMPLING TO RND (TOKO= OKE25)/` berisi **tiga hari penuh**
ekspor asli satu toko (panel DP+WD, FR bracket, BRI, BCA CSV, BCA PDF, Mandiri, NXPay,
QR Flyer).

| Hari | Berkas | Total | Rata-rata/berkas |
|---|---|---|---|
| 27-06 | 13 | 5,51 MB | 434 KB |
| 28-06 | 13 | 5,73 MB | 451 KB |
| 29-06 | 13 | 5,50 MB | 433 KB |

Seluruh 13 berkas hari 27-06 di-ingest ke DB scratch untuk mendapat rasio yang tidak
bergantung pada asumsi jumlah toko: **31.675 baris `Transaction` dari 5.780.822 byte =
182,5 byte per baris.**

Rumus runbook A2 diisi lewat DUA jalur yang saling menguji:

```
(a) dari rasio + laju tumbuh produksi (v1.25.0: ±500 rb baris/hari, koreksi dari 185 rb):
        500.000 baris/hari × 182,5 byte  ≈  91 MB/hari

(b) dari ukuran hari nyata + jumlah toko:
        5,6 MB/hari/toko × 16 toko aktif ≈  90 MB/hari

                                         ≈  2,8 GB/bulan
                                         ≈  33 GB/tahun
```

**Kedua jalur itu TIDAK sepenuhnya independen** — keduanya bersandar pada ukuran berkas
hari OKE25 yang sama — jadi jangan dibaca sebagai dua konfirmasi terpisah atas angka
90 MB. Yang benar-benar diuji oleh kecocokannya adalah **asumsi skala**: (b) mengandaikan
produksi setara 16 toko sebesar OKE25, dan 16 × 31.675 = 507 rb baris/hari memang cocok
dengan laju tumbuh 500 rb baris/hari yang diukur di produksi (a). Itu asumsi yang paling
mudah meleset di sini, dan ia lolos.

Pada $0,15/GB/bulan, akhir tahun pertama ≈ **$5/bulan**.

**Batas kejujuran angka ini** — sengaja dicatat supaya tidak dikutip sebagai kepastian:

- Rasio 182,5 byte/baris berasal dari **satu** toko dan satu hari. Bentuk berkas
  berbeda punya rasio berbeda jauh (BRI CSV 1,87 MB untuk 4.905 baris = 382 byte/baris;
  panel xlsx 987 KB untuk 6.787 baris = 145), jadi toko dengan bauran sumber lain akan
  meleset dari rasio ini.
- Unggah ulang menyimpan **salinan lagi** — disengaja (pasangan "ketiban" adalah dua
  bukti berbeda), tapi menambah pemakaian di luar hitungan di atas.
- **Jumlah unggahan/hari di produksi belum diukur langsung** — sesi ini tidak
  menjalankan apa pun ke produksi. Yang menopang angka di atas adalah laju tumbuh baris
  (diukur produksi) dikali rasio byte/baris (diukur berkas), bukan hitungan berkas.

**Saran ukuran volume — dengan runway-nya dihitung, bukan dikira-kira.** Runbook A2
menyarankan 1–2 GB, tapi angka itu untuk `staging/` saja; pada 90 MB/hari ia habis
dalam **11–22 hari**. Pada laju yang sama:

| Ukuran | Runway (retensi = simpan selamanya) | Biaya/bulan |
|---|---|---|
| 5 GB | ±**55 hari** | $0,75 |
| 20 GB | ±7,5 bulan | $3,00 |
| 40 GB | ±**14 bulan** (satu tahun buku + margin) | $6,00 |

**Saran: 40 GB.** Bukan karena butuh segitu hari ini, tapi karena retensinya "simpan
selamanya" dan **tidak ada alarm otomatis** untuk volume ini (lihat gerbang pemantauan
di bawah) — jadi ukuran yang dipilih harus punya runway lebih panjang dari jarak antar-
tinjauan operasional, bukan sekadar "cukup untuk sekarang". Railway me-resize live tanpa
downtime selama volume belum 100% penuh, jadi menaikkan belakangan memang murah — tapi
membiarkannya penuh memicu offline resize (restart), dan proyek ini sudah punya dua
preseden `DiskFull` yang mematikan layanan.

Kalau pemilik memilih ukuran kecil (5 GB), itu sah — asal disertai pemantauan manual
`df -h` pada mount media dan resize sebelum 80%.

### Gerbang pemantauan yang BELUM tertutup

`manage.py periksa_kesehatan` mengukur sisa disk di `settings.BASE_DIR`
(`core/management/commands/periksa_kesehatan.py` `_bagian_disk`), **bukan**
`settings.MEDIA_ROOT`. Begitu A2 memindahkan `MEDIA_ROOT` ke `/data`, keduanya jadi
volume berbeda dan health check akan melaporkan disk kontainer sambil volume media
diam-diam terisi. Jadi hari ini **tidak ada satu pun alarm otomatis** untuk volume ini.

Perbaikannya kecil (satu baris laporan tambahan untuk `MEDIA_ROOT` bila berbeda dari
`BASE_DIR`), tapi sengaja TIDAK dikerjakan di sini: `periksa_kesehatan` punya kontrak
tesnya sendiri dan berada di luar cakupan tugas ini. Dicatat sebagai tindak lanjut.

## Retensi — alat ada, sengaja tidak bersenjata

`python manage.py pangkas_berkas_unggahan --hari N [--toko key] [--terapkan]`

- **`--hari` wajib**, tanpa nilai bawaan. Tanpa itu perintah menolak jalan sambil
  menyebutkan alasannya: retensi yang berlaku adalah simpan selamanya.
- **Dry-run bawaan**; menghapus hanya dengan `--terapkan` (pola `perbaiki_arah_qris_uno`).
- **Tidak dipasang di penjadwal mana pun.**
- Yang dihapus hanya berkasnya. Baris `Upload`, `Transaction`, tautan
  `duplicate_transactions`, dan penanda `superseded_by` tidak disentuh — dijaga tes.

Alasan bentuk ini: aturan proyek "jangan pernah hapus data produksi" melarang
penghapusan otomatis, sementara dua preseden `DiskFull` (Postgres 2026-07-04,
`/dev/shm` 2026-08-13) menunjukkan disk penuh di proyek ini mematikan layanan dengan
cara mengejutkan. Alat yang sudah teruji lebih baik daripada `rm` improvisasi di dalam
kontainer, yang akan meninggalkan baris `Upload` menunjuk berkas hantu.

## Ketergantungan pada A2 — baca sebelum menjanjikan apa pun ke pengguna

Rilis ini **tidak** melindungi berkas apa pun sampai butir A2 tuntas di sisi infra:

1. Volume Railway dipasang di service `web` (dashboard/CLI — `railway.json` tidak bisa
   mendeklarasikannya, lihat riset skema di runbook A2).
2. Env `MEDIA_ROOT` di-set ke mount path itu (kode env-configurable-nya **sudah ada di
   `main`** sejak A2/v1.25.0 — yang kurang tinggal volumenya).
3. Deploy (keputusan pemilik).

Sebelum ketiganya, berkas tersimpan di disk kontainer dan **lenyap tiap deploy** —
tombol unduhnya lalu menjawab 404 (ditangani, bukan 500). Fungsional, tapi bukan jejak
audit yang bisa disandari.

**Hubungan dengan runbook A2** — cabang A2 sudah mendarat di `main` (`4ca270d`) saat
pekerjaan ini di-rebase. Dua berkas di sana kini perlu disesuaikan, dan sengaja TIDAK
diubah dari sini supaya sejarah keduanya tetap terbaca terpisah:

1. `docs/runbook-media-volume-2026-09-04.md` — bagian "Ukuran volume yang disarankan"
   (1–2 GB, ditulis saat belum ada retensi berkas) dan butir (4) "definisi selesai"
   ("pemilik memutuskan apakah `Upload.file` akan disambungkan") sudah **terjawab**
   dokumen ini. Saran ukurannya naik dari 1–2 GB ke 40 GB.
2. `core/tests_media_root.py` memuat catatan eksplisit bahwa "produksi hari ini tidak
   pernah mengisi `file=`". Benar saat ditulis, **basi sejak rilis ini** — perbarui
   komentarnya, bukan tesnya (tesnya sendiri tetap sah).

## Yang TIDAK dikerjakan, dan kenapa

- **Berkas yang gagal di-parse tidak disimpan.** `ingest()` melempar sebelum
  `_persist_rows`, jadi tidak ada baris `Upload` untuk ditautkan. Justru berkas inilah
  yang paling berguna untuk debugging vendor yang mengganti kolom — tapi menyimpannya
  butuh model/alur baru (`Upload` berstatus `error` tanpa transaksi), di luar cakupan.
- **24 residu `uji*.csv`** di `media/uploads/` checkout utama tidak dibersihkan, dan tes
  yang melahirkannya (`web/tests_delete.py`, `web/tests_kelola.py`) tidak diperbaiki
  untuk memakai `MEDIA_ROOT` sementara. Kebersihan repo, bukan bagian fitur ini.
- **`core/management/commands/periksa_kesehatan.py`** — dua hal, keduanya di luar
  cakupan: (a) masih menulis `kesehatan.json` ke `BASE_DIR/media` yang di-hardcode
  (divergensi yang sudah dicatat runbook A2), dan (b) `_bagian_disk` mengukur
  `BASE_DIR`, bukan `MEDIA_ROOT` — lihat "Gerbang pemantauan yang BELUM tertutup".

## Bukti

- `sources/tests_berkas_asli.py` — 14 tes (penyimpanan, opt-in, berkas terenkripsi asli,
  pembersihan yatim, retry IntegrityError, 5 karakterisasi dedup/tiban, 2 CLI).
- `web/tests_unduh_berkas.py` — 9 tes (jalur commit menyimpan, staging tetap tersapu,
  unduh byte-identik, nama unduhan, scope toko 404, baris lama 404, berkas hilang 404,
  anonim → login, tautan hanya muncul bila ada berkas).
- `sources/tests_pangkas_berkas.py` — 8 tes (menolak tanpa `--hari`, dry-run bawaan,
  metadata utuh, saringan usia & toko, penanda ketiban selamat).
- `python manage.py test` (suite penuh) — lihat laporan sesi.
