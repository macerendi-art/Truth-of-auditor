# Runbook — Volume media produksi (A2, 2026-09-04)

Status: **bagian kode SELESAI** (env `MEDIA_ROOT` siap, teruji). **Bagian infrastruktur
(memasang volume Railway) TERTAHAN PADA PEMILIK** — butir A2 baru boleh disebut selesai
setelah volume benar-benar terpasang di dashboard/CLI Railway dan env `MEDIA_ROOT` di-set
di service `web`. Sumber tugas: `docs/daftar-perbaikan-2026-09-03.md` butir A2.

## Temuan penting yang mengubah bentuk pekerjaan ini — baca dulu

Rumusan tugas berangkat dari premis "setiap deploy menghapus seluruh berkas unggahan"
(`sources/models.py:135` `Upload.file = FileField(upload_to="uploads/%Y/%m/")` di atas
`MEDIA_ROOT` yang tanpa volume). Investigasi untuk runbook ini menemukan sesuatu yang
lebih mendasar: **`Upload.file` TIDAK PERNAH diisi oleh kode apa pun, hari ini maupun di
seluruh riwayat git repo ini.**

Bukti, empat lapis independen:

1. **`sources/services.py` `_persist_rows`** — satu-satunya tempat `Upload.objects.create(...)`
   dipanggil di jalur produksi (web upload maupun `manage.py ingest`) — tidak pernah
   menyertakan argumen `file=`.
2. **`web/views.py` `upload()`** — alur commit menyimpan berkas ke `staging/<nama>` lewat
   `default_storage.save(...)` untuk keperluan parsing (`_analyze_file`), lalu di blok
   `finally` pada baris commit: `if default_storage.exists(path_rel): default_storage.delete(path_rel)`
   — berkas **dihapus dalam request yang sama**, terlepas dari sukses/gagal ingest.
3. **Riwayat git** — `git log -p --follow -- sources/services.py` tidak pernah menunjukkan
   `file=` pada pembuatan `Upload`; `FileField` sendiri muncul persis dua kali di seluruh
   sejarah `sources/models.py`: ditambahkan di *initial commit* (`58a5c04`) dan tidak pernah
   disentuh lagi. Field ini scaffold yang tidak pernah disambungkan.
4. **Pengukuran langsung** — lihat bagian "Konsekuensi berkas yang sudah hilang" di bawah:
   **0 dari 34** baris `Upload` di `db.sqlite3` lokal punya nilai `file` terisi. Bukan
   "menunjuk ke berkas yang hilang" — `file` memang kosong string sejak baris itu dibuat.
   Satu-satunya pemakaian `up.file` di kode selain model adalah **defensif** —
   `web/admin_views.py` tiga kali memanggil `if up.file: up.file.delete(save=False)` saat
   menghapus Upload, jaga-jaga seandainya field itu suatu hari terisi, bukan bukti bahwa ia
   pernah terisi.

**Konsekuensinya bagi rumusan tugas:** "setiap deploy menghapus seluruh berkas unggahan"
tidak akurat sebagai deskripsi perilaku HARI INI — tidak ada berkas asli yang bertahan
lebih lama dari satu siklus request analyze→commit untuk hilang lewat deploy sekalipun.
Yang sebenarnya bisa hilang lewat redeploy (dan sudah sejak awal transien, bukan akibat
tanpa-volume) hanyalah berkas `staging/` yang sedang di tengah alur analyze-tapi-belum-commit
saat kontainer di-restart — kerugian kecil, pemulihannya cukup unggah ulang.

Ini **tidak berarti pekerjaan A2 sia-sia** — dua alasan ia tetap bernilai:

- `Upload.file` + migrasinya + kode defensif `admin_views.py` adalah bukti **niat** desain:
  suatu hari berkas asli dimaksudkan tersimpan per-Upload (menjawab pertanyaan audit
  "berkas mana yang melahirkan baris ini?" yang disebut rumusan tugas). Menyiapkan
  `MEDIA_ROOT` agar tahan-deploy SEBELUM fitur itu benar-benar disambungkan menghindari
  migrasi volume kedua nanti.
