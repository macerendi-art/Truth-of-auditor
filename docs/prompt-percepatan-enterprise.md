# Prompt siap pakai — "Buat TOA secepat kelas enterprise"

Salin blok di bawah ini dan kirim sebagai satu pesan. Ia sudah memuat konteks,
angka dasar, dan pagar-pagar yang mencegah pekerjaan berbelok ke arah yang
terbukti merugikan. Perbarui angka "Titik awal" bila sudah berubah.

---

```
Kerjakan program percepatan Truth of Auditor sampai kelas enterprise: cepat,
stabil, tanpa bug, dan memakai VPS kita seefektif mungkin. Jalankan paralel —
gunakan workflow, summon subagent sebanyak yang perlu, campur Fable 5 untuk
bagian yang sulit. Commit dan push tiap potong pekerjaan yang selesai supaya
kita selalu punya jalan pulang.

DEFINISI SELESAI (terukur, bukan perasaan):
1. Tidak ada halaman > 2 detik pada toko terbesar (g25/COR, 1,54 juta baris),
   diukur panas lewat Django test client di VPS.
2. Tidak ada halaman > 5 detik pada rentang satu bulan penuh.
3. Rekonsiliasi harian toko tersibuk < 30 detik wall-clock, dan tidak ada satu
   pun jalur yang bisa menyentuh batas 100 detik Cloudflare / 120 detik gunicorn.
4. Suite tes penuh hijau (~1.700+) sebelum tiap push. Nol regresi angka:
   rekonsiliasi tanggal lama harus menghasilkan angka identik.
5. Setiap klaim percepatan disertai angka SEBELUM dan SESUDAH yang kamu ukur
   sendiri di VPS, bukan estimasi.

PAGAR — sudah diriset, jangan diulang dari nol:
- JANGAN ganti stack. ASGI/uvicorn, ClickHouse, PgBouncer, ganti frontend:
  semuanya sudah dievaluasi dan DITOLAK dengan pengukuran. Beban ini CPU-bound
  dan bottleneck-nya ada di bentuk query + materialisasi ORM, bukan teknologi.
- JANGAN pasang cache di atas query yang masih buruk — itu menyembunyikan
  masalah dan run pertama tetap lambat. Perbaiki query dulu.
- JANGAN menaikkan shared_buffers/work_mem tanpa mengukur; sudah dibuktikan
  tidak memberi apa-apa pada beban ini.
- Data produksi tidak boleh disentuh untuk eksperimen. VPS berisi salinan
  penuh — pakai itu.
- Bahasa Indonesia untuk UI, komentar, dan commit. Baca CLAUDE.md dulu.

PRIORITAS (urut dampak/usaha, sudah diukur — kerjakan dari atas):
A. Tiga titik kode panas yang memakan waktu di PYTHON, bukan SQL:
   - web/rekening.py rentang bulan: 23–47 detik, 20,7 detik di antaranya hanya
     membuat 801 ribu objek ORM. Ganti ke values()/agregasi SQL.
   - web/breakdown.py mode rentang dan web/biaya.py: pola cacat yang sama.
   - Query jendela dashboard (panel_sum/metode): tak dibatasi toko & tanggal.
B. Tabel ringkasan harian per (toko, tanggal, sumber, jenis), diisi saat
   run_batch + backfill. Batch historis tidak pernah berubah, jadi ini benar
   secara konstruksi dan harus di-tie-out dengan tes. Membuat halaman Semua
   Toko (13,5 dtk) dan Rekap Bulanan turun ke orde milidetik.
C. Worker latar untuk rekonsiliasi — BELUM ADA sama sekali hari ini
   (run_batches_auto dipanggil langsung di web/views.py:1301, tidak ada
   Celery/RQ/apa pun). Ini yang menghapus risiko HTTP 524, bukan mempercepat.
D. Empat halaman yang biayanya tumbuh mengikuti SELURUH RIWAYAT — ini utang
   struktural yang pasti memburuk walau volume harian tetap: _saldo_carry
   (11–12 ms per hari sejarah), dashboard tanpa filter, /bracket/, /tinjau/.
   Perlu batas tanggal, snapshot saldo, atau ringkasan.
E. Anomali matcher yang BELUM terpecahkan: g25 tanggal 26-08 memakan 24 detik
   sementara 20-08 dengan ukuran hampir sama hanya 1,5 detik — reprodusibel,
   dan hipotesis "banyak baris tak berpasangan" sudah ditolak datanya sendiri.
   Selidiki sampai ketemu sebabnya sebelum menambal.
F. Buang ~2,26 GB index yang tidak pernah dipakai satu query pun. Dulu ini
   soal hemat disk; sekarang soal hemat CACHE, karena database akan melewati
   ukuran RAM.

KEBERSIHAN YANG HARUS IKUT DIKERJAKAN:
- Perintah manajemen pemeriksa kesehatan yang bisa dijalankan berkala dan
  melaporkan: ukuran DB, waktu halaman terberat, index hilang/invalid, umur
  cadangan terakhir, dan ambang mana yang sudah terlampaui.
- Patokan waktu halaman dicatat berkala supaya perlambatan ketahuan SEBELUM
  operator mengeluh.

Laporkan dalam bahasa manusia: apa yang berubah, angkanya berapa, apa yang
kamu tolak dan kenapa, dan apa yang masih tersisa.
```

---

## Titik awal (diukur 01-09-2026, VPS berisi salinan penuh produksi)

Sesudah empat index yang sudah terpasang:

| Halaman | MXW | COR (g25) | HK2 (k25) |
|---|---|---|---|
| Dashboard | 0,60 dtk | 0,70 | 0,42 |
| Mutasi Bank | 2,03 | 1,75 | 1,29 |
| Transaksi | 0,16 | 0,16 | 0,12 |
| Bracket (1 hari) | 1,97 | 1,57 | 0,96 |
| Area Pengecekan | 0,24 | 0,68 | 0,20 |

Yang masih jauh dari target: `/rekening/` rentang sebulan **23–28 detik**
(dua bulan: 47 detik), dashboard Semua Toko + jendela **13,5 detik**,
`/bracket/` rentang sebulan **5–7 detik**.

## Kenapa ini akan melambat lagi kalau dibiarkan

- Database 13 GB tumbuh ±10 GB/bulan dan **melewati RAM 23 GB pada bulan ke-1**;
  cakupan cache jatuh ke ~58% di bulan ke-2 dan ~26% di bulan ke-6.
- Empat halaman biayanya linear terhadap **seluruh riwayat**, jadi memburuk
  selamanya walau tidak ada tambahan berkas per hari.
- Dashboard tanpa filter menembus 3 detik di **bulan ke-4–5**, `/bracket/`
  1 hari di **bulan ke-1–3**.

## Yang tidak perlu dikhawatirkan

Dependensi aplikasi bersih — nol paket tertinggal. Yang jatuh tempo lebih dulu
adalah **Python 3.11 (EOL Oktober 2027)**, bukan Django (LTS April 2028) atau
PostgreSQL 18 (2030).
