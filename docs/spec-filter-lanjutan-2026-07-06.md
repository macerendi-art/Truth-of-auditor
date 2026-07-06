# Spec: Filter Lanjutan & Dependable — siap diimplementasikan agen (2026-07-06)

Spec ini ditulis untuk DIKERJAKAN OLEH AGEN (Claude Code) di repo ini, TDD per filter.
Sumber: kebutuhan auditor nyata dari trial OKE25 (fork Sabianhk) + pola yang sudah ada
di repo ini (sorting server-side, export-ikut-filter). Scope sudah disetujui pemilik fork;
bagian "Preset tersimpan" sengaja DITUNDA (fase 2, jangan dikerjakan).

## Kontrak "dependable" (fondasi — berlaku untuk SEMUA filter di bawah)

1. **Server-side query-param.** Tak ada filter JS-only. Setiap filter = param GET dengan
   nama stabil; halaman dirender dari DB, bukan menyaring DOM.
2. **Komposabel (AND).** Semua kombinasi param valid. Fungsi helper tunggal per halaman
   yang menerapkan seluruh param ke queryset — jangan tersebar di banyak cabang if.
3. **URL shareable.** Auditor bisa copy URL berisi kombinasi filter dan kirim ke rekan;
   halaman terbuka dengan state sama. Konsekuensi: pagination & tautan sorting WAJIB
   mempertahankan seluruh param aktif (querystring merge, bukan rebuild manual per link).
4. **Export mengikuti filter aktif.** Pola ini sudah ada di export Transaksi repo ini —
   perluas ke semua halaman yang dapat filter baru. Guard batas baris tetap berlaku.
