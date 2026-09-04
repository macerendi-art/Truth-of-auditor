#!/usr/bin/env bash
# Pemantauan kesehatan terjadwal (B1) -- lihat docs/runbook-pemantauan-2026-09-04.md.
#
# Ini SATU-SATUNYA hal yang hilang dari `periksa_kesehatan`/`periksa_index`: keduanya sudah
# jadi dan bagus (lihat docstring masing-masing di core/management/commands/), tapi tidak ada
# yang menjalankannya selain manusia yang mengingatnya. Skrip ini yang menjalankannya, harian,
# lewat systemd timer -- lihat toa-kesehatan.service/.timer di direktori yang sama.
#
# Menyatukan EMPAT hal yang wajib dipantau:
#   1. Cadangan TERAKHIR -- verdict DAN umur `terakhir_ok` dari ~/cadangan/status.json (A1,
#      scripts/cadangan/backup-harian.sh). Cadangan sukses tapi berumur berhari-hari dianggap
#      GAGAL juga -- bukan cuma "berkasnya ada". Ini SATU hal yang eksplisit diminta jangan
#      sampai terlewat: cadangan yang gagal DIAM-DIAM adalah mode kegagalan paling mahal di sini.
#   2. Index hilang/INVALID (F6) -- lewat `manage.py periksa_index` (F6 murni) DAN
#      `manage.py periksa_kesehatan` (yang menyertakannya lagi secara internal, bagian "Index
#      (hilang/invalid)", plus batch/sequence/referensi/patokan). Sengaja DIJALANKAN DUA KALI:
#      `periksa_index` sendirian memberi status F6 yang bersih tanpa perlu mengurai teks keluaran
#      `periksa_kesehatan`, dengan biaya satu kueri SQL tambahan yang murah. Logikanya TIDAK
#      diduplikasi di sini -- keduanya memanggil `core.management.commands.periksa_index`
#      apa adanya.
#   3. Ukuran basis data PRODUKSI (byte/MB/GB) -- BUKAN sisa disk. `periksa_kesehatan` sendiri
#      TIDAK bisa menjawab sisa disk produksi kalau dijalankan dari VPS: bagian "Ruang disk"-nya
#      SENGAJA mengukur direktori tempat PERINTAH itu berjalan (lihat docstring-nya) -- dari sini
#      itu disk VPS, BUKAN volume Postgres produksi di Railway. Bagian itu tetap tampil di laporan
#      (info disk VPS, bagian 4) tapi tidak pernah menjawab sisa disk produksi.
#
#      ⚠️ REVISI 04-09-2026 (VETO PEMILIK, wajib): versi sebelumnya mengukur sisa disk NYATA lewat
#      `COPY dfout FROM PROGRAM 'df -kP <data_directory>'` -- superuser Postgres produksi
#      (`current_user` punya `rolsuper=true` lewat proxy) bisa menjalankan PERINTAH SHELL apa pun
#      di host database lewat jalur itu. Itu primitif eksekusi-kode PERMANEN terhadap produksi di
#      dalam skrip pemantauan HARIAN -- tidak dapat diterima terlepas dari status kredensial mana
#      pun (rotasi kunci A3 tetap berjalan terpisah). Pemilik MEMVETO; dicabut di SINI dan di
#      salinan VPS yang sedang berjalan -- tidak boleh ada satu pun yang tertinggal.
#
#      Pendekatan pengganti, TANPA eksekusi apa pun di host produksi: satu SELECT biasa,
#      `pg_database_size(current_database())` -- bukan superuser, bukan COPY, bukan PROGRAM.
#      Laju tumbuh SUDAH dipantau bagian 4 (`periksa_kesehatan` Django, baris "Laju tumbuh: ..."
#      dari potret media/kesehatan.json) -- TIDAK diduplikasi di sini. Sisa disk PRODUKSI
#      SESUNGGUHNYA (persen/GB) TIDAK BISA lagi dijawab skrip ini -- itu keputusan SADAR, bukan
#      lupa: cek metrik volume Postgres di dashboard Railway (Project -> service Postgres ->
#      Metrics) untuk angka itu; lihat juga opsi (C) Railway cron di
#      docs/runbook-pemantauan-2026-09-04.md. **Presisi turun dari "persen sisa disk terukur" ke
#      "ukuran DB + laju tumbuh saja" -- dinyatakan terang-terangan di sini, bukan dipura-purakan
#      setara.**
#   4. (B6, hidup/mati layanan) SENGAJA TIDAK di sini -- lihat probe-layanan.sh: jadwalnya jauh
#      lebih sering (tiap 5 menit vs harian di sini) dan tak butuh DB sama sekali. Menyatukannya
#      dengan cek berat (Django + SQL, jadwal harian) di sini akan memaksa salah satu jadi salah
#      jadwal -- probe jadi terlalu jarang, atau cek berat jadi terlalu sering membebani produksi.
#
# Menjalankan `manage.py periksa_kesehatan` DAN `periksa_index` terhadap PRODUKSI (lewat proxy
# TCP publik Railway) -- BUKAN basis data gladi migrasi lokal `toa` di VPS ini (itu cuma salinan
# drill/pembanding cutover Contabo, tidak mencerminkan insiden produksi nyata: batch, sequence,
# ukuran DB, semuanya beku di titik snapshotnya). Kredensial: `DATABASE_URL="$(cat
# ~/.prod-url)"` -- berkas itu TERBUKTI TANPA SANDI (`urlparse(...).password is None`, diperiksa
# lewat python3 sebelum skrip ini ditulis); psycopg/libpq mengisi sandinya sendiri dari
# ~/.pgpass persis seperti pg_dump/psql di backup-harian.sh. Sandi TIDAK PERNAH masuk argv/env
# secara eksplisit di skrip ini.
#
# Skrip ini HANYA MEMBACA -- tidak ada satu query pun di sini yang menulis ke produksi:
# `periksa_kesehatan`/`periksa_index` cuma SELECT (dibaca dari sumbernya, tak diubah di sini),
# potretnya sendiri ditulis LOKAL ke media/kesehatan.json (VPS, bukan produksi), dan bagian 3 di
# atas kini juga cuma SELECT (`pg_database_size`) -- tidak ada lagi eksekusi shell di host
# produksi sama sekali (lihat revisi 04-09-2026 di bagian 3).
#
# App Django yang dipakai adalah checkout gladi migrasi 2026-09-01 di /opt/toa (dipasang oleh
# ~/migrasi/fase3-app.sh) -- SUDAH ADA, tidak dibangun ulang di sini. `periksa_index.py` di sana
# identik byte-untuk-byte dengan repo (dibandingkan sebelum skrip ini ditulis);
# `periksa_kesehatan.py` sempat berupa berkas belum ter-commit di checkout itu dari eksplorasi
# sebelumnya, juga identik.
#
# ⚠️ KOREKSI 04-09-2026 (tinjauan akhir P2): kalimat lama "checkout itu boleh basi" hanya SEPARUH
# benar. `periksa_index` membandingkan Transaction._meta.indexes dari KODE YANG BERJALAN dengan
# pg_index: index INVALID terdeteksi dari kode mana pun (seluruh index tabel dibaca dari katalog),
# tapi index HILANG hanya bisa dilaporkan kode yang mengenal namanya -- checkout basi melaporkan
# "Bersih" untuk index baru yang tak pernah terbangun. Dua hal ditambahkan karena itu: revisi
# /opt/toa (commit + branch) dicatat di log & status.json supaya drift TERLIHAT (memperbarui
# checkout ke commit yang di-deploy = langkah pasca-deploy wajib, runbook rollback), dan bagian 2b
# memeriksa index INVALID DB-wide lewat SQL langsung -- setara gerbang J4 cadangan, tak bergantung
# checkout sama sekali (index HILANG memang tetap hanya terjawab kode terbaru; dinyatakan apa adanya).
set -uo pipefail   # TANPA -e SENGAJA: prinsip "laporan selalu utuh" (periksa_kesehatan aturan
                   # #1 di docstring-nya) -- satu gerbang gagal tidak boleh membungkam gerbang
                   # lainnya. Tiap bagian di bawah menangkap kegagalannya sendiri.
