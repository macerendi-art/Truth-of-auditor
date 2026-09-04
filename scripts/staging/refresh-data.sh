#!/usr/bin/env bash
# Penyegaran data STAGING (F3) -- lihat docs/runbook-staging-2026-09-04.md.
#
# Menarik dump HARIAN TERBARU yang sudah TERBUKTI baik dari ~/cadangan/status.json (A1,
# scripts/cadangan/backup-harian.sh) dan me-restore-nya ke database `toa_staging` --
# SATU-SATUNYA nama target yang boleh disentuh skrip ini. Dijalankan DI VPS `toa` sebagai
# user `toa` (yang sama dipakai backup-harian.sh/restore-run.sh gladi migrasi -- peer auth
# lokal, bisa membaca direktori dump mode 700 milik `toa`).
#
# TIDAK PERNAH menyentuh:
#   - Database `toa` (pembanding gladi migrasi/scripts/gerbang.sh) -- digerbangi eksplisit
#     di bawah (assert TARGET_DB != "toa") DAN dibuktikan dengan hitung ulang baris+sum
#     `toa` sebelum/sesudah, harus identik.
#   - ~/baseline.txt -- skrip ini tidak membaca/menulisnya sama sekali.
#   - ~/.pgpass / ~/.prod-url -- tidak dipakai; semua koneksi di sini LOKAL (peer, tanpa TCP,
#     tanpa sandi produksi).
#
# Kenapa dari ~/cadangan/status.json, bukan `ls /var/backups/toa | tail -1`: sebuah refresh
# yang kebetulan jalan tepat saat jendela cadangan 03:00-03:30 WIB bisa membaca direktori
# dump yang MASIH DITULIS. status.json HANYA diperbarui di AKHIR setiap percobaan cadangan
# (sukses maupun gagal, lihat A1), jadi `dump_dir` di dalamnya selalu menunjuk arsip yang
# SUDAH SELESAI ditulis (atau skrip ini menolak kalau verdict-nya bukan "OK").
set -euo pipefail
umask 077

TARGET_DB="toa_staging"
STAGING_ROLE="toa_staging"
APP_DIR="/opt/toa-staging"
ENV_FILE="/etc/toa-staging.env"
SERVICE="toa-staging.service"
CADANGAN_STATUS="${CADANGAN_STATUS:-/home/toa/cadangan/status.json}"

# Gerbang paling penting di seluruh skrip ini -- kalau ini pernah salah ketik jadi "toa",
# HARUS berhenti sebelum menyentuh apa pun.
if [ "$TARGET_DB" = "toa" ]; then
  echo "FATAL: TARGET_DB tidak boleh 'toa' -- itu database pembanding gladi migrasi." >&2
  exit 2
fi

log() { printf '[%s] %s\n' "$(date '+%F %T %Z')" "$*" >&2; }

[ -r "$CADANGAN_STATUS" ] || { echo "FATAL: $CADANGAN_STATUS tidak terbaca -- cadangan A1 belum pernah jalan?" >&2; exit 2; }

VERDICT="$(jq -r '.verdict // empty' "$CADANGAN_STATUS")"
DUMP_DIR="$(jq -r '.dump_dir // empty' "$CADANGAN_STATUS")"
CHECKSUM_MANIFEST="$(jq -r '.sha256_manifest // empty' "$CADANGAN_STATUS")"

[ "$VERDICT" = "OK" ] || { echo "FATAL: cadangan TERAKHIR verdict='$VERDICT' (bukan OK) -- tidak ada dump baik untuk dipakai" >&2; exit 2; }
[ -n "$DUMP_DIR" ] && [ -d "$DUMP_DIR" ] || { echo "FATAL: dump_dir '$DUMP_DIR' tidak ada" >&2; exit 2; }
[ -n "$CHECKSUM_MANIFEST" ] && [ -r "$CHECKSUM_MANIFEST" ] || { echo "FATAL: manifest checksum '$CHECKSUM_MANIFEST' tidak terbaca" >&2; exit 2; }

log "=== penyegaran $TARGET_DB dari $DUMP_DIR ==="

log "--- verifikasi checksum manifest ---"
( cd "$(dirname "$CHECKSUM_MANIFEST")" && sha256sum -c "$(basename "$CHECKSUM_MANIFEST")" >/dev/null )
log "checksum OK"

log "--- verifikasi TOC arsip terbaca ---"
pg_restore -l "$DUMP_DIR" >/dev/null
log "TOC OK"

# --- Baseline `toa` SEBELUM (properti yang dijaga: skrip ini tidak boleh mengubahnya) -----
log "--- baseline toa SEBELUM (bukti tak tersentuh) ---"
BEFORE="$(psql toa -Atc "SELECT count(*)||'|'||sum(amount)||'|'||sum(credit_delta)||'|'||sum(money_delta) FROM transactions_transaction;")"
log "toa (sebelum) = $BEFORE"

# --- Hentikan layanan staging supaya tidak ada koneksi aktif ke $TARGET_DB ----------------
log "--- stop $SERVICE ---"
sudo systemctl stop "$SERVICE" 2>/dev/null || true