5. **Empty-state jujur.** Hasil kosong menyebut filter yang aktif ("0 baris untuk
   channel=DANA, alasan=weak_name") + tombol "Reset filter" (URL tanpa param).
6. **Index.** Kolom yang difilter berulang perlu index: `reason_code` (MatchResult),
   `jenis`, dan (bila mengadopsi PR #6) `dest_account` sudah ber-index.
7. **Hitungan pada chip = kebenaran.** Chip menampilkan count hasil query yang sama
   dengan tabel; jangan hitung terpisah dengan logika beda.

**GOTCHA wajib tahu (sudah menggigit di fork):**
- Key JSON berspasi (`raw["Player Bank"]`) TIDAK bisa dipakai
  `values_list("left__raw__Player Bank")` — error "Column aliases cannot contain
  whitespace". Wajib `annotate(x=KeyTextTransform("Player Bank", "left__raw"))`.
  Filter `filter(**{"left__raw__Player Bank__istartswith": ...})` aman.
- Parsing nominal input user: terima format lokal `50.000` → normalisasi ke int
  (referensi: quick-search nominal di repo ini).

## Konvensi param

| Param | Nilai | Arti |
|---|---|---|
| `akun` | id Upload-group / label akun | rekening operator (bisa multi: `akun=a&akun=b`) |
| `channel` | string segmen-1 Player Bank | channel pemain (DANA/GOPAY/BCA/…) |
| `alasan` | reason_code | filter alasan hasil |
| `skor` | `55-69` \| `70-84` \| `85-100` | band skor |
| `malam` | `1` | hanya baris jam ≥ 18:00 |
| `nmin`,`nmax` | int rupiah | rentang nominal (preset UI mengisi ini) |
| `uang` | `bebas` \| `terpakai` \| `carried` | status penyelesaian baris uang |
| `arah` | `dp` \| `wd` | arah transaksi |

---

## Bundle A — Identitas sumber uang

### A1. Filter Rekening Operator (per AKUN, bukan per bank)

**Kebutuhan.** Auditor bertanya "mutasi lewat rekening mana yang banyak nyangkut" —
BCA-HENDI ≠ BCA-NIJUN ≠ BRI-PANCA ≠ MANDIRI-SITI. Filter per-bank saja terlalu kasar.

**Sumber identitas.** Baris uang punya FK `upload`; identitas akun diturunkan dari
`upload.account` (bila terisi) atau dari `upload.original_name` (pola nama file:
`27_JUNI_2026_WD_BCA_NIJUN_...` → label "BCA NIJUN"). Buat helper murni
`akun_label(original_name) -> str` + tes untuk semua pola nama file nyata
(lihat daftar di bawah), fallback = nama file utuh.

Pola nama file nyata (dari trial OKE25):
```
27_JUNI_2026_WD_BCA_NIJUN_x.CSV      -> BCA NIJUN
27_JUNI_2026_WD_BCA_HENDI_x.pdf     -> BCA HENDI
27_JUNI_2026_WD_BRI_PANCA_SENTANA_x -> BRI PANCA SENTANA
28 JUN 2026 DP MANDIRI PUTRI AYU ASARI_x -> MANDIRI PUTRI AYU ASARI
29-06-2026 DP BRI PANCA SENTANA_x   -> BRI PANCA SENTANA
MUTASI DP QR FLYER OKE25 27-06_x    -> QR FLYER (gateway)
```

**Penerapan.**
- Halaman Transaksi: dropdown/chips akun (distinct upload dalam scope toko+filter tanggal),
  `qs.filter(upload_id__in=<uploads akun terpilih>)`.
- Run/Batch detail sisi uang & "Uang Tanpa Pasangan": filter `right__upload_id__in=...`.

**Acceptance.**
- [ ] Dua file BCA beda pemilik menghasilkan dua opsi akun berbeda.
- [ ] Filter akun + filter tanggal + arah bisa dikombinasikan.
- [ ] Export hasil terfilter hanya berisi baris akun itu.

### A2. Filter Channel Pemain (Player Bank segmen-1)

**Kebutuhan.** "Deposit DANA yang gagal match berapa?" Channel = segmen-1
`raw["Player Bank"]` sisi panel (`DANA|nama|nomor`).

**Referensi implementasi hidup** (boleh ditiru utuh): fork
`web/views.py` + `web/templates/web/_run_table.html` di branch
`Sabianhk:integrasi/ui-makeover-hardening` — chip channel + count, nested di dalam
filter bucket, pakai `KeyTextTransform`; termasuk tes-tesnya (11 tes).

**Penerapan.** Run detail (chips di bawah tab bucket) + halaman Transaksi (dropdown).
Baris non-panel / Player Bank kosong → grup "—" (tetap bisa dipilih; jangan hilang).

**Acceptance.**
- [ ] Chip channel menampilkan count per channel di bucket aktif; klik = filter; klik
      "Semua channel" = reset param channel saja (bucket bertahan).
- [ ] Channel kosong tidak membuat error dan tampil sebagai "—".

---

## Bundle B — Triage hasil

### B1. Chips reason_code

**Kebutuhan.** Auditor mau menyaring "hanya kandidat lemah" atau "hanya no_money".
Reason yang ada hari ini: `ticket`, `ticket_amount`, `amount+date+name`, `amount_fee`,
`date_before`, `weak_name`, `no_money`, `no_bracket`, `no_panel` (+ bila PR #6 diadopsi:
`bank_dest`, `alias_history`, `pulsa_manual`, `gateway_unpaid`, `gateway_no_panel`).

**Penerapan.** Run detail & Antrean Tinjau: chips reason (distinct + count) DI DALAM
bucket aktif, param `alasan=`. Jangan hardcode daftar reason — derive dari data
(`values("reason_code").annotate(n=Count("id"))`) supaya reason baru otomatis muncul.
Sekalian: label ramah per reason (peta reason→label; fork punya contoh lengkap di
`web/templatetags/web_extras.py`).

**Acceptance.**
- [ ] Chips hanya menampilkan reason yang ada di bucket aktif, dengan count benar.
- [ ] Reason baru di masa depan tampil tanpa perubahan kode.

### B2. Band skor

**Kebutuhan.** Prioritas review: yang paling meragukan dulu. Param `skor=55-69` dst →
`score__gte/__lt`. Terapkan di Antrean Tinjau (utama) + run detail (sekunder).

**Acceptance.**
- [ ] `skor=55-69` hanya menampilkan 55 ≤ score < 70; kombinasi dgn `alasan=weak_name` benar.
- [ ] Nilai param tak dikenal diabaikan dengan aman (tanpa 500).

### B3. Toggle jam malam (ekor T+1)

**Kebutuhan.** Baris malam (≥18:00) di hari terakhir window besar kemungkinan ekor
settlement besok, bukan selisih riil — auditor perlu memisahkan dua populasi ini cepat.
Param `malam=1` → `annotate(h=ExtractHour("left__occurred_at")).filter(h__gte=18)`
(atau `occurred_at__hour__gte=18` bila didukung). Terapkan di run detail + batch detail.

**Acceptance.**
- [ ] Toggle malam menampilkan hanya baris jam 18:00–23:59.
- [ ] Kombinasi malam+alasan+channel konsisten dengan tabel dan export.

---

## Bundle C — Uang & nominal

### C1. Rentang nominal + preset

**Kebutuhan.** "Selisih gede dulu yang gw kejar." Param `nmin`/`nmax` (rupiah, int)
pada `amount`; UI menyediakan preset yang mengisi param: `<50rb`, `50rb–1jt`, `1–5jt`,
`>5jt`, plus input bebas. Normalisasi input `50.000` → 50000.

**Acceptance.**
- [ ] nmin saja / nmax saja / keduanya — semuanya valid.
- [ ] Preset menghasilkan URL yang sama dengan pengisian manual.

### C2. Status uang (bebas / terpakai / carried)

**Kebutuhan.** "Uang nganggur berapa sekarang?" Di halaman Transaksi, untuk baris
sumber uang (bank/gateway):
- `uang=bebas`   → belum dipakai batch mana pun (sesuaikan ke field repo ini:
  `consumed_by_batch IS NULL` dan tidak ter-resolve mekanisme late-settlement).
- `uang=terpakai` → sudah dikonsumsi/di-resolve batch (tampilkan batch-nya di kolom).
- `uang=carried` → khusus sisi KREDIT: baris panel yang sedang menunggu settlement
  (pakai helper `_carried_results`/`pending_settlement_count` yang sudah ada — satu
  sumber kebenaran, jangan duplikasi query).

**Acceptance.**
- [ ] Jumlah `uang=bebas` + `uang=terpakai` = total baris uang scope yang sama.
- [ ] `uang=carried` cocok dengan `pending_settlement_count(toko)`.

### C3. Arah DP/WD konsisten

**Kebutuhan.** Param `arah=dp|wd` tersedia SERAGAM di Transaksi, run detail, Antrean
Tinjau, Uang Tanpa Pasangan (sebagian halaman sudah punya — samakan nama param & posisi
UI). `jenis="admin"` tak pernah ikut kedua arah.

---

## Urutan pengerjaan yang disarankan (TDD per langkah)

1. Fondasi: helper penerapan-param per halaman + preservasi querystring di
   pagination/sorting/export (tes: URL kombinasi 3 param bertahan lintas halaman-2).
2. A1 `akun_label` (pure function, tes pola nama file nyata) → filter Transaksi → sisi uang.
3. A2 channel (tiru referensi fork) → B1 reason chips + peta label.
4. B2 skor + B3 malam.
5. C1 nominal + C3 arah → C2 status uang (paling nempel ke internal engine — terakhir).
6. Sapu: empty-state + reset, export semua halaman, index.

## Non-goals

- Preset filter tersimpan (fase 2 — belum disetujui).
- Filter sisi UI-only/JS — dilarang oleh kontrak dependable.
- Mengubah semantik engine/carry-over — spec ini murni lapisan baca.
