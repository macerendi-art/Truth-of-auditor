#!/usr/bin/env bash
# gerbang.sh — GERBANG Fase 2 / Fase 4 migrasi Truth of Auditor (Railway -> Contabo).
# Pengganti empat perintah psql di rencana lama. Membandingkan produksi dengan
# restore lewat `diff`, bukan lewat mata, dan memeriksa index/constraint/
# sequence/statistik yang sebelumnya tidak diperiksa sama sekali.
#
#   ./gerbang.sh banding <IP-VPS> live   # Fase 2 (produksi masih menulis)
#   ./gerbang.sh banding <IP-VPS> final  # Fase 4 (penulisan sudah dihentikan)
#
# DUMP & RESTORE TIDAK ADA DI SINI — dengan sengaja. Prosedurnya ada di
# docs/rencana-migrasi-contabo-2026-08-31.md FASE 2 bagian C-G, karena ia
# butuh hal-hal yang tak bisa diotomatiskan dari satu berkas: sesi snapshot
# MVCC yang harus tetap terbuka di jendela tmux terpisah, dump yang DITARIK
# OLEH VPS (bukan lewat laptop), dan restore ke database BARU (toa_new) yang
# lalu ditukar namanya. Versi awal skrip ini memakai
# `railway ssh "pg_dump -Fc" > berkas` dan me-restore langsung ke `toa` —
# dua-duanya justru yang dilarang rencana itu.
#
# Butuh: gerbang.sql di direktori yang sama.

set -Eeuo pipefail
shopt -s inherit_errexit 2>/dev/null || true

KERJA="${KERJA:-$HOME/toa-migrasi}"
SQL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/gerbang.sql"
RAILWAY_SVC="${RAILWAY_SVC:-Postgres}"
DB_PROD="${DB_PROD:-railway}"
DB_VPS="${DB_VPS:-toa}"   # Fase 4: DB_VPS=toa_new ./gerbang.sh banding ...
VPS_USER="${VPS_USER:-toa}"
mkdir -p "$KERJA"

mati() { echo; echo "!! GAGAL: $*" >&2; exit 1; }
oke()  { echo "   ok: $*"; }