- Kesiapan kode (env-configurable `MEDIA_ROOT`) adalah pekerjaan murah dan tanpa risiko
  (default identik, dibuktikan tes) — mengerjakannya sekarang tidak merugikan apa pun.

**Yang HARUS diputuskan pemilik terpisah dari A2 ini:** apakah menyambungkan
`Upload.file` (mengisinya sungguhan di `_persist_rows`, tidak menghapus `staging/<nama>`
melainkan memindahkannya ke lokasi permanen) adalah pekerjaan yang diinginkan. Itu
mengubah `web/views.py` dan `sources/services.py` — berkas yang SENGAJA di luar cakupan
tugas ini (lihat batasan berkas di brief). **Tidak dikerjakan di sini.**

## Apa yang dikerjakan di sini

1. **`truth_auditor/settings.py`** — `MEDIA_ROOT` kini bisa diatur lewat env `MEDIA_ROOT`,
   dengan default **persis** perilaku lama:
   ```python
   MEDIA_ROOT = Path(os.environ.get('MEDIA_ROOT') or (BASE_DIR / 'media'))
   ```
   `or` (bukan `.get(key, default)` polos) sengaja dipakai — Railway bisa menyuntik
   variabel env sebagai string kosong, bukan cuma tak-ada, dan string kosong harus tetap
   jatuh ke default lama, bukan jadi `MEDIA_ROOT = Path('')` (= direktori kerja proses).
2. **`core/tests_media_root.py`** (baru) — empat tes:
   - tanpa env → `MEDIA_ROOT == BASE_DIR / 'media'` persis (subprocess bersih, pola yang
     sama dengan `core/tests_settings_guard.py` — modul settings benar-benar diimpor
     ulang dari env, bukan ekspresi yang dievaluasi ulang di tes);
   - dengan env `MEDIA_ROOT=<path>` → path itu yang dipakai;
   - env `MEDIA_ROOT=""` (string kosong) → tetap jatuh ke default lama;
   - `FileField` (`Upload.file`) sungguhan menulis DI BAWAH `MEDIA_ROOT` kustom
     (`override_settings` + `ContentFile`) — dengan catatan eksplisit di tes bahwa
     produksi hari ini tidak pernah mengisi `file=`, supaya pembaca berikutnya tidak
     salah simpul bahwa ini sudah jalur aktif.
3. **`railway.json` / `Procfile` — TIDAK diubah.** Lihat riset di bawah: deklarasi volume
   tidak didukung format ini.

Modul tes terkait dijalankan dan hijau (lihat bagian "Bukti" di akhir dokumen).

## Apakah `railway.json` mendukung deklarasi volume?

**Tidak.** Diperiksa terhadap skema resmi (`railway.json` → `$schema`:
`https://railway.com/railway.schema.json`, redirect ke
`https://backboard.railway.app/railway.schema.json`):

- Properti top-level: `$schema`, `build`, `deploy`, `environments`.
- Properti di bawah `build`: `builder`, `watchPatterns`, `buildCommand`, `dockerfilePath`,
  `nixpacksConfigPath`, `nixpacksPlan`, `nixpacksVersion`, `railpackVersion`.
- Properti di bawah `deploy`: `startCommand`, `preDeployCommand`, `preDeployTimeoutSeconds`,
  `numReplicas`, `healthcheckPath`, `healthcheckTimeout`, `sleepApplication`, `runtime`,
  `registryCredentials`, `restartPolicyType`, `restartPolicyMaxRetries`, `cronSchedule`,
  `region`, `multiRegionConfig`, `limitOverride`, **`requiredMountPath`**,
  `overlapSeconds`, `drainingSeconds`, `ipv6EgressEnabled`.
- **Tidak ada** properti untuk mendeklarasikan/membuat volume atau menentukan ukurannya.

