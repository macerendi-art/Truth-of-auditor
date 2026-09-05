# Runbook — Rotasi `SECRET_KEY` + `DATABASE_URL` (butir A3)

**Status: TERTAHAN PADA PEMILIK. Dokumen ini menyiapkan langkahnya; yang menjalankan adalah kamu.**

Alasannya bukan kehati-hatian berlebihan: langkah-langkah di bawah menuntut membaca dan menempelkan
kredensial produksi. Agen tidak memasukkan kata sandi, kunci, atau token ke mana pun — jadi
perintahnya diserahkan utuh untuk kamu jalankan sendiri.

## Kenapa ini perlu

Butir A3 pada `docs/daftar-perbaikan-2026-09-03.md`:

> **`SECRET_KEY` + `DATABASE_URL` bocor belum dirotasi** — terekspos di log sesi 31-08-2026;
> riwayat 20 deployment tak menunjukkan perubahan variabel sesudahnya.

Dua nilai itu masih yang sama sampai hari ini. `SECRET_KEY` menandatangani cookie sesi dan token
reset sandi; siapa pun yang memilikinya bisa memalsukan sesi login **tanpa perlu tahu satu pun kata
sandi**, dan `IPAllowlistMiddleware` tidak menolongmu di sini karena admin/superuser memang tidak
pernah digerbang olehnya. `DATABASE_URL` memberi akses baca-tulis penuh ke basis data lewat proxy
TCP publik Railway — dari mana saja di internet.

## ⛔ Dua aturan yang tidak bisa ditawar

1. **Keduanya harus dibuat BARU, tidak pernah disalin dari nilai lama.**
2. **`SECRET_KEY_FALLBACKS` yang berisi kunci lama DILARANG.** Django menyediakannya supaya sesi
   pengguna tidak putus saat rotasi — tapi memasang kunci yang bocor di sana berarti kunci itu
   **masih berlaku**, dan seluruh rotasi ini tidak ada gunanya. Harga yang benar untuk dibayar:
   semua orang logout sekali. Beri tahu tim sebelumnya.

---

## ⚠️ URUTAN — baca ini sebelum menjalankan apa pun

Sejak butir A1 selesai (4 September 2026), **cadangan harian basis data menarik dump dari produksi
memakai kredensial di `~/.pgpass` pada VPS `toa`.** Artinya:

> **Merotasi `DATABASE_URL` tanpa memperbarui `~/.pgpass` di VPS akan membuat cadangan harian
> gagal — dan gagal secara senyap, di jam 03:00, tanpa ada yang menonton.**

Itu persis mode kegagalan yang paling mahal di sistem ini, dan persis yang butir B1 dibangun untuk
menangkap. Jadi langkah pembaruan `.pgpass` **bukan catatan tambahan, melainkan bagian wajib dari
rotasi.** Jangan anggap selesai sebelum satu jalan cadangan berhasil dengan kredensial baru.

Urutan yang benar:

| # | Langkah | Kenapa urutannya begitu |
|---|---|---|
| 1 | Rotasi `SECRET_KEY` | Berdiri sendiri, tidak menyentuh cadangan. Kerjakan lebih dulu supaya risiko terbesar (pemalsuan sesi) ditutup paling cepat. |
| 2 | Rotasi kredensial basis data | — |
| 3 | **Perbarui `~/.pgpass` di VPS `toa`** | Tanpa ini cadangan mati senyap. |
| 4 | **Jalankan cadangan sekali secara manual dan buktikan `verdict: OK`** | Satu-satunya bukti bahwa langkah 3 benar. Jangan menunggu jadwal 03:00 untuk mengetahuinya. |
| 5 | Verifikasi aplikasi produksi masih sehat | — |

---

## Langkah 1 — `SECRET_KEY`

Buat kunci baru di mesinmu sendiri (jangan lewat layanan online mana pun):

