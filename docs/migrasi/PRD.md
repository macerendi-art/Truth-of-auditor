# PRD Migrasi Railway → Contabo VPS

**Untuk:** eksekutor sesi terpisah, tanpa konteks selain repo ini.
**Runbook wajib:** `docs/rencana-migrasi-contabo-2026-08-31.md` (v2.1, 978 baris).
PRD ini menetapkan **apa yang harus benar**; rencana v2.1 menetapkan **cara mengerjakannya**.
Bila keduanya berbeda, **rencana v2.1 menang** — kecuali pada butir yang tercatat di
"Catatan penyimpangan" di akhir dokumen.

**Repo:** worktree sudah di-rebase ke `origin/main`, versi berjalan **v1.21.0**
(`core/version.py`). Skrip gerbang sudah ada: `scripts/gerbang.sh` + `scripts/gerbang.sql`.

---

## 1. Tujuan

Memindahkan **MESIN** — Railway → Contabo VPS Singapura, Ubuntu 24.04 — **tanpa mengubah satu
angka pun di layar**. Yang dipindahkan adalah tempat proses berjalan; yang tidak boleh bergeser:

- versi interpreter (**Python 3.11.10**, lewat deadsnakes — bukan 3.12 bawaan Ubuntu 24.04)
- versi pustaka (**Django 5.2.17**, `requirements.txt` dipatok dari freeze produksi)
- setelan perencana Postgres (paritas produksi terukur: `random_page_cost=1.1`,
  `effective_cache_size=16GB`, `work_mem=4MB`, `max_parallel_workers_per_gather=2`,
  `jit_above_cost=1e6`) — **tulis setiap parameter EKSPLISIT**; sebagian nilai produksi
  ber-`source=default`, jadi "paritas lewat default" mereproduksi kecelakaan, bukan keputusan
- perilaku aplikasi: rekonsiliasi tanggal lama menghasilkan angka identik

Definisi selesai: **GATE C lulus** dan satu tulisan nyata end-to-end (unggah + rekonsiliasi)
menghasilkan angka yang cocok.

## 2. Non-tujuan — ditulis eksplisit karena inilah yang paling sering merembes

- **Menyetel ulang Postgres.** `shared_buffers` 6GB tetap 6GB. `work_mem` 4MB tetap 4MB.
  Menaikkan apa pun berarti menyetel database di tengah pemindahan mesin: perlambatan
  apa pun jadi tak bisa dilacak. Profil restore FASE 2 (`maintenance_work_mem=2GB` dst.)
  adalah pengecualian **sementara** yang WAJIB dikembalikan sebelum verifikasi apa pun.
- **Menaikkan Python 3.11 → 3.12**, atau memutakhirkan pustaka apa pun.
- **Worker latar / antrean rekonsiliasi.** Tegas: **batas ~100 detik Cloudflare TIDAK hilang
  karena pindah VPS.** Worker membuat *permintaan* jadi pendek — batasnya sendiri tetap ada.
  Kerjakan setelah migrasi terbukti stabil; menggabungkannya membuat penyebab masalah
  tak bisa dilacak.
- **Backlog:** ~870 MB index mati · cacat `row_hash` lintas-bentuk QRIS Flyer · 6.118 baris
  tak bertanggal · migrasi berkas unggahan (**tidak ada yang perlu dimigrasikan**, lihat E3).
- **Memperbaiki `web/penjaga.py`, matcher, atau laporan apa pun.**

## 3. Batasan keras

