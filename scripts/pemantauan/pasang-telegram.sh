#!/usr/bin/env bash
# Pemasang saluran alarm Telegram — dijalankan PEMILIK, di VPS, sekali.
#
# Kenapa ada skrip ini alih-alih sekadar `echo "TOKEN=..." >> alarm.env`:
# perintah itu menaruh token bot di ~/.bash_history dalam bentuk polos. Kredensial
# produksi aplikasi ini sudah pernah bocor sekali lewat log sesi (butir A3,
# 31-08-2026); tidak ada gunanya menutup satu jalur bocor lalu membuka jalur lain.
# Di sini token dibaca dengan `read -rs` (tidak digemakan, tidak masuk argv, tidak
# masuk history) dan langsung ditulis ke alarm.env bermode 0600.
#
# Pakai:  ~/pemantauan/pasang-telegram.sh
set -uo pipefail

ENV_FILE="${ALARM_ENV_FILE:-$HOME/pemantauan/alarm.env}"
API="${TELEGRAM_API_BASE:-https://api.telegram.org}"

printf 'Token bot dari @BotFather (tidak akan terlihat saat diketik): '
read -rs TOKEN; echo
[ -n "$TOKEN" ] || { echo "Token kosong — dibatalkan."; exit 1; }

echo "Memeriksa token ke Telegram..."
NAMA="$(curl -sS -m 15 "$API/bot$TOKEN/getMe" 2>/dev/null | jq -r 'select(.ok) | .result.username // empty')"
[ -n "$NAMA" ] || { echo "GAGAL: Telegram menolak token itu. Periksa lalu ulangi."; exit 1; }
echo "Token sah — bot @$NAMA."

echo
echo "Sekarang KIRIM satu pesan apa saja ke @$NAMA dari Telegram-mu,"
echo "lalu tekan Enter di sini."
read -r _

CHAT="$(curl -sS -m 15 "$API/bot$TOKEN/getUpdates" 2>/dev/null \
  | jq -r '[.result[]?.message.chat.id] | last // empty')"
if [ -z "$CHAT" ]; then
  echo "Belum ada pesan masuk yang terbaca."
  printf 'Masukkan chat id secara manual (atau Enter untuk batal): '
  read -r CHAT
  [ -n "$CHAT" ] || { echo "Dibatalkan."; exit 1; }
fi
echo "Chat id: $CHAT"

umask 077
TMP="$(mktemp "${ENV_FILE}.XXXXXX")"
# Baris Telegram lama dibuang supaya menjalankan ulang skrip ini tidak menumpuk duplikat.
[ -f "$ENV_FILE" ] && grep -vE '^[[:space:]]*(#[[:space:]]*)?TELEGRAM_(BOT_TOKEN|CHAT_ID)=' "$ENV_FILE" >> "$TMP"
printf 'TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n' "$TOKEN" "$CHAT" >> "$TMP"
mv "$TMP" "$ENV_FILE"; chmod 600 "$ENV_FILE"
unset TOKEN
echo "Tersimpan ke $ENV_FILE (mode $(stat -c %a "$ENV_FILE"))."

echo
echo "Mengirim pesan uji lewat jalur alarm yang SEBENARNYA..."
"$HOME/pemantauan/kirim-alarm.sh" --uji
echo "Selesai. Kalau pesan uji tidak sampai, jalankan:  journalctl -t toa-alarm -n 5"
