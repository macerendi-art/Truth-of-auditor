#!/usr/bin/env bash
# Probe HTTP ringan ke domain produksi -- B6, "service mati setelah 3x restart" (railway.json:
# restartPolicyType=ON_FAILURE, restartPolicyMaxRetries=3; sesudahnya Railway diam dan TAK ADA
# yang memberi tahu siapa pun). Lihat docs/runbook-pemantauan-2026-09-04.md.
#
# SENGAJA terpisah dari periksa-kesehatan-terjadwal.sh: butuh jadwal JAUH lebih sering (default
# tiap 5 menit, lihat toa-probe.timer) untuk mendeteksi kematian layanan dengan cepat, dan TIDAK
# butuh DB/Django sama sekali -- hanya `curl` ke domain publik. Menyatukannya dengan cek berat
# (Django + SQL produksi, jadwal harian) akan memaksa salah satu jadi salah jadwal: probe jadi
# terlalu jarang untuk deteksi cepat, atau cek berat jadi terlalu sering membebani produksi.
#
# ============================================================================================
# GEO-BLOCK KH-only AKTIF DI PRODUKSI (GEO_BLOCK_ENABLED=true, GEO_BLOCK_COUNTRIES=KH -- lihat
# bagian Geo-block di CLAUDE.md). VPS ini BUKAN di Kamboja, jadi respons NORMAL/SEHAT dari sini
# adalah HTTP 403 halaman "Trust No One"/"Akses Ditolak" (dibuktikan lewat curl sungguhan ke
# produksi sebelum skrip ini ditulis: title halamannya persis "Akses Ditolak · Truth of
# Auditor") -- BUKAN tanda layanan mati, JUSTRU BUKTI layanan hidup dan middleware geo bekerja.
# JANGAN PERNAH mencoba mem-bypass geo-block atau menambah IP VPS ini ke GEO_BLOCK_ALLOWLIST
# supaya probe ini "lolos" -- itu di luar wewenang skrip pemantauan dan melanggar batasan tugas.
#
# Yang jadi tanda MATI di sini:
#   (a) curl gagal terhubung sama sekali (DNS/timeout/refused/TLS) -- tidak ada jawaban TCP/HTTP
#       sama sekali. Ini kasus paling jelas: railway.json ON_FAILURE+3x lalu diam berarti container
#       benar-benar berhenti menjawab port.
#   (b) HTTP 5xx APA PUN (revisi P3, tinjauan akhir 04-09-2026 -- versi awal hanya 502/503/504):
#       - 502/503/504 dari EDGE Railway SENDIRI saat container di baliknya tidak menjawab port;
#       - 521/522/523/524 dari CLOUDFLARE: domain probe ini di belakang Cloudflare (WAF KH-only
#         ber-scope hostname), dan saat Cloudflare tidak bisa mencapai origin ia menjawab 52x,
#         BUKAN 502/503/504 -- versi awal memasukkannya ke "tak_terduga" (tidak mengalarm), jadi
#         bentuk mati yang paling khas dilihat dari luar justru tak pernah menaikkan gagal_beruntun;
#       - 500 dari aplikasi sendiri (mis. Postgres jatuh: gunicorn menjawab 500, Cloudflare
#         meneruskannya) -- layanan yang menjawab 500 pada halaman root BUKAN layanan hidup.
#       Semuanya "ada respons HTTP" tapi maknanya sama: tidak ada aplikasi sehat di baliknya.
#   (c) HTTP 403 TANPA judul halaman geo-block aplikasi (revisi P3). 403 hanya berarti hidup kalau
#       APLIKASI ITU SENDIRI yang menjawabnya (GeoBlockMiddleware -> halaman "Akses Ditolak · Truth
#       of Auditor"). Kalau aturan WAF Cloudflare berubah atau IP VPS ini masuk daftar blokir WAF,
#       403 datang dari Cloudflare walau origin mati total -- dan versi awal akan melaporkan
#       hidup_tergerbang selamanya. docs/rencana-migrasi-contabo-2026-08-31.md sudah melarang
#       persis ini ("assert isi halaman, jangan 'bukan 5xx'"). Judulnya diperiksa dari $BODY_FILE
#       yang memang sudah disimpan; nilainya bisa ditimpa env JUDUL_TERGERBANG bila judul halaman
#       berubah SADAR (ubah di sini juga, jangan biarkan probe mengalarm palsu).
# HTTP 200 (mis. dari IP Kamboja/staf berbypass) dan kode non-5xx lain yang tak diduga (404/3xx/
# dst) dicatat sebagai "tak_terduga" -- aplikasi MASIH menjawab, jadi TIDAK mengalarm, tapi dicatat
# supaya kelihatan kalau geo-block/config berubah tak terduga.
#
# Probe kedua ke domain Railway asli (tanpa Cloudflare) SUDAH DIPERTIMBANGKAN dan TIDAK LAYAK:
# https://truth-of-auditor.up.railway.app/ menjawab 404 dari edge Railway (dicek curl 04-09-2026)
# -- domain itu tidak lagi merutekan ke service ini, jadi tidak membuktikan apa pun. Jangan dipasang.
# ============================================================================================
#
# Anti-kedip: SATU kegagalan tunggal (jaringan publik VPS<->Railway bisa nyendat sesaat, bukan
# berarti layanan mati) TIDAK langsung mengalarm -- perlu $AMBANG_BERUNTUN kegagalan
# BERTURUT-TURUT (bawaan 3, dengan jadwal 5 menit itu ~15 menit downtime nyata) baru verdict
# GAGAL dan skrip keluar bukan-nol (memicu OnFailure). Pola `terakhir_hidup` yang dipertahankan
# LINTAS-RUN sama persis dengan `terakhir_ok` di scripts/cadangan/backup-harian.sh -- baca
# komentarnya di sana kalau perlu banding; sengaja ditiru, bukan dirancang ulang.
set -uo pipefail
umask 077