| # | Batasan | Cara memverifikasi |
|---|---|---|
| **B1** | Produksi tidak tersentuh sampai FASE 4. FASE 0–3 **hanya BACA** dari Railway. | Tak ada satu pun perintah tulis ke Railway di transkrip FASE 0–3. Perintah `railway ssh` yang sah hanya `SELECT`/`pg_dump`/`railway variables --json`. |
| **B2** | Rotasi WAJIB `DATABASE_URL` + `SECRET_KEY` (J13: keduanya terekspos di log sesi 31-08-2026). **DILARANG** `SECRET_KEY_FALLBACKS` berisi kunci lama — kunci itulah yang bocor. | `grep -c '<potongan kunci lama>' /etc/toa.env` = **0**; `grep -c SECRET_KEY_FALLBACKS /etc/toa.env` = **0**. Password DB lahir dari `openssl rand`, dioper lewat heredoc stdin, tak pernah di argv. |
| **B3** | Geo-block KH-only tetap hidup melewati cutover. nginx WAJIB `proxy_set_header X-Forwarded-For $remote_addr;` (**TIMPA**). Dilarang `$proxy_add_x_forwarded_for`; dilarang `set_real_ip_from`/`real_ip_header` (J2). | Dari IP tak terdaftar: `curl -H 'X-Forwarded-For: 127.0.0.1' https://<host>/` → **403**. **200 = geo-block mati.** Diuji dua kali: gerbang FASE 3 dan GATE C. |
| **B4** | Dilarang menghapus data produksi. Railway hidup **≥7 hari** pasca-cutover dalam keadaan **read-only** (R5). `DROP DATABASE` hanya boleh mengenai `toa_new`/`toa_fase3` di VPS. | `grep -i 'drop database' ` di transkrip hanya menghasilkan `toa_new`/`toa_fase3`. Hari ke-7: `ALTER DATABASE railway ... default_transaction_read_only` masih `on`. |
| **B5** | Dilarang menyalin berkas sampel berisi username pemain ke repo. `samples/` dan `db.sqlite3` tetap terabaikan — **JANGAN PERNAH `git add -f`**. Keluaran gerbang dan dump hidup di luar checkout. | `git status --porcelain` bersih dari sampel; dump di `/var/backups/toa/`, bukan `/opt/toa/`. |
| **B6** | Setiap `manage.py` memuat env **DI DALAM** batas sudo (J1 + sudoers `Defaults env_reset`). | Pakai wrapper verbatim di bawah tabel, lalu tripwire `test ! -f /opt/toa/db.sqlite3`. |
| **B7** | `/media/` ditolak nginx (`location /media/ { deny all; }`) — isinya ekspor bank berisi username pemain asli. | `curl -sI https://<host>/media/` → **403**, bukan 200/404 dari `alias`. |

Wrapper B6 — **verbatim dari rencana v2.1**, jangan ditulis ulang:

```bash
toa_manage() {
  sudo -u toa bash -c 'set -a; . /etc/toa.env; set +a; cd /opt/toa && exec .venv/bin/python manage.py "$@"' _ "$@"
}
```

Alasan bentuk itu: `set -a; . /etc/toa.env; set +a` di shell **pemanggil** lalu `sudo -u toa …`
tidak bekerja — `Defaults env_reset` membuang `DATABASE_URL` dan `DEBUG` tepat sebelum Python
berjalan, Django jatuh ke SQLite, `migrate` mencetak sukses, dan `periksa_index` mengembalikan
"Tidak berlaku" dengan **exit 0**. Tripwire `test ! -f /opt/toa/db.sqlite3` adalah bukti termurah
bahwa env benar-benar sampai.

## 4. Errata terhadap v2 — status per 01-09-2026

- **E1/E2 — SELESAI, bukan cacat.** Dugaan bahwa tabel `web_hutangmanual` tidak ada, dan
  keraguan "28 vs 29 tabel", **berasal dari worktree yang basi 30+ commit**. Diverifikasi
  langsung di Postgres produksi: `to_regclass('public.web_hutangmanual')` mengembalikan tabel
  itu, dan `count(*) information_schema.tables WHERE table_schema='public'` = **29**.
  `scripts/gerbang.sql` sudah benar — ia bahkan **tidak meng-hardcode angka 29**: inventaris
  kedua sisi dibandingkan apa adanya, jadi kecurigaan worktree basi itu secara struktural tak
  bisa merusaknya. Worktree kini sudah di-rebase ke `origin/main` (v1.21.0, memuat
  `web/migrations/0004_hutang_manual.py`).
  **Pelajaran yang harus dibawa ke seluruh migrasi: jangan pernah menyimpulkan skema dari
  checkout — introspeksi produksi.**
- **E3 — klaim v1 "berkas unggahan jadi persisten" DICABUT.** `sources/services.py:275`
  membuat `Upload` **tanpa pernah mengoper `file=`**. Konsekuensinya: 14.936 baris `Upload`
  adalah metadata murni dan sepenuhnya inert — **tak ada yang perlu dimigrasikan dari
  `MEDIA_ROOT`**, dan disk persisten tidak mengubah apa pun. Mewujudkan janji itu = perubahan
  kode + kebijakan retensi, rilis tersendiri, bukan butir migrasi.
- **E4 — `resolved_by_batch` ada di `MatchResult`** (`reconciliation/models.py:104`), **bukan**
  di `Transaction`. Query verifikasi apa pun yang mencarinya di `transactions_transaction`
  akan gagal atau, lebih buruk, diam-diam mengukur hal lain.

## 5. Keputusan kapasitas

Sumber tunggal: bagian **"Penetapan ukuran mesin"** rencana v2.1 (diukur 01-09-2026, 8 riset
paralel + 2 skeptik adversarial). Jangan menyalin ulang tabelnya; baca di sana.

