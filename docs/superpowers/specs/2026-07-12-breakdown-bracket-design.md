# Breakdown Bracket (FR) — Desain

Tanggal: 2026-07-12 · Status: disetujui user (plan mode)

## Masalah

Bracket/FR selama ini hanya tampil sebagai baris transaksi mentah di halaman
Transaksi. Auditor butuh melihat *isi* FR harian secara terstruktur: per
rekening aset operator (FR Account), uang masuk/keluar per kategori, dan
apakah saldo berjalannya konsisten.

## Referensi

Situs teman user (draw-to-data-magic.lovable.app → halaman *Rincian Bank*):

- Tabel **"Control Bracket Transaction (Harian)"** — baris per FR Account,
  kolom: Begining Balance, Deposit, Pending DP, Withdrawal, Adjustment,
  Sesama CM, Beban Admin Bank, Beban Admin QRIS, Beban Mistake CS, Expense,
  Hutang, Piutang, Nett/Loss, Akuran, Ending Balance.
- Tabel rekap **"Pergerakan per Bank"** — Deposit, Withdraw, Net, Trx,
  Saldo Akhir Real per rekening. Catatan situs: *pending tidak dihitung*.

Kelemahan referensi (diverifikasi dari angkanya): kolom *Nett/Loss*
menjumlahkan angka tampilan yang tandanya campur (WD tampil positif padahal
uang keluar), lalu *Akuran* sekadar angka penyeimbang agar
`Awal + Nett/Loss + Akuran = Akhir`. Maknanya kabur.

**Keputusan user: versi disempurnakan** — kategori sama, tetapi mutasi
dijumlah bertanda benar dan kolom kontrol yang jujur:

```
Selisih Kontrol = Saldo Akhir − (Saldo Awal + Σ mutasi bertanda)   → idealnya 0
```

Selisih ≠ 0 = anomali di FR itu sendiri — justru nilai auditnya.

## Pemetaan data (diverifikasi terhadap file FR asli MUL & OKE25)

| Konsep            | Sumber di `Transaction` (source_type=bracket)          |
|-------------------|---------------------------------------------------------|
| FR Account        | `raw["Bank"]` — mis. `BANK BRI \| YOGA \| WITHDRAW`, `QRIS HOKI \| DEPOSIT / WITHDRAW` |
| Kategori asli     | `raw["Kategori"]` (field `jenis` menggepengkan jadi 5 — tidak dipakai) |
| Mutasi bertanda   | `money_delta` (= kolom `Total` file, sudah bertanda)    |
| Saldo berjalan    | `balance_after` (= `Saldo Akhir` file, berjalan **per FR Account**) |
| Urutan kronologis | `(raw["Jam"], id)` — id mempertahankan urutan file      |
| Tanggal report    | `posted_date` (= kolom `Tanggal`, dayfirst)             |

Catatan: kolom `Asset Bank` file BUKAN dimensi akun (satu nilai per file =
nama brand). COR tidak punya sumber bracket → halaman empty-state.

## Bentuk

Halaman `/bracket/` (login + RBAC toko standar), filter tanggal tunggal
(default = tanggal terakhir yang punya data bracket), dua kartu:

1. **Pergerakan per Bank** — per FR Account: Deposit, Withdraw, Net
   (bertanda), Trx (jumlah baris Deposit+Withdrawal; Pending DP tidak
   dihitung), Saldo Akhir. + baris TOTAL.
2. **Control Bracket Transaction (Harian)** — per FR Account: Saldo Awal,
   kolom kategori dinamis (urutan kanonik; hanya yang muncul hari itu;
   kategori tak dikenal tampil di ujung — tidak ada data tersembunyi),
   Total Mutasi, Saldo Akhir, **Selisih Kontrol** (badge hijau 0 / merah).
   + baris TOTAL.

Saldo Awal = `balance_after − money_delta` baris pertama ber-balance;
Saldo Akhir = `balance_after` baris terakhir ber-balance (urut `(Jam, id)`).

Semua baris bracket ikut (termasuk `jenis="admin"` dan baris ter-consume
batch) — ini view data, bukan matching.

## Arsitektur

- `web/breakdown.py` — fungsi murni `bracket_breakdown(toko, tanggal)`;
  query `KeyTextTransform` atas `raw` (tanpa migrasi DB, retroaktif untuk
  data produksi), agregasi Python satu-pass (≤ ~8rb baris/hari/toko).
- View `bracket_breakdown` di `web/views.py` (pola `bank_mutations`),
  URL `bracket/`, template `web/breakdown_bracket.html`.
- Sidebar: sub-item **Breakdown Bracket** di bawah Transaksi; perapihan
  sub-menu — kelas `.link.sub` menggantikan inline style sub-item lama.

## Di luar scope

Export xlsx/csv halaman ini; breakdown bulanan; perombakan urutan menu
sidebar (user hanya minta struktur sub-menu dirapikan).