Satu kunci yang HAMPIR relevan — `deploy.requiredMountPath` — memang ada di skema, tapi
deskripsinya di skema hanya "Required mount path for the deployment", tanpa dokumentasi
resmi lain yang ditemukan (halaman panduan volume Railway, halaman config-as-code, dan
pencarian umum tidak menyebutnya sama sekali). Namanya menyiratkan "tolak deploy kalau
tidak ada volume terpasang di path ini" — **tapi semantik pastinya TIDAK TERVERIFIKASI**.
**Sengaja TIDAK ditambahkan ke `railway.json` di sini**: kalau tebakan itu benar, memasang
kunci ini SEBELUM volume terpasang akan menggagalkan deploy berikutnya pada aplikasi
finansial yang live — risiko yang tidak sepadan dengan manfaat sebuah guard opsional.
Dokumentasi resmi tegas: volume **dibuat dan dipasang lewat dashboard (Command Palette
`⌘K` atau klik-kanan kanvas project, lalu atur mount path di panel service) atau CLI**
(`railway volume add` / `railway volume list` / `railway volume delete`), tidak pernah
lewat config-as-code.

**Karena `railway.json`/`Procfile` tidak disentuh, `core.tests_start_command` (penjaga
kembar kedua berkas itu) tidak relevan untuk perubahan ini** — tidak dijalankan ulang
sebagai bagian definisi-selesai, tapi tetap hijau (tidak ada yang berubah untuknya).

## Langkah pemilik — memasang volume

1. **Buat volume di dashboard Railway**: project → service `web` → Command Palette
   (`⌘K`) atau klik-kanan kanvas → "Create Volume" (atau `railway volume add` lewat CLI,
   cek `railway volume add --help` untuk flag persis di versi CLI yang terpasang —
   dokumentasi publik tidak merinci flag-nya).
2. **Mount path yang disarankan: `/data`** (langsung, BUKAN `/data/media`). Alasan: dengan
   `MEDIA_ROOT` di-set persis ke root mount, tidak ada langkah `mkdir -p` tambahan yang
   perlu terjadi saat boot — direktori mount SUDAH ada begitu volume terpasang. Kalau
   pemilik tetap memilih subdirektori (mis. volume dipakai bersama untuk keperluan lain),
   tambahkan langkah `mkdir -p $MEDIA_ROOT` eksplisit ke `startCommand`
   (`railway.json`+`Procfile`, KEDUANYA — lihat aturan kembar di atas) SEBELUM
   `collectstatic`, karena Django tidak membuat `MEDIA_ROOT` sendiri.
3. **Set env di service `web`**: `MEDIA_ROOT=/data` (Railway dashboard → Variables, atau
   `railway variables --set MEDIA_ROOT=/data --service web --environment production`).
4. **Deploy** (di luar cakupan sesi ini — keputusan pemilik dengan gerbang izin eksplisit,
   lihat aturan proyek). Setelah live, verifikasi:
   - `railway ssh -s web "python manage.py shell -c \"from django.conf import settings; print(settings.MEDIA_ROOT)\""`
     harus mencetak `/data`.
   - `railway ssh -s web "ls -la /data"` menunjukkan direktori mount, bukan error "no such
     file or directory".
   - Restart/redeploy sekali lagi lalu cek berkas yang sempat ditulis (kalau ada) masih
     ada — bukti volume benar-benar independen dari siklus hidup kontainer.

## Cara memindahkan berkas yang ADA sekarang

Berdasarkan temuan di atas: **tidak ada berkas asli (`Upload.file`) untuk dipindahkan** —
`uploads/%Y/%m/` di `MEDIA_ROOT` produksi kemungkinan besar kosong, persis seperti di
lokal (lihat pengukuran di bawah). Yang secara nyata menghuni `MEDIA_ROOT` hari ini:

