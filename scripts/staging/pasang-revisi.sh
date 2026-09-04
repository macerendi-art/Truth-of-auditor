#!/usr/bin/env bash
# Pasang revisi (branch/commit) tertentu ke STAGING -- F3, lihat
# docs/runbook-staging-2026-09-04.md.
#
# Dijalankan DARI MESIN LOKAL (checkout mana pun yang punya revisi yang mau dicoba), BUKAN
# di VPS -- skrip ini butuh `git archive` atas riwayat git lokal. Sengaja TIDAK lewat
# `git push` ke GitHub: cabang kerja hari ini sering berisi commit yang belum (dan mungkin
# tak akan) di-push, jadi jalur ini bekerja untuk revisi APA PUN yang ada di riwayat git
# lokal -- ter-push atau tidak -- tanpa pernah menyentuh origin/GitHub. `git archive` juga
# otomatis menghormati .gitignore-tree (tak menyeret .venv/db.sqlite3/staticfiles lokal).
#
# Pemakaian:
#   scripts/staging/pasang-revisi.sh <ref>
#   scripts/staging/pasang-revisi.sh HEAD
#   scripts/staging/pasang-revisi.sh origin/main
#   scripts/staging/pasang-revisi.sh 4d2f6a1
#
# Urutan: (1) resolve ref -> SHA penuh, pastikan ref itu ADA (git cat-file), (2) bersihkan
# checkout staging LAMA (kecuali .venv/staticfiles/media -- lihat alasan "stale files" di
# bawah), (3) `git archive <sha> | ssh toa tar -x`, (4) tulis penanda REVISI, (5) pip install
# (idempoten, cepat kalau tak ada perubahan requirements.txt), (6) migrate + collectstatic +
# periksa_index atas DATABASE toa_staging yang SUDAH ADA (skrip ini TIDAK menyentuh data --
# itu tugas refresh-data.sh), (7) restart toa-staging.service, (8) verifikasi HTTP dari VPS.
#
# Kenapa checkout lama harus DIBERSIHKAN dulu (bukan `tar -x` menimpa begitu saja): sebuah
# berkas yang DIHAPUS di revisi baru (mis. migrasi yang di-squash, modul yang direname) akan
# tetap ada dari revisi lama kalau cuma ditimpa -- Django/Python bisa mengimpornya dan
# berperilaku beda dari revisi yang sebenarnya diminta. `.venv` (besar, lambat dipasang
# ulang), `staticfiles` (hasil collectstatic, dibangun ulang di langkah 6), dan `media`
# (symlink/berkas unggahan staging, bukan bagian revisi kode) sengaja DIKECUALIKAN dari
# pembersihan.
set -euo pipefail

HOST="toa"
APP_DIR="/opt/toa-staging"
ENV_FILE="/etc/toa-staging.env"
SERVICE="toa-staging.service"
STAGING_USER="toa_staging"

REF="${1:?Pemakaian: $0 <ref-git>  (mis. HEAD, origin/main, atau SHA commit)}"

SHA="$(git rev-parse --verify "${REF}^{commit}")"
echo "[lokal] ref '$REF' -> commit $SHA"
git cat-file -e "$SHA" || { echo "FATAL: commit $SHA tidak ada di riwayat lokal" >&2; exit 2; }

echo "[lokal] bersihkan checkout lama di $HOST:$APP_DIR (kecuali .venv/staticfiles/media)"
# `cd "$APP_DIR"` dulu WAJIB: sesi SSH mewarisi cwd /home/toa (login user), dan `sudo -u
# toa_staging` TIDAK mengubah cwd -- proses lalu mencoba ber-cwd di direktori yang justru
# TERBUKTI tak bisa dibaca toa_staging (itu poin isolasinya), jadi `find` gagal duluan sebelum
# sempat menyentuh argumen path absolutnya sendiri (dibuktikan gagal 2026-09-04, "Failed to
# change directory: /home/toa" -- bukan bug find, itu konsekuensi isolasi yang sengaja dibuat).
ssh "$HOST" "sudo -u $STAGING_USER bash -c '
  cd \"$APP_DIR\" &&
  find . -mindepth 1 -maxdepth 1 \
    ! -name .venv ! -name staticfiles ! -name media -exec rm -rf {} +
'"

echo "[lokal] kirim arsip commit $SHA -> $HOST:$APP_DIR (git archive | tar -x, tanpa push ke origin)"
git archive "$SHA" | ssh "$HOST" "sudo -u $STAGING_USER tar -x -C \"$APP_DIR\""
ssh "$HOST" "sudo -u $STAGING_USER bash -c 'echo $SHA > \"$APP_DIR/REVISI\"'"

echo "[VPS] pip install (idempoten) + migrate + collectstatic + periksa_index"
ssh "$HOST" "sudo -u $STAGING_USER bash -c '
  set -euo pipefail
  cd \"$APP_DIR\"
  .venv/bin/pip install -q --no-input -r requirements.txt
  set -a; . \"$ENV_FILE\"; set +a
  .venv/bin/python manage.py migrate --noinput
  .venv/bin/python manage.py collectstatic --noinput | tail -3
  .venv/bin/python manage.py periksa_index || echo \"PERHATIAN: periksa_index melapor temuan (lihat di atas)\"
'"

echo "[VPS] restart $SERVICE"
ssh "$HOST" "sudo systemctl restart $SERVICE && sleep 2 && sudo systemctl is-active --quiet $SERVICE && echo 'layanan aktif'"

echo "[VPS] verifikasi HTTP (dari VPS sendiri, lewat loopback -- akses tailnet sesungguhnya dites terpisah dari mesin lain)"
ssh "$HOST" "curl -sS -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:8001/login/"

echo "=== SELESAI. Revisi $SHA terpasang di staging (lihat $APP_DIR/REVISI). ==="
echo "Akses: https://truthofauditor.taila54dc6.ts.net/ (lewat tailnet)"
