#!/usr/bin/env bash
# gerbang.sh — GERBANG Fase 2 / Fase 4 migrasi Truth of Auditor (Railway -> Contabo).
# Pengganti empat perintah psql di rencana lama. Membandingkan produksi dengan
# restore lewat `diff`, bukan lewat mata, dan memeriksa index/constraint/
# sequence/statistik yang sebelumnya tidak diperiksa sama sekali.
#
#   ./gerbang.sh dump                    # laptop: tarik dump + buktikan utuh
#   ./gerbang.sh restore <IP-VPS>        # kirim, DROP+CREATE, restore, ANALYZE
#   ./gerbang.sh banding <IP-VPS> live   # Fase 2 (produksi masih menulis)
#   ./gerbang.sh banding <IP-VPS> final  # Fase 4 (penulisan sudah dihentikan)
#
# Butuh: gerbang.sql di direktori yang sama.

set -Eeuo pipefail
shopt -s inherit_errexit 2>/dev/null || true

KERJA="${KERJA:-$HOME/toa-migrasi}"
SQL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/gerbang.sql"
RAILWAY_SVC="${RAILWAY_SVC:-Postgres}"
DB_PROD="${DB_PROD:-railway}"
DB_VPS="${DB_VPS:-toa}"
VPS_USER="${VPS_USER:-toa}"
mkdir -p "$KERJA"

mati() { echo; echo "!! GAGAL: $*" >&2; exit 1; }
oke()  { echo "   ok: $*"; }

# ---------------------------------------------------------------- dump -------
cmd_dump() {
  local f="$KERJA/toa-$(date +%F-%H%M).dump"
  echo "== 1. Dump dari Railway -> $f"
  # -Fc wajib (pg_restore -l & -j butuh custom format). Aliran biner lewat
  # `railway ssh` TIDAK dipercaya begitu saja — lihat langkah 2.
  railway ssh -s "$RAILWAY_SVC" "pg_dump -Fc -Z6 -d $DB_PROD" > "$f" \
    || mati "pg_dump lewat railway ssh gagal"

  echo "== 2. Bukti arsipnya utuh (bukan cuma 'ada file besar')"
  [ -s "$f" ] || mati "dump kosong"
  ls -l "$f"
  sha256sum "$f" | tee "$f.sha256"
  # INI penangkap kerusakan PTY/CRLF: arsip custom yang ternoda gagal dibaca
  # TOC-nya seketika. Dump 17 GB yang 'terkirim sukses' tapi tak bisa
  # di-list adalah kegagalan diam yang paling mahal di rencana ini.
  pg_restore -l "$f" > "$f.toc" 2>"$f.toc.err" \
    || { cat "$f.toc.err" >&2; mati "pg_restore -l menolak arsip -> dump RUSAK (kemungkinan besar aliran biner railway ssh ternoda). Ulangi dengan: railway ssh -s $RAILWAY_SVC \"pg_dump -Fc -Z6 -d $DB_PROD | base64 -w0\" | base64 -d > $f"; }
  oke "TOC terbaca, $(grep -c . "$f.toc") entri"
  grep -qi 'TABLE DATA public transactions_transaction' "$f.toc" \
    || mati "TOC tak memuat data transactions_transaction"
  oke "entri data transactions_transaction ada di TOC"
  echo "$f" > "$KERJA/DUMP_TERAKHIR"
  echo; echo "Dump siap: $f"
}

# ------------------------------------------------------------- restore -------
cmd_restore() {
  local ip="${1:?IP VPS}"
  local f; f="$(cat "$KERJA/DUMP_TERAKHIR")"
  echo "== 3. Kirim ke VPS + cocokkan sha256 DUA SISI"
  scp "$f" "$f.sha256" "$VPS_USER@$ip:/tmp/"
  ssh "$VPS_USER@$ip" "cd /tmp && sha256sum -c $(basename "$f").sha256" \
    || mati "sha256 tidak cocok setelah transfer"
  oke "arsip sampai utuh"

  echo "== 4. DROP + CREATE database (LANGKAH YANG HILANG DI RENCANA)"
  # Restore Fase 4 masuk ke DB yang SUDAH berisi percobaan Fase 2. Tanpa ini
  # pg_restore menabrak 'already exists' di seluruh skema lalu menempelkan data
  # ke tabel lama.
  ssh "$VPS_USER@$ip" "sudo -u postgres psql -v ON_ERROR_STOP=1 \
      -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB_VPS' AND pid<>pg_backend_pid();\" \
      -c 'DROP DATABASE IF EXISTS $DB_VPS;' \
      -c 'CREATE DATABASE $DB_VPS OWNER $VPS_USER;'" || mati "drop/create database gagal"
  oke "database $DB_VPS bersih"

  echo "== 5. pg_restore (galat TIDAK boleh diabaikan)"
  # Bawaan pg_restore adalah MELANJUTKAN saat galat lalu mencetak jumlahnya di
  # akhir — restore yang 'selesai' bisa kehilangan index/constraint/setval.
  # --exit-on-error mengubahnya jadi gerbang.
  ssh "$VPS_USER@$ip" "pg_restore -d $DB_VPS -j 8 --no-owner --no-privileges \
      --exit-on-error /tmp/$(basename "$f") 2>/tmp/restore.err" && rc=0 || rc=$?
  if [ "${rc:-0}" -ne 0 ]; then
    ssh "$VPS_USER@$ip" "tail -40 /tmp/restore.err" >&2
    echo >&2
    echo "Kelas galat jinak yang diketahui saat restore sebagai non-superuser:" >&2
    echo "  COMMENT ON EXTENSION plpgsql  (butuh pemilik ekstensi)" >&2
    echo "Bila HANYA itu yang muncul, saring TOC-nya lalu ulangi:" >&2
    echo "  pg_restore -l d.dump | grep -v 'COMMENT - EXTENSION' > toc.txt" >&2
    echo "  pg_restore -d $DB_VPS -j 8 --no-owner --no-privileges --exit-on-error -L toc.txt d.dump" >&2
    mati "restore berhenti karena galat — periksa /tmp/restore.err di VPS"
  fi
  oke "restore selesai tanpa galat"

  echo "== 6. ANALYZE (TIDAK opsional)"
  # pg_restore tak pernah menjalankan ANALYZE dan tak membangun visibility map.
  # Tanpa ini pg_statistic kosong, index-only scan mati, dan setiap pembacaan
  # pertama menulis hint bit. Mengukur waktu halaman sebelum langkah ini =
  # mengukur derau; autoanalyze memang akan menyusul sendiri dalam hitungan
  # menit, tapi 'menit' itu jatuh tepat di jam cutover.
  ssh "$VPS_USER@$ip" "vacuumdb --analyze-in-stages -j 8 -d $DB_VPS" \
    || mati "vacuumdb gagal"
  oke "statistik planner terbangun"

  echo "== 7. periksa_index (index bernama + indisvalid)"
  ssh "$VPS_USER@$ip" "cd /opt/toa && .venv/bin/python manage.py periksa_index" \
    || mati "periksa_index menemukan index hilang/invalid"
  oke "index model bersih"
}

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
  dump)    shift; cmd_dump "$@" ;;
  restore) shift; cmd_restore "$@" ;;
  banding) shift; cmd_banding "$@" ;;
  *) sed -n '2,16p' "${BASH_SOURCE[0]}"; exit 2 ;;
esac