- **`staging/`** — berkas mentah antara langkah "analyze" (preview + deteksi parser) dan
  "commit" (ingest sungguhan). Transien by design: dihapus di akhir `commit` (sukses
  ATAUPUN gagal — blok `finally` di `web/views.py`), dan yang yatim (ditinggal tanpa commit,
  mis. tab browser ditutup) disapu `_sweep_staging()` pada request analyze berikutnya kalau
  lebih tua dari `_STAGING_TTL = 24 jam`. **Tidak perlu dipindahkan** — kalau ada isinya
  saat volume dipasang, biarkan; ia akan tersapu atau terpakai secara alami dalam ≤24 jam.
- **`kesehatan.json`** (dari `manage.py periksa_kesehatan`, lihat CLAUDE.md bagian
  "Performa v1.23.0") — **PERINGATAN**: berkas ini di-hardcode
  `Path(settings.BASE_DIR) / "media" / "kesehatan.json"`
  (`core/management/commands/periksa_kesehatan.py` baris 405), **BUKAN**
  `settings.MEDIA_ROOT`. Artinya setelah `MEDIA_ROOT` dipindah ke `/data`, berkas ini
  **TETAP** di disk kontainer (`BASE_DIR/media/kesehatan.json`) dan **TETAP hilang tiap
  deploy** — divergensi nyata, dicatat di sini apa adanya, TIDAK diperbaiki dalam pekerjaan
  ini (berkas itu di luar daftar berkas yang boleh disentuh). Konsekuensinya kecil:
  `kesehatan.json` cuma potret laju-tumbuh untuk perbandingan tren
  (`--dibanding-dgn media/kesehatan.json`), bukan data transaksional — hilang berarti
  hilang satu titik pembanding historis, bukan kehilangan data.
- Kalau di produksi ternyata ADA isi di bawah `uploads/` (mis. hasil percobaan lama
  menyalakan jalur `file=` yang tidak ditemukan investigasi ini, atau perubahan kode di
  masa depan setelah runbook ini ditulis) — pindahkan dengan `rsync` biasa SEBELUM
  memutar env ke volume baru:
  ```bash
  railway ssh -s web "tar -C /app/media -czf - uploads" > uploads-lama.tar.gz
  # setelah volume terpasang & MEDIA_ROOT=/data aktif:
  railway ssh -s web "tar -C /data -xzf -" < uploads-lama.tar.gz
  ```
  lalu verifikasi dengan skrip deteksi di bawah SEBELUM dan SESUDAH — jumlah `Upload`
  ber-`file` valid harus sama persis.

### Skrip deteksi "`Upload` yang `file`-nya tak ada lagi di disk"

Berguna sekarang (untuk memastikan pemahaman di atas), dan tetap berguna nanti kalau
`Upload.file` suatu hari benar-benar disambungkan:

```bash
python manage.py shell -c "
from sources.models import Upload
import os
from django.conf import settings
total = Upload.objects.count()
kosong = hilang = ada = 0
for u in Upload.objects.all().iterator():
    name = u.file.name if u.file else ''
    if not name:
        kosong += 1
        continue
    if os.path.exists(os.path.join(settings.MEDIA_ROOT, name)):
        ada += 1
    else:
        hilang += 1
        print('HILANG:', u.pk, name, u.original_name)
print(f'total={total} kosong(field-blank)={kosong} ada={ada} hilang(field-terisi-tapi-berkas-tak-ada)={hilang}')
"
```