# ------------------------------------------------------------- banding -------
cmd_banding() {
  local ip="${1:?IP VPS}" mode="${2:?live|final}"
  local full
  case "$mode" in
    live)  full=false ;;
    final) full=true  ;;
    *) mati "mode harus 'live' atau 'final'" ;;
  esac

  echo "== 8. Ambil batas id DARI SISI RESTORE"
  # Kunci perbaikan gerbang: produksi bertambah ±185 rb baris/hari, jadi
  # 'sama persis dengan produksi' mustahil selama produksi hidup. Membatasi
  # kedua sisi pada id <= batas milik restore membuat perbandingan setara
  # walau produksi terus menulis (id hanya bertambah, tak pernah dipakai ulang).
  local ceil ceilmr
  ceil=$(ssh "$VPS_USER@$ip" "psql -d $DB_VPS -tAc 'SELECT coalesce(max(id),0) FROM transactions_transaction;'")
  ceilmr=$(ssh "$VPS_USER@$ip" "psql -d $DB_VPS -tAc 'SELECT coalesce(max(id),0) FROM reconciliation_matchresult;'")
  [ "$ceil" -gt 0 ] 2>/dev/null || mati "batas id transactions_transaction = $ceil (tabel kosong?)"
  oke "batas tx=$ceil matchresult=$ceilmr"

  local args="-v full=$full -v ceil=$ceil -v ceilmr=$ceilmr -v ON_ERROR_STOP=1"
  local lap_p="$KERJA/laporan-produksi-$mode.txt"
  local lap_v="$KERJA/laporan-restore-$mode.txt"

  echo "== 9. Jalankan laporan yang SAMA di dua sisi"
  railway ssh -s "$RAILWAY_SVC" "psql -d $DB_PROD $args -f -" < "$SQL" > "$lap_p" \
    || mati "laporan sisi produksi gagal"
  ssh "$VPS_USER@$ip" "psql -d $DB_VPS $args -f -" < "$SQL" > "$lap_v" \
    || mati "laporan sisi restore gagal"

  echo "== 10. Asersi mandiri sisi restore (tak perlu pembanding)"
  local gagal=0
  if grep -q 'KOSONG-FATAL' "$lap_v"; then
    grep 'KOSONG-FATAL' "$lap_v" >&2
    echo "   ^ tabel referensi kosong. `migrate` TIDAK akan mengisinya ulang:" >&2
    echo "     data migration-nya ikut ter-restore sebagai SUDAH SELESAI." >&2
    gagal=1
  fi
  if grep -qE 'BAHAYA-(TABRAKAN-PK|BELUM-PERNAH-DIPANGGIL)' "$lap_v"; then
    grep -E 'BAHAYA-' "$lap_v" >&2
    echo "   ^ sequence tertinggal di belakang max(id): INSERT berikutnya menabrak PK." >&2
    echo "     Perbaiki: SELECT setval(pg_get_serial_sequence('<tabel>','id'), (SELECT max(id) FROM <tabel>));" >&2
    gagal=1
  fi
  if grep -q 'valid=f' "$lap_v"; then
    grep 'valid=f' "$lap_v" >&2
    echo "   ^ index ADA tapi INVALID — planner mengabaikannya, namanya memblokir rebuild." >&2
    gagal=1
  fi
  if grep -q 'analyzed=BELUM-PERNAH' "$lap_v"; then
    grep 'analyzed=BELUM-PERNAH' "$lap_v" >&2
    echo "   ^ statistik planner belum ada — jalankan vacuumdb --analyze-in-stages." >&2
    gagal=1
  fi
  if [ "$gagal" -eq 0 ]; then oke "asersi mandiri lolos"; fi

  echo "== 11. DIFF"
  local saring='cat'
  if [ "$mode" = live ]; then saring="grep -v ^~"; fi
  local d="$KERJA/diff-$mode.txt"
  if diff <(eval "$saring" < "$lap_p") <(eval "$saring" < "$lap_v") > "$d"; then
    oke "produksi dan restore IDENTIK pada seluruh baris yang digerbang"
  else
    echo "   ketidakcocokan (baris '<' = produksi, '>' = restore):" >&2
    head -60 "$d" >&2
    echo "   ... selengkapnya di $d" >&2
    gagal=1
  fi

  echo
  if [ "$gagal" -ne 0 ]; then
    mati "GERBANG TIDAK LULUS — JANGAN lanjut ke fase berikutnya."
  fi
  echo "GERBANG LULUS (mode $mode)."
  if [ "$mode" = live ]; then cat <<'CATATAN'

Catatan mode live: baris berawalan '~' tidak digerbang karena produksi memang
masih menulis (jumlah baris tabel yang tumbuh, statistik planner, versi server).
Kesetaraan penuh — termasuk consumed_by_batch_id, is_duplicate, bucket
MatchResult, dan jumlah baris SETIAP tabel — baru dibuktikan oleh
`banding <ip> final`, yang WAJIB dijalankan di Fase 4 setelah penulisan
produksi dihentikan.
CATATAN
  fi
  return 0
}

case "${1:-}" in
  banding) shift; cmd_banding "$@" ;;
  dump|restore)
    echo "Perintah '$1' sengaja dihapus dari skrip ini." >&2
    echo "Ikuti docs/rencana-migrasi-contabo-2026-08-31.md FASE 2 bagian C-G:" >&2
    echo "  C. dump ber-snapshot, DITARIK OLEH VPS (bukan lewat laptop)" >&2
    echo "  D. buktikan utuh: pg_restore --file=/dev/null (bukan cuma --list)" >&2
    echo "  E. restore ke DB BARU + --exit-on-error --no-comments" >&2
    echo "  F. vacuumdb --analyze  G. kembalikan profil paritas" >&2
    exit 2 ;;
  *) sed -n '2,16p' "${BASH_SOURCE[0]}"; exit 2 ;;
esac
