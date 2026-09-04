#!/usr/bin/env bash
# Cadangan harian database produksi Truth of Auditor.
#
# Ditarik dari Railway (produksi) LEWAT PROXY TCP publik, dijalankan dari VPS
# `toa` (satu-satunya host yang boleh melakukan ini — lihat larangan di
# docs/runbook-cadangan-2026-09-04.md). Kredensial TIDAK PERNAH masuk argv:
# host/port/db ada di ~/.prod-url (tanpa sandi), sandi diambil ~/.pgpass oleh
# psql/pg_dump sendiri.
#
# Diturunkan dari ~/migrasi/dump-run.sh (gladi migrasi 2026-09-01), dengan DUA
# perbedaan sengaja:
#   1. TANPA --snapshot=$SNAP / ~/snap.out — itu artefak koordinasi cutover
#      migrasi (menahan satu transaksi REPEATABLE READ terbuka supaya dump dan
#      baseline query membaca titik waktu yang PERSIS sama). Cadangan harian
#      berdiri sendiri tidak butuh itu: `pg_dump -j` sudah membuat snapshot
#      sinkronnya sendiri di awal untuk keperluan worker paralelnya, dan
#      mengandalkan ~/snap.out di sini hanya akan gagal karena berkas itu
#      cuma diperbarui saat gladi migrasi berjalan.
#   2. Gerbang J4 di paling awal — lihat komentar di bawah.
#
# Dijalankan lewat systemd (lihat toa-cadangan.service/.timer di direktori
# yang sama), bukan cron — supaya dapat OnFailure + Persistent=true.
set -euo pipefail
umask 077

PROD_URL_FILE="${PROD_URL_FILE:-/home/toa/.prod-url}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/toa}"
STATE_DIR="${STATE_DIR:-/home/toa/cadangan}"
LOG_FILE="$STATE_DIR/backup.log"
STATUS_FILE="$STATE_DIR/status.json"

mkdir -p "$STATE_DIR" "$BACKUP_DIR"

STAMP="$(date +%F)"
TS_MULAI="$(date -Is)"
DUMPDIR="$BACKUP_DIR/dump-$STAMP"
TOC_FILE="$BACKUP_DIR/toc-$STAMP.txt"
SHA_FILE="$BACKUP_DIR/dump-$STAMP.sha256"

log() {
  printf '[%s] %s\n' "$(date '+%F %T %Z')" "$*" | tee -a "$LOG_FILE" >&2
}

# Tulis/perbarui berkas status yang dipantau B1. Prinsip desain: berkas ini
# HARUS mencerminkan hasil percobaan TERAKHIR (OK atau GAGAL), bukan sekadar
# "apakah ada berkas dump" — dump yang ada tapi TOC-nya tak terbaca, atau
# gerbang J4 yang menolak, tetap harus menulis verdict GAGAL di sini. Field
# `terakhir_ok` dipertahankan lintas-run (lewat jq, dibaca dari status lama)
# supaya B1 tetap tahu "kapan terakhir kali BENAR berhasil" walau beberapa
# run terakhir berturut-turut gagal — itu yang membedakan "baru saja gagal
# sekali" dari "sudah 5 hari tak ada cadangan sah".
tulis_status() {
  local verdict="$1" pesan="$2" kode="$3"
  local ts_selesai ukuran_bytes sha_ringkas terakhir_ok_prev terakhir_ok_baru

  ts_selesai="$(date -Is)"

  ukuran_bytes=0
  if [ -d "$DUMPDIR" ]; then
    ukuran_bytes="$(du -sb "$DUMPDIR" 2>/dev/null | cut -f1)"
    ukuran_bytes="${ukuran_bytes:-0}"
  fi

  sha_ringkas=""
  [ -f "$SHA_FILE" ] && sha_ringkas="$(sha256sum "$SHA_FILE" | cut -d' ' -f1)"

  terakhir_ok_prev=""
  if [ -f "$STATUS_FILE" ]; then
    terakhir_ok_prev="$(jq -r '.terakhir_ok // empty' "$STATUS_FILE" 2>/dev/null || true)"
  fi
  if [ "$verdict" = "OK" ]; then
    terakhir_ok_baru="$ts_selesai"
  else
    terakhir_ok_baru="$terakhir_ok_prev"
  fi

  jq -n \
    --arg tanggal "$STAMP" \
    --arg mulai "$TS_MULAI" \
    --arg selesai "$ts_selesai" \
    --arg verdict "$verdict" \
    --argjson kode "$kode" \
    --arg pesan "$pesan" \
    --arg dump_dir "$DUMPDIR" \
    --argjson ukuran_bytes "$ukuran_bytes" \
    --arg toc_file "$TOC_FILE" \
    --arg sha256_manifest "$SHA_FILE" \
    --arg sha256_manifest_hash "$sha_ringkas" \
    --arg terakhir_ok "$terakhir_ok_baru" \
    '{
      tanggal: $tanggal,
      mulai: $mulai,
      selesai: $selesai,
      verdict: $verdict,
      kode_keluar: $kode,
      pesan: $pesan,
      dump_dir: $dump_dir,
      ukuran_bytes: $ukuran_bytes,
      toc_file: $toc_file,
      sha256_manifest: $sha256_manifest,
      sha256_manifest_hash: $sha256_manifest_hash,
      terakhir_ok: (if ($terakhir_ok | length) > 0 then $terakhir_ok else null end)
    }' > "$STATUS_FILE.tmp"
  mv "$STATUS_FILE.tmp" "$STATUS_FILE"
}