URL="${URL:-https://auditor.wolfgang-77.com/}"
STATE_DIR="${STATE_DIR:-/home/toa/probe}"
LOG_FILE="$STATE_DIR/probe.log"
STATUS_FILE="$STATE_DIR/status.json"
AMBANG_BERUNTUN="${AMBANG_BERUNTUN:-3}"
TIMEOUT_DETIK="${TIMEOUT_DETIK:-15}"
# Judul <title> halaman geo-block APLIKASI (web/templates ... GeoBlockMiddleware). 403 tanpa judul
# ini = bukan aplikasi yang menjawab (WAF/edge) -> diperlakukan mati. Lihat butir (c) di atas.
JUDUL_TERGERBANG="${JUDUL_TERGERBANG:-Akses Ditolak · Truth of Auditor}"

mkdir -p "$STATE_DIR"
log() { printf '[%s] %s\n' "$(date '+%F %T %Z')" "$*" | tee -a "$LOG_FILE" >&2; }

TS="$(date -Is)"
BODY_FILE="$(mktemp)"
trap 'rm -f "$BODY_FILE"' EXIT

HTTP_CODE="000"
WAKTU="0"
CURL_OK=1
OUT="$(curl -sS -o "$BODY_FILE" -w '%{http_code} %{time_total}' --max-time "$TIMEOUT_DETIK" "$URL" 2>>"$LOG_FILE")" || CURL_OK=0
if [ "$CURL_OK" -eq 1 ]; then
  HTTP_CODE="$(echo "$OUT" | awk '{print $1}')"
  WAKTU="$(echo "$OUT" | awk '{print $2}')"
fi

if [ "$CURL_OK" -ne 1 ]; then
  KATEGORI="mati"
  PESAN="curl gagal terhubung ke $URL (timeout/DNS/refused/TLS) dalam ${TIMEOUT_DETIK}d -- TIDAK ADA jawaban TCP/HTTP sama sekali"
elif [ "$HTTP_CODE" = "403" ]; then
  if grep -qF -- "$JUDUL_TERGERBANG" "$BODY_FILE"; then
    KATEGORI="hidup_tergerbang"
    PESAN="HTTP 403 berjudul '$JUDUL_TERGERBANG' -- geo-block KH-only APLIKASI membalas (HIDUP; ini NORMAL dari VPS non-KH, bukan tanda mati)"
  else
    KATEGORI="mati"
    PESAN="HTTP 403 TANPA judul '$JUDUL_TERGERBANG' -- bukan aplikasi yang menjawab (WAF/edge Cloudflare?); origin bisa saja mati di baliknya"
  fi
