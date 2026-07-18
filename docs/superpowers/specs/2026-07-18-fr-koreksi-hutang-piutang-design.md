# Paket A — Koreksi Sel FR + Hutang/Piutang — Desain

**Tanggal:** 2026-07-18 · **Status:** disetujui user · **Paket:** A (peta feedback klien 16–17 Jul; paket G selesai duluan)

## Latar

Feedback klien untuk halaman `/bracket/` ("Control Bracket Transaction"):

1. **Edit angka + note**: angka di tabel FR bisa dikoreksi lewat popup kecil; setelah
   diedit, sel diberi tanda (segitiga merah pojok, seperti indikator komentar
   spreadsheet). Referensi visual: screenshot klien (popup kecil + tanda sel).
2. **Header ikut acuan spreadsheet kuning**: `Beban Admin Bank | Biaya Transaksi |
   Beban Other Expense | Beban Mistake CS`.
3. **Hutang/piutang**: kolom di tabel FR (sudah otomatis ada bila datanya muncul)
   **plus halaman terpisah** untuk melihat daftar hutang/piutang saja.

Keputusan user (sesi 2026-07-17/18):
- Model edit = **timpa tampilan, asli utuh** (bukan mengubah Transaction).
- **Semua role** boleh mengedit; semua edit tercatat di Log Audit.
- **Total & Selisih Kontrol ikut nilai koreksi** (dihitung ulang); nilai asli selalu
  terlihat di popup & log.
- Popup: nilai baru + **dropdown kategori alasan** (daftar klien) + catatan bebas.
- Lingkup edit: **semua sel angka baris akun** (sel kategori + Saldo Awal/Akhir).
  Baris TOTAL & kolom Selisih Kontrol tidak bisa diedit langsung (selalu hitungan).
- Halaman hutang/piutang = **daftar otomatis dari data FR** (tanpa input manual).

## Desain

### 1. Model `FRKoreksi` (app `web` — migrasi web 0001, tabel baru, data lama tak tersentuh)

`web/models.py` (saat ini kosong):

- `toko` FK `sources.Toko` (CASCADE)
- `tanggal` DateField — hari breakdown
- `account` CharField(255) — label akun FR mentah (`raw["Bank"]`,
  mis. `BANK BCA | SUSILAWATI | DEPOSIT`), kunci yang sama dipakai `breakdown.py`
- `kolom` CharField(64) — slug kolom: slug kategori (`deposit`, `sesama cm`, …)
  atau `saldo_awal` / `saldo_akhir`
- `nilai` DecimalField(max_digits=18, decimal_places=2) — nilai pengganti
- `alasan` CharField(32), choices `ALASAN_KOREKSI` (lihat bawah), boleh kosong
- `catatan` TextField blank
- `dibuat_oleh` FK `accounts.User` SET_NULL null — snapshot username juga masuk
  Log Audit sehingga jejak tahan hapus-user
- timestamps via `core.TimeStampedModel`
- `UniqueConstraint(toko, tanggal, account, kolom)` — satu koreksi aktif per sel;
  edit ulang = update baris yang sama (riwayat nilai ada di Log Audit)

`ALASAN_KOREKSI` (dari daftar klien, + Lainnya):
`cutoff_mutation` Cutoff Mutation · `mistake_cs` Mistake CS · `biaya_admin_bank`
Biaya Admin Bank · `biaya_admin_qris` Biaya Admin QRIS · `dana_pending` Dana
Pending · `cm_pindah_dana` Sesama CM (Pindah Dana) · `cm_naik_tampung` Sesama CM
(Naik Tampung) · `cm_turun_tampung` Sesama CM (Turun Tampung) ·
`bank_title_beda` Bank Title Tidak Sesuai · `lainnya` Lainnya

### 2. Overlay di `web/breakdown.py`

`bracket_breakdown(toko, tanggal)` mengambil koreksi hari itu (satu query) dan
menumpangkannya SETELAH agregasi mentah:

- Per akun: sel kategori terkoreksi mengganti nilai `kategori[slug]`;
  `saldo_awal`/`saldo_akhir` terkoreksi mengganti hasil `_saldo_batas`.
- **`mutasi` dihitung ulang = Σ kategori terkoreksi** (setara Σ delta mentah bila
  tak ada koreksi — setiap baris FR masuk tepat satu kategori).
- `deposit`/`withdraw`/`net` mengikuti nilai kategori terkoreksi
  (`withdraw = abs(...)` tetap); `trx` (hitungan baris) TIDAK berubah.
- `selisih = saldo_akhir − (saldo_awal + mutasi)` memakai nilai terkoreksi.
- Baris TOTAL = Σ nilai per-akun terkoreksi.
- Tiap sel terkoreksi membawa metadata utk template:
  `{"asli": Decimal|None, "nilai": Decimal, "alasan": str, "catatan": str,
  "oleh": str, "waktu": dt}` dalam dict `acc["koreksi"][kolom_key]`;
  `kolom_key` = slug kategori atau `saldo_awal`/`saldo_akhir`.