```bash
/Users/macads/Truth-of-auditor/.venv/bin/python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Pasang ke Railway pada service `web`, environment `production`, lalu biarkan service redeploy.
Gunakan dashboard Railway, atau CLI dari checkout utama `/Users/macads/Truth-of-auditor`.

Yang perlu diketahui sebelum menekan tombol:

- **Semua pengguna akan logout.** Sesi lama ditandatangani kunci lama dan menjadi tidak sah.
- **Tautan reset sandi yang belum dipakai akan mati.** Kalau ada yang sedang menunggu, minta mereka
  meminta ulang setelah rotasi.
- `truth_auditor/settings.py` (guard di bagian atas berkas, dipin `core/tests_settings_guard.py`; BUKAN `security.py`, yang hanya berisi `configure_sentry`) membuat `SECRET_KEY` tanpa env **gagal-keras saat boot** ketika
  `DEBUG=False`. Itu perilaku yang benar — tapi artinya salah ketik pada nilai barunya akan
  menahan port tertutup, bukan menghasilkan halaman error. Tempel dengan hati-hati.

## Langkah 2 — kredensial basis data

⚠️ **DIKOREKSI 05-09-2026 setelah memeriksa variabel Railway yang sebenarnya.** Versi pertama
dokumen ini menulis "rotasi dilakukan dari dashboard Railway" dan itu **menyesatkan**: service
Postgres memang punya `POSTGRES_PASSWORD`, tapi variabel itu hanya dibaca entrypoint Postgres
**saat basis data PERTAMA KALI diinisialisasi**. Database ini sudah berjalan sejak Juli, jadi
mengubah variabel itu **TIDAK mengubah sandi role yang sesungguhnya** — ia hanya membuat aplikasi
memakai sandi yang salah, dan hasilnya bukan rotasi melainkan pemadaman.

Urutan yang benar: **ubah di dalam Postgres dulu, baru samakan variabelnya.**

### 2a. Siapkan sandi baru
```bash
LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 40; echo
```
Sengaja hanya huruf+angka: sandi yang memuat `@ : / ?` merusak parsing URL koneksi, dan itu jenis
kerusakan yang baru terlihat saat cadangan gagal jam 3 pagi.

⚠️ Sebelum lanjut, **buka dashboard Railway service Postgres di tab lain dan siapkan sandi barunya
di clipboard.** Antara langkah 2b dan 2c aplikasi tidak bisa membuka koneksi BARU (koneksi lama
bertahan sampai `CONN_MAX_AGE=600`), jadi jendela itu harus pendek. Kerjakan di jam sepi, dan
JANGAN di 03:00–03:30 (cadangan sedang memegang transaksi panjang).

### 2b. Ubah sandi di dalam Postgres
```bash
ssh -t toa 'psql -d "$(cat ~/.prod-url)"'
```
Lalu di prompt psql:
```
\password postgres
\q
```
`\password` meminta sandi dua kali tanpa menggemakannya, dan mengirim `ALTER USER` dengan nilai
yang sudah di-hash — sandinya tidak pernah muncul di `argv`, di `~/.psql_history`, maupun di log
server. **Jangan** memakai `psql -c "ALTER USER ... PASSWORD '...'"`: itu menaruh sandi di
`/proc/<pid>/cmdline` dan di riwayat.

### 2c. Perbarui `~/.pgpass` VPS SEGERA (lihat Langkah 3)
Lakukan ini **sebelum** menyentuh dashboard — cadangan adalah hal yang paling tidak boleh mati,
dan langkah ini yang menjaganya.

### 2d. Samakan variabel di Railway
Di service **Postgres**, ubah `PGPASSWORD` **dan** `POSTGRES_PASSWORD` ke sandi baru.
`DATABASE_URL` dan `DATABASE_PUBLIC_URL` diturunkan darinya dan ikut berubah.

⚠️ Lalu periksa service **web**: buka variabel `DATABASE_URL` di dashboard.
- Kalau isinya **`${{Postgres.DATABASE_URL}}`** (referensi) → ia ikut otomatis, tidak perlu apa-apa.
- Kalau isinya **string mentah** yang memuat sandi → ubah juga di sana, kalau tidak aplikasi tetap
  memakai sandi lama.

Perubahan variabel memicu redeploy; itu wajar. Start command menjalankan `migrate` lebih dulu —
tak ada migrasi tertunda, jadi cepat.

## Langkah 3 — perbarui `~/.pgpass` di VPS (WAJIB)

```bash
ssh toa
```

Lalu di mesin itu, sunting `~/.pgpass` (satu baris, format
`host:port:database:user:password`) dan `~/.prod-url` bila host/port ikut berubah.

⛔ **Jangan pernah menaruh kata sandi di `argv`.** `pg_dump -d "postgres://user:pass@..."`
memperlihatkannya di `/proc/<pid>/cmdline` bagi setiap pengguna di mesin itu. Skrip cadangan
memang sudah dirancang mengambil sandi dari `.pgpass` — pertahankan itu.

Jaga izinnya tetap ketat; Postgres akan menolak `.pgpass` yang lebih longgar dari `0600`:

```bash
chmod 600 ~/.pgpass && ls -l ~/.pgpass
```

## Langkah 4 — buktikan cadangan masih jalan (WAJIB)

Jangan menunggu jadwal 03:00. Jalankan sekali sekarang, lalu baca berkas statusnya:

```bash
ssh toa 'sudo systemctl start toa-cadangan.service && journalctl -u toa-cadangan.service -n 30 --no-pager'
```

Cadangan dinyatakan sehat hanya bila berkas statusnya menunjukkan `verdict: OK` **dan**
`terakhir_ok` bergerak ke stempel waktu hari ini. Langkah dan lokasi berkasnya ada di
[`runbook-cadangan-2026-09-04.md`](runbook-cadangan-2026-09-04.md).

Kalau gagal: hampir pasti `.pgpass` salah ketik atau izinnya bukan `0600`. Perbaiki, jalankan lagi.
**Jangan tinggalkan rotasi dalam keadaan cadangan merah** — sejak saat itu sampai diperbaiki,
sistem ini kembali ke keadaan sebelum butir A1: tanpa cadangan sama sekali.

## Langkah 5 — verifikasi aplikasi

⚠️ **Geo-block KH-only aktif di produksi.** Dari luar Kamboja kamu akan menerima **403 halaman
"Trust No One"**. Itu **bukan** tanda aplikasi rusak — 403 justru membuktikan aplikasinya hidup dan
middleware-nya bekerja. Yang menandakan masalah adalah tidak ada jawaban sama sekali, atau 500.

Untuk memeriksa dari dalam kontainer, pakai `railway ssh` dari checkout utama
`/Users/macads/Truth-of-auditor`.

Periksa juga:
- login berhasil dengan sandi yang benar (sesi baru ditandatangani kunci baru);
- `python manage.py periksa_kesehatan` di kontainer — laporan utuh, tidak ada BAHAYA;
- `python manage.py periksa_index` — keluar 0.

---

## Sesudahnya

- Nilai lama sudah **mati**. Jangan disimpan "untuk jaga-jaga" di mana pun — catatan, chat, atau
  `SECRET_KEY_FALLBACKS`. Menyimpannya membatalkan seluruh rotasi ini.
- Kalau kunci pernah bocor sekali, ada baiknya rotasi dijadwalkan berkala, bukan hanya reaktif.
  Itu keputusanmu; dokumen ini tidak memutuskannya.

## Yang belum pernah diuji

Prosedur ini **belum pernah dijalankan di produksi**. Langkah 1, 3, dan 4 diturunkan dari perilaku
yang sudah diverifikasi (guard `SECRET_KEY` di `settings.py` gagal-keras, skrip cadangan membaca `.pgpass`, berkas status
menulis `verdict`/`terakhir_ok`). Langkah 2 bergantung pada bentuk dashboard Railway saat kamu
menjalankannya, dan itu di luar kendali dokumen ini.
