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

# `--uji` : kirim pesan percobaan lewat SEMUA saluran yang terpasang, tanpa merusak apa pun.
# Ada supaya pemilik bisa membuktikan salurannya benar-benar sampai SEBELUM mempercayainya --
# tanpa harus memalsukan kegagalan pemantauan lebih dulu.
if [ "${1:-}" = "--uji" ]; then
  PESAN="UJI SALURAN $(date '+%F %T %Z') dari $(hostname) -- ini bukan alarm sungguhan."
else
  PESAN="${1:-(tanpa pesan)}"
fi
ENV_FILE="${ALARM_ENV_FILE:-/home/toa/pemantauan/alarm.env}"

# Journal selalu jalan -- FALLBACK yang SUDAH ADA dan TERBUKTI (lihat bukti di
# docs/runbook-pemantauan-2026-09-04.md), bukan bagian yang menunggu pemilik.
# `-t toa-alarm` WAJIB: tanpa tag stabil, journald kadang salah atribusi proses `logger` yang
# cepat keluar ke unit systemd-nya -- dibuktikan nyata di sesi ini (`journalctl -u
# toa-kesehatan-gagal.service` sempat TIDAK menunjukkan baris alarmnya sama sekali walau unitnya
# start/finish normal; baru ketemu lewat `-t root` sebelum tag ini ditambah). Baca alarm dengan
# `journalctl -t toa-alarm` (lintas SEMUA unit alarm, stabil, tidak bergantung atribusi unit) --
# JANGAN mengandalkan `-u <nama>-gagal.service` sendirian untuk memastikan alarm TIDAK berbunyi.
logger -p user.err -t toa-alarm "ALARM toa: $PESAN"

[ -r "$ENV_FILE" ] || exit 0
# shellcheck source=/dev/null
. "$ENV_FILE"

# --- AKTIFKAN DI SINI -- opsi A: webhook generik (Slack incoming webhook / Discord / n8n / dst.
#     -- semuanya menerima POST JSON serupa; sesuaikan bentuk $body kalau formatnya beda) -----
if [ -n "${WEBHOOK_URL:-}" ]; then
  # BERISIK, bukan diam: WEBHOOK_URL terisi berarti pemilik MENGIRA alarm terkirim. Kalau `jq`
  # tidak ada, versi lama melewati blok ini tanpa sepatah kata pun -- persis kelas kegagalan
  # senyap yang seluruh rilis ini ada untuk menutupnya.
  if ! command -v jq >/dev/null 2>&1; then
    logger -p user.err -t toa-alarm \
      "ALARM toa: WEBHOOK_URL terpasang TAPI \`jq\` tidak ada -- webhook TIDAK terkirim. Pasang: sudo apt install jq"
  fi
  body="$(jq -n --arg text "ALARM toa: $PESAN" '{text: $text}' 2>/dev/null)"
  if [ -n "$body" ]; then
    curl -fsS -m 10 -X POST -H 'Content-Type: application/json' -d "$body" "$WEBHOOK_URL" \
      >/dev/null 2>&1 || logger -p user.err -t toa-alarm "ALARM toa: webhook GAGAL terkirim ke saluran terpasang"
  fi
fi

# --- AKTIFKAN DI SINI -- opsi B: SMTP lewat msmtp (butuh `apt install msmtp` + ~/.msmtprc
#     TERISI oleh pemilik lebih dulu; keduanya di luar cakupan skrip ini) ----------------------
if [ -n "${ALARM_EMAIL_TO:-}" ]; then
  # Sama seperti webhook di atas: kondisi `&& command -v msmtp` yang lama membuat blok ini
  # dilewati DIAM-DIAM ketika msmtp belum terpasang -- pemilik mengisi ALARM_EMAIL_TO, mengira
  # email menyala, dan tidak pernah menerima apa pun. Diperiksa 04-09-2026 di VPS: msmtp memang
  # BELUM ada. Jadi ketiadaannya sekarang berbunyi.
  if command -v msmtp >/dev/null 2>&1; then
    printf 'Subject: [toa] ALARM pemantauan\n\n%s\n' "$PESAN" | msmtp "$ALARM_EMAIL_TO" \
      || logger -p user.err -t toa-alarm "ALARM toa: email GAGAL terkirim ke saluran terpasang"
  else
    logger -p user.err -t toa-alarm \
      "ALARM toa: ALARM_EMAIL_TO terpasang TAPI \`msmtp\` tidak ada -- email TIDAK terkirim. Pasang: sudo apt install msmtp + isi ~/.msmtprc"
  fi
fi

# --- AKTIFKAN DI SINI -- opsi C: Telegram bot -------------------------------------------------
# Butuh DUA nilai di alarm.env: TELEGRAM_BOT_TOKEN (dari @BotFather) dan TELEGRAM_CHAT_ID.
# TELEGRAM_API_BASE hanya untuk PENGUJIAN (diarahkan ke penerima lokal); biarkan kosong di produksi.
#
# Sengaja BERISIK saat setengah terisi: mengisi satu tapi lupa satunya adalah kesalahan yang
# paling mungkin terjadi, dan versi diam akan membuat pemilik mengira alarm menyala.
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] || [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    logger -p user.err -t toa-alarm \
      "ALARM toa: Telegram setengah terpasang (butuh TELEGRAM_BOT_TOKEN DAN TELEGRAM_CHAT_ID) -- pesan TIDAK terkirim"
  else
    tg_base="${TELEGRAM_API_BASE:-https://api.telegram.org}"
    # Token TIDAK pernah masuk log: hanya kode HTTP yang dicatat saat gagal.
    tg_kode="$(curl -sS -m 15 -o /dev/null -w '%{http_code}' \
      -X POST "$tg_base/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
      --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" \
      --data-urlencode "text=ALARM toa: $PESAN" 2>/dev/null || echo 000)"
    if [ "$tg_kode" != "200" ]; then
      logger -p user.err -t toa-alarm "ALARM toa: Telegram GAGAL terkirim (HTTP $tg_kode)"
    fi
  fi
fi

exit 0
