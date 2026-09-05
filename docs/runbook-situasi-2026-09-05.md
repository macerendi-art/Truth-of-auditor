# Runbook situasi — apa yang harus dilakukan saat X terjadi

Kartu triase. Cari gejalanya, kerjakan langkahnya. Dokumen ini **tidak** menggantikan runbook
khusus yang ditautkan di tiap bagian — ia menjawab pertanyaan yang datang lebih dulu: *"ini
sebenarnya apa, dan apa yang saya lakukan sekarang?"*

Sebagian besar entri di sini dipicu oleh alarm yang masuk ke grup Telegram **RND Audit**.

---

## Aturan yang berlaku di semua situasi

1. **HTTP 403 dari `auditor.wolfgang-77.com` BUKAN tanda rusak.** Geo-block KH-only menjawab 403
   untuk semua orang di luar Kamboja. 403 justru membuktikan aplikasi HIDUP dan middleware
   bekerja. Yang menandakan mati: **502 / 503 / 504**, atau tidak ada jawaban sama sekali.
2. **Jangan `railway up` dua kali** karena yang pertama "kelihatan gagal". CLI sering kehilangan
   streaming log padahal build-nya jalan terus. Periksa statusnya lebih dulu (§B).
3. **Jangan deploy antara 03:00–03:30 WIB.** `pg_dump` cadangan memegang transaksi belasan menit,
   dan migrasi index akan mengantre di belakangnya sambil membekukan tabel inti.
4. **Cadangan gagal = prioritas tertinggi.** Selama itu merah, sistem ini kembali ke keadaan
   sebelum September 2026: tanpa jaring pengaman.
5. Kalau ragu, **jangan menghapus apa pun.** Hampir semua situasi di bawah bisa ditunggu; data
   yang terlanjur hilang tidak bisa.

---

## A. 🔴 "CADANGAN toa GAGAL"

**Artinya:** cadangan harian tidak selesai. Salinan terverifikasi kemarin **masih utuh** — skrip
sengaja tidak menyentuhnya sampai dump baru terbukti terbaca.

```bash
ssh toa 'cat ~/cadangan/status.json; tail -20 ~/cadangan/backup.log'
```

Baca `verdict` dan `pesan`, lalu cocokkan:

| `pesan` memuat | Artinya | Lakukan |
|---|---|---|
| `index invalid` | Gerbang J4 menolak. `pg_dump` MEMBUANG index invalid diam-diam, jadi dump ditolak sebelum dibuat | Jalankan §C dulu. Cadangan akan sehat sendiri begitu index beres |
| `pg_dump gagal` | Koneksi/kredensial | Sering karena `DATABASE_URL` dirotasi tanpa memperbarui `~/.pgpass`. Lihat [runbook rotasi kunci](runbook-rotasi-kunci-2026-09-04.md) langkah 3 |
| `dihentikan sinyal` | Kena `TimeoutStartSec` (4 jam) atau mesin dimatikan | Cek beban produksi; jalan jam sibuk pernah 1,7–4× lebih lambat. Jalankan ulang manual |
| `TOC` / `pg_restore -l` | Arsip rusak | **Jangan pakai dump itu.** Jalankan ulang; kalau berulang, curigai disk |

Menjalankan ulang secara manual (aman kapan saja kecuali 03:00–03:30):

```bash
ssh toa 'sudo systemctl start toa-cadangan.service'   # ±15-25 menit
ssh toa 'tail -f ~/cadangan/backup.log'
```

**Selesai bila** `verdict: OK` dan `terakhir_ok` bergerak ke hari ini.
Rincian: [runbook cadangan](runbook-cadangan-2026-09-04.md).

---

## B. 🔴 "PROBE toa: layanan produksi TIDAK MENJAWAB"

