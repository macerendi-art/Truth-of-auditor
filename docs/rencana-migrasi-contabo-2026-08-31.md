# Rencana Migrasi: Railway → Contabo VPS (v2.1)

**Disusun:** 31 Agustus 2026 · **Direvisi total:** 31 Agustus 2026 setelah 7 audit paralel
**Ukuran mesin ditetapkan ulang:** 1 September 2026 setelah 8 riset paralel + 2 skeptik adversarial
**Target semula (rekomendasi):** Cloud VPS 12 · 12 vCPU · 48 GB · 400+800 GB SSD
**MESIN YANG BENAR-BENAR DIBELI (01-09-2026):** Contabo **Cloud VPS 8 (2026)** · **8 vCPU ·
24 GB RAM · 300 GB SSD** · Singapura (host 29421) · Ubuntu 24.04 · termin **1 bulan**
· €24,25/bln · IP `217.216.39.105` · VNC `194.233.66.221:63089` · Auto Backup **belum aktif**

> **Turun dari VPS 16 adalah hasil pengukuran, bukan penghematan.** Setelan Postgres FASE 1
> SENGAJA tidak berubah satu pun — semuanya paritas produksi (`shared_buffers` 6GB,
> `effective_cache_size` 16GB, `work_mem` 4MB), puncak RAM steady-state ±8 GB. Satu-satunya
> angka berskala-RAM ada di **profil restore FASE 2**, dan itu justru cacat laten yang v2
> bawa dari VPS 16 — lihat "Penetapan ukuran" di bawah.
**Prinsip:** produksi tidak tersentuh sampai FASE 4. Migrasi ini memindahkan **MESIN** — bukan
menyetel ulang database, bukan menukar versi pustaka, bukan mengubah perilaku aplikasi.

> **v1 dokumen ini TIDAK BOLEH dipakai.** Audit menemukan 20+ cacat, empat di antaranya
> merusak database produksi atau mematikan geo-block secara senyap. Ringkasannya di bagian
> "Apa yang berubah dari v1".

---

## Fakta sumber — DIUKUR 31-08-2026, bukan disalin dari dokumen

Setiap angka di bawah dibaca langsung dari produksi. **Beberapa mengoreksi CLAUDE.md.**

| | Nilai terukur | Catatan |
|---|---|---|
| Python | **3.11.10** | v1 menulis 3.11.15 (itu venv lokal, bukan produksi) |
| Django | **5.2.17** | v1 menulis 5.2.15 |
| OS kontainer | **Ubuntu 24.04.2 LTS** | target VPS 24.04 = benar |
| PostgreSQL | **18.6** (PGDG) | |
| Encoding / collate | **UTF8 / en_US.utf8 / en_US.utf8** | VPS WAJIB sama persis |
| Ekstensi | `plpgsql` + `pg_stat_statements` | v1 hanya menyebut plpgsql |
| DB / user | `railway` / `postgres` | |
| Tabel publik | 29 | |
| Ukuran | **18 GB · 8.839.002 baris · ±11 GB/bln** · ±185 rb baris/hari | diukur 01-09; angka lama "17 GB / 9,37 jt / +5 GB/bln" tidak tereproduksi — lihat "Penetapan ukuran" |
| Zona waktu | jam OS **UTC**; Django memaksa `TZ=Asia/Jakarta` | lihat jebakan J11 |
| DEBUG produksi | `False` (terkonfirmasi) | |
| Index `transactions_transaction` | **20 index, semua `indisvalid=true`** | wajib dicek ulang sebelum dump — lihat J4 |

### Setelan Postgres produksi — **CLAUDE.md sudah melenceng, ini yang benar**

| Setelan | CLAUDE.md | v1 rencana | **PRODUKSI** |
|---|---|---|---|
| `work_mem` | 32MB ❌ | 32MB ❌ | **4MB** |
| `shared_buffers` | "masih 128MB" ❌ | 16GB ❌ | **6GB** |
| `effective_cache_size` | 16GB ✅ | 48GB ❌ | **16GB** |
| `max_parallel_workers_per_gather` | 2 ✅ | 4 ❌ | **2** |
| `jit_above_cost` | 1e6 ✅ | *dihilangkan* ❌ | **1e6** |
| `max_wal_size` | 2GB ✅ | 4GB ❌ | **2GB** |
| `random_page_cost` | 1.1 ✅ | 1.1 ✅ | **1.1** |
| `dynamic_shared_memory_type` | — | — | **mmap** (perbaikan insiden /dev/shm) |
| `max_connections` | 100 ❌ | 200 | **500** (200 di VPS = sengaja, app butuh 32) |

`work_mem=4MB` membenarkan catatan sesi 13-08-2026 (dikembalikan setelah `DiskFull`
`/dev/shm`), bukan CLAUDE.md. **Sebelum FASE 1, baca ulang setelan produksi — jangan
percaya tabel ini pun.**

⚠️ **Dan satu lapis lebih dalam (diukur 01-09):** `work_mem=4MB` serta
`maintenance_work_mem=64MB` di produksi keduanya `source=default` — **bukan hasil tuning**.
Artinya `ALTER SYSTEM` v1.18.0 tidak seluruhnya selamat ke instance PG 18.6 yang berjalan
sekarang. Konsekuensi untuk VPS: **tulis setiap parameter secara EKSPLISIT**; "paritas" yang
mengandalkan default akan mereproduksi dua kecelakaan, bukan dua keputusan.

```bash
railway ssh -s Postgres "psql -U postgres -d railway -Atc \"SELECT name||' = '||setting||coalesce(' '||unit,'') FROM pg_settings WHERE source NOT IN ('default','override') ORDER BY name;\""
```

---

## Penetapan ukuran mesin (v2.1 — diukur 01-09-2026)

v2 menargetkan Cloud VPS 16. Itu pilihan aman **sebelum ada pengukuran**. Pengukurannya
sekarang ada — 8 riset paralel + 2 skeptik adversarial — dan hasilnya membalik pilihan
tiernya, bukan isi runbook-nya.

### ⚠️ Mesin nyata ≠ mesin yang direkomendasikan — konsekuensinya dihitung, bukan ditaksir

Yang dibeli adalah **Cloud VPS 8**, bukan VPS 12 + 800 GB. Dua sumbu meleset, dan keduanya
punya akibat yang berbeda derajatnya.