elif echo "$HTTP_CODE" | grep -qE '^5[0-9]{2}$'; then
  KATEGORI="mati"
  case "$HTTP_CODE" in
    502|503|504) PESAN="HTTP $HTTP_CODE dari edge Railway -- container di baliknya tidak menjawab port" ;;
    52*)         PESAN="HTTP $HTTP_CODE dari Cloudflare -- origin (edge Railway) tidak terjangkau" ;;
    *)           PESAN="HTTP $HTTP_CODE dari aplikasi/edge -- halaman root menjawab 5xx (mis. Postgres jatuh); bukan layanan sehat" ;;
  esac
elif echo "$HTTP_CODE" | grep -qE '^[0-9]{3}$'; then
  KATEGORI="tak_terduga"
  PESAN="HTTP $HTTP_CODE -- aplikasi menjawab tapi bukan 403 yang diharapkan; cek geo-block/konfigurasi (tidak mengalarm)"
else
  KATEGORI="mati"
  PESAN="kode HTTP tak terbaca ('$HTTP_CODE')"
fi

log "$KATEGORI: $PESAN (kode=$HTTP_CODE, ${WAKTU}d, url=$URL)"
# Cuplikan badan untuk SEMUA respons HTTP yang bukan hidup_tergerbang (termasuk 403 tanpa judul
# dan 5xx): itulah bukti pertama yang dibutuhkan saat membaca log insiden.
if [ "$CURL_OK" -eq 1 ] && [ "$KATEGORI" != "hidup_tergerbang" ]; then
  log "cuplikan badan respons (200 byte pertama): $(head -c 200 "$BODY_FILE" | tr '\n' ' ')"
fi

# -- beruntun + terakhir_hidup, dipertahankan LINTAS-RUN (pola sama dgn terakhir_ok cadangan) --
BERUNTUN_LAMA=0
TERAKHIR_HIDUP_LAMA=""
if [ -f "$STATUS_FILE" ]; then
  BERUNTUN_LAMA="$(jq -r '.gagal_beruntun // 0' "$STATUS_FILE" 2>/dev/null || echo 0)"
  TERAKHIR_HIDUP_LAMA="$(jq -r '.terakhir_hidup // empty' "$STATUS_FILE" 2>/dev/null || true)"
fi
case "$BERUNTUN_LAMA" in ''|*[!0-9]*) BERUNTUN_LAMA=0 ;; esac

if [ "$KATEGORI" = "mati" ]; then
  BERUNTUN=$((BERUNTUN_LAMA + 1))
  TERAKHIR_HIDUP="$TERAKHIR_HIDUP_LAMA"
else
  BERUNTUN=0
  TERAKHIR_HIDUP="$TS"
fi

if [ "$BERUNTUN" -ge "$AMBANG_BERUNTUN" ]; then
  VERDICT="GAGAL"
  KODE=1
else
  VERDICT="OK"
  KODE=0
fi

jq -n \
  --arg waktu "$TS" --arg url "$URL" --arg kategori "$KATEGORI" --arg pesan "$PESAN" \
  --arg http_code "$HTTP_CODE" --argjson waktu_respons "${WAKTU:-0}" \
  --arg verdict "$VERDICT" --argjson gagal_beruntun "$BERUNTUN" --argjson ambang_beruntun "$AMBANG_BERUNTUN" \
  --arg terakhir_hidup "$TERAKHIR_HIDUP" \
  '{
     waktu: $waktu, url: $url, http_code: $http_code, kategori: $kategori, pesan: $pesan,
     waktu_respons_detik: $waktu_respons, verdict: $verdict,
     gagal_beruntun: $gagal_beruntun, ambang_beruntun: $ambang_beruntun,
     terakhir_hidup: (if ($terakhir_hidup|length) > 0 then $terakhir_hidup else null end)
   }' > "$STATUS_FILE.tmp"
mv "$STATUS_FILE.tmp" "$STATUS_FILE"

if [ "$VERDICT" = "GAGAL" ]; then
  log "=== VERDICT GAGAL ($BERUNTUN gagal beruntun >= ambang $AMBANG_BERUNTUN) ==="
  exit 1
fi
log "=== VERDICT OK (gagal beruntun saat ini: $BERUNTUN) ==="
exit 0
