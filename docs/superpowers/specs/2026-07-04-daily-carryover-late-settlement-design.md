# Rekonsiliasi Harian: recon_date + Carry-Over "Menunggu Settlement" + Late Settlement

Tanggal: 2026-07-04 · Status: disetujui & diimplementasikan

## Latar belakang

Kebutuhan tim: alur kerja selalu **satu run = satu tanggal**. Transaksi panel malam
tanggal N sering baru muncul mutasinya di file bank tanggal N+1. Sebelum perubahan
ini, konsumsi-saat-sukses mengunci baris panel `tidak_cocok` ke batch-nya, sehingga
mutasi yang datang keesokan hari **tidak pernah bisa match** — selisih tanggal N
terlihat lebih besar dari kenyataan.

Spec awal dari pihak lain ("isolasi per-hari + lookback tepat 1 hari + hasil
immutable") ditolak karena tiga hal:

1. **Diagnosis keliru** — sistem berbasis pool aktif (`consumed_by_batch__isnull=True`),
   bukan "hasil per-tanggal yang tertimpa"; hasil batch lama tidak pernah diubah run baru.
2. **Lookback sudah ada** — `date_ok` sudah window terarah (uang ≥ kredit, maks
   `ToleranceProfile.date_window_days`); masalahnya di konsumsi, bukan di matching.
3. **Immutability bertentangan dengan kebutuhan user** — user justru ingin transaksi 27
   yang ketemu mutasinya saat run 28 **berubah jadi cocok di hasil tanggal 27**.

## Keputusan desain

- **`ReconBatch.recon_date`** (nullable, unik per `(toko, recon_date)` bila terisi).
  Form run wajib mengisi "Tanggal rekonsiliasi"; guard view menolak tanggal yang sudah
  ada (pesan + link batch lama). Mengulang tanggal = hapus batch lama dulu (fitur yang
  sudah ada). Tidak ada checkbox "force".
- **Carry-over:** saat run tanggal N sukses, semua dalam scope dikonsumsi **kecuali**
  baris kredit `tidak_cocok`/`no_money` yang masih dalam window
  (`d > recon_date - date_window_days`) — tetap aktif "menunggu settlement".
  Ketat (window 0) → tidak ada carry-over.
- **Late settlement:** run N+1 memasukkan baris carried ke pool matching biasa
  (`date_ok` membatasi lookback secara alami). Bila match:
  - MatchResult **lama di batch asalnya di-flip** (cocok/perlu_tinjau sesuai skor,
    `reason_code="late_settlement"`, reason asal tersimpan di `reason_detail`,
    ditandai `resolved_by_batch`);
  - summary batch asal dihitung ulang (`refresh_batch_summary` — selisih mengecil);
  - baris kredit dikonsumsi ke **batch asalnya**; baris uang ke batch N+1.
  - Baris carried **tidak pernah** membuat MatchResult baru di batch N+1 dan
    **tidak ikut** gross total batch N+1 (`exclude_tx_ids`) — tanpa dobel hitung.
    Ringkasannya tampil terpisah: kartu "Settlement tertunda dari tanggal sebelumnya".
- **Expiry:** carried yang tak match dan lewat window dikonsumsi diam-diam ke batch
  asalnya; jejak `{tx, home}` disimpan di `summary["late_settlement"]["expired"]`
  batch N+1 supaya bisa dipulihkan.
- **Hapus batch penyelesai:** `revert_late_settlements(batch)` (dipanggil view hapus,
  atomic) mengembalikan flip ke `tidak_cocok/no_money`, mengaktifkan lagi baris
  carried/expired, dan menghitung ulang summary batch asal.
- **`run_batch` atomic:** gagal di tengah = rollback total (tidak ada batch yatim yang
  memblokir tanggal via unique constraint).
- Path legacy (`recon_date=None`, CLI/test lama) berperilaku persis seperti sebelumnya.

## Risiko yang diterima (tercatat)

- Override manual atas hasil `no_money` yang barisnya masih aktif mengeluarkannya dari
  carry-over (jadi baris "baru" di run berikut) — guard defensif ada; perbaikan penuh
  ditandai sebagai follow-up di komentar `web/views.py review()`.
- Ganti profil toleransi antar hari (Longgar → Ketat) membuat carry lama langsung
  kadaluarsa — didokumentasikan di docstring `_can_still_settle`.
- Delete programatik (shell/queryset) melewati revert — jalur resmi adalah view web.
- Filter `date_from`/`date_to` bila diisi mengecualikan baris carried dari run
  (tetap aktif) — ada hint di form.

## Verifikasi

- `reconciliation/tests_carry.py` (15 kasus: carry, window Ketat/Longgar, flip,
  refresh summary, anti dobel hitung, expiry, guard duplikat, rollback atomic,
  revert round-trip, legacy).
- `web/tests_carry_ui.py` (8 kasus: field wajib, guard + link, info pending,
  kartu settlement, catatan di batch asal, kolom Tanggal, hapus batch me-revert).
- Seluruh suite: 280 test hijau.