**CPU dan RAM: layak, tanpa drama.** Beban terukur produksi 0,23 core dan RAM rigid ±8 GB,
jadi 8 vCPU tetap ±35× berlebih dan 24 GB tetap 3× di atas kebutuhan proses. 24 GB juga
persis **batas bawah** yang ditetapkan analisis ("di bawah 24 GB tidak layak, karena
`shared_buffers` 6 GB paritas harus diturunkan — dan itu berarti menyetel ulang database di
tengah pemindahan mesin"). Paritas tetap utuh. Yang hilang bukan kapasitas melainkan
**cadangan**: page cache tersedia ±16 GB atas DB 18 GB (cakupan ~89%, produksi hari ini 94%),
jadi kinerja awal sebanding tetapi tidak ada ruang tumbuh.

**Disk: inilah yang benar-benar meleset.** Pada laju terukur 11 GB/bln:

| Disk | Maintenance berhenti mungkin | Disk mentok |
|---|---|---|
| **300 GB (terbeli)** | **bulan ~9** | bulan ~16 |
| 500 GB (+ Storage Extension 200 GB) | bulan ~17 | bulan ~29 |
| 800 GB (rekomendasi semula) | bulan ~29 | bulan ~48 |

"Maintenance berhenti" bukan ketidaknyamanan: begitu `pg_repack`/`VACUUM FULL` dan uji-restore
berdampingan tidak lagi muat, dua prosedur yang diwajibkan FASE 5 berhenti bisa dijalankan
**sementara disknya sendiri masih terlihat lapang**. Itu kegagalan yang datang tanpa alarm.

**Yang wajib dilakukan sebelum FASE 4 (cutover), bukan sesudahnya:** tambah **Storage
Extension +200 GB** (±€2,45/bln, bisa dari Customer Panel di tengah kontrak, **tanpa reinstall
dan tanpa ganti IP**) sehingga disk menjadi 500 GB. Biayanya menjadikan mesin ini ±€26,70/bln —
masih jauh di bawah VPS 12 + 800 GB (€45,05), dan untuk beban yang sudah diukur itu
proporsional. **FASE 0–3 boleh berjalan penuh di 300 GB**: puncak sementara saat restore
percobaan hanya ±90 GB (`toa_fase3` 18 + `toa_new` 18 + direktori dump ±7 + WAL profil restore
+ OS/venv 15), jadi tidak ada alasan menunda pekerjaan sambil menunggu keputusan disk.

**Penyesuaian teknis yang mengikat karena RAM 24 GB, bukan 48 GB:** profil restore FASE 2/4
memakai **`pg_restore --jobs=4`**, bukan 8. Aritmetikanya: tiap job adalah sesi terpisah yang
berhak atas `maintenance_work_mem` penuh, jadi 8 × 2 GB = 16 GB di atas `shared_buffers` 6 GB
dan OS ±2 GB = **24 GB dari 24 GB** — nol margin, dan OOM killer menghentikan restore di
tengah. Dengan `-j 4`: 8 GB, total 16 GB, sisa 8 GB untuk page cache. `vacuumdb` ikut turun ke
`-j 4` (8 core). Konsekuensinya restore lebih lama — **ukur di FASE 2 dan pakai angka itu**,
jangan angka dokumen.

### Vonis

**Cloud VPS 12 + opsi disk 800 GB SSD.** VPS 16 tidak dibutuhkan, dan bila diambil justru
merugikan.

| Sumbu | Terukur di produksi | VPS 12 | Kesimpulan |
|---|---|---|---|
| CPU | **0,23 core** rata-rata sepanjang hari kerja penuh; throttle 2/24.367 (web) dan 0/101.788 (PG) pada kuota 24 vCPU | 12 vCPU | ±50× berlebih. Jumlah core **tidak boleh** masuk pertimbangan tier |
| RAM rigid | **±8 GB** — PG anon 54 MB + `shared_buffers` 6,62 GB + puncak gunicorn 1,36 GB | 48 GB | 6× berlebih. 48 GB dipilih untuk *page cache*, bukan untuk proses |
| Disk | DB **18 GB**, laju **±11 GB/bln** | 400 GB jebol ~bln 22 · **800 GB aman ~bln 29+** | **Satu-satunya sumbu yang mengikat** |
| Jaringan | puncak nyata = unggah cadangan harian | 800 Mbit | berlebih (fair-use throttle 100 Mbit/s tetap jauh di atas kebutuhan) |

**Laju +5 GB/bln yang dipakai v2 adalah fiksi.** Tiga turunan independen sepakat di ±9,5–11,7
GB/bln: (a) 185 rb baris/hari × **1,90 KB/baris** terukur (16 GB `transactions_transaction` /
8.839.002 baris) + MatchResult + M2M = 390 MB/hari; (b) 18 GB dibagi umur data 48–57 hari =
316–377 MB/hari; (c) struktural — heap **saja** sudah ~985 B/baris sebelum 20 index, sedangkan
+5 GB/bln menuntut 0,81 KB/baris *all-in*. Semua tanggal jebol di dokumen ini diturunkan dari
±11 GB/bln.

### Kenapa BUKAN VPS 16 — dominasi, bukan penghematan

| | VPS 12 + 800 GB | VPS 16 |
|---|---|---|
| Harga Singapura, 24 bln | **€40,05/bln** | €50,35/bln |
| Disk | **800 GB** | 500 GB |
| Daya tahan (laju terukur, ruang `pg_repack` utuh) | **~bln 29** | ~bln 17 |

VPS 16 lebih mahal 25% untuk disk 37% lebih kecil pada satu-satunya sumbu yang mengikat.
Ia juga **tidak** membeli keandalan: VPS 12 dan VPS 16 berada di kelas vCPU bersama dan
tingkat penyimpanan yang **sama persis**, jadi ia tak memperbaiki dua risiko kinerja nyata
migrasi ini — steal time dan IOPS acak.

### Asimetri kontrak — ini yang menentukan arah kesalahan yang aman

Terverifikasi di help.contabo.com (KB 103000269700) dan configurator hidup:

- **Upgrade tier**: swalayan, **tanpa biaya upgrade**, selisih diprorata harian, Live Migration
  tanpa kehilangan data, **IP tetap**.
- **Downgrade**: **MUSTAHIL** — harus pesan server baru + migrasi manual + **IP berubah**
  (artinya mengulang seluruh konfigurasi Cloudflare + geo-block KH).
- **Core (SSD) → Plus (NVMe)**: bukan jalur upgrade — butuh tiket support dan **kehilangan
  data total**; gratis hanya bila diminta ≤14 hari sejak order.
- **Region**: sekali pakai — pindah region mengganti seluruh IPv4/IPv6 dan berbayar.
  **Singapura harus benar sejak layar order.**

→ **"Ambil yang lebih besar biar aman" adalah pintu satu arah yang mahal.** Arah kesalahan
yang murah adalah membeli lebih kecil lalu naik.

*Konflik dokumen yang belum terpecahkan:* blog resmi Contabo (3-Jun-2025) dan KB lama
103000269722 menyatakan Live Migration **berbayar** dan New Deployment memberi **IP baru** —
bertentangan dengan KB kanonik pada dua fakta yang justru menopang rencana ini. Minta
konfirmasi tertulis support sebelum prepay.

### Tangga harga Singapura (terverifikasi 3 jalur independen)

`api/products.json` + `api/addons.json` + Order Summary hidup, nol penyimpangan:

| Termin | Basis | Location fee SG | Disk 800 GB | **Total/bln** |
|---|---|---|---|---|
| 1 bulan | €25,00 | €14,05 | €6,00 | **€45,05** |
| 12 bulan (−15%) | €21,25 | €14,05 | €6,00 | **€41,30** |
| 24 bulan (−20%) | €20,00 | €14,05 | €6,00 | **€40,05** |

**Location fee SG €14,05 flat dan TIDAK pernah ikut diskon** (dibuktikan: "You save" tidak
berubah saat region dipilih). Setup fee **€0** di semua termin, termasuk bulanan. Framing
"€20 untuk 24 bulan pertama, lalu €25" **BENAR** — teks legal checkout: *kontrak berlanjut
bulanan pada harga standar sesudah termin awal*, jadi bulan ke-25 = €39,05/bln kecuali
diperpanjang lebih awal.

### Urutan pembelian — aturan keras

1. **Order 1 bulan dulu**: VPS 12 · Asia (Singapore) · Ubuntu 24.04 · add-on 800 GB SSD →
   **€45,05**, One-Time €0. Contabo adalah undian node; jangan prepay node yang belum terbukti.
2. Jalankan **FASE 0–3 + gerbang node** di mesin itu: `fio`, steal p95 (`mpstat` jam sibuk),
   durasi restore, dan **wall-clock `run_batch` toko tersibuk**. Gerbang yang sesungguhnya
   adalah run_batch dan durasi restore — bukan `fio` mentah, karena pembacaan harian dilayani
   RAM (DB muat penuh di page cache).
3. Node lulus → **perpanjang lebih awal instance yang SAMA ke 12 bulan (€41,30/bln).**
   **JANGAN order ulang demi −20%**: order baru = node baru + **IP baru** = seluruh validasi
   hangus, demi selisih €1,25/bln.
4. Node gagal → redeploy / instance baru (murah — data belum pindah). Bila I/O benar-benar
   masalah, fallback berbayar = Cloud VPS **Plus** 12 SG €80,30/bln (NVMe ±3,5× IOPS) —
   catat bahwa itu **deployment baru**, bukan upgrade.

### Yang TIDAK lagi menjadi syarat beli

Pengukuran Δ-30-hari pertumbuhan DB **diturunkan dari pra-syarat pembelian menjadi kewajiban
monitoring**: opsi 800 GB sudah menutup kedua cabang laju (baik 5 maupun 11 GB/bln), jadi
menunggu 30 hari hanya menunda migrasi tanpa mengubah keputusan.

**Empat angka dipantau mingguan, dengan ambang tindakan:**

| Angka | Ambang | Tindakan |
|---|---|---|
| `pg_database_size` | Δ30 hari > 12 GB | pesan Storage Extension sekarang, jangan tunggu penuh |
| `df -h /` | > 70% / > 85% | tindakan / berhenti menerima unggahan |
| steal `%st` jam 13:00–22:00 WIB | > 15% berkelanjutan | jadwalkan pindah ke Plus (ingat: deployment baru) |
| wall-clock `run_batch` toko tersibuk | > 80 dtk | worker latar naik prioritas di atas semua fitur |

### Spesifikasi minimum yang jujur

**8 vCPU / 24–32 GB / disk ≥400 GB**, dengan syarat disiplin retensi (dump lokal 1 hari,
Drive 14 hari). VPS 12 dipilih di atas itu bukan karena core melainkan karena 48 GB menampung
seluruh DB di cache untuk tahun-tahun mendatang, **dan** karena ia punya jalur disk 800 GB.

---

## ⚠️ Jebakan — 13, diurut dari yang paling merusak

### J1 — `manage.py` tanpa `/etc/toa.env` menulis ke SQLite dan MELAPORKAN SUKSES 🔴
`EnvironmentFile=` systemd **tidak berlaku untuk shell manual**. Rantai kegagalannya:
1. `DATABASE_URL` absen → `settings.py:112` diam-diam pakai SQLite `BASE_DIR/db.sqlite3`
2. `migrate --noinput` membuat DB baru, menjalankan seluruh migrasi + seed, **cetak sukses**.
   Postgres 17 GB hasil restore tidak tersentuh
3. `DEBUG` absen → tanpa `RAILWAY_ENVIRONMENT` → `DEBUG=True` → penjaga SECRET_KEY
   `settings.py:37` **tak menyala** → kunci dev yang ter-commit di repo publik dipakai
4. `periksa_index` di SQLite → `"Tidak berlaku"` → **exit 0** → ceklis lolos tanpa memeriksa apa pun

**Wajib:** `set -a; . /etc/toa.env; set +a` sebelum **SETIAP** `manage.py`, plus asersi
`test ! -f /opt/toa/db.sqlite3` dan `dbshell` menghitung baris.

### J2 — nginx merusak geo-block, tiga arah, semuanya senyap 🔴
`web/middleware.py:67` mengambil elemen **paling kiri** `X-Forwarded-For`; docstring-nya
menyatakan itu dikalibrasi karena **Railway MENIMPA** XFF.

| nginx | Akibat |
|---|---|
| tanpa XFF | `REMOTE_ADDR`=127.0.0.1 → dianggap internal → **geo-block + IP allowlist mati sedunia** |
| `$proxy_add_x_forwarded_for` (idiom baku) | menambah ke kiriman Cloudflare → paling kiri **dapat dipalsukan**; `curl -H 'X-Forwarded-For: 127.0.0.1'` membuka semuanya |
| modul `realip` (praktik "terbaik") | `REMOTE_ADDR` jadi IP end-user → `_via_cloudflare` gagal → **semua 403** |

**Satu-satunya benar:** `proxy_set_header X-Forwarded-For $remote_addr;` — **TIMPA**, jangan tambah.
Jangan pakai `set_real_ip_from`/`real_ip_header`.

### J3 — FASE 4 v1 me-restore ke database yang SUDAH BERISI 🔴
Saat FASE 4, `toa` berisi data FASE 2 **plus** tulisan rekonsiliasi uji FASE 3 (`ReconBatch`,
`MatchRun`, `MatchResult`, UPDATE `consumed_by_batch` di ribuan baris). Tanpa `--clean`:
skema di-skip seluruhnya ("already exists"), data ditempel ke tabel lama, batch uji FASE 3
tertinggal **di dalam produksi** dan menabrak constraint unik `(toko, recon_date)`.
**Wajib:** restore ke database **baru**, verifikasi di sana, lalu tukar nama.

### J4 — `pg_dump` MEMBUANG index yang invalid 🔴
Terverifikasi di sumber `pg_dump.c` (`getIndexes`, REL_18_STABLE):
`WHERE (i.indisvalid OR t2.relkind='p') AND i.indisready`. `transactions_transaction` itu
`relkind='r'`, jadi tak ada jalan keluar. Digabung dengan `core/db_ops.TambahIndexAman` yang
**menelan kegagalan build** sementara migrasinya tetap tercatat selesai, dan `django_migrations`
yang ikut ter-restore sebagai sudah-selesai → **index invalid di produksi lenyap permanen dan
`migrate` tak akan pernah membangunnya ulang.**
**Wajib:** cek `indisvalid` di **produksi** sebelum tiap dump. Per 31-08-2026 semua 20 valid.

### J5 — 28 dari 29 tabel tidak pernah dihitung; sebagian gagal SENYAP 🔴
v1 hanya menghitung `transactions_transaction`. Data referensi dibuat **data migration**, dan
`django_migrations` ter-restore sebagai sudah-selesai → **`migrate` tak akan pernah mengisi ulang**.

*Gagal berisik:* `accounts_user` (tak ada yang bisa login) · `sources_sourcetype` (setiap unggahan
`DoesNotExist`) · `sources_toko` (semua user lihat `no_toko`) · `reconciliation_toleranceprofile`
(`run_batch` tanpa profil).
*Gagal SENYAP — kelas terburuk:* `web_frkoreksi` (semua koreksi Control Bracket lenyap, total
diam-diam kembali ke nilai mentah) · `web_rekapmanual`/`web_hutangmanual`/`web_rekappenyebab`
(NET PROFIT berubah tanpa error) · **`web_allowedip` → GAGAL-TERBUKA** (middleware dorman saat
daftar kosong = gerbang IP hilang untuk seluruh auditor & supervisor, tanpa gejala apa pun) ·
`accounts_user_allowed_tokos` (RBAC hilang).

### J6 — `SUM(amount)` buta terhadap hampir semua kerusakan 🔴
Lolos gerbang tanpa terdeteksi: `occurred_at` NULL (mesin berhenti mencocokkan) · `posted_date`
NULL (baris hilang dari semua laporan; cek bulanan v1 justru **mengecualikan** NULL) · `raw` jsonb
kosong (semua halaman laporan blank) · teks rusak encoding (fuzzy + kunci exact per-brand degradasi) ·
`row_hash` rusak (idempotensi ingest hilang) · `consumed_by_batch` NULL (9,4 jt baris jadi "aktif") ·
`is_duplicate` reset · **nilai tertukar antar baris** (SUM tidak peduli urutan).

### J7 — Gerbang FASE 2 v1 MUSTAHIL LULUS 🟠
Menuntut "sama persis dengan produksi" sementara produksi menulis ±185 rb baris/hari.
Gerbang yang tak pernah bisa lulus melatih orang untuk mengabaikannya.
**Wajib:** batasi kedua sisi dengan **snapshot MVCC** (`pg_export_snapshot`) atau plafon id
dari sisi restore. Kesetaraan penuh hanya dibuktikan di FASE 4 setelah penulisan berhenti.

### J8 — `sudo` tidak akan pernah bisa dipakai 🟠
`adduser --disabled-password` mengisi field shadow dengan `*`; tidak ada password yang bisa
cocok, dan `sudo` meminta password user pemanggil. Tanpa `NOPASSWD`, **setiap `sudo` di FASE 1
dan seterusnya gagal** — baru ketahuan setelah operator mengira provisioning selesai.

### J9 — `sed PasswordAuthentication no` kemungkinan besar tak berefek 🟠
Ubuntu 24.04 menaruh `Include /etc/ssh/sshd_config.d/*.conf` sebagai directive **pertama**, dan
sshd memakai nilai **pertama** per keyword. Contabo memprovisioning dengan password root, jadi
cloud-init menaruh `50-cloud-init.conf` berisi `PasswordAuthentication yes` — terbaca lebih dulu,
menang. sed sukses, restart sukses, **login password tetap hidup**.
**Wajib:** tulis `00-toa-hardening.conf` (00 < 50) dan verifikasi lewat `sshd -T`.

### J10 — Let's Encrypt MUSTAHIL di topologi ini 🟠
Record oranye → ACME me-resolve ke anycast Cloudflare → tantangan HTTP-01 tiba di **edge**, lalu
diteruskan ke origin lewat **443**, yang menuntut origin sudah punya sertifikat valid. Ayam-dan-telur.
Jalan keluarnya hanya meng-abu-abukan record + buka port 80 ke dunia — yang mempublikasikan IP VPS
ke DNS pasif selamanya dan melanggar tujuan firewall itu sendiri.
**Wajib:** **Cloudflare Origin CA** (15 tahun, tanpa port 80, dan karena CA privat **tidak masuk
Certificate Transparency** — sertifikat LE akan menaruh `staging.wolfgang-77.com` di crt.sh permanen).
Mode SSL/TLS zona **wajib diverifikasi = Full (strict)**; kalau "Flexible", Cloudflare menyambung ke
port 80 yang tertutup → **situs mati saat cutover**.

### J11 — `tzdata`, bukan `timedatectl`, yang load-bearing 🟡
Diuji langsung: jam OS produksi **UTC**; Django yang menyetel `TZ=Asia/Jakarta` sehingga
`datetime.now()` benar 22:51 WIB. Yang wajib ada adalah **paket `tzdata`**.
`timedatectl set-timezone Asia/Jakarta` justru membuat VPS **berbeda** dari produksi — tidak
berbahaya bagi aplikasi, tapi menggeser stempel log dan **jam cron backup**. Tetap dilakukan
(operator manusia baca log dalam WIB), tapi sebagai keputusan sadar.

### J12 — `GEO_BLOCK_BYPASS_STAFF` BUKAN pintu darurat 🟠
`middleware.py` langkah (6) menuntut `user.is_authenticated and user.is_staff`. Permintaan anonim
ke halaman login tidak punya sesi → bypass tidak bisa dipakai untuk masuk. Setelah `SECRET_KEY`
diputar (semua sesi mati), **satu-satunya pintu dari luar Kamboja adalah `GEO_BLOCK_ALLOWLIST`** —
dan di berkas tes IP-nya dilabeli `TIM_IP` tanpa keterangan asal.
Tambahan: perintah break-glass `railway variables --set GEO_BLOCK_ENABLED=false` **mati bersama Railway**.

### J13 — Rahasia produksi sudah terekspos 🟠
**`DATABASE_URL` DAN `SECRET_KEY`** produksi keduanya muncul di log sesi kerja 31-08-2026.
Keduanya wajib dibuat BARU di VPS. Jangan pakai `SECRET_KEY_FALLBACKS` dengan kunci lama —
kunci itu justru yang bocor.

---

## Apa yang berubah dari v1

| | v1 | v2 |
|---|---|---|
| Python | `apt install python3.12` | **3.11 via deadsnakes** (= produksi 3.11.10) |
| requirements | tanpa patokan | **dipatok dari freeze produksi** |
| Setelan Postgres | 5 dari 8 salah | **paritas produksi terukur** |
| Gerbang FASE 2 | 4 query, mustahil lulus | **skrip diff ber-snapshot, ~17 blok pemeriksaan** |
| Restore FASE 4 | ke DB berisi | **ke DB baru + tukar nama** (rollback 2 detik) |
| nginx/systemd | satu kalimat | **berkas lengkap, tiap directive beralasan** |
| FASE 0 | satu blok tanpa gerbang | **dua gerbang login wajib** |
| TLS | tak disebut | **Cloudflare Origin CA + verifikasi mode zona** |
| Jendela cutover | "sebelum 12:00" | **runbook berwaktu + 2 batas abort** |
| Rollback | "pindahkan manual" | **R1–R5: split-brain mustahil secara struktural** |
| Suite tes | tidak dijalankan | **~1.700 tes = gerbang FASE 3** |

---

## FASE 0 — Siapkan mesin (produksi tidak tersentuh)

```bash
# Login sebagai root. JANGAN TUTUP SESI INI sampai Gerbang 1 lulus.
apt update

# 0.1 User operator + sudo yang benar-benar bisa dipakai (J8)
adduser --disabled-password --gecos "" toa
echo 'toa ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-toa
chmod 440 /etc/sudoers.d/90-toa
visudo -c -f /etc/sudoers.d/90-toa || { rm -f /etc/sudoers.d/90-toa; echo "sudoers rusak"; exit 1; }

# 0.2 Kunci SSH — BERHENTI kalau sumbernya tak ada (Contabo lazim pakai password root)
if [ -s /root/.ssh/authorized_keys ]; then
  mkdir -p /home/toa/.ssh
  cp /root/.ssh/authorized_keys /home/toa/.ssh/authorized_keys
else
  echo "BERHENTI: /root/.ssh/authorized_keys tidak ada."
  echo "Tempel public key operator manual, lalu ulangi blok ini:"
  echo "  mkdir -p /home/toa/.ssh && nano /home/toa/.ssh/authorized_keys"
  exit 1
fi
chown -R toa:toa /home/toa/.ssh && chmod 700 /home/toa/.ssh
chmod 600 /home/toa/.ssh/authorized_keys
```

> ### 🚦 GERBANG 0 — WAJIB sebelum menyentuh sshd_config
> Buka **terminal kedua** (jangan tutup sesi root):
> ```
> ssh toa@<IP-VPS>
> sudo whoami          # harus "root", tanpa diminta password
> ```
> Gagal → **BERHENTI**. Sesi root ini satu-satunya jalan mundur.

```bash
# 0.3 Matikan login password/root — drop-in bernomor rendah, BUKAN sed (J9)
cat >/etc/ssh/sshd_config.d/00-toa-hardening.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
EOF
sshd -t || { echo "sshd_config tidak valid — JANGAN restart"; exit 1; }
systemctl restart ssh
sshd -T | grep -Ei '^(permitrootlogin|passwordauthentication) '
# WAJIB persis: permitrootlogin no / passwordauthentication no
```

> ### 🚦 GERBANG 1 — WAJIB sebelum menutup sesi root
> Di terminal kedua: `ssh toa@<IP-VPS>` masih berhasil, `sudo whoami` masih "root".
> Dari mesin lain: `ssh root@<IP-VPS>` harus **DITOLAK**.

```bash
# 0.4 Zona waktu (J11) + pertahanan dasar
timedatectl set-timezone Asia/Jakarta      # keputusan sadar: log dalam WIB
apt install -y tzdata fail2ban unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades
# Aplikasi keuangan TIDAK boleh reboot sendiri:
echo 'Unattended-Upgrade::Automatic-Reboot "false";' > /etc/apt/apt.conf.d/99-no-reboot
systemctl enable --now fail2ban

# 0.5 Firewall — validasi daftar Cloudflare SEBELUM mengaktifkan (J10)
apt install -y ufw
ufw default deny incoming && ufw default allow outgoing
ufw limit 22/tcp          # `limit`, bukan `allow` polos, di mesin berisi DB keuangan

tambah_cf() {                                  # $1=url $2=port $3=regex
  local body n=0
  body=$(curl -fsSL "$1") || { echo "GAGAL curl $1"; return 1; }   # -f -L, BUKAN -s saja
  [ -n "$body" ] || { echo "GAGAL: daftar kosong"; return 1; }
  while IFS= read -r c; do
    [ -n "$c" ] || continue
    [[ "$c" =~ $3 ]] || { echo "GAGAL: bukan CIDR: '$c'"; return 1; }
    ufw allow from "$c" to any port "$2" proto tcp; n=$((n+1))
  done <<< "$body"
  echo "$1 → $n rentang (port $2)"
  [ "$n" -ge 5 ] || { echo "GAGAL: rentang terlalu sedikit ($n)"; return 1; }
}
V4='^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$'; V6='^[0-9a-fA-F:]+/[0-9]{1,3}$'
for p in 443 80; do
  tambah_cf https://www.cloudflare.com/ips-v4 $p "$V4" || exit 1
  tambah_cf https://www.cloudflare.com/ips-v6 $p "$V6" || exit 1
done
ufw --force enable && ufw status verbose
# BACA keluarannya. Nol aturan Cloudflare = situs mati, dan ufw tetap "sukses".
```

> **Catatan FASE 5:** rentang Cloudflare berubah. Jadwalkan `tambah_cf` bulanan, dan
> pertimbangkan **Authenticated Origin Pulls per-zona** (mTLS) — karena firewall rentang
> Cloudflare **tidak** menutup bypass origin: penyerang bisa mengarahkan zona Cloudflare
> miliknya sendiri ke IP VPS Anda dan datang dari IP yang sah.

---

## FASE 1 — Tumpukan (paritas produksi, bukan penyetelan baru)

```bash
# 1.1 PostgreSQL 18 dari PGDG
sudo apt install -y postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y     # -y: tanpa ini menggantung
sudo apt install -y postgresql-18 postgresql-contrib-18
pg_lsclusters                      # PASTIKAN port 5432, bukan 5433

# 1.2 Python 3.11 = produksi (Ubuntu 24.04 default-nya 3.12)
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa && sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev \
                    build-essential libffi-dev libpq-dev git nginx
```

```bash
# 1.3 Setelan Postgres — PARITAS PRODUKSI. Ganti tiap nilai dengan hasil
#     pembacaan `pg_settings` produksi hari itu; angka di bawah = terukur 31-08-2026.
sudo -u postgres psql <<'SQL'
-- Masukan PERENCANA — wajib sama persis. Mengubahnya = menyetel ulang database
-- di tengah pemindahan mesin, sehingga perlambatan apa pun tak bisa dilacak.
ALTER SYSTEM SET random_page_cost                = '1.1';
ALTER SYSTEM SET effective_cache_size            = '16GB';    -- v1: 48GB ❌
ALTER SYSTEM SET max_parallel_workers_per_gather = '2';       -- v1: 4 ❌ (2 dibeli dgn outage 524)
ALTER SYSTEM SET jit_above_cost                  = '1000000'; -- v1 menghilangkannya ❌
ALTER SYSTEM SET work_mem                        = '4MB';     -- v1 & CLAUDE.md: 32MB ❌
-- Sumber daya (bukan masukan perencana)
ALTER SYSTEM SET shared_buffers                  = '6GB';     -- v1: 16GB ❌; CLAUDE.md: 128MB ❌
ALTER SYSTEM SET max_wal_size                    = '2GB';     -- v1: 4GB ❌
ALTER SYSTEM SET max_connections                 = '200';     -- app butuh 32 (4×8)
ALTER SYSTEM SET maintenance_work_mem            = '1GB';
ALTER SYSTEM SET dynamic_shared_memory_type      = 'mmap';    -- = produksi
ALTER SYSTEM SET effective_io_concurrency        = '200';
-- Instrumen (produksi sudah memuatnya)
ALTER SYSTEM SET shared_preload_libraries        = 'pg_stat_statements';
ALTER SYSTEM SET log_checkpoints                 = 'on';
ALTER SYSTEM SET log_autovacuum_min_duration     = '0';
ALTER SYSTEM SET log_min_duration_statement      = '2000';
SQL
sudo systemctl restart postgresql@18-main

# ALTER SYSTEM TIDAK memvalidasi apa pun. Nilai yang tak sanggup dipenuhi =
# Postgres MENOLAK START, dan psql tak ada lagi untuk membatalkannya.
# Pemulihan manual: sudo -e /var/lib/postgresql/18/main/postgresql.auto.conf
systemctl is-active --quiet postgresql@18-main || { journalctl -u postgresql@18-main -n 50; exit 1; }
sudo -u postgres psql -Atc "SELECT name||'='||setting||CASE WHEN pending_restart THEN ' ⚠PENDING' ELSE '' END
  FROM pg_settings WHERE name IN ('work_mem','shared_buffers','effective_cache_size',
  'max_parallel_workers_per_gather','jit_above_cost','max_wal_size','random_page_cost') ORDER BY 1;"
# Tidak boleh ada PENDING, dan tiap nilai == baseline produksi.
```

```bash
# 1.4 DB & user — locale EKSPLISIT (J6-adjacent: SQL_ASCII merusak nama Indonesia SENYAP)
NEWPW=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)   # aman utk URL & systemd
sudo -u postgres psql <<SQL
CREATE USER toa WITH PASSWORD '$NEWPW';
ALTER USER toa CREATEDB;                       -- suite tes butuh CREATE DATABASE
CREATE DATABASE toa OWNER toa TEMPLATE template0
  ENCODING 'UTF8' LC_COLLATE 'en_US.utf8' LC_CTYPE 'en_US.utf8';
SQL
echo "SIMPAN password ini di password manager, lalu pakai di /etc/toa.env: $NEWPW"
sudo -u postgres psql -Atc "SELECT pg_encoding_to_char(encoding)||' / '||datcollate
  FROM pg_database WHERE datname='toa';"       # WAJIB: UTF8 / en_US.utf8
```

> Password lewat heredoc stdin, **bukan** `psql -c "...'$PW'..."` — argumen baris perintah
> masuk shell history dan terlihat di `/proc/<pid>/cmdline`.

---

## FASE 2 — 🚦 GERBANG: restore percobaan & verifikasi

**Migrasi DIBATALKAN kalau fase ini tidak lulus.**

Skrip lengkap ada di `scripts/gerbang.sh` + `scripts/gerbang.sql` (17 blok pemeriksaan:
inventaris tabel, hitung SEMUA tabel, asersi tabel referensi tidak kosong, gagal-terbuka
`web_allowedip`, overlay koreksi, census kolom penentu, checksum nilai, sebaran per
toko×sumber, **sidik jari md5 per blok 1 juta id** termasuk `raw::text`, definisi seluruh
index + `indisvalid`, seluruh constraint, sequence vs `max(id)`, statistik planner).

### Kenapa v1 tidak bisa dipakai
Produksi menulis ±185 rb baris/hari selama dump berjalan, jadi "sama persis" **mustahil**
(J7). Solusinya: **snapshot MVCC** — angka pembanding diambil dari tampilan yang sama persis
dengan yang dilihat dump.

```bash
# A. PRA-TERBANG di produksi (baca saja) — WAJIB, lihat J4
railway ssh -s Postgres "psql -U postgres -d railway -Atc \"
  SELECT c.relname||' '||i.indisvalid FROM pg_class c
    JOIN pg_index i ON i.indexrelid=c.oid JOIN pg_class t ON t.oid=i.indrelid
   WHERE t.relname='transactions_transaction' AND c.relkind='i' ORDER BY 1;\""
# SEMUA harus true. Ada false → REINDEX INDEX CONCURRENTLY di PRODUKSI dulu,
# karena pg_dump membuangnya dan `migrate` tak akan pernah membangunnya ulang.

# A2. Uji kecepatan disk — `random_page_cost=1.1` mengasumsikan penyimpanan
#     mendekati-NVMe. Contabo Cloud VPS memakai tingkat SSD BERSAMA, bukan NVMe
#     khusus. Asuransi murah; konsekuensinya tetap tertangkap GATE B + EXPLAIN.
sudo apt install -y fio
fio --name=acak --filename=/var/lib/postgresql/ujidisk --size=1G --bs=8k \
    --rw=randread --iodepth=16 --ioengine=libaio --direct=1 --runtime=30 --time_based \
    --group_reporting | grep -E 'IOPS|lat .*avg'
sudo rm -f /var/lib/postgresql/ujidisk
# IOPS acak jauh di bawah ±10rb atau latensi >1ms → catat, dan pertimbangkan
# random_page_cost lebih tinggi SEBAGAI PERUBAHAN TERPISAH pasca-cutover.

# B. Profil RESTORE sementara (di VPS)
# maintenance_work_mem 2GB (BUKAN 8GB) dan mpmw 2 (BUKAN 4) — ini CACAT LATEN v2.
# `pg_restore --jobs=N` = N sesi terpisah, dan tiap CREATE INDEX berhak atas
# maintenance_work_mem PENUH. Plafonnya N x mwm, DI ATAS shared_buffers 6GB yang sudah
# residen. Nilai v2 (8 job x 8GB = 64 GB) sudah melampaui RAM VPS 16 sebelum mesinnya
# diperkecil sama sekali.
# Anggaran mesin nyata (VPS 8, RAM 24 GB): 6GB shared_buffers + ~2GB OS = 8GB terpakai
# sebelum restore dimulai. --jobs=4 x 2GB = 8GB → total 16 dari 24, sisa 8GB page cache.
# --jobs=8 x 2GB = 16GB → total 24 dari 24: nol margin, OOM killer menghentikan restore
# di tengah jalan. Karena itu --jobs=4 — lihat "Mesin nyata != yang direkomendasikan".
sudo -u postgres psql <<'SQL'
ALTER SYSTEM SET maintenance_work_mem='2GB';
ALTER SYSTEM SET max_parallel_maintenance_workers='2';
ALTER SYSTEM SET max_wal_size='16GB';
ALTER SYSTEM SET checkpoint_timeout='30min';
ALTER SYSTEM SET synchronous_commit='off';   -- aman: gagal = ulangi restore
ALTER SYSTEM SET autovacuum='off';
SQL
sudo systemctl restart postgresql@18-main
# fsync=off SENGAJA TIDAK dipakai — aplikasi keuangan.

# C. DUMP DITARIK OLEH VPS, ter-snapshot, di dalam tmux
#    JANGAN `railway ssh "pg_dump -Fc" > file`: kanal WebSocket itu tidak terbukti
#    8-bit clean (skrip pun harus di-base64), tidak bisa dilanjutkan bila putus, dan
#    `-Fc` ke pipe = output tak seekable → offset TOC tak ditulis balik → `-j` sia-sia.
tmux new -s migrasi
# Password TIDAK di argv/URL — `pg_dump -d "$PROD_URL"` membuatnya terlihat di
# /proc/<pid>/cmdline, persis yang dilarang di FASE 1.4.
umask 077; cat > ~/.pgpass <<'PGP'
<railway-tcp-proxy>:<port>:railway:postgres:<PW>
PGP
chmod 600 ~/.pgpass
export PROD_URL='postgresql://postgres@<railway-tcp-proxy>:<port>/railway?sslmode=require'
sudo install -d -o toa -g toa /var/backups/toa
STAMP=$(date +%F); DUMPDIR=/var/backups/toa/dump-$STAMP

#  jendela 1 — buka snapshot, BIARKAN TERBUKA
psql "$PROD_URL"
  BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;
  SELECT pg_export_snapshot();          -- catat id-nya

#  jendela 2 — dump terikat snapshot yang SAMA
sudo -u toa pg_dump -d "$PROD_URL" --format=directory --jobs=4 \
     --snapshot='<ID>' --statistics --compress=zstd:3 --verbose --file="$DUMPDIR"
#  --statistics: PG18 default-nya --no-statistics. Tanpa ini database lahir
#  TANPA histogram sama sekali → seq scan 9,37 jt baris → kelas 524.

#  jendela 1 — ambil patokan DARI TRANSAKSI YANG SAMA, lalu COMMIT
  SELECT count(*) FROM transactions_transaction;
  SELECT sum(amount), sum(credit_delta), sum(money_delta) FROM transactions_transaction;
  SELECT to_char(posted_date,'YYYY-MM'), count(*) FROM transactions_transaction
    WHERE posted_date IS NOT NULL GROUP BY 1 ORDER BY 1;
  COMMIT;
# Simpan keluaran ini — INILAH patokan. Bukan angka hardcoded.

# D. BUKTIKAN DUMP UTUH sebelum ada yang mempercayainya
pg_restore --list "$DUMPDIR" > /var/backups/toa/toc-$STAMP.txt   # perlu, TIDAK cukup
pg_restore --file=/dev/null "$DUMPDIR" && echo "PEMBACAAN PENUH OK — tidak terpotong"
#  ^ satu-satunya uji pemotongan sungguhan: --list hanya mem-parse daftar isi dan
#    tetap sukses pada arsip yang blok datanya terputus.

# E. RESTORE — sebagai OS user `toa` (peer auth → role toa). Kalau dijalankan sebagai
#    `postgres`, SEMUA tabel dimiliki postgres tanpa GRANT → aplikasi mati dengan
#    "permission denied for table transactions_transaction" di query pertama.
sudo -u toa pg_restore --dbname=toa --jobs=4 --no-owner --no-privileges \
     --no-comments --exit-on-error --verbose "$DUMPDIR" 2>/var/backups/toa/restore-$STAMP.err
#  --no-comments: COMMENT ON EXTENSION plpgsql ditolak utk non-superuser dan akan
#    menggugurkan --exit-on-error. Jangan diselesaikan dgn superuser sementara —
#    langkah revoke di runbook keuangan adalah langkah yang terlupakan separuh jadi.
#  --exit-on-error: tanpa ini pg_restore mencatat galat lalu LANJUT, dan Anda dapat
#    database keuangan separuh terisi yang tampak berhasil.

# F. STATISTIK & VISIBILITY MAP — TIDAK OPSIONAL
sudo -u toa vacuumdb -d toa --analyze-in-stages --jobs=4
sudo -u toa vacuumdb -d toa --analyze --jobs=4

# G. KEMBALIKAN profil paritas SEBELUM verifikasi apa pun
sudo -u postgres psql <<'SQL'
ALTER SYSTEM RESET maintenance_work_mem;  ALTER SYSTEM RESET max_parallel_maintenance_workers;
ALTER SYSTEM RESET checkpoint_timeout;    ALTER SYSTEM RESET synchronous_commit;
ALTER SYSTEM RESET autovacuum;
ALTER SYSTEM SET maintenance_work_mem='1GB'; ALTER SYSTEM SET max_wal_size='2GB';
SQL
sudo systemctl restart postgresql@18-main
# autovacuum WAJIB 'on', synchronous_commit WAJIB 'on'.

# H. GERBANG
./scripts/gerbang.sh banding <IP-VPS> live
```

**Lulus bila:** diff kosong pada seluruh baris yang digerbang · tidak ada `KOSONG-FATAL` ·
tidak ada `BAHAYA-TABRAKAN-PK` · tidak ada `valid=f` · tidak ada `analyzed=BELUM-PERNAH` ·
kepemilikan tabel = `toa` (29) · `EXPLAIN` query mesin memakai `tx_toko_src_posted_idx`,
bukan Seq Scan. **Satu saja meleset → BERHENTI.**

```bash
# Autovacuum per-tabel (setelah restore). Alasan: engine.py `_consume_scope(...).update(
# consumed_by_batch=batch)` mem-UPDATE massal tiap batch; kolom itu FK (ter-index) sehingga
# update-nya TIDAK BISA HOT — tiap baris menulis tuple heap baru DAN entri di semua index.
sudo -u toa psql -d toa <<'SQL'
ALTER TABLE transactions_transaction SET (
  autovacuum_analyze_scale_factor = 0.01, autovacuum_analyze_threshold = 20000,
  autovacuum_vacuum_scale_factor  = 0.02, autovacuum_vacuum_threshold  = 20000,
  autovacuum_vacuum_cost_limit    = 2000,
  autovacuum_vacuum_insert_scale_factor = 0.05
);
SQL
```

---

## FASE 3 — Aplikasi, nginx, systemd, uji

```bash
sudo install -d -o toa -g toa /opt/toa                    # /opt itu root:root 755
sudo -u toa git clone <repo> /opt/toa && cd /opt/toa
sudo -u toa python3.11 -m venv .venv
sudo -u toa .venv/bin/pip install -r requirements.txt     # versi DIPATOK
sudo install -d -o toa -g toa /var/lib/toa/media
sudo -u toa ln -sfn /var/lib/toa/media /opt/toa/media     # MEDIA_ROOT di dalam checkout git!
```

### `/etc/toa.env`

```bash
sudo tee /etc/toa.env >/dev/null <<'ENV'
# Dibaca DUA jalur: systemd (EnvironmentFile=) DAN shell manual
#   set -a; . /etc/toa.env; set +a
# sebelum SETIAP manage.py. Tanpa itu Django diam-diam jatuh ke SQLite (J1).
# Hindari karakter ! # $ % & * ( ) — aman utk systemd sekaligus `source`.
# SENGAJA TIDAK ADA RAILWAY_ENVIRONMENT: memalsukannya hanya menyembunyikan cacat.

DEBUG=False                        # J1: tanpa ini DEBUG=True, cookie tanpa Secure, kunci dev dipakai
SECRET_KEY=<BARU: python3 -c "import secrets;print(secrets.token_urlsafe(64))">
DATABASE_URL=postgres://toa:<PASSWORD-BARU>@127.0.0.1:5432/toa
PORT=8000                          # Procfile mengikat $PORT; VPS tak menyuntiknya

# RAILWAY_PUBLIC_DOMAIN tak ada di VPS → daftar ini satu-satunya sumber.
# `audit.` MASIH aktif di produksi hari ini — menghapusnya = HTTP 400.
ALLOWED_HOSTS=auditor.wolfgang-77.com,audit.wolfgang-77.com,staging.wolfgang-77.com
CSRF_TRUSTED_ORIGINS=https://auditor.wolfgang-77.com,https://audit.wolfgang-77.com,https://staging.wolfgang-77.com

GEO_BLOCK_ENABLED=true
GEO_BLOCK_COUNTRIES=KH
GEO_BLOCK_BYPASS_STAFF=true        # J12: BUKAN pintu darurat — butuh sesi yang sudah ada
GEO_BLOCK_REQUIRE_CF=true
GEO_BLOCK_ALLOWLIST=202.178.121.42,167.179.18.162,<IP-OPERATOR>
GEO_BLOCK_TRUST_CF=true
GEO_BLOCK_CF_CIDRS=                # kosong = daftar bawaan settings.py; isi dari sumber ufw

SECURE_SSL_REDIRECT=True           # break-glass loop redirect: ubah False sementara
SECURE_HSTS_SECONDS=0              # = produksi. >0 otomatis menyalakan PRELOAD (tak bisa dibatalkan cepat)
PYTHONUNBUFFERED=1
ENV
sudo chown root:toa /etc/toa.env && sudo chmod 640 /etc/toa.env
```

```bash
# Perintah manajemen — env WAJIB dimuat DI DALAM batas sudo.
#
# ⚠ `set -a; . /etc/toa.env; set +a` di shell pemanggil LALU `sudo -u toa …`
#   TIDAK BEKERJA: sudoers Ubuntu memuat `Defaults env_reset`, sehingga
#   DATABASE_URL dan DEBUG dibuang tepat sebelum Python berjalan — dan Django
#   jatuh ke SQLite. Itu J1 yang lahir kembali di dalam perbaikan J1-nya sendiri.
toa_manage() {
  sudo -u toa bash -c 'set -a; . /etc/toa.env; set +a; cd /opt/toa && exec .venv/bin/python manage.py "$@"' _ "$@"
}
toa_manage collectstatic --noinput
toa_manage migrate --noinput
toa_manage periksa_index

# Tripwire J1 — murah, dan satu-satunya bukti env benar-benar sampai.
test ! -f /opt/toa/db.sqlite3 || { echo "FATAL: SQLite terbuat — env TIDAK termuat"; exit 1; }
sudo -u toa bash -c 'set -a; . /etc/toa.env; set +a; psql "$DATABASE_URL" -Atc \
  "select count(*) from transactions_transaction;"'    # harus ±9,37 juta
```

### `/etc/systemd/system/toa.service`

```ini
[Unit]
Description=Truth of Auditor — gunicorn
After=network-online.target postgresql@18-main.service
StartLimitIntervalSec=600
StartLimitBurst=3

[Service]
Type=simple
User=toa
Group=toa
WorkingDirectory=/opt/toa
EnvironmentFile=/etc/toa.env
# collectstatic & migrate SENGAJA TIDAK DI SINI. Procfile aman karena kontainer
# Railway sekali-pakai; systemd Restart= akan MENGULANG `migrate --noinput` pada
# setiap crash, tanpa pengawasan, terhadap database keuangan hidup.
ExecStart=/opt/toa/.venv/bin/gunicorn truth_auditor.wsgi:application \
    --bind 127.0.0.1:8000 \
    --workers 4 --threads 8 --worker-class gthread \
    --worker-tmp-dir /dev/shm \
    --timeout 120 --graceful-timeout 125 \
    --max-requests 1000 --max-requests-jitter 100 \
    --access-logfile - --error-logfile -
ExecReload=/bin/kill -s HUP $MAINPID
Restart=on-failure
RestartSec=5
TimeoutStopSec=140
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/toa/media

[Install]
WantedBy=multi-user.target
```

### nginx

```nginx
server {
    # Bentuk gabungan, BUKAN `http2 on;` — directive itu baru ada di nginx
    # 1.25.1 sedangkan Ubuntu 24.04 mengirim 1.24, jadi `nginx -t` akan gagal.
    listen 443 ssl http2;
    server_name auditor.wolfgang-77.com audit.wolfgang-77.com staging.wolfgang-77.com;

    # Cloudflare Origin CA — BUKAN Let's Encrypt (J10). Port 80 tak dipakai origin.
    ssl_certificate     /etc/ssl/cloudflare/wolfgang-77-origin.pem;
    ssl_certificate_key /etc/ssl/cloudflare/wolfgang-77-origin.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    # web/views.py: _FILE_MAX 50MB, _REQ_MAX 300MB. Default nginx 1MB menolak
    # setiap unggahan nyata dengan 413 telanjang, sebelum Django sempat bicara.
    client_max_body_size 320m;

    # Di ATAS gunicorn --timeout 120 + --graceful-timeout 125, supaya watchdog
    # gunicorn yang menjawab, bukan nginx memutus diam-diam di default 60s.
    proxy_connect_timeout 130s; proxy_send_timeout 130s;
    proxy_read_timeout    130s; send_timeout       130s;

    # urls.py melayani /media/ HANYA bila DEBUG. Di produksi TIDAK ADA berkas
    # unggahan yang bisa diakses lewat URL, dan itu disengaja: isinya ekspor bank
    # berisi username pemain asli. `alias` di sini = kebocoran data tanpa auth.
    location /media/ { deny all; }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-Proto $scheme;   # tanpa ini: loop redirect tak terbatas
        proxy_set_header X-Forwarded-For   $remote_addr;   # ← TIMPA. Baris paling load-bearing
        # JANGAN $proxy_add_x_forwarded_for (menambah → dapat dipalsukan, J2)
        # JANGAN set_real_ip_from/real_ip_header (merusak _via_cloudflare → 403 semua)
        proxy_redirect off;
    }
}
```

Static tetap di WhiteNoise — nama berkasnya sudah ber-hash dan Cloudflare men-cache di edge;
memecahnya ke nginx menciptakan sumber kebenaran kedua untuk `STATIC_ROOT`.

### 🚦 Gerbang FASE 3 — semua wajib lulus

- [ ] **Suite tes penuh di VPS**: `manage.py test` (~1.700) — **0 gagal**. Ini detektor termurah
      untuk pergeseran versi pustaka & interpreter
- [ ] `curl -sI https://staging.wolfgang-77.com/login/` → **200** dari IP operator
- [ ] `curl -H 'X-Forwarded-For: 127.0.0.1' https://staging…/` dari IP tak terdaftar → **403**
      (bukti J2 tertutup — kalau 200, geo-block mati)
- [ ] Akses langsung ke IP VPS → ditolak
- [ ] URL ngawur → **404 polos**, bukan halaman kuning Django
- [ ] `test ! -f /opt/toa/db.sqlite3`
- [ ] Dashboard g25/k25/mxw — **catat waktunya** (patokan GATE B di FASE 4)
- [ ] **Wall-clock `run_batch` toko tersibuk — ambang 80 detik.** Tak satu pun gerbang lain
      mengukur ini: semuanya menghitung baris atau membaca EXPLAIN. Rekonsiliasi berjalan
      SINKRON di dalam permintaan HTTP, sudah menyentuh ±100 dtk batas Cloudflare, dan
      `gunicorn --timeout 120` hanya memberi margin 20%. Perlambatan single-core 25% (steal
      di vCPU bersama) mengubah 100 dtk jadi 133 dtk → **HTTP 524 di edge**. Di atas 80 dtk:
      worker latar naik prioritas di atas semua pekerjaan lain — dan tidak ada ukuran VPS
      yang memperbaikinya (batasnya algoritma + GIL, bukan jumlah core)
- [ ] Unggah **batch multi-berkas ±20 MB**, bukan satu berkas kecil
- [ ] Satu rekonsiliasi tanggal lama → angka **sama persis** dengan produksi
- [ ] **Reboot VPS** → situs kembali tanpa satu pun langkah manual
- [ ] Login konsol VNC Contabo **diuji** (break-glass bila SSH mati)
- [ ] Mode SSL/TLS zona Cloudflare = **Full (strict)**, tercatat

---

## FASE 4 — Cutover

**Aturan keras (R2):** database VPS `default_transaction_read_only = on` sampai langkah 18.
Sebelum itu, rollback gratis di titik mana pun.

### T-1 hari
1. `railway variables --json` → **diff** terhadap `/etc/toa.env`. Tiap beda direkonsiliasi atau
   ditulis alasannya. **Beda tanpa penjelasan = cutover batal.**
2. Cloudflare: catat mode SSL/TLS (wajib Full strict) · konfirmasi sertifikat Origin CA terpasang ·
   konfirmasi aturan WAF KH-only **ber-scope hostname**, bukan zona · pastikan record apex Pages tak tersentuh
3. Siapkan aturan WAF pemeliharaan (Block + teks Indonesia, Skip untuk IP operator), **simpan nonaktif**
4. Verifikasi `curl -s https://api.ipify.org` masih cocok dengan allowlist & WAF Skip
5. Umumkan ke operator: jendela, jam kembali, **"semua sesi berakhir, wajib login ulang"**

### Hari-H

| # | Jam | Langkah | Est. |
|---|---|---|---|
| 6 | 06:40 | Konfirmasi tak ada `ReconBatch` berjalan | 5m |
| 7 | 06:45 | **Aktifkan WAF pemeliharaan.** Verifikasi dari luar: halaman Indonesia; dari IP operator: lolos | 5m |
| 8 | 06:50 | Hentikan service web Railway | 5m |
| 9 | 06:55 | **R1 — bekukan di level DB:** `ALTER DATABASE railway SET default_transaction_read_only=on;` + `pg_terminate_backend`. Catat `pg_stat_user_tables` + `max(id)` sumber | 5m |
| 10 | 07:00 | Cek `indisvalid` produksi (J4). Dump ber-snapshot **ditarik VPS** | **30–90m** |
| 11 | ~08:15 | `systemctl stop toa`; `DROP/CREATE toa_new`; restore `-j 4 --exit-on-error` | **60–120m** |
| 12 | ~09:45 | `vacuumdb --analyze-in-stages -j 4` — langkah sendiri, jangan digabung | **10–25m** |
| 13 | ~10:10 | **GATE A** — `gerbang.sh banding <ip> final` + `periksa_index`. Checksum wajib sama **sampai sen** | 15m |
| 14 | ~10:25 | `ALTER DATABASE toa RENAME TO toa_fase3; ALTER DATABASE toa_new RENAME TO toa;` set read-only. Start toa; `migrate`; `periksa_index` | 10m |
| 15 | ~10:35 | **GATE B** — smoke test lokal via `curl --resolve`, lalu waktu dashboard vs FASE 3 | 10m |
| 16 | ~10:45 | Pindahkan IP origin di **dashboard** Cloudflare. **Pastikan tetap oranye** — screenshot sebelum/sesudah. Purge Everything | 5m |
| 17 | ~10:50 | **GATE C** — uji lewat hostname produksi asli (publik masih ditahan WAF): login, 3 dashboard, pratinjau ingest, `/bracket/`, `/rekap-bulanan/`, **dan uji XFF J2 → 403** | 20m |
| 18 | ~11:10 | **Buka penulisan:** `ALTER DATABASE toa RESET default_transaction_read_only;` + restart. **Catat watermark — ini batas split-brain** | 5m |
| 19 | ~11:15 | Satu tulisan nyata end-to-end: unggah berkas kecil, jalankan rekonsiliasi, cocokkan angka | 15m |
| 20 | ~11:30 | Nonaktifkan WAF pemeliharaan. Situs publik | 2m |
| 21 | ~11:35 | Umumkan selesai + notis login ulang. `manage.py clearsessions` | 10m |

**Total realistis: 06:45 → 11:35 ≈ 4 jam 50 menit**, selesai ±90 menit sebelum jendela unggah 13:00.

**Dua batas abort — tidak bisa ditawar:**
- **08:45** dump belum selesai → abort
- **11:00** GATE A belum lulus → abort

Abort itu murah dan identik: nonaktifkan WAF pemeliharaan, `ALTER DATABASE railway RESET
default_transaction_read_only`, hidupkan service web Railway. DNS tak pernah disentuh, VPS
tak pernah menerima tulisan.

### Aturan anti-split-brain (R1–R5)

| | Aturan |
|---|---|
| **R1** | Railway dibekukan di **level database**, bukan sekadar service dimatikan |
| **R2** | VPS read-only sampai smoke test lulus → jendela paling berisiko jadi **bebas tulisan** |
| **R3** | Watermark diambil **dua kali** (pasca-restore & saat membuka tulisan). Gunakan `n_tup_upd`, bukan hanya `max(id)` — tulisan UPDATE (`consumed_by_batch`, flip bucket) tak terlihat oleh `max(id)` |
| **R4** | **Rollback DNS ke Railway diizinkan HANYA bila watermark VPS belum bergerak.** Kalau sudah: perbaiki maju, atau migrasi balik penuh. **Merge parsial tidak pernah diizinkan** |
| **R5** | Railway tetap hidup ≥7 hari, **read-only**, agar restart liar tak bisa menerima tulisan |

**Kenapa "pindahkan manual" ditolak:** satu unggah+rekonsiliasi menulis ke 12+ tabel, dengan
UPDATE di tempat pada baris **lama** (late settlement membalik hasil di batch sebelumnya). Kedua
sisi juga melanjutkan `nextval` dari titik yang sama → PK kembar untuk baris berbeda. Dan
`ReviewAction`/`AuditLog` adalah **produk** yang integritasnya dijual aplikasi ini.

---

## ⛔ Lubang yang diketahui dan BELUM ditutup — wajib dibereskan sebelum hari-H

Dokumen ini menawarkan dua pilihan bila watermark VPS sudah bergerak (R4): **perbaiki maju**
atau **migrasi balik penuh**. Pilihan kedua **tidak punya prosedur di mana pun** — ia disebut
sebagai opsi, lalu tidak pernah dijelaskan. Sebuah jalan keluar yang hanya ada namanya lebih
berbahaya daripada tidak ada, karena ia terbaca seperti jaring pengaman saat keputusan diambil
di bawah tekanan.

**Bentuk kasarnya memang bisa diturunkan** dari FASE 2 dengan arah dibalik (dump VPS →
restore ke Railway → kembalikan DNS), tetapi tiga hal membuatnya **bukan sekadar FASE 2
terbalik**, dan ketiganya belum pernah diuji:

1. **Railway sisi tujuan tidak kosong.** DB `railway` masih memegang data pra-cutover dan
   berstatus `default_transaction_read_only=on` (R2/R5). Restore ke sana menuntut mematikan
   read-only **dan** memutuskan nasib baris lama — persis kelas operasi yang J3 hindari di
   arah sebaliknya dengan pola `toa_new` + tukar nama. Pola yang sama harus dirancang untuk
   arah ini, bukan diimprovisasi.
2. **Sequence sudah bercabang.** Kedua sisi melanjutkan `nextval` dari titik yang sama sejak
   langkah 18, jadi id yang sama sudah menunjuk baris berbeda. Ini juga alasan merge parsial
   dilarang; migrasi balik penuh menghindarinya hanya bila Railway benar-benar **ditimpa
   seluruhnya**, bukan digabung.
3. **Ini satu-satunya prosedur dalam rencana yang menulis ke produksi lama.** Setiap langkah
   lain memperlakukan Railway sebagai sumber baca. Karena itu ia butuh gerbangnya sendiri —
   minimal: dump VPS lolos `pg_restore --file=/dev/null`, hitungan dan checksum dibandingkan
   sebelum read-only Railway dibuka, dan salinan DB Railway pra-timpa disimpan lebih dulu.

**Sampai prosedur itu ditulis dan diuji, perlakukan "perbaiki maju di VPS" sebagai
satu-satunya jalan keluar pasca-langkah 18** — dan tetapkan itu di kepala sebelum cutover
dimulai, bukan saat memilih di bawah tekanan. Konsekuensi praktisnya: GATE A/B/C harus
dianggap sebagai gerbang yang sungguh-sungguh mengikat, karena setelah langkah 18 tidak ada
tombol mundur yang murah.

---

## FASE 5 — Setelah pindah

### Jalur deploy (menggantikan `railway up`, yang mati bersama Railway)

```bash
sudo tee /usr/local/bin/toa-deploy >/dev/null <<'EOF'
#!/bin/bash
set -Eeuo pipefail
cd /opt/toa
sudo -u toa git fetch origin && sudo -u toa git merge --ff-only origin/main
sudo -u toa .venv/bin/pip install -r requirements.txt
# env dimuat DI DALAM sudo — `Defaults env_reset` membuang variabel yang
# diekspor di luar, dan `migrate` lalu diam-diam mengenai SQLite baru sementara
# service tetap melayani Postgres: deploy separuh jadi, tanpa satu pun error.
m() { sudo -u toa bash -c 'set -a; . /etc/toa.env; set +a; cd /opt/toa && exec .venv/bin/python manage.py "$@"' _ "$@"; }
m migrate --noinput
m collectstatic --noinput
m periksa_index
test ! -f /opt/toa/db.sqlite3 || { echo "FATAL: SQLite terbuat — deploy DIHENTIKAN"; exit 1; }
systemctl restart toa
EOF
sudo chmod 755 /usr/local/bin/toa-deploy
```

### Break-glass geo-block (menggantikan `railway variables --set`, J12)

```bash
sudo tee /usr/local/bin/toa-geo-off >/dev/null <<'EOF'
#!/bin/bash
set -Eeuo pipefail
sed -i 's/^GEO_BLOCK_ENABLED=.*/GEO_BLOCK_ENABLED=False/' /etc/toa.env
systemctl restart toa      # EnvironmentFile dibaca saat START; reload TIDAK cukup
echo "geo-block MATI. Nyalakan: toa-geo-on"
EOF
sudo chmod 750 /usr/local/bin/toa-geo-off
```

Buat juga `toa-geo-on` dan `toa-allow <IP>`. **Simpan path-nya di password manager tim**, dan
ingat: skrip ini butuh SSH. Kalau SSH/ufw/jaringan yang rusak, jalan masuknya **konsol VNC
Contabo** — sudah diuji di FASE 3.

### Cadangan — rclone + crypt ke Google Drive (keputusan pemilik)

```bash
# Sekali: rclone config → remote "gdrive" (Google Drive) → remote "gcrypt" (crypt,
# membungkus gdrive:toa-arsip). SIMPAN kedua password crypt di password manager,
# BUKAN di VPS. Tanpa keduanya, cadangan tidak bisa dibuka selamanya.
sudo tee /usr/local/bin/toa-backup >/dev/null <<'EOF'
#!/bin/bash
set -Eeuo pipefail                    # pipefail: tanpa ini pg_dump mati di tengah
                                      # tetap menghasilkan berkas terpotong yang
                                      # TAMPAK seperti cadangan
STAMP=$(date +%F-%H%M); TMP=/var/backups/toa/db-$STAMP.dump
# Kompresi SAMA dengan FASE 2 — bukan `-Fc -Z6`. Dua alasan: (1) seluruh model disk
# dikalibrasi pada rasio zstd, jadi gzip membuat estimasi ruang mewarisi angka yang
# salah; (2) `-Z6` gzip satu-utas atas DB 137 GB = ~85-90 menit satu core tiap 03:00
# sambil membaca seluruh heap dan MENGOSONGKAN page cache tepat sebelum jam kerja.
pg_dump --format=directory --jobs=4 --compress=zstd:3 -d toa -f "$TMP"
pg_restore -l "$TMP" >/dev/null       # TOC terbaca = arsip tidak rusak
tar -cf - "$TMP" | sha256sum > "$TMP.sha256"
rclone copy "$TMP" "$TMP.sha256" gcrypt:harian/
rclone copy /var/lib/toa/media gcrypt:media/ --max-age 48h   # pg_dump tak mencakup berkas
# +1 hari, BUKAN +7. Verifikasi (pg_restore -l + sha256) sudah terjadi SEBELUM unggah,
# jadi salinan lokal hanya perlu hidup sampai rclone terkonfirmasi. `-mtime +7` menahan
# 8 salinan x 0,4xDB = 3,2xDB: dump lokal mengalahkan databasenya sendiri dan menjebol
# disk di bulan ~6. Ini cacat kapasitas terbesar rencana, dan ia duduk di FASE 5
# sehingga lolos SEMUA gerbang.
find /var/backups/toa -name 'db-*.dump*' -mtime +1 -delete
# 14 hari harian, BUKAN 90. Retensi 90 hari x dump penuh = 36xDB tersimpan: pada pool
# 2 TB itu pecah di bulan ~4. Retensi panjang ditangani salinan mingguan/bulanan.
rclone delete gcrypt:harian/ --min-age 14d
EOF
sudo chmod 700 /usr/local/bin/toa-backup
# 03:00 WIB — aman terhadap jendela unggah 13:00–20:00
# Alarm WAJIB sampai ke manusia. `|| logger` menulis ke journald yang tidak pernah
# dibaca siapa pun — cadangan yang gagal senyap sama dengan tidak ada cadangan.
# Pakai heartbeat monitor uptime (URL ping saat SUKSES; alarm justru saat ping HILANG,
# sehingga VPS mati total pun tetap membunyikan alarm) + email.
echo '0 3 * * * root /usr/local/bin/toa-backup && curl -fsS -m 10 "$HEARTBEAT_URL" || logger -p user.err "toa-backup GAGAL"' \
  | sudo tee /etc/cron.d/toa-backup
```

- [ ] **Uji restore cadangan sungguhan** — sekali sekarang, lalu **tiap kuartal**. Cadangan yang belum diuji bukan cadangan
- [ ] Putar `SECRET_KEY` & password DB (J13) — sudah dilakukan di FASE 1/3, konfirmasi
- [ ] Timer `clearsessions` mingguan (`django_session` tidak pernah membersihkan diri)
- [ ] Timer sapu `media/staging/` — di Railway sampah ini hilang tiap deploy; **di VPS ia menetap**
- [ ] Batasi journald: `SystemMaxUse=2G` di `/etc/systemd/journald.conf`
- [ ] Monitor uptime: tambahkan IP-nya ke `GEO_BLOCK_ALLOWLIST` **dan** WAF Skip; assert **200 + isi halaman**, jangan "bukan 5xx" (403 dari origin rusak terlihat sama)
- [ ] Cron bulanan menyegarkan rentang Cloudflare di ufw
- [ ] Tetapkan **kuota Google Drive** yang tersedia sebelum mengandalkan retensi apa pun
- [ ] Nyalakan Auto Backup Contabo (**€6,70/bln di tier VPS 12** — €8,35 adalah harga VPS 16)
      sebagai lapis kedua. **Snapshot Contabo BUKAN cadangan**: terhapus otomatis setelah 30
      hari dan hangus total bila VPS dibatalkan — ia rollback pra-update, bukan DR
- [ ] **Tenggat keputusan bulan ke-12: partisi bulanan / arsip `transactions_transaction`.**
      Ini syarat kelangsungan, bukan optimasi — lewat ±150 GB, `pg_repack` menuntut 0,9×DB
      ruang bebas DAN jendela 6–14 jam, dan keduanya berhenti tersedia pada saat yang sama

### ❌ Klaim v1 yang HARUS dihapus

> ~~"Berkas unggahan sekarang persisten — tidak hilang saat deploy lagi"~~

**Salah.** `sources/services.py:275` membuat `Upload` **tanpa pernah mengoper `file=`** —
diverifikasi tiga cara, termasuk `git log -S "file=" -- sources/services.py` yang mengembalikan
**nol commit**. Berkasnya tidak pernah disimpan, jadi disk persisten tidak mengubah apa pun.
Sebabnya bukan efemeralitas Railway melainkan **kode**. Konsekuensi baiknya: 14.936 baris Upload
itu metadata murni dan **sepenuhnya inert** — tak ada halaman yang 500, tak ada yang perlu
dimigrasikan dari `MEDIA_ROOT`. Mewujudkan janji itu butuh perubahan kode + kebijakan retensi:
rilis tersendiri, bukan butir ceklis migrasi.

---

## Sesudah stabil — bukan sekarang

**Worker latar untuk rekonsiliasi.** Rekonsiliasi berjalan sinkron di dalam permintaan HTTP dan
sudah menyentuh batas ~100 detik Cloudflare. Batas itu **tidak hilang** dengan pindah ke VPS —
yang hilang adalah permintaan yang lama, dan itu butuh antrean + worker. Di VPS keduanya proses
biasa (di Railway = dua service berbayar). **Kerjakan setelah migrasi terbukti stabil**, jangan
sekaligus: memindahkan server dan mengubah cara kerja rekonsiliasi bersamaan membuat penyebab
masalah tak bisa dilacak.

Backlog lain yang sudah terdokumentasi: ~870 MB index mati · cacat `row_hash` lintas-bentuk
QRIS Flyer · 6.118 baris sampah tak bertanggal · `shared_buffers` naik dari 6 GB (butuh `EXPLAIN`
query **mesin**, bukan halaman laporan).
