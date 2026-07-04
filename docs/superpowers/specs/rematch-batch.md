# Re-match Batch — pasangkan mutasi susulan tanpa hapus batch

## Kenapa (masalah)

Ekspor bank/gateway telat semalam. File yang diupload tgl 27 berisi baris **malam
tgl 25** (settlement pending kemarin, tetap membawa tanggal transaksi ASLI) + tgl 26
siang. Akibatnya tiap batch harian lahir dengan **ekor malam T+1**: baris Panel
`tidak_cocok` yang uangnya baru datang di upload HARI BERIKUTNYA. Kasus serupa:
**statement BNI bulanan** — sepanjang bulan baris BNI `tidak_cocok`, sampai file bulanan
masuk.

Sebelum fitur ini satu-satunya jalan: hapus batch + run ulang (atribusi uang pindah ke
tanggal yang salah). Re-match: upload file baru → klik **Re-match** di batch lama →
baris `tidak_cocok`-nya dipasangkan ke mutasi uang AKTIF yang baru datang, uang
dikonsumsi ke batch itu, summary/selisih dihitung ulang → atribusi tetap di tanggal
yang benar.

## Semantik (implementasi: `reconciliation.engine.rematch_batch`)

- **Cakupan:** hanya run `PANEL_BANK` dari batch. `PANEL_BRACKET` di luar v1.
- **Target:** `MatchResult` run itu dengan `bucket == tidak_cocok` DAN `left != None`
  (orphan / `gateway_no_panel` dilewati). Semua reason_code ikut — matcher mengevaluasi
  ulang; verdict terminal (`gateway_unpaid`, `gateway_amount_mismatch`) mereproduksi diri
  (no-op idempoten) terhadap data lama, tapi baris gateway baru (row_hash baru, sudah
  settle) bisa menang lewat Pass 1.
- **Pool kandidat = uang AKTIF** di window yang **SAMA dengan run asli**
  (`matcher.sides(batch.date_from, batch.date_to, ..., include=batch.include,
  tol=batch.tolerance)` — window atas tetap di-widen T+n). **Tidak menyentuh baris yang
  sudah dikonsumsi batch lain** (tak mencuri).
- **Update in-place:** target yang fresh-result-nya berpasangan (`right != None`) ATAU
  ganti bucket → bucket/right/score/reason_code/reason_detail di-update, reason_detail
  disuffix `" (re-match)"` (jejak audit: dipasangkan telat). `ambiguous_multi`
  (TINJAU, right=None) dihitung sebagai perubahan (flip TIDAK→TINJAU, tanpa konsumsi).
  Fresh result yang masih `tidak_cocok`/`no_money` → baris dibiarkan (tak churn).
  **Tidak membuat MatchResult baru** (tak ada orphan `gateway_no_panel` baru; baris pool
  tak terpakai tetap aktif untuk batch berikutnya).
- **Konsumsi:** tiap `right` yang baru berpasangan → `consumed_by_batch = batch` (guard
  `consumed_by_batch__isnull=True` untuk keamanan race).
- **Recompute summary:** hitungan bucket per-run dari `MatchResult` aktual;
  `summary["left"]/["right"]` (ukuran pool historis) dibiarkan. Summary batch dihitung
  ulang lewat `_aggregate_batch(..., batch=batch)` — **pengecualian batch sendiri**: baris
  yang DIKONSUMSI batch ini tetap masuk gross (kalau tidak, gross kolaps ke ~0). Baris
  milik batch LAIN tetap dikecualikan.
- Semua dalam `transaction.atomic()`. **Idempoten:** panggilan kedua tanpa data baru tak
  mengubah apa pun (`terpasang=0`).
- Return: `{"diperiksa", "terpasang", "cocok", "perlu_tinjau"}` untuk flash message.
  `terpasang` = baris yang dapat `right` (uang menempel); `ambiguous_multi` (tanpa right)
  tak dihitung `terpasang`.

## Ritual harian

1. Upload file mutasi baru (bank/gateway). Banner upload menandai batch lama yang
   berpotensi tertutup ("Batch #N (dd/mm) — buka lalu klik Re-match").
2. Buka batch lama → klik **⟳ Re-match** (tombol muncul saat `tidak_cocok > 0`).
3. Baru **reconcile hari berikutnya**.

Urutan penting: re-match dulu batch lama, BARU reconcile hari baru — supaya reconcile
hari baru tak keburu menelan uang susulan yang seharusnya jadi milik batch lama.

## Batas diketahui

- `PANEL_BANK` saja (bukan `PANEL_BRACKET`).
- Kalau reconcile hari baru terlanjur jalan dan menelan uang susulan (jadi orphan/
  ter-konsumsi batch baru), re-match **tak mencuri** dari batch lain — hapus batch tetap
  jalan keluar terakhir.
- Persist `include` di `ReconBatch.include` (batch lama = `None` → diperlakukan "semua
  sumber", perilaku legacy). Pool re-match menghormati `include` batch.
