#!/usr/bin/env bash
# TITIK TUNGGAL untuk memasang saluran pemberitahuan NYATA (B1/B6). Dipanggil oleh KEDUA unit
# alarm sistem -- `toa-kesehatan-gagal.service` (OnFailure dari toa-kesehatan.service) DAN
# `toa-probe-gagal.service` (OnFailure dari toa-probe.service), lewat baris ExecStart mereka.
# Lihat docs/runbook-pemantauan-2026-09-04.md bagian "Memasang saluran pemberitahuan nyata".
#
# Kenapa satu titik: repo ini tidak punya SMTP/Slack/webhook terkonfigurasi (tak ada kredensial,
# tak ada keputusan layanan mana yang dipakai), dan memilih/membayar layanan semacam itu adalah
# KEPUTUSAN PEMILIK -- bukan sesuatu yang boleh dipasang sendiri oleh agen ini. Jadi hari ini
# berkas ini HANYA mencatat ke journal systemd (prioritas user.err) -- itu SENGAJA, bukan gagal
# senyap: journal + berkas status.json masing-masing (~/kesehatan/status.json,
# ~/probe/status.json) + kode keluar bukan-nol sudah cukup untuk "gagal dengan berisik dan bisa
# dicolok". Yang belum ada cuma saluran yang MENGHUBUNGI SESEORANG secara aktif.
#
# CARA MEMASANG SALURAN NYATA (langkah konkret untuk pemilik, tidak perlu menyentuh unit systemd
# atau skrip pemantauan LAIN sama sekali -- titik masuknya cuma berkas ini):
#   1. Pilih SATU (atau lebih) saluran: webhook (Slack/Discord/Telegram/PagerDuty/n8n/dst.)
#      dan/atau SMTP (msmtp/sendmail).
#   2. Simpan kredensialnya di /home/toa/pemantauan/alarm.env, mode 0600 (BUKAN di unit systemd,
#      yang 0644 dan bisa dibaca semua user lokal; BUKAN pula commit ke repo). Format
#      KUNCI=nilai biasa, contoh:
#        WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ
#        ALARM_EMAIL_TO=ops@contoh.com
#   3. Berkas ini SUDAH punya blok "AKTIFKAN" untuk webhook (opsi A) dan SMTP lewat msmtp
#      (opsi B) di bawah -- keduanya otomatis aktif begitu env yang relevan terisi di
#      alarm.env. Tidak perlu mengedit kode ini kecuali mau saluran lain.
#   4. Uji dengan kegagalan yang SENGAJA dibuat sebelum mempercayainya di produksi -- lihat
#      "Menguji alarm" di runbook; pola yang sama dipakai saat B1/B6 ini dibangun (salinan
#      status, bukan produksi sungguhan).
#
# Argumen: $1 = pesan ringkas satu baris dari unit alarm pemanggil.
set -uo pipefail

PESAN="${1:-(tanpa pesan)}"
ENV_FILE="${ALARM_ENV_FILE:-/home/toa/pemantauan/alarm.env}"

# Journal selalu jalan -- FALLBACK yang SUDAH ADA dan TERBUKTI (lihat bukti di
# docs/runbook-pemantauan-2026-09-04.md), bukan bagian yang menunggu pemilik.
# `journalctl -p err` (lintas SEMUA unit alarm sekaligus) atau `-u <nama>-gagal.service`
# untuk satu jenis saja.
logger -p user.err "ALARM toa: $PESAN"

[ -r "$ENV_FILE" ] || exit 0
# shellcheck source=/dev/null
. "$ENV_FILE"

# --- AKTIFKAN DI SINI -- opsi A: webhook generik (Slack incoming webhook / Discord / n8n / dst.
#     -- semuanya menerima POST JSON serupa; sesuaikan bentuk $body kalau formatnya beda) -----
if [ -n "${WEBHOOK_URL:-}" ]; then
  body="$(jq -n --arg text "ALARM toa: $PESAN" '{text: $text}' 2>/dev/null)"
  if [ -n "$body" ]; then
    curl -fsS -m 10 -X POST -H 'Content-Type: application/json' -d "$body" "$WEBHOOK_URL" \
      >/dev/null 2>&1 || logger -p user.err "ALARM toa: webhook GAGAL terkirim ke saluran terpasang"
  fi
fi

# --- AKTIFKAN DI SINI -- opsi B: SMTP lewat msmtp (butuh `apt install msmtp` + ~/.msmtprc
#     TERISI oleh pemilik lebih dulu; keduanya di luar cakupan skrip ini) ----------------------
if [ -n "${ALARM_EMAIL_TO:-}" ] && command -v msmtp >/dev/null 2>&1; then
  printf 'Subject: [toa] ALARM pemantauan\n\n%s\n' "$PESAN" | msmtp "$ALARM_EMAIL_TO" \
    || logger -p user.err "ALARM toa: email GAGAL terkirim ke saluran terpasang"
fi

exit 0