umask 077

APP_DIR="${APP_DIR:-/opt/toa}"
ENV_FILE="${ENV_FILE:-/etc/toa.env}"
PROD_URL_FILE="${PROD_URL_FILE:-/home/toa/.prod-url}"
CADANGAN_STATUS="${CADANGAN_STATUS:-/home/toa/cadangan/status.json}"
STATE_DIR="${STATE_DIR:-/home/toa/kesehatan}"
LOG_FILE="$STATE_DIR/kesehatan.log"
STATUS_FILE="$STATE_DIR/status.json"

# Ambang. AMBANG_CADANGAN_JAM: lihat docs/runbook-cadangan-2026-09-04.md (jadwal 03:00 harian +
# jitter 5 menit -- 26 jam memberi sedikit slack di atas siklus 24 jam sebelum dianggap basi).
# (DISK_BAHAYA/DISK_PERHATIAN dulu ada di sini untuk ambang persen sisa disk -- dicabut bersama
# COPY FROM PROGRAM, lihat revisi bagian 3 di atas; bagian 3 sekarang tak punya ambang BAHAYA/
# PERHATIAN sendiri, cuma INFO, persis pola "laju tumbuh tak punya ambang" di
# core/management/commands/periksa_kesehatan.py.)
AMBANG_CADANGAN_JAM="${AMBANG_CADANGAN_JAM:-26}"

