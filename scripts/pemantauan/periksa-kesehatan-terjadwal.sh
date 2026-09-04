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
#   3. Sisa disk PRODUKSI, dalam PERSEN -- bukan gigabyte (volume pernah 500 MB, lalu 5 GB;
#      insiden DiskFull 2026-07-04 dan 13-08-2026). `periksa_kesehatan` sendiri TIDAK bisa
#      menjawab ini kalau dijalankan dari VPS: bagian "Ruang disk"-nya SENGAJA mengukur direktori
#      tempat PERINTAH itu berjalan (lihat docstring-nya) -- dari sini itu disk VPS, BUKAN volume
#      Postgres produksi di Railway. Jadi bagian itu tetap tampil di laporan (sebagai info disk
#      VPS) dan disk PRODUKSI diukur TERPISAH di sini lewat superuser Postgres:
#        COPY dfout FROM PROGRAM 'df -kP <data_directory>'
#      -- satu-satunya cara membaca disk NYATA tempat data Postgres produksi hidup dari proxy TCP
#      publik, tanpa akses shell ke host Postgres itu sendiri (dibuktikan: `current_user` lewat
#      proxy produksi punya `rolsuper=true`). Baris ini TIDAK menulis apa pun yang bertahan --
#      `CREATE TEMP TABLE` hidup selama SESI psql ini saja, hilang otomatis saat koneksi ditutup.
#      Ambang PERSEN-nya SENGAJA angka yang SAMA dengan `DISK_BAHAYA`/`DISK_PERHATIAN` di
#      core/management/commands/periksa_kesehatan.py (10% / 20%) -- kalau salah satu berubah,
#      ubah juga yang lain; keduanya harus tetap seiring (pola yang sama dengan catatan gerbang
#      J4 di scripts/cadangan/backup-harian.sh soal `periksa_index`: SQL langsung karena Django
#      tak selalu murah/perlu di jalur itu, tapi logika/ambangnya WAJIB seiring).
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
# potretnya sendiri ditulis LOKAL ke media/kesehatan.json (VPS, bukan produksi), dan
# `COPY ... FROM PROGRAM` di atas hidup selama sesi.
#
# App Django yang dipakai adalah checkout gladi migrasi 2026-09-01 di /opt/toa (dipasang oleh
# ~/migrasi/fase3-app.sh) -- SUDAH ADA, tidak dibangun ulang di sini. `periksa_index.py` di sana
# identik byte-untuk-byte dengan repo (dibandingkan sebelum skrip ini ditulis);
# `periksa_kesehatan.py` sempat berupa berkas belum ter-commit di checkout itu dari eksplorasi
# sebelumnya, juga identik. Checkout itu boleh basi di commit lain (branch drill, bukan main) --
# tidak masalah, kedua perintah ini murni membaca skema+data lewat Django ORM/SQL mentah, tidak
# bergantung pada kode aplikasi lain yang mungkin sudah berubah.
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
# DISK_BAHAYA/DISK_PERHATIAN: HARUS seiring core/management/commands/periksa_kesehatan.py.
AMBANG_CADANGAN_JAM="${AMBANG_CADANGAN_JAM:-26}"
DISK_BAHAYA="${DISK_BAHAYA:-10}"
DISK_PERHATIAN="${DISK_PERHATIAN:-20}"

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
log "--- 2. Index F6 (manage.py periksa_index, produksi) ---"
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

# --- 3. Sisa disk PRODUKSI dalam persen --------------------------------------
log "--- 3. Sisa disk produksi (COPY FROM PROGRAM df, superuser) ---"
DISK_STATUS="PERHATIAN"
DISK_PESAN="tak bisa membaca disk produksi"
PERSEN_BEBAS=""

DATADIR="$(psql "$PROD_URL" -qtAc 'SHOW data_directory;' 2>>"$LOG_FILE")" || DATADIR=""
if [ -z "$DATADIR" ]; then
  DISK_PESAN="gagal membaca data_directory produksi (lihat $LOG_FILE)"
