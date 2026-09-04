#!/usr/bin/env bash
# Bootstrap SATU-KALI staging (F3) di VPS `toa` -- lihat docs/runbook-staging-2026-09-04.md.
#
# Dijalankan DI VPS (ssh toa), sebagai user `toa` dengan sudo. Idempoten kalau diulang (tiap
# langkah memeriksa dulu sebelum membuat). Ini CATATAN-TERVERSI dari apa yang sudah dijalankan
# tangan 2026-09-04 untuk membangun staging pertama kali -- bukan skrip yang perlu dijalankan
# lagi kalau staging sudah berdiri (checkout kode & data disegarkan lewat pasang-revisi.sh /
# refresh-data.sh, bukan skrip ini).
#
# Filosofi isolasi (kenapa SEMUANYA terpisah dari /opt/toa milik gladi migrasi/pemantauan):
#   - OS user `toa_staging` BARU, home terpisah dari `toa` -- TIDAK BISA membaca
#     ~/.pgpass / ~/.prod-url milik user `toa` (dibuktikan: `sudo -u toa_staging cat
#     /home/toa/.pgpass` -> Permission denied). Bahkan kalau DATABASE_URL staging suatu saat
#     salah ketik kehilangan sandi, psycopg TIDAK akan diam-diam jatuh ke kredensial produksi
#     lewat .pgpass milik user lain -- struktural, bukan janji konfigurasi.
#   - Role Postgres `toa_staging` BARU, password sendiri (hex -- lihat catatan di bawah
#     kenapa bukan base64), tanpa SUPERUSER/CREATEDB/CREATEROLE.
#   - Database `toa_staging` BARU, TIDAK PERNAH `toa` (pembanding gladi migrasi Contabo) atau
#     produksi Railway.
#   - Checkout kode di /opt/toa-staging, TERPISAH dari /opt/toa (dipakai pemantauan B1 untuk
#     periksa_kesehatan/periksa_index read-only terhadap PRODUKSI -- lihat
#     docs/runbook-pemantauan-2026-09-04.md). Mengubah /opt/toa dilarang di sini karena
#     berisiko menabrak pekerjaan itu.
#   - Port loopback sendiri (8001, BUKAN 8000 milik toa.service) + systemd unit sendiri
#     (toa-staging.service, BUKAN toa.service).
#
# Kenapa hex, bukan base64, untuk password/SECRET_KEY: base64 mengandung +/=, yang merusak
# parsing DATABASE_URL (URL-encoding) dan bisa merusak `set -a; . env-file; set +a` (pola yang
# dipakai skrip pemantauan) kalau karakternya bertepatan dengan metacharacter shell. Hex hanya
# [0-9a-f], aman di kedua konteks.
set -euo pipefail
umask 077

echo "=== 1. OS user toa_staging ==="
if ! id toa_staging >/dev/null 2>&1; then
  sudo useradd --system --create-home --home-dir /home/toa_staging --shell /bin/bash toa_staging
fi
sudo -u toa_staging test -r /home/toa/.pgpass && { echo "FATAL: toa_staging BISA baca .pgpass milik toa -- perbaiki sebelum lanjut"; exit 2; } || true
echo "OK: toa_staging tidak bisa membaca rahasia milik user toa"

echo "=== 2. Role Postgres toa_staging ==="
if ! sudo -u postgres psql -Atc "select 1 from pg_roles where rolname='toa_staging'" | grep -q 1; then
  PGPASS_STAGING="$(openssl rand -hex 24)"
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE ROLE toa_staging LOGIN PASSWORD '${PGPASS_STAGING}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;"
  echo "Role dibuat. Simpan PGPASS_STAGING ini ke /etc/toa-staging.env secara MANUAL (skrip ini sengaja tidak menuliskannya sendiri -- lihat runbook bagian 'Cara memasang')."
  unset PGPASS_STAGING
else
  echo "Role toa_staging sudah ada -- lewati (pakai ALTER ROLE ... PASSWORD manual kalau perlu reset)."
fi

echo "=== 3. Direktori ==="
sudo install -d -o toa_staging -g toa_staging -m 0750 /opt/toa-staging
sudo install -d -o toa_staging -g toa_staging -m 0750 /var/lib/toa-staging /var/lib/toa-staging/media

echo "=== 4. Unit systemd (berkas ter-versi: scripts/staging/toa-staging.service) ==="
echo "Salin manual: scp scripts/staging/toa-staging.service toa:/tmp/ && ssh toa 'sudo mv /tmp/toa-staging.service /etc/systemd/system/ && sudo systemctl daemon-reload'"

echo "=== 5. tailscale serve (HTTPS tailnet-only -> loopback:8001) ==="
sudo tailscale serve --bg --https=443 http://127.0.0.1:8001
tailscale serve status

echo "=== SELESAI bootstrap. Langkah selanjutnya: isi /etc/toa-staging.env (lihat runbook),"
echo "lalu scripts/staging/pasang-revisi.sh <ref> untuk kode, scripts/staging/refresh-data.sh untuk data."