mkdir -p "$STATE_DIR"

TS_MULAI="$(date -Is)"
STAMP="$(date +%F)"

log() { printf '[%s] %s\n' "$(date '+%F %T %Z')" "$*" | tee -a "$LOG_FILE" >&2; }

log "=== mulai pemeriksaan kesehatan $STAMP ==="

[ -r "$PROD_URL_FILE" ] || { log "FATAL: $PROD_URL_FILE tidak terbaca"; exit 2; }
PROD_URL="$(cat "$PROD_URL_FILE")"

# Status keseluruhan naik monoton: OK -> PERHATIAN -> BAHAYA, tak pernah turun dalam satu jalan.
KESELURUHAN="OK"
naikkan() {
  local baru="$1"
  case "$KESELURUHAN:$baru" in
    *:BAHAYA) KESELURUHAN="BAHAYA" ;;
    OK:PERHATIAN) KESELURUHAN="PERHATIAN" ;;
  esac
}

jalankan_manage() {
  ( cd "$APP_DIR" \
      && set -a && . "$ENV_FILE" && set +a \
      && DATABASE_URL="$PROD_URL" "$APP_DIR/.venv/bin/python" manage.py "$@" )
}

# --- 1. Cadangan terakhir ----------------------------------------------------
log "--- 1. Cadangan terakhir ($CADANGAN_STATUS) ---"
CAD_STATUS="BAHAYA"
CAD_PESAN="berkas status cadangan tidak terbaca di $CADANGAN_STATUS -- cadangan belum pernah jalan, atau jalur salah?"
CAD_VERDICT=""
CAD_TERAKHIR_OK=""
CAD_UMUR_JAM=""