Yang mengikat di sini:

- **Cloud VPS 12 + add-on 800 GB SSD, region Singapura, Ubuntu 24.04.**
- **Beli 1 bulan dulu.** Contabo adalah undian node; jangan prepay node yang belum terbukti.
- Node lulus gerbang → **perpanjang lebih awal instance yang SAMA ke 12 bulan.**
  **JANGAN order ulang** demi diskon 24-bulan: order baru = node baru + **IP baru** = seluruh
  validasi + konfigurasi Cloudflare/geo-block hangus.
- **Risiko nyata bukan core atau RAM** (CPU ±50× berlebih, RAM 6× berlebih) melainkan
  **IOPS acak + steal time** — dua hal yang tidak diperbaiki dengan naik ke VPS 16, karena
  tier itu berbagi kelas vCPU dan tingkat penyimpanan yang sama persis. Disk adalah
  satu-satunya sumbu yang mengikat (±11 GB/bln terukur, bukan +5 GB/bln versi v2).
- Downgrade **mustahil** dan mengganti IP; upgrade swalayan dan gratis. Arah kesalahan yang
  murah adalah membeli lebih kecil lalu naik.

## 6. Kriteria sukses per gerbang

Biner. Tidak ada penilaian subjektif. Satu saja meleset → **BERHENTI**.

| Gerbang | Lulus bila |
|---|---|
| **GERBANG 0 & 1** (FASE 0) | `ssh toa@<IP>` berhasil **dan** `sudo whoami` → `root` tanpa diminta password · `ssh root@<IP>` dari mesin lain **DITOLAK** · `sshd -T` → `permitrootlogin no` **dan** `passwordauthentication no` · `ufw status` menampilkan **≥5** rentang Cloudflare **per port** (443 dan 80). |
| **FASE 1** | `postgresql@18-main` aktif · setiap setelan == baseline produksi **yang dibaca hari itu** (jangan percaya tabel dokumen) · **tidak ada `PENDING`** di `pg_settings.pending_restart` · `pg_encoding_to_char` = `UTF8` dan `datcollate` = `en_US.utf8` · `pg_lsclusters` menunjukkan port **5432**, bukan 5433. |
| **FASE 2** | `pg_restore --file=/dev/null "$DUMPDIR"` lolos (uji pemotongan sungguhan; `--list` tidak cukup) · `./scripts/gerbang.sh banding <IP> live` → **diff kosong** · **nol** `KOSONG-FATAL` · **nol** `BAHAYA-TABRAKAN-PK` · **nol** `valid=f` · **nol** `analyzed=BELUM-PERNAH` · pemilik tabel = `toa` untuk **29/29** · `EXPLAIN` query mesin memakai **`tx_toko_src_posted_idx`**, bukan Seq Scan. |
| **FASE 3** | Suite penuh (~1.700) → **0 gagal** · `curl -H 'X-Forwarded-For: 127.0.0.1' …` dari IP tak terdaftar → **403** · `curl -sI https://staging…/login/` dari IP operator → **200** · akses langsung ke IP VPS **ditolak** · URL ngawur → **404 polos**, bukan halaman kuning Django · `test ! -f /opt/toa/db.sqlite3` · reboot VPS → situs pulih **tanpa satu pun langkah manual** · login konsol **VNC Contabo teruji** · mode SSL/TLS zona = **Full (strict)**, tercatat · waktu **3 dashboard** (g25/k25/mxw) **tercatat** (patokan GATE B) · unggah **batch multi-berkas ±20 MB** berhasil · satu rekonsiliasi tanggal lama → angka **sama persis** dengan produksi · **wall-clock `run_batch` toko tersibuk ≤ 80 detik**. |
| **GATE A** (lgk 13) | `DB_VPS=toa_new ./scripts/gerbang.sh banding <IP> final` → **diff kosong sampai sen** · `toa_manage periksa_index` → **exit 0**. |
| **GATE B** (lgk 15) | Smoke test lokal `curl --resolve` → **200** · waktu dashboard **≤ patokan FASE 3 × 1,5**. |
| **GATE C** (lgk 17) | Lewat **hostname produksi asli** (publik masih ditahan WAF pemeliharaan): login berhasil · 3 dashboard benar · pratinjau ingest benar · `/bracket/` benar · `/rekap-bulanan/` benar · **DAN** `curl -H 'X-Forwarded-For: 127.0.0.1' …` → **403**. |

