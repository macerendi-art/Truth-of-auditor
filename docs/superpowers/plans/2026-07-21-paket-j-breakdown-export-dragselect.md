# Paket J — Saldo carry-forward + rentang, export diperkaya, drag-select, rotasi quote, keseragaman UI

> **For agentic workers:** dieksekusi Workflow ultracode (4 scout paralel → 5 implementer TDD sekuensial [file bersama views.py/app_base.html] → suite + 3 reviewer adversarial + ronde perbaikan), lalu verifikasi browser inline (fixture carry-forward sintetis).

**Goal (5 permintaan klien, 4 gambar):** (I1) Control Bracket — saldo awal/akhir bank tetap tampil walau tanpa gerak SELAMA masih bersaldo, hilang saat saldo dikeluarkan/pindah/cost + filter breakdown RENTANG (mis. 1–30 Juli), bukan 1 hari; (I3) export "yang sekarang hanya ringkasan panel vs panel vs mutasi bank" diperkaya; (I2) tiap tabel bisa drag angka/huruf ala Excel (drag B6:C20 tanpa kena kolom sebelah); rotasi quote login tiap refresh; keseragaman UI (kesan profesional & elegan).

## Keputusan desain

- **I1** `web/breakdown.py`: `bracket_breakdown(toko, dari, sampai=None, ...)` model rentang (`sampai=dari` = perilaku 1-hari; `?date=` back-compat). Carry-forward via `_saldo_carry` (satu agregat `Max(posted_date)<dari` per akun → `_saldo_batas` hanya di hari-penutup itu; dormant tanpa batas lookback). Akun bersaldo tanpa gerak → tampil (mutasi 0, awal==akhir, Selisih Kontrol 0); saldo cleared ke 0 → hilang esoknya. `FRKoreksi` overlay HANYA single-day (kunci koreksi = tanggal tunggal); mode rentang = agregat mentah. Query-time, TANPA migrasi.
- **I3** superset: (A) `build_batch_workbook` + sheet Breakdown Bracket & Rincian Rekening (sheet lama tak diubah); (B) `/bracket/export/` (`export_breakdown`) export tabel breakdown ikut rentang + carry. **Belum ada** tombol export standalone di `/rekening/` (rekening_sheet dipakai (A) saja) — tambahan kecil bila klien mau.
- **I2** `web/static/web/js/range-select.js` global di `app_base.html`, pasang `class="selectable"` ke tabel angka. Seleksi persegi (bounding rowIndex/cellIndex), Cmd/Ctrl+C → TSV; bail pada elemen interaktif (link/tombol koreksi/input) → klik & copy-teks normal tetap jalan.
- **I4** `AuditorLoginView` pilih `login_tagline` acak (10 quote profesional Indonesia) per GET; hero kinetik utuh.
- **I5** perbaikan keseragaman NYATA (tombol submit "Terapkan" seragam, token `.row`/`--warn`); bukan redesign. **DITOLAK** (sengaja, terdokumentasi): aset 3D/meshy/threejs ke app keuangan = sumber "AI slop"; kesan premium dikejar via keseragaman + quote.

## Hasil

- **Workflow**: 13 agent, 1,27 jt token subagent, 0 ronde perbaikan (semua reviewer bersih dari serius). Suite penuh **956 test OK** (dari 906). Commit `e7922b6`(I1)→`2bfc00c`(I2)→`c737651`(I3)→`ad1de4f`(I4)→`d7c615f`(I5).
- **2 temuan minor dibereskan inline** (`f4d2f17`): (a) range-select.js — mousedown pada elemen interaktif kini `clearPaint()` (cegah rect basi membajak Ctrl+C berikutnya); (b) docstring `_saldo_carry` diakurasikan (agregat tetap men-scan SQL pra-`dari`; catat: bila bracket/toko membengkak ratusan ribu, tambah indeks komposit (toko, source_type, posted_date)).
- **Verifikasi browser** (DB scratch fixture carry-forward lintas-hari + DB dev): 02/07 BCA carry 5.000.000 (mutasi 0, Selisih 0); 04/07 BCA HILANG (saldo 0 di 03/07); rentang 01–03/07 agregasi benar. Drag-select: drag kol 3→4 baris 0→1 = tepat 4 sel kolom {3,4}, kolom sebelah TAK tersapu; Ctrl+C → TSV `5.000.000⇥0\n4.500.000⇥-4.500.000`; klik link → seleksi clear (fix minor). Export breakdown 200 xlsx ikut rentang; workbook batch = Ringkasan + 2 Hasil + Breakdown Bracket + Rincian Rekening. Quote login: 6 request → 6 quote elegan berbeda; hero utuh.
- **Catatan lanjutan klien (kuflag, belum dikerjakan):** export interpretasi = superset (batch **dan** halaman breakdown) — bisa dipangkas bila kelebihan; kontinuitas ledger lintas-hari tak terverifikasi dari data dev (1 hari/toko) → carry diuji via fixture sintetis, jaring pengaman = kolom Selisih Kontrol; tombol export di `/rekening/` bisa ditambah bila diinginkan.