if [ -r "$CADANGAN_STATUS" ]; then
  CAD_VERDICT="$(jq -r '.verdict // empty' "$CADANGAN_STATUS" 2>/dev/null || true)"
  CAD_TERAKHIR_OK="$(jq -r '.terakhir_ok // empty' "$CADANGAN_STATUS" 2>/dev/null || true)"

  if [ -n "$CAD_TERAKHIR_OK" ]; then
    T_OK_EPOCH="$(date -d "$CAD_TERAKHIR_OK" +%s 2>/dev/null || true)"
    if [ -n "$T_OK_EPOCH" ]; then
      CAD_UMUR_JAM="$(awk -v a="$T_OK_EPOCH" -v b="$(date +%s)" 'BEGIN{printf "%.1f", (b-a)/3600}')"
    fi
  fi

  if [ -z "$CAD_VERDICT" ]; then
    CAD_STATUS="BAHAYA"
    CAD_PESAN="berkas status ada tapi field 'verdict' kosong/tidak terbaca -- berkas mencurigakan"
  elif [ "$CAD_VERDICT" != "OK" ]; then
    CAD_STATUS="BAHAYA"
    CAD_PESAN="run cadangan TERAKHIR verdict='$CAD_VERDICT' (bukan OK)"
  elif [ -z "$CAD_TERAKHIR_OK" ]; then
    CAD_STATUS="BAHAYA"
    CAD_PESAN="verdict OK tapi 'terakhir_ok' kosong -- tak pernah ada run yang benar-benar sukses"
  elif [ -z "$CAD_UMUR_JAM" ]; then
    CAD_STATUS="PERHATIAN"
    CAD_PESAN="terakhir_ok='$CAD_TERAKHIR_OK' tak bisa diuraikan sebagai tanggal"
  elif awk -v u="$CAD_UMUR_JAM" -v a="$AMBANG_CADANGAN_JAM" 'BEGIN{exit !(u>=a)}'; then
    CAD_STATUS="BAHAYA"
    CAD_PESAN="terakhir_ok berumur ${CAD_UMUR_JAM} jam (>= ambang ${AMBANG_CADANGAN_JAM} jam) -- CADANGAN SAH SUDAH BASI walau run terakhir kebetulan verdict OK"
  else
    CAD_STATUS="OK"
    CAD_PESAN="verdict OK, terakhir_ok berumur ${CAD_UMUR_JAM} jam (< ambang ${AMBANG_CADANGAN_JAM} jam)"
  fi
fi
log "$CAD_STATUS: $CAD_PESAN"
naikkan "$CAD_STATUS"

# --- 2. Index hilang/INVALID (F6), murni -------------------------------------
# Revisi /opt/toa dicatat lebih dulu: hasil periksa_index hanya selengkap kode yang menjalankannya
# (lihat KOREKSI di kepala berkas). Gagal membaca git = "?" -- bukan alasan menggagalkan laporan.
REVISI_APP="$(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo '?')"
BRANCH_APP="$(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
log "--- 2. Index F6 (manage.py periksa_index, produksi; kode $APP_DIR @ $REVISI_APP [$BRANCH_APP]) ---"
INDEX_OUT="$(jalankan_manage periksa_index 2>&1)"
INDEX_KODE=$?
{ echo "### periksa_index ($TS_MULAI) ###"; echo "$INDEX_OUT"; } >> "$LOG_FILE"
if [ "$INDEX_KODE" -eq 0 ]; then
  INDEX_STATUS="OK"
  INDEX_PESAN="$(echo "$INDEX_OUT" | tail -1)"
else
  INDEX_STATUS="BAHAYA"
  INDEX_PESAN="periksa_index keluar $INDEX_KODE -- ada index hilang/invalid (rincian: $LOG_FILE)"
fi
log "$INDEX_STATUS: $INDEX_PESAN"
naikkan "$INDEX_STATUS"