Catatan `run_batch ≤ 80 dtk`: tak satu pun gerbang lain mengukurnya — yang lain menghitung baris
atau membaca `EXPLAIN`. Rekonsiliasi berjalan **sinkron di dalam permintaan HTTP**, sudah
menyentuh batas ~100 dtk Cloudflare, dan `gunicorn --timeout 120` hanya memberi margin 20%.
Perlambatan single-core 25% (steal di vCPU bersama) mengubah 100 dtk jadi 133 dtk → **HTTP 524
di edge**. Di atas 80 dtk: worker latar naik prioritas di atas semua pekerjaan lain — dan
**tidak ada ukuran VPS yang memperbaikinya** (batasnya algoritma + GIL, bukan jumlah core).

## 7. Rencana mundur

**Sebelum langkah 18** (VPS masih `default_transaction_read_only=on`, R2) — abort gratis,
identik di titik mana pun:

1. Nonaktifkan WAF pemeliharaan.
2. `ALTER DATABASE railway RESET default_transaction_read_only;`
3. Start service web Railway.

**DNS tidak pernah disentuh** dan VPS tidak pernah menerima tulisan, jadi tidak ada yang perlu
direkonsiliasi. Biaya ≈10 menit.

**Setelah langkah 18** — rollback DNS ke Railway diizinkan **HANYA bila watermark VPS belum
bergerak** (R4). Watermark diambil **dua kali** (pasca-restore dan saat membuka tulisan) dan
memakai **`pg_stat_user_tables.n_tup_upd`**, bukan hanya `max(id)` (R3): tulisan berbentuk
**UPDATE** — `consumed_by_batch`, flip bucket late-settlement, `resolved_by_batch` — tidak
menaikkan `max(id)` sama sekali, jadi `max(id)` sendirian **buta** terhadap kelas tulisan yang
justru paling merusak bila ditinggalkan.

Bila watermark **sudah** bergerak: **maju-perbaiki**, atau migrasi balik **penuh**.
**Merge parsial tidak pernah diizinkan** — satu unggah+rekonsiliasi menulis ke **12+ tabel**,
dengan **UPDATE di tempat pada baris lama** (late settlement membalik hasil di batch
sebelumnya), dan kedua sisi melanjutkan `nextval` dari titik yang sama → **PK kembar untuk
baris berbeda**. `ReviewAction`/`AuditLog` adalah produk yang integritasnya dijual aplikasi ini.

**Dua batas abort — tidak bisa ditawar:**

| Jam | Kondisi | Tindakan |
|---|---|---|
| **08:45** | Dump belum selesai | **Abort** |
| **11:00** | GATE A belum lulus | **Abort** |

**Break-glass:**

| Kegagalan | Jalan keluar |
|---|---|
| Terkunci geo-block | `toa-geo-off` — **butuh SSH**. `GEO_BLOCK_BYPASS_STAFF` **BUKAN** pintu darurat (J12: menuntut sesi terautentikasi; setelah rotasi `SECRET_KEY` semua sesi mati). Dari luar Kamboja, satu-satunya pintu adalah `GEO_BLOCK_ALLOWLIST`. |
| SSH / ufw / jaringan rusak | **Konsol VNC Contabo** — wajib sudah diuji di FASE 3, bukan ditemukan saat darurat. |
| — | `railway variables --set GEO_BLOCK_ENABLED=false` **mati bersama Railway** (J12). Jangan mengandalkannya pasca-cutover. |

---

## Catatan penyimpangan

Dua angka di bawah **tidak ada** di rencana v2.1; keduanya dipasok instruksi penulisan PRD ini
dan dipertahankan karena gerbang biner menuntut angka, bukan kalimat. Bila eksekutor menganggap
angkanya salah, rencana v2.1 tidak akan menyanggah — putuskan sadar, jangan diam-diam.

1. **GATE B: "waktu dashboard ≤ patokan FASE 3 × 1,5".** Rencana v2.1 langkah 15 hanya menulis
   "waktu dashboard vs FASE 3" tanpa pengali. `×1,5` adalah ambang yang ditetapkan PRD ini.
2. **"Biaya abort ≈10 menit".** Rencana v2.1 hanya menyebut abort "murah dan identik" tanpa
   estimasi durasi.

Tidak ada penyimpangan lain: seluruh isi B1–B7, E1–E4, kriteria gerbang, dan aturan R1–R5
berasal dari rencana v2.1 dan sudah diverifikasi ulang terhadap repo (v1.21.0,
`reconciliation/models.py:104`, `sources/services.py:275`, `scripts/gerbang.sql`).
Daftar gerbang FASE 3 di sini **lebih panjang** dari yang diminta instruksi karena rencana v2.1
memuat butir tambahan — terutama *"satu rekonsiliasi tanggal lama → angka sama persis"*, yang
merupakan uji harfiah atas tujuan §1 dan tidak boleh dijatuhkan.