else
  # -q (quiet) WAJIB di sini: tanpa itu psql mencetak tag status "CREATE TABLE"/"COPY 1" untuk
  # dua pernyataan pertama, ikut masuk ke $DF_LINE dan mengotori baris df yang mau diparse.
  # Dibuktikan sebelum baris ini ditulis: -Atc saja meloloskan "CREATE TABLE\nCOPY 1\n<df>" dan
  # kebetulan masih terparse benar (awk men-skip whitespace di depan angka) -- tapi itu untung
  # implementasi, bukan desain; -q membuat DF_LINE cuma satu baris seperti seharusnya.
  DF_LINE="$(psql "$PROD_URL" -qtAc "
CREATE TEMP TABLE dfout(line text);
COPY dfout FROM PROGRAM 'df -kP ${DATADIR} 2>&1 | tail -1';
SELECT line FROM dfout;
" 2>>"$LOG_FILE")" || DF_LINE=""
  if [ -z "$DF_LINE" ]; then
    DISK_PESAN="gagal menjalankan 'df' di host produksi lewat COPY FROM PROGRAM (lihat $LOG_FILE)"
  else
    PERSEN_DIPAKAI="$(echo "$DF_LINE" | awk '{gsub("%","",$5); print $5}')"
    if ! echo "$PERSEN_DIPAKAI" | grep -qE '^[0-9]+(\.[0-9]+)?$'; then
      DISK_PESAN="keluaran 'df' tak terbaca: '$DF_LINE'"
    else
      PERSEN_BEBAS="$(awk -v p="$PERSEN_DIPAKAI" 'BEGIN{printf "%.1f", 100-p}')"
      if awk -v p="$PERSEN_BEBAS" -v a="$DISK_BAHAYA" 'BEGIN{exit !(p<a)}'; then
        DISK_STATUS="BAHAYA"
      elif awk -v p="$PERSEN_BEBAS" -v a="$DISK_PERHATIAN" 'BEGIN{exit !(p<a)}'; then
        DISK_STATUS="PERHATIAN"
      else
        DISK_STATUS="OK"
      fi
      DISK_PESAN="sisa ${PERSEN_BEBAS}% di volume data produksi ('$DF_LINE')"
    fi
  fi
fi
log "$DISK_STATUS: $DISK_PESAN"
naikkan "$DISK_STATUS"

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
PERSEN_BEBAS_JSON="${PERSEN_BEBAS:-null}"

jq -n \
  --arg tanggal "$STAMP" --arg mulai "$TS_MULAI" --arg selesai "$TS_SELESAI" \
  --arg keseluruhan "$KESELURUHAN" \
  --arg cad_status "$CAD_STATUS" --arg cad_pesan "$CAD_PESAN" \
  --arg cad_verdict "$CAD_VERDICT" --arg cad_terakhir_ok "$CAD_TERAKHIR_OK" \
  --argjson cad_umur_jam "$CAD_UMUR_JAM_JSON" \
  --arg index_status "$INDEX_STATUS" --arg index_pesan "$INDEX_PESAN" \
  --arg disk_status "$DISK_STATUS" --arg disk_pesan "$DISK_PESAN" \
  --argjson disk_persen_bebas "$PERSEN_BEBAS_JSON" \
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
     index_f6: { status: $index_status, pesan: $index_pesan },
     disk_produksi: { status: $disk_status, pesan: $disk_pesan, persen_bebas: $disk_persen_bebas },
     periksa_kesehatan_django: { status: $kes_status, kode_keluar: $kes_kode, ringkasan: $kes_ringkasan },
     log_file: $log_file
   }' > "$STATUS_FILE.tmp"
mv "$STATUS_FILE.tmp" "$STATUS_FILE"

log "=== SELESAI: $KESELURUHAN ==="
case "$KESELURUHAN" in
  BAHAYA) exit 1 ;;
  *) exit 0 ;;
esac