# --- 2b. Index INVALID DB-wide, SQL langsung (tak bergantung checkout) ------
# Setara gerbang J4 di scripts/cadangan/backup-harian.sh: pg_dump membuang index invalid diam-diam
# dan J4 membatalkan dump bila ada satu pun -- jadi yang sama harus terlihat di sini SEHARI
# SEBELUM cadangan berhenti, dari kode mana pun. Satu SELECT atas pg_index, bukan superuser.
log "--- 2b. Index INVALID DB-wide (SELECT pg_index, produksi) ---"
INVALID_DBWIDE="$(psql "$PROD_URL" -qtAc "SELECT i.indexrelid::regclass || ' on ' || i.indrelid::regclass FROM pg_index i WHERE NOT i.indisvalid;" 2>>"$LOG_FILE")"
INVALID_KODE=$?
if [ "$INVALID_KODE" -ne 0 ]; then
  INVALID_STATUS="PERHATIAN"
  INVALID_PESAN="query pg_index ke produksi gagal (lihat $LOG_FILE)"
elif [ -n "$(echo "$INVALID_DBWIDE" | tr -d '[:space:]')" ]; then
  INVALID_STATUS="BAHAYA"
  INVALID_PESAN="index INVALID di produksi (cadangan besok akan DIBATALKAN gerbang J4): $(echo "$INVALID_DBWIDE" | tr '\n' ';')"
else
  INVALID_STATUS="OK"
  INVALID_PESAN="tidak ada index invalid di seluruh basis data produksi"
fi
log "$INVALID_STATUS: $INVALID_PESAN"
naikkan "$INVALID_STATUS"

# --- 3. Ukuran basis data PRODUKSI (pg_database_size, TANPA eksekusi shell) --
# COPY FROM PROGRAM DICABUT 04-09-2026 (veto pemilik) -- lihat penjelasan panjang di kepala
# berkas ini. Pengganti: satu SELECT biasa, tak butuh superuser, tak menjalankan apa pun di host.
# Ini TIDAK menjawab sisa disk produksi (persen/GB) -- itu keputusan sadar, presisi turun,
# dinyatakan di sini apa adanya. Laju tumbuh ada di bagian 4 (periksa_kesehatan Django), tak
# diulang di sini. Tanpa ambang BAHAYA/PERHATIAN sendiri (tak ada kapasitas yang bisa dipakai
# menilainya dari sini) -- selalu INFO kecuali gagal dibaca sama sekali, pola yang sama dengan
# "laju tumbuh tak punya ambang" di core/management/commands/periksa_kesehatan.py.
log "--- 3. Ukuran basis data produksi (pg_database_size, BUKAN sisa disk asli) ---"
DBSIZE_STATUS="INFO"
DBSIZE_PESAN="tak bisa membaca ukuran basis data produksi"
DBSIZE_BYTES=""

DBSIZE_RAW="$(psql "$PROD_URL" -qtAc 'SELECT pg_database_size(current_database());' 2>>"$LOG_FILE")" || DBSIZE_RAW=""
DBSIZE_RAW="$(echo "$DBSIZE_RAW" | tr -d '[:space:]')"
if ! echo "$DBSIZE_RAW" | grep -qE '^[0-9]+$'; then
  DBSIZE_STATUS="PERHATIAN"
  DBSIZE_PESAN="gagal membaca ukuran basis data produksi lewat pg_database_size (lihat $LOG_FILE)"
else
  DBSIZE_BYTES="$DBSIZE_RAW"
  # GB dengan 2 desimal kalau >=1 GB (lebih enak dipindai manusia di log harian utk DB berukuran
  # produksi); MB dengan 1 desimal di bawah itu.
  DBSIZE_MANUSIA="$(awk -v b="$DBSIZE_BYTES" 'BEGIN{
    gb = b/1024/1024/1024;
    if (gb >= 1) printf "%.2f GB", gb;
    else printf "%.1f MB", b/1024/1024;
  }')"
  DBSIZE_PESAN="ukuran basis data produksi: ${DBSIZE_MANUSIA} (pg_database_size, BUKAN sisa disk -- cek metrik volume Postgres di dashboard Railway utk sisa disk sesungguhnya; laju tumbuh: lihat bagian 4 di bawah)"
fi
log "$DBSIZE_STATUS: $DBSIZE_PESAN"
naikkan "$DBSIZE_STATUS"

