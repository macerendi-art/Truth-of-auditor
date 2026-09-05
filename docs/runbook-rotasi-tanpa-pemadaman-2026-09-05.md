# Rotasi kredensial basis data tanpa pemadaman

Alternatif dari [`runbook-rotasi-kunci`](runbook-rotasi-kunci-2026-09-04.md) langkah 2. Pakai yang
ini kalau kamu tidak mau ada momen di mana produksi bergantung pada sesuatu yang belum terbukti.

**Prinsipnya satu kalimat:** jangan mengganti sandi role yang sedang melayani trafik — buat role
baru, pindahkan semuanya satu per satu sambil membuktikan tiap langkah, dan matikan kredensial
yang bocor **paling akhir**, setelah penggantinya terbukti bekerja.

Bandingkan dengan cara langsung: di sana kredensial lama mati **sebelum** yang baru terbukti, jadi
kalau ada yang meleset di dashboard kamu sedang memperbaikinya dengan produksi dalam keadaan mati.

## Kejujuran soal "tanpa pemadaman"

Bukan berarti nol restart. Fase 4 mengubah variabel Railway, dan itu memicu redeploy service `web`.
Yang membuatnya aman: **Railway menahan deployment lama tetap melayani sampai yang baru sehat** —
terbukti pada deploy 05-09-2026, di mana `4fdba10b` tetap `SUCCESS` selama `04af95a3` masih
`BUILDING`. Jadi pergantiannya mulus seperti deploy biasa.

Yang benar-benar dihilangkan cara ini adalah **jendela rusak**: tidak ada saat di mana aplikasi
memakai kredensial yang salah.

## Keadaan awal (diperiksa 05-09-2026)

| | |
|---|---|
| Role login di produksi | **hanya `postgres`** (superuser) |
| `DATABASE_URL` service `web` | `postgresql://postgres:<sandi>@postgres.railway.internal:5432/railway` |
| `~/.prod-url` di VPS | `postgresql://postgres@hayabusa.proxy.rlwy.net:24027/railway?sslmode=require` |
| `~/.pgpass` di VPS | `hayabusa.proxy.rlwy.net:24027:railway:postgres:<sandi>` |

⚠️ Aplikasi lewat jaringan **internal**, cadangan lewat **proxy publik**. Keduanya memakai
kredensial yang sama, jadi keduanya harus dipindahkan.

---

## Fase 1 — Buat role baru (nol dampak, aplikasi tak tersentuh)

```bash
ssh -t toa 'psql -d "$(cat ~/.prod-url)"'
```

Di prompt psql:

```sql
CREATE ROLE toa_app WITH LOGIN SUPERUSER;
\password toa_app
\q
```

`\password` meminta sandi dua kali tanpa menggemakannya dan mengirimkannya sudah ter-hash —
sandinya tidak pernah masuk `argv`, `~/.psql_history`, maupun log server. Jangan memakai
`CREATE ROLE ... PASSWORD '...'`, itu menaruhnya di riwayat.

**Kenapa SUPERUSER:** setara dengan `postgres` sekarang, jadi tidak ada perubahan perilaku yang
perlu diuji di tengah rotasi darurat. Membatasi hak akses adalah perbaikan yang benar, tapi itu
perubahan tersendiri — jangan dicampur ke sini.

Sandinya: huruf dan angka saja. `@ : / ?` merusak parsing URL koneksi.

```bash
LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 40; echo
```

Simpan di password manager sekarang juga. Kamu akan memerlukannya di fase 3 dan 4.

## Fase 2 — Buktikan role baru bekerja SEBELUM apa pun dipindahkan

```bash
ssh -t toa 'read -rs -p "Sandi toa_app: " P; echo; PGPASSWORD="$P" psql \
  -d "postgresql://toa_app@hayabusa.proxy.rlwy.net:24027/railway?sslmode=require" \
  -tAc "select current_user, count(*) from transactions_transaction"; unset P'
```

Harus mencetak `toa_app|<jumlah baris>`. Kalau gagal, berhenti di sini — belum ada yang berubah,
tidak ada yang perlu dipulihkan.

## Fase 3 — Pindahkan cadangan & pemantauan (paling mudah dibatalkan, kerjakan lebih dulu)

```bash
ssh -t toa 'read -rs -p "Sandi toa_app: " P; echo; umask 077
  cp ~/.pgpass ~/.pgpass.lama; cp ~/.prod-url ~/.prod-url.lama
  printf "hayabusa.proxy.rlwy.net:24027:railway:toa_app:%s\n" "$P" > ~/.pgpass
  printf "postgresql://toa_app@hayabusa.proxy.rlwy.net:24027/railway?sslmode=require\n" > ~/.prod-url
  chmod 600 ~/.pgpass; unset P
  psql -d "$(cat ~/.prod-url)" -tAc "select current_user"'
```