log "--- putuskan sisa koneksi ke $TARGET_DB (kalau ada) ---"
sudo -u postgres psql -Atc "
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
WHERE datname = '$TARGET_DB' AND pid <> pg_backend_pid();" >/dev/null || true

log "--- drop + create ulang $TARGET_DB (owner sementara: toa, restore butuh peer auth lokal) ---"
sudo -u postgres dropdb --if-exists "$TARGET_DB"
sudo -u postgres createdb -O toa "$TARGET_DB"

log "--- pg_restore (bisa beberapa menit pada data 10+ juta baris) ---"
pg_restore --dbname="$TARGET_DB" --jobs=4 --no-owner --no-privileges --exit-on-error "$DUMP_DIR"

log "--- pindahkan kepemilikan objek ke role $STAGING_ROLE (BUKAN REASSIGN OWNED, itu ikut menyentuh objek bersama) ---"
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "$TARGET_DB" -Atc "
DO \$\$ DECLARE r record; BEGIN
  FOR r IN SELECT c.oid::regclass AS rel, c.relkind
           FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind IN ('r','p','S','v','m')
             -- Sequence 'owned by' sebuah kolom (identity/serial) ikut berpindah
             -- otomatis saat tabel induknya di-ALTER OWNER -- mencoba ALTER SEQUENCE
             -- langsung atasnya justru GAGAL ('is linked to table ...'), jadi
             -- dilewati di sini (terbukti perlu: percobaan pertama berhenti di
             -- 'accounts_user_allowed_tokos_id_seq' sebelum perbaikan ini).
             AND NOT (c.relkind = 'S' AND EXISTS (
               SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'a'
             ))
  LOOP
    EXECUTE format('ALTER %s %s OWNER TO $STAGING_ROLE',
      CASE r.relkind
        WHEN 'S' THEN 'SEQUENCE'
        WHEN 'v' THEN 'VIEW'
        WHEN 'm' THEN 'MATERIALIZED VIEW'
        ELSE 'TABLE'
      END, r.rel);
  END LOOP;
END \$\$;"
sudo -u postgres psql -v ON_ERROR_STOP=1 -Atc "ALTER DATABASE $TARGET_DB OWNER TO $STAGING_ROLE;"
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "$TARGET_DB" -Atc "GRANT USAGE, CREATE ON SCHEMA public TO $STAGING_ROLE;"

BUKAN_PEMILIK="$(sudo -u postgres psql -d "$TARGET_DB" -Atc "
SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m')
  AND pg_catalog.pg_get_userbyid(c.relowner) <> '$STAGING_ROLE';")"
if [ "$BUKAN_PEMILIK" != "0" ]; then
  echo "FATAL: $BUKAN_PEMILIK objek di $TARGET_DB masih BUKAN milik $STAGING_ROLE -- migrate akan gagal senyap (TambahIndexAman menelan error 'must be owner')" >&2
  exit 2
fi
log "kepemilikan OK -- semua objek milik $STAGING_ROLE"

log "--- vacuum analyze ---"
sudo -u postgres vacuumdb -d "$TARGET_DB" --analyze-in-stages --jobs=4 >/dev/null
sudo -u postgres vacuumdb -d "$TARGET_DB" --analyze --jobs=4 >/dev/null

log "--- migrate ke revisi kode yang SEDANG terpasang di $APP_DIR ---"
( cd "$APP_DIR" && set -a && . "$ENV_FILE" && set +a && \
  "$APP_DIR/.venv/bin/python" manage.py migrate --noinput )

log "--- periksa_index (F6) atas $TARGET_DB pasca-migrate ---"
( cd "$APP_DIR" && set -a && . "$ENV_FILE" && set +a && \
  "$APP_DIR/.venv/bin/python" manage.py periksa_index ) || \
  log "PERHATIAN: periksa_index melapor index hilang/invalid -- lihat keluaran di atas"

log "--- start $SERVICE ---"
sudo systemctl start "$SERVICE"
sleep 2
sudo systemctl is-active --quiet "$SERVICE" && log "layanan aktif" || { echo "FATAL: $SERVICE gagal start setelah refresh" >&2; exit 2; }

# --- Baseline `toa` SESUDAH -- WAJIB identik dengan SEBELUM ------------------------------
log "--- baseline toa SESUDAH (harus identik) ---"
AFTER="$(psql toa -Atc "SELECT count(*)||'|'||sum(amount)||'|'||sum(credit_delta)||'|'||sum(money_delta) FROM transactions_transaction;")"
log "toa (sesudah) = $AFTER"
if [ "$BEFORE" != "$AFTER" ]; then
  echo "FATAL: baseline toa BERUBAH ('$BEFORE' -> '$AFTER') -- ini seharusnya MUSTAHIL, laporkan segera, jangan lanjut apa pun" >&2
  exit 3
fi
log "toa tak tersentuh -- terbukti identik"

ROWS_STAGING="$(sudo -u postgres psql -d "$TARGET_DB" -Atc "SELECT count(*) FROM transactions_transaction;")"
log "=== SELESAI. $TARGET_DB siap, $ROWS_STAGING baris di transactions_transaction (sumber: $DUMP_DIR) ==="