Baris `kosong` (field `file` blank) dan `hilang` (field terisi tapi berkas benar-benar
tak ada di disk) SENGAJA dipisah — keduanya cerita berbeda: `kosong` adalah keadaan
NORMAL untuk field yang tidak pernah dipakai (lihat temuan di atas), `hilang` adalah
tanda bahaya SUNGGUHAN (berkas pernah ada, sekarang lenyap — persis skenario "deploy
menghapus volume" yang dikhawatirkan rumusan tugas).

## Konsekuensi berkas yang SUDAH hilang

**Diukur terhadap `db.sqlite3` lokal di worktree ini** (satu-satunya salinan yang
tersedia untuk sesi ini — lihat catatan jujur di bawah soal keterbatasannya):

```
total uploads = 34
present = 0
missing = 0
empty_name (field `file` blank) = 34
```

**Seluruh 34 baris `Upload` di database lokal punya `file` KOSONG** — nol yang
"hilang" dalam arti pernah-ada-sekarang-tak-ada; semuanya memang tidak pernah diisi,
konsisten dengan temuan kode di atas.

**Catatan jujur soal keterbatasan pengukuran ini:**

- `db.sqlite3` di worktree ini adalah **salinan dev lokal** bertanggal 8 Juli 2026 (jauh
  di belakang skema kode saat ini) — `python manage.py migrate` dijalankan lebih dulu
  di salinan ini (14 migrasi tertunda, termasuk `sources.0008`–`0014`) supaya bisa
  dibaca ORM sama sekali. Ini database gitignored, disposable, bukan cadangan/salinan
  produksi resmi — legal untuk dimigrasikan maju karena tidak dibagi siapa pun.
- **34 baris jauh lebih kecil dari skala produksi** (CLAUDE.md: produksi ±10,3 juta baris
  `Transaction` per 04-09-2026, tumbuh ±185 rb baris/hari). Ini bukan sampel representatif
  — ini cuma cukup untuk MEMBUKTIKAN pola kode (field selalu kosong), bukan untuk
  mengklaim distribusi produksi.
- **Angka produksi BELUM diukur** dan sesi ini tidak diberi akses menjalankan apa pun ke
  produksi (dilarang eksplisit di brief: "Jangan menjalankan `railway` apa pun"). Karena
  temuan di atas adalah soal KODE (tidak ada jalur yang pernah mengisi `Upload.file`,
  dibuktikan lewat `git log` atas SELURUH riwayat repo, bukan cuma database titik-waktu),
  kesimpulannya berlaku untuk produksi JUGA selama produksi menjalankan kode dari repo
  yang sama (tidak ada hotfix tak-tercatat yang menyimpang) — tapi pemilik yang berhak
  memverifikasi ini langsung di produksi bila ingin kepastian mutlak, dengan skrip deteksi
  di atas lewat `railway ssh -s web "python manage.py shell -c \"...\""`.

## Ukuran volume yang disarankan

Berangkat dari temuan di atas, kebutuhan RIIL hari ini kecil — tidak ada retensi berkas
asli untuk dijaga. Yang perlu ditampung `MEDIA_ROOT` hari ini murni `staging/` (transien,
disapu ≤24 jam) plus (di luar `MEDIA_ROOT`, TIDAK relevan untuk volume ini)
`kesehatan.json`.

**Batas atas yang bisa diturunkan dari kode, bukan ditebak:**
`web/views.py` `_REQ_MAX_BYTES = 300 * 1024 * 1024` (300MB) adalah batas keras SATU
permintaan "analyze" (`if sum(f.size for f in uploaded) > _REQ_MAX_BYTES: … error`), dan
`_ZIP_MAX_BYTES = 200 * 1024 * 1024` untuk isi zip. Jadi `staging/` di titik waktu mana pun
dibatasi oleh **(jumlah batch analyze-belum-commit yang aktif bersamaan) × 300MB** — dalam
praktik jauh di bawah itu karena commit biasanya menyusul analyze dalam hitungan detik–menit
pada aplikasi audit internal dengan pemakai terbatas (RBAC per-Toko + `IPAllowlistMiddleware`
untuk auditor/supervisor — bukan aplikasi publik dengan lalu lintas tak terduga).

**Rekomendasi: mulai dari volume kecil, 1–2 GB.** Alasan memilih ANGKA INI bukan menebak
bulat tapi memberi headroom besar di atas kebutuhan terukur (`staging/` lokal hari ini
132KB/33 berkas — walau berkas itu sendiri artefak uji sintetis, bukan ekspor nyata, jadi
tidak dipakai sebagai dasar proyeksi, cuma bukti bahwa direktori ini memang kecil dan
tersapu teratur) sekaligus di atas kasus terburuk realistis (beberapa MB–puluhan MB kalau
dua-tiga auditor kebetulan menganalisis file besar bersamaan). Railway men-charge volume
**$0.15/GB/bulan** (tidak ada minimum tercatat di dokumentasi) dan **resize LIVE tanpa
downtime** (kecuali volume benar-benar penuh 100%, lihat bagian berikutnya) — jadi
under-provisioning di awal murah untuk diperbaiki, tidak perlu menebak angka besar
"untuk jaga-jaga".

**Kalau `Upload.file` suatu hari benar-benar disambungkan** (keputusan terpisah, lihat di
atas), ukuran ini HARUS dihitung ulang dengan basis nyata, bukan proyeksi di sini:
`ukuran_volume ≈ (rata-rata_byte_per_berkas_ekspor_nyata) × (unggahan_per_hari_nyata) ×
(hari_retensi_yang_diinginkan) + margin`. CLAUDE.md mencatat **±185 rb BARIS/hari**
produksi — itu ukuran DATABASE (baris `Transaction`), **BUKAN** jumlah berkas atau byte
berkas, dan TIDAK bisa dikonversi langsung tanpa tahu rata-rata baris-per-file dan
byte-per-file dari ekspor NYATA (xlsx/csv vendor bank/panel/gateway) — data itu tidak
tersedia di worktree ini (satu-satunya berkas sampel yang ada, `media/staging/*.csv`
46–132 byte, adalah artefak uji manual, bukan ekspor sungguhan, sehingga sengaja TIDAK
dipakai sebagai dasar). Pemilik yang menyambungkan fitur itu harus mengukur ulang dari
beberapa hari unggahan produksi nyata.

## Apa yang terjadi kalau volume penuh

Dua preseden `DiskFull` NYATA di proyek ini — keduanya Postgres, BUKAN media, tapi
pelajarannya tentang "disk penuh mematikan aplikasi dengan cara mengejutkan, bukan cuma
melambat" berlaku umum:

- **2026-07-04**: volume Postgres 500MB (plan Hobby) penuh oleh `pg_wal` (WAL run besar,
  `max_wal_size=1GB` mustahil untuk volume 500MB). Dipulihkan tanpa kehilangan data
  (`pg_wal` dipindah sementara ke disk ephemeral, lalu `max_wal_size=96MB` dipasang
  permanen) — lihat `docs/laporan-trial-oke25-2026-07-05.md` baris 109–111.
- **2026-08-13**: insiden `DiskFull` `/dev/shm` memaksa `work_mem` dikembalikan ke bawaan
  di produksi (CLAUDE.md bagian "Performa v1.18.0" dan
  `docs/rencana-migrasi-contabo-2026-08-31.md` baris ~57) — setelan `ALTER SYSTEM` v1.18.0
  ternyata tidak seluruhnya bertahan ke instance Postgres yang berjalan sekarang.

**Untuk volume MEDIA (bukan Postgres) yang penuh, blast radius-nya spesifik dan lebih
kecil**, karena tidak menyentuh database sama sekali:

- `web/views.py` `_analyze_file` memanggil `default_storage.save(f"staging/{name}", fileobj)`
  — kalau disk penuh, panggilan ini melempar `OSError` (disk penuh) yang **tidak
  ditangkap** di jalur analyze. Akibatnya: request "analyze" (langkah PERTAMA upload,
  sebelum commit) gagal dengan error 500 ke pengguna. **Tidak ada tulisan ke database**
  yang gagal setengah jalan — `_persist_rows` (yang menulis `Upload`+`Transaction`, dibalut
  `transaction.atomic()`) belum pernah dipanggil pada tahap ini, jadi kegagalan di sini
  murni gagal-cepat, bukan korupsi data.
- Kalau volume penuh justru terjadi DI TENGAH commit (setelah analyze, saat `ingest()`
  membaca file dari `staging/` untuk diparse) — pembacaan file yang SUDAH ada di disk
  tidak butuh ruang kosong tambahan (baca, bukan tulis), jadi ingest kemungkinan tetap
  berhasil; yang gagal hanyalah penghapusan `staging/<nama>` di blok `finally` bila disk
  penuh membuat operasi filesystem lain ikut macet — laporan Django biasanya masih
  mencatat error ini di log tanpa menjatuhkan seluruh proses gunicorn.
- Railway sendiri: volume 100% penuh memicu **offline resize** (restart service, downtime
  singkat) alih-alih live-resize — jadi kalaupun pemilik lengah dan volume kehabisan ruang,
  pemulihannya adalah restart terkontrol, bukan kehilangan data (volume tetap ada, cuma
  butuh diperbesar).
- Karena kebutuhan riil hari ini kecil (lihat bagian ukuran di atas) dan `kesehatan.json`
  TIDAK ikut volume ini (tetap di disk kontainer, lihat divergensi di atas), risiko
  volume-media-penuh jauh lebih kecil dari dua insiden Postgres di atas — tapi tetap layak
  dipantau (mis. `df -h /data` lewat `railway ssh`, atau metrik volume di dashboard
  Railway) terutama kalau/ketika `Upload.file` disambungkan sungguhan di masa depan.

## Definisi selesai — status per butir

| Butir | Status |
|---|---|
| (a) `MEDIA_ROOT` bisa diatur env, default tak berubah, dibuktikan tes yang gagal tanpa perubahan | **SELESAI** — `core/tests_media_root.py`, 4 tes, dikonfirmasi merah tanpa perubahan (`git stash` percobaan) |
| (b) Modul tes terkait hijau | **SELESAI** — `core` (semua modul), `web.tests_upload`, `sources` (577 tes) + seluruh `web` (1.288 tes) dijalankan, 0 gagal. `core.tests_start_command` tidak tersentuh (railway.json/Procfile tidak diubah) |
| (c) Runbook lengkap dengan langkah pemilik eksplisit | **SELESAI** — dokumen ini |
| (d) Laporan menyatakan A2 tertahan pada pemilik | **SELESAI** — lihat status di puncak dokumen ini dan laporan sesi |

**A2 TERTAHAN PADA PEMILIK** sampai: (1) volume Railway benar-benar dipasang di service
`web`, (2) env `MEDIA_ROOT` di-set mengarah ke mount path itu, (3) deploy dijalankan
(keputusan terpisah, di luar sesi ini), (4) pemilik memutuskan — terpisah dari A2 —
apakah `Upload.file` akan disambungkan sungguhan, karena TANPA keputusan itu volume yang
terpasang tidak melindungi berkas apa pun yang benar-benar ada hari ini.

## Bukti (dijalankan 2026-09-04, worktree ini)

- `core/tests_media_root.py` — 4/4 tes lulus (`OK`).
- Uji-negatif: `git stash` sementara atas `truth_auditor/settings.py` (mengembalikan
  `MEDIA_ROOT = BASE_DIR / 'media'` polos) → `test_dengan_env_media_root_dipakai` GAGAL
  seperti diharapkan (`AssertionError` membandingkan path lama vs target env) — tes
  benar-benar menjaga perubahan, bukan tautologi. `git stash pop` mengembalikan perubahan.
- `python manage.py test core web.tests_upload sources` → **577 tes, 0 gagal** (4 skip,
  tak terkait perubahan ini).
- `python manage.py test web` (seluruh app, bukan cuma `tests_upload`) → **1.288 tes,
  0 gagal** (1 skip). Satu traceback `Exception: db hiccup` di log adalah efek-samping
  sebuah tes yang SENGAJA mem-mock kegagalan query (`web.middleware` fail-open IP
  allowlist), bukan kegagalan sungguhan — status akhir suite tetap `OK`.
- Pengukuran `Upload.file` lokal: lihat bagian "Konsekuensi berkas yang sudah hilang" di
  atas untuk angka dan metodenya.
- Riset schema `railway.json`: lihat bagian "Apakah `railway.json` mendukung deklarasi
  volume?" di atas untuk daftar properti dan sumbernya.