Harus mencetak `toa_app`. Lalu buktikan kedua pemakainya benar-benar jalan:

```bash
ssh toa 'sudo systemctl start toa-kesehatan.service; sleep 5; systemctl show toa-kesehatan.service -p Result --value'
ssh toa 'sudo systemctl start toa-cadangan.service'   # ±15-25 menit
ssh toa 'tail -f ~/cadangan/backup.log'               # tunggu "=== SELESAI OK ==="
```

⛔ **Jangan lanjut ke fase 4 sebelum satu cadangan penuh berhasil dengan kredensial baru.**
Kalau gagal, kembalikan: `mv ~/.pgpass.lama ~/.pgpass; mv ~/.prod-url.lama ~/.prod-url`.

## Fase 4 — Pindahkan aplikasi

Di dashboard Railway, service **web**, ubah `DATABASE_URL` menjadi **string mentah**:

```
postgresql://toa_app:<sandi-baru>@postgres.railway.internal:5432/railway
```

⚠️ Kalau nilainya sekarang berupa referensi `${{Postgres.DATABASE_URL}}`, mengetik string mentah
memutus tautan itu — **itu memang yang diinginkan** (kita sedang memakai role lain), tapi catat
konsekuensinya: variabel ini tidak lagi ikut berubah otomatis bila kredensial service Postgres
diubah nanti.

Railway akan redeploy. Tunggu sampai `SUCCESS`, lalu:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://auditor.wolfgang-77.com/   # 403 = sehat
cd /Users/macads/Truth-of-auditor && railway ssh --service web \
  '/opt/venv/bin/python manage.py periksa_index'                             # harus keluar 0
```

Sampai titik ini kredensial lama **masih hidup**, jadi kalau ada yang meleset kamu bisa
mengembalikan `DATABASE_URL` ke nilai lama dan semuanya pulih.

## Fase 5 — Baru matikan kredensial yang bocor

Hanya setelah fase 3 dan 4 terbukti.

```bash
ssh -t toa 'psql -d "$(cat ~/.prod-url)"'
```

```sql
\password postgres
\q
```

**Jangan** `ALTER ROLE postgres NOLOGIN`. `postgres` adalah superuser bootstrap dan sebagian
tooling Railway mengasumsikannya bisa login; matikan sandinya saja. Simpan sandi `postgres` yang
baru di password manager sebagai jalur darurat kalau `toa_app` bermasalah.

Sandi yang bocor mati pada detik ini.

## Fase 6 — Bereskan sisa

Di dashboard service **Postgres**, `PGPASSWORD` dan `POSTGRES_PASSWORD` masih memuat **sandi lama
yang bocor**. Keduanya hanya dibaca saat inisialisasi pertama, jadi tidak berpengaruh pada apa pun
— tapi membiarkan rahasia yang bocor tergeletak di dashboard tidak ada gunanya. Samakan dengan
sandi `postgres` yang baru.

Verifikasi terakhir, dan jangan lewati:

```bash
ssh toa '~/pemantauan/kirim-alarm.sh --uji'    # saluran alarm masih hidup
ssh toa 'cat ~/cadangan/status.json'           # verdict OK, terakhir_ok hari ini
```

Lalu hapus salinan lama supaya kredensial yang bocor tidak tertinggal di disk:

```bash
ssh toa 'rm -f ~/.pgpass.lama ~/.prod-url.lama'
```

---

## Kalau harus dibatalkan di tengah

| Berhenti di | Cara pulih |
|---|---|
| Fase 1–2 | Tidak ada yang berubah. `DROP ROLE toa_app;` kalau mau bersih |
| Fase 3 | `mv ~/.pgpass.lama ~/.pgpass; mv ~/.prod-url.lama ~/.prod-url` |
| Fase 4 | Kembalikan `DATABASE_URL` service web ke nilai lama; kredensial lama masih hidup |
| Fase 5 | Tidak bisa dibatalkan — sandi lama sudah mati. Tapi `toa_app` sudah terbukti sejak fase 3–4 |

## Yang belum pernah diuji

Prosedur ini **belum pernah dijalankan**. Fase 1, 2, 3, dan 5 memakai perintah yang perilakunya
sudah diverifikasi di sistem ini; fase 4 bergantung pada bentuk dashboard Railway saat kamu
membukanya. Kerjakan di jam sepi, dan pastikan tidak ada yang sedang menjalankan rekonsiliasi —
run yang terputus **tetap bisa sudah commit**.