- Nilai `asli` = hasil agregasi mentah sel itu (bisa `None` utk saldo yang tak
  terhitung). Data `Transaction` TIDAK PERNAH diubah.
- Sel kategori yang di data mentahnya TIDAK ada (akun tak punya baris kategori itu)
  tetap bisa dikoreksi (asli = 0/kosong) — kebutuhan nyata: FR lupa mencatat beban.
  Kolom ber-koreksi ikut `slugs_muncul` supaya kolomnya tampil.

### 3. UI edit (template `breakdown_bracket.html` + views + HTMX)

- Setiap sel angka baris akun jadi target klik (semua role login; RBAC toko lewat
  `_active_toko` seperti view lain). Baris TOTAL dan kolom Selisih Kontrol bukan
  target.
- Klik sel → `GET /bracket/koreksi/?tanggal=&account=&kolom=` (HTMX) → partial
  `_fr_koreksi_form.html`: popup kecil dekat sel (absolute), berisi nilai asli
  (read-only), input nilai baru, select alasan, textarea catatan, tombol Simpan /
  Batal / (bila sudah ada koreksi) "Kembalikan nilai asli".
- Simpan → `POST /bracket/koreksi/` → validasi (Decimal; account+kolom dikenal) →
  `update_or_create` FRKoreksi → `core.audit.catat` aksi `fr_koreksi`
  (meta: toko, tanggal, account, kolom, asli→baru, alasan) → respons HTMX
  me-refresh SELURUH bagian tabel Control Bracket (nilai, total, selisih ikut
  terhitung ulang server-side; pola refresh sama dgn aksi review yang ada).
- "Kembalikan nilai asli" → POST hapus koreksi → audit `fr_koreksi_hapus` → refresh.
- Tanda sel: pseudo-element CSS segitiga merah kecil di pojok kanan-atas sel
  (`--danger` var token, tanpa emoji/ikon teks) + `title` ringkas
  "asli X → koreksi Y · alasan". Konsisten design system (var token, bahasa
  Indonesia, tanpa glyph teks).

### 4. Urutan header

`KATEGORI_KANONIK` di `web/breakdown.py`: tukar dua entri terakhir blok beban jadi
`… ("biaya transaksi", …), ("beban other expense", …), ("beban mistake cs", …) …`
sesuai acuan kuning klien. Tidak ada perubahan lain.

### 5. Halaman Hutang/Piutang (`/hutang-piutang/`)

- Modul agregasi murni **`web/hutang.py`** (pola `breakdown.py`: query-time dari
  `Transaction.raw`, tanpa migrasi, teruji tanpa render):
  `hutang_piutang(toko, dari=None, sampai=None)` → baris bracket
  `_slug_kategori(raw["Kategori"]) ∈ {"hutang", "piutang"}`, urut tanggal desc lalu
  (Jam, id): `{"tanggal", "account", "kategori", "member"
  (raw["Member"]/raw["Username"] mana yang terisi), "keterangan" (raw["Expense"]
  bila ada), "nominal" (money_delta), "jam"}` + ringkasan
  `{"total_hutang", "total_piutang", "netto", "count"}`.
- View `hutang_piutang` + template `hutang_piutang.html`: filter rentang tanggal
  (default 30 hari terakhir), tabel + ringkasan 3 angka, pager `{% pager %}` 40/hal,
  empty-state `.empty`. Menu sidebar di grup FR/Bracket, label "Hutang/Piutang".
- Scoped toko aktif (`_active_toko`), read-only murni.

### 6. Ekspor

Halaman FR belum punya ekspor Excel — di luar lingkup paket ini. Karena ekspor
kelak membaca `bracket_breakdown`, nilai terkoreksi otomatis ikut bila fitur itu
dibangun.

## Rencana uji

1. Model: unique constraint; str; choices.
2. Overlay (`web/tests_breakdown.py` diperluas + modul test baru): koreksi sel
   kategori mengubah nilai sel, mutasi, selisih, TOTAL; koreksi saldo_awal/akhir;
   koreksi kategori-tak-muncul menambah kolom; tanpa koreksi = perilaku lama persis
   (regresi 0); metadata sel (asli→nilai).
3. View: GET form (login wajib), POST buat/update/hapus + entri AuditLog + respons
   refresh; auditor role boleh; toko scoping.
4. Hutang: agregasi murni (filter kategori, rentang tanggal, ringkasan, urutan);
   view render + pager + empty state.
5. Header: test urutan kolom kanonik baru.
6. Template render (butuh `collectstatic` di worktree segar).

## Risiko & catatan

- **Kunci sel = string label akun mentah**: bila FR mengganti ejaan label akun,
  koreksi lama tak menempel ke label baru (dibiarkan — koreksi bersifat per-hari,
  bukan berkelanjutan).
- **Migrasi baru (web 0001)** — deploy perlu `migrate` (start command prod sudah
  menjalankannya otomatis); tabel baru murni, tanpa risiko data lama.
- Overlay menambah 1 query per render halaman breakdown (ringan, ber-index unik).
- Kolom `hutang`/`piutang` di tabel FR tidak butuh kerja baru (kanonik sudah ada).
