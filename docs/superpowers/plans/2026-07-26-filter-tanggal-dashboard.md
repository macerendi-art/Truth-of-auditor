# Filter Tanggal Dashboard (v1.12.0) — permintaan end user

**Permintaan (26 Juli 2026):** "tambahkan fitur filter pada dashboard sehingga bisa
melihat dashboard pada tanggal-tanggal sebelumnya, dan bisa juga mengambil rentang tanggal."
Acuan tampilan yang dikirim end user: bar `Dari` / `Sampai` / `Terapkan` yang sudah
dipakai di Rincian Biaya & Rincian Rekening.

## Yang dikerjakan

Satu bar filter di dashboard (mode satu toko **dan** mode "Semua Toko"), memakai
pola markup yang sama persis dengan halaman laporan lain — `?dari=&sampai=`.

| Bagian dashboard | Tanpa filter (default) | Mode filter |
|---|---|---|
| Kartu "Rekon terakhir" | batch terakhir | "Rekon dipilih" — tanggal/rentang + jumlah batch + selisih dijumlah |
| Ringkasan Panel & Metode Pembayaran | baris terkunci di batch terakhir | agregat `consumed_by_batch_id__in` seluruh batch in-range |
| Ringkasan Bracket | `ringkas_bracket_hari` tanggal batch | `ringkas_bracket_rentang` seluruh rentang |
| Uang periksa (D) | D batch terakhir | jumlah D seluruh batch rentang |
| Kalender 14 hari | anchor = rekon terakhir / hari ini | anchor = `sampai` |
| Tren selisih | 30 hari terakhir | seluruh batch dalam rentang |
| Rekonsiliasi Terkini | 6 run terbaru | run milik batch dalam rentang |
| **Kerjakan hari ini** | daftar kerja hidup | **tetap hidup — sengaja tak ikut filter** |

## Keputusan yang tak terlihat dari kode

1. **Tanpa parameter = perilaku lama, byte per byte.** Ini kontrak yang dijaga tes
   (`DefaultTetapTests`). Filter adalah lapisan tambahan, bukan penggantian: auditor
   yang tak pernah menyentuh filter tidak boleh melihat perubahan apa pun.

2. **"Kerjakan hari ini" sengaja tidak ikut jendela.** Panel itu daftar kerja, bukan
   laporan. Kalau ikut, badge "Periksa uang tanpa pasangan" akan menampilkan jumlah
   lintas batch sementara tombol di sebelahnya hanya membuka SATU batch — angka dan
   tombol bercerita beda. Karena itu view mengirim `live_last`/`um_d_live` (selalu
   dari batch terakhir toko) khusus untuk panel ini; di mode default nilainya identik
   dengan kartu status, jadi tak ada perubahan tampilan.

3. **Koreksi sel FR (`FRKoreksi`) hanya berlaku pada rentang satu hari** — kunci
   koreksi memang satu tanggal. Aturannya disamakan dengan halaman `/bracket/` supaya
   kartu dashboard selalu tie out dengan halaman yang dituju tautannya (tautan kartu
   Bracket ikut membawa `?dari=&sampai=` yang sedang aktif).

4. **`abs()` withdraw per akun, bukan global.** `ringkas_bracket_rentang` menjumlahkan
   `|Σ withdrawal|` per akun lalu menjumlahkan hasilnya — persis cara
   `bracket_breakdown` menjumlah lintas akun. Kalau di-abs global, satu akun dengan
   koreksi/retur bertanda positif akan saling meniadakan dengan akun lain dan angkanya
   melenceng dari halaman Breakdown.

5. **Mode "Semua Toko" ikut kebagian filter.** Admin yang sedang di mode gabungan tak
   boleh kehilangan filter yang ada di mode satu toko. Semantiknya dicerminkan:
   seluruh batch in-range lintas toko, kolom tabel per toko menampilkan batch terakhir
   **di dalam rentang** (+N bila ada lebih dari satu), dan toko tanpa batch di rentang
   ditandai "tak ada di rentang". Kolom Tinjau & Settlement tetap angka hidup — keduanya
   memang bukan angka bertanggal — dan itu ditulis di sub-judul tabel.

6. **Jumlah query wajib konstan terhadap jumlah toko di kedua mode.** Dijaga dua tes
   N+1 (`DashboardSemuaQueryTests`, `DashboardSemuaFilterTests.test_query_tetap_konstan_di_mode_filter`);
   keduanya sudah diuji-mutasi (loop per toko → tes merah).

## Verifikasi

- Suite penuh hijau (1.369 → 1.383 tes; 14 tes baru: 5 panel kerja/aria + 9 mode gabungan).
- Uji mutasi dua tes penjaga baru: overlay koreksi dipaksa berlaku di rentang → merah;
  bracket gabungan diubah jadi loop per toko → merah.
- Render browser (DB visual 26 batch, 3 toko berdata) 1280 & 375: default, satu tanggal
  lampau, rentang, rentang kosong, mode Semua Toko + rentang. Tanpa error konsol,
  tanpa overflow horizontal di 375.

## Catatan lanjutan (belum dikerjakan, sengaja)

- Rentang sangat panjang (> ~2 bulan) membuat bar tren jadi rapat; jumlah batch yang
  tercakup selalu ditulis di bar filter sehingga angkanya tetap jujur. Bila nanti perlu,
  batasi jumlah bar dengan keterangan eksplisit — jangan memotong diam-diam.
- Kartu "Transaksi per Sumber" dan "Upload Terakhir" tetap angka inventaris global
  (bukan jendela) karena keduanya memang bukan angka bertanggal.