gagal() {
  local pesan="$1"
  log "GAGAL: $pesan"
  tulis_status "GAGAL" "$pesan" 1
  exit 1
}

[ -r "$PROD_URL_FILE" ] || gagal "berkas $PROD_URL_FILE tidak terbaca"
PROD_URL="$(cat "$PROD_URL_FILE")"

log "=== mulai cadangan $STAMP ==="

# --- Gerbang J4 -------------------------------------------------------------
# pg_dump MEMBUANG index dengan indisvalid=false (terverifikasi di sumber
# pg_dump.c, getIndexes, REL_18_STABLE) — dump dari DB ber-index INVALID
# diam-diam kehilangan index itu, dan `migrate` tidak akan pernah
# membangunnya ulang karena migrasinya sudah tercatat selesai
# (core/db_ops.TambahIndexAman menelan kegagalan CONCURRENTLY). Setara
# dengan core/management/commands/periksa_index.py, tapi lewat SQL langsung
# ke pg_index — bukan `manage.py periksa_index`, karena Django tidak
# terpasang di VPS ini dan memasangnya cuma menambah permukaan yang tak
# perlu untuk satu query. Ini DB-wide (bukan hanya transactions_transaction)
# karena pg_dump membuang index invalid APA PUN tabelnya.
INVALID="$(psql "$PROD_URL" -Atc \
  "SELECT i.indexrelid::regclass || ' on ' || i.indrelid::regclass FROM pg_index i WHERE NOT i.indisvalid;" \
  2>>"$LOG_FILE")" || gagal "gerbang J4: query pg_index ke produksi gagal (lihat $LOG_FILE)"

if [ -n "$INVALID" ]; then
  gagal "gerbang J4: index INVALID ditemukan di produksi -> dump DIBATALKAN: $(echo "$INVALID" | tr '\n' ';')"
fi
log "gerbang J4 lolos: tidak ada index invalid di produksi"

# --- Dump ---------------------------------------------------------------
rm -rf "$DUMPDIR"
if ! pg_dump -d "$PROD_URL" --format=directory --jobs=4 --statistics \
      --compress=zstd:3 --file="$DUMPDIR" 2>>"$LOG_FILE"; then
  gagal "pg_dump gagal (lihat $LOG_FILE)"
fi
log "pg_dump selesai -> $DUMPDIR ($(du -sh "$DUMPDIR" 2>/dev/null | cut -f1))"

# --- Bukti arsip tidak rusak: TOC harus terbaca --------------------------
if ! pg_restore -l "$DUMPDIR" > "$TOC_FILE" 2>>"$LOG_FILE"; then
  gagal "pg_restore -l gagal membaca TOC -> arsip dump kemungkinan rusak"
fi
log "TOC terbaca: $(wc -l < "$TOC_FILE") baris -> $TOC_FILE"

# --- Checksum atas ISI dump (format=directory = banyak berkas, bukan satu) ---
if ! ( cd "$BACKUP_DIR" && find "dump-$STAMP" -type f -print0 | sort -z | xargs -0 sha256sum ) > "$SHA_FILE" 2>>"$LOG_FILE"; then
  gagal "sha256sum atas isi dump gagal"
fi
log "sha256 tersimpan: $(wc -l < "$SHA_FILE") berkas -> $SHA_FILE"

# --- Retensi: -mtime +1 (BUKAN +7) ---------------------------------------
# 8 salinan x ~0,4xDB menjebol disk sekitar bulan ke-6
# (docs/rencana-migrasi-contabo-2026-08-31.md, ±baris 1040-1065). Retensi
# pendek ini sengaja hanya menyisakan hari ini + kemarin di disk lokal.
# Best-effort: gagal membersihkan salinan lama TIDAK menggagalkan cadangan
# hari ini (sudah terbukti valid lewat TOC+sha256 di atas).
find "$BACKUP_DIR" -maxdepth 1 -name 'dump-*' -type d -mtime +1 -print -exec rm -rf {} + >> "$LOG_FILE" 2>&1 \
  || log "PERINGATAN: retensi dump-* lama mengalami kendala (lihat log)"
find "$BACKUP_DIR" -maxdepth 1 -name 'toc-*.txt' -mtime +1 -print -delete >> "$LOG_FILE" 2>&1 \
  || log "PERINGATAN: retensi toc-*.txt lama mengalami kendala (lihat log)"
find "$BACKUP_DIR" -maxdepth 1 -name 'dump-*.sha256' -mtime +1 -print -delete >> "$LOG_FILE" 2>&1 \
  || log "PERINGATAN: retensi dump-*.sha256 lama mengalami kendala (lihat log)"

tulis_status "OK" "cadangan berhasil" 0
log "=== SELESAI OK ==="