# --- 4. periksa_kesehatan Django (mencakup index F6 lagi + batch + sequence +
#        tabel referensi + kueri patokan; lihat catatan di kepala berkas) -------
log "--- 4. periksa_kesehatan (Django, produksi) ---"
KES_OUT="$(jalankan_manage periksa_kesehatan 2>&1)"
KES_KODE=$?
{ echo "### periksa_kesehatan ($TS_MULAI) ###"; echo "$KES_OUT"; } >> "$LOG_FILE"
if [ "$KES_KODE" -eq 0 ]; then
  KES_STATUS="OK"
else
  KES_STATUS="BAHAYA"
fi
RINGKASAN_KES="$(echo "$KES_OUT" | grep -E 'BAHAYA .* PERHATIAN .* OK .* INFO' | tail -1 | sed -E 's/^ +//')"
log "$KES_STATUS: periksa_kesehatan keluar $KES_KODE -- ${RINGKASAN_KES:-tak ada baris ringkasan terbaca}"
naikkan "$KES_STATUS"

# --- Berkas status konsolidasi ------------------------------------------------
TS_SELESAI="$(date -Is)"
CAD_UMUR_JAM_JSON="${CAD_UMUR_JAM:-null}"
DBSIZE_BYTES_JSON="${DBSIZE_BYTES:-null}"

jq -n \
  --arg tanggal "$STAMP" --arg mulai "$TS_MULAI" --arg selesai "$TS_SELESAI" \
  --arg keseluruhan "$KESELURUHAN" \
  --arg cad_status "$CAD_STATUS" --arg cad_pesan "$CAD_PESAN" \
  --arg cad_verdict "$CAD_VERDICT" --arg cad_terakhir_ok "$CAD_TERAKHIR_OK" \
  --argjson cad_umur_jam "$CAD_UMUR_JAM_JSON" \
  --arg index_status "$INDEX_STATUS" --arg index_pesan "$INDEX_PESAN" \
  --arg app_dir "$APP_DIR" --arg revisi_app "$REVISI_APP" --arg branch_app "$BRANCH_APP" \
  --arg invalid_status "$INVALID_STATUS" --arg invalid_pesan "$INVALID_PESAN" \
  --arg dbsize_status "$DBSIZE_STATUS" --arg dbsize_pesan "$DBSIZE_PESAN" \
  --argjson dbsize_bytes "$DBSIZE_BYTES_JSON" \
  --arg kes_status "$KES_STATUS" --argjson kes_kode "$KES_KODE" \
  --arg kes_ringkasan "${RINGKASAN_KES:-}" \
  --arg log_file "$LOG_FILE" \
  '{
     tanggal: $tanggal,
     mulai: $mulai,
     selesai: $selesai,
     verdict: $keseluruhan,
     cadangan: {
       status: $cad_status, pesan: $cad_pesan, verdict_run_terakhir: $cad_verdict,
       terakhir_ok: (if ($cad_terakhir_ok|length) > 0 then $cad_terakhir_ok else null end),
       umur_jam: $cad_umur_jam
     },
     index_f6: { status: $index_status, pesan: $index_pesan,
                 kode_app: { dir: $app_dir, revisi: $revisi_app, branch: $branch_app } },
     index_invalid_dbwide: { status: $invalid_status, pesan: $invalid_pesan },
     ukuran_db_produksi: { status: $dbsize_status, pesan: $dbsize_pesan, bytes: $dbsize_bytes },
     periksa_kesehatan_django: { status: $kes_status, kode_keluar: $kes_kode, ringkasan: $kes_ringkasan },
     log_file: $log_file
   }' > "$STATUS_FILE.tmp"
mv "$STATUS_FILE.tmp" "$STATUS_FILE"

log "=== SELESAI: $KESELURUHAN ==="
case "$KESELURUHAN" in
  BAHAYA) exit 1 ;;
  *) exit 0 ;;
esac