**Artinya:** tiga kali berturut-turut produksi membalas 5xx atau tidak membalas sama sekali.
Probe sudah membedakan 403 geo-block dari mati, jadi ini bukan alarm palsu geografis.

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://auditor.wolfgang-77.com/
ssh toa 'cat ~/probe/status.json'
```

- **403** → aplikasi hidup; alarmnya sudah lewat, tidak perlu tindakan.
- **502/503/504** → kontainer mati atau tidak sehat. Periksa Railway:

```bash
cd /Users/macads/Truth-of-auditor && railway status --json | head -30
```

Kalau deployment terakhir `CRASHED`/`FAILED`, jangan langsung deploy ulang — baca lognya dulu di
dashboard Railway. ⚠️ Penyebab paling mungkin di aplikasi ini: **`migrate` gagal saat boot**.
Start command menjalankan `collectstatic` + `migrate` SEBELUM gunicorn membuka port, jadi migrasi
yang gagal = port tak pernah terbuka = 502, bukan halaman error.

- **Tidak ada jawaban sama sekali** → kemungkinan di luar aplikasi (Cloudflare/Railway). Periksa
  status penyedia sebelum menyentuh apa pun.

Kalau perlu mundur: [runbook rollback](runbook-rollback-2026-09-04.md).

---

## C. 🔴 "kesehatan toa BAHAYA"

Satu alarm, beberapa sebab. Lihat barisnya:

```bash
ssh toa 'cat ~/kesehatan/status.json; tail -40 ~/kesehatan/kesehatan.log'
```

### C1. Index hilang / INVALID
**Paling mendesak**, karena ia juga **menghentikan cadangan** lewat gerbang J4.

```bash
cd /Users/macads/Truth-of-auditor && railway ssh --service web '/opt/venv/bin/python manage.py periksa_index'
```

⚠️ `TambahIndexAman` **menelan kegagalan build**: migrasi tercatat selesai walau index gagal
dibangun, dan **tidak akan pernah dibangun ulang sendiri**. Jadi ini tidak sembuh dengan menunggu.
Bangun ulang lewat psql dengan `CREATE INDEX CONCURRENTLY` — DDL persisnya ada di docstring
migrasi yang bersangkutan (`transactions/migrations/0008`–`0012`). Sesudahnya `periksa_index`
harus keluar 0.

### C2. Sisa disk
Ambangnya persen, bukan gigabyte. Preseden nyata: volume penuh 2026-07-04 (`pg_wal`) dan
`DiskFull` di `/dev/shm` 2026-08-13. Jangan menghapus dump untuk melegakan disk sebelum
memastikan ada salinan lain yang sah.

### C3. Umur batch per toko
`PERHATIAN` di 3 hari, `BAHAYA` di 7. **Hampir selalu bukan masalah teknis** — lihat §F.

### C4. Tabel referensi KOSONG
`SourceType`, `Toko aktif`, atau `ToleranceProfile "Default"` kosong. Ini diisi **migrasi data**,
bukan fixture. Kosong = tanda basis data di-restore separuh. Aplikasi akan terlihat sehat sampai
rekonsiliasi pertama gagal. **Berhenti dan selidiki restore-nya sebelum ada yang mengunggah apa pun.**

### C5. Sequence mendekati tabrakan
Belum pernah terjadi. Kalau muncul, naikkan tipe kolomnya sebelum mencapai 100%.

---

## D. Deploy

**Sebelum deploy apa pun yang memuat migrasi index:** jalankan DDL-nya lewat psql lebih dulu
(`CREATE`/`DROP INDEX CONCURRENTLY`), di luar 03:00–03:30. Alasannya di §B: `migrate` berjalan
sebelum port terbuka, dan `DROP INDEX` biasa membekukan tabel inti selama transaksi terpanjang
saat itu — termasuk `pg_dump` cadangan.

```bash
cd /Users/macads/Truth-of-auditor && git fetch origin && git merge --ff-only origin/main
railway up --ci --service web --environment production
```

**Kalau CLI berhenti dengan error jaringan:** jangan ulangi. Periksa dulu —
`railway status --json` akan menunjukkan deployment yang sedang `BUILDING`.

**Sesudah naik:**
```bash
railway ssh --service web '/opt/venv/bin/python manage.py periksa_index'   # harus keluar 0
curl -sS -o /dev/null -w '%{http_code}\n' https://auditor.wolfgang-77.com/  # 403 = sehat
```

⚠️ Kalau deploy menyentuh perintah `periksa_*`, perbarui juga checkout `/opt/toa` di VPS — dari
sanalah pemantauan harian menjalankannya. Kalau tidak, pemantauan menghakimi produksi baru dengan
kode lama.

---

## E. Unggahan "berhasil" tapi barisnya tidak muncul

Kelas kegagalan yang **paling sering terjadi di aplikasi ini** — empat kali pada QRIS Flyer.
Vendor mengganti nama kolom, parser tidak mengenalinya, dan unggahan tetap dilaporkan sukses.

Gejala: `Upload` berstatus `parsed`, tapi `rows_parsed` jauh di bawah kebiasaan, atau barisnya
tidak punya tanggal sehingga tak terlihat di halaman mana pun.

⚠️ **Membandingkan tanggal unggah dengan tanggal transaksi akan menyesatkanmu.** Berkas yang
diunggah hari ini berisi data KEMARIN — itu memang cara kerjanya. Bandingkan `rows_parsed`
terhadap kebiasaan berkas sejenis, bukan terhadap tanggal.

⛔ **Jangan mengunggah ulang berkasnya.** Kalau parser sudah diperbaiki, `row_hash` yang dihitung
sekarang berbeda dari yang tersimpan, jadi unggah ulang **menggandakan** harinya alih-alih
memperbaikinya. Pemulihan dilakukan di tempat dari kolom `raw`, mis.
`manage.py perbaiki_gateway_tanpa_tanggal`. Kirim berkas contohnya ke pengembang.

---

## F. Satu toko berhenti berbatch

Cek dulu apakah berkasnya memang diunggah:

```sql
SELECT max(created_at) FROM sources_upload WHERE toko_id = <id>;
```

**Ada unggahan tapi tak ada batch** → rekonsiliasinya belum dijalankan.
**Tidak ada unggahan** → ini masalah orang, bukan sistem.

Unggahan harian dipegang per-orang, dan itu titik gagal nyata: pada 5 September 2026, empat toko
(`bts`, `kigar`, `krn`, `tgs`) berhenti serentak karena satu pengunggah absen dua hari, dan `hks`
berhenti karena hanya satu orang yang memegangnya. Tidak ada yang menambal.

**Tindakannya bukan teknis:** cari tahu siapa yang absen, dan pastikan tiap toko punya lebih dari
satu orang yang bisa mengunggahnya.

---

## G. Rekonsiliasi gagal dengan 524 / timeout

⚠️ **Run yang kena 524 TETAP COMMIT di sisi server.** Pengguna melihat kegagalan padahal batch-nya
benar-benar jadi.

**Jangan langsung menjalankan ulang.** Periksa dulu apakah batch tanggal itu sudah ada — kalau ya,
menjalankan ulang akan ditolak unique constraint, dan menghapus batch yang sebenarnya sah justru
merusak hasil hari-hari berikutnya.

Pemicu paling mungkin bukan pertumbuhan data, melainkan **menumpuk banyak tanggal dalam satu
klik**. Kerjakan per tanggal. Rancangan perbaikan jangka panjang:
[rancangan rekonsiliasi async](rancangan-rekonsiliasi-async-2026-09-04.md).

---

## H. Data terlihat salah — perlu dipulihkan

1. **Jangan menyentuh apa pun dulu.** Tentukan sejak kapan salah.
2. Cadangan tersedia **7 hari terakhir** di `/var/backups/toa/`.
3. ⛔ **Jangan pernah restore ke database `toa`** di VPS — itu pembanding gladi migrasi. Restore uji
   selalu ke database sekali-pakai.
4. Langkah restore lengkap: [runbook cadangan](runbook-cadangan-2026-09-04.md).

**Belum pernah diuji:** memulihkan produksi yang sedang mati, di bawah tekanan waktu. Yang sudah
terbukti hanyalah dump bisa dipulihkan utuh ke database kosong.

---

## I. Alarm tidak berbunyi padahal ada masalah

```bash
ssh toa '~/pemantauan/kirim-alarm.sh --uji'
```

Harus mencetak `Telegram: terkirim (HTTP 200)` **dan** muncul di grup. Kalau tercetak terkirim tapi
tidak muncul, chat id-nya salah sasaran — ulangi lewat `~/pemantauan/pasang-telegram.sh` (pakai
`ssh -t`, kalau tidak ketikan token akan tergema di layar).

⚠️ **Alarm yang selalu merah = alarm yang berhenti dibaca.** Kalau ada temuan yang memang tidak
akan diperbaiki, selesaikan atau bisukan secara sadar — jangan biarkan berbunyi tiap hari sampai
semua orang mengabaikannya, termasuk saat ada yang sungguhan.

---

## J. Kredensial bocor

Anggap **sudah dipakai orang** sampai terbukti sebaliknya — Postgres tidak mencatat koneksi secara
default, jadi biasanya tidak akan pernah bisa dipastikan. Karena itu obatnya rotasi, bukan
investigasi.

[runbook rotasi kunci](runbook-rotasi-kunci-2026-09-04.md). ⚠️ Urutannya mengikat: setelah
merotasi `DATABASE_URL`, **wajib** memperbarui `~/.pgpass` di VPS lalu menjalankan satu cadangan
manual sampai `verdict: OK` — kalau tidak, cadangan mati senyap di jam 03:00.

⛔ `SECRET_KEY_FALLBACKS` berisi kunci lama **dilarang**: itu membuat kunci yang bocor tetap
berlaku dan membatalkan seluruh rotasi.

---

## Yang belum pernah diuji, dan sebaiknya kamu tahu

- Memulihkan **produksi** dari cadangan di bawah tekanan (yang teruji: restore ke DB kosong).
- **Migrasi mundur** apa pun di produksi.
- Rotasi kredensial ujung-ke-ujung.
- Perilaku sistem saat VPS `toa` hilang — di sanalah cadangan **dan** pemantauan tinggal
  bersamaan, jadi keduanya hilang serentak. Ini bukan cadangan offsite.
