# Flow Harian Tanpa Mikir — Design Spec (T+1, Re-match, Upload Massal)

**Status:** SHIPPED 2026-07-05 (branch `fix/t1-settlement-matching`, PR #2 ke upstream `main`).
**Plan:** `docs/superpowers/plans/2026-07-05-daily-flow-rematch.md` · **Spec detail re-match:** `specs/rematch-batch.md`

## Masalah

Ekspor mutasi bank/gateway **tertinggal satu malam**: file yang diupload tanggal 27 berisi ekor
25-malam (settlement pending kemarin, tanggalnya tetap tanggal transaksi ASLI) + 26-siang.
Akibatnya setiap batch harian lahir dengan **ekor `tidak_cocok`** yang uangnya baru datang di
upload besoknya — dan satu-satunya obat dulu adalah hapus batch + re-run. Kasus ekstrem: BNI
hanya keluar statement 1×/bulan (±171 baris WD/hari menggantung sebulan).

Masalah kedua: QR payment ternyata punya kunci **immutable & unik** — TX ID (`D1761515`) yang
digenerate gateway dan muncul di panel maupun mutasi QR. Fuzzy matching untuk QR itu salah alat;
sebelum overhaul, 2.798 baris nyangkut di perlu_tinjau karena tie skor-100 antar deposit berulang.

## Keputusan produk (locked, dari user)

1. QR UNPAID di-exclude dari uang → muncul sebagai selisih; ticket ada tapi UNPAID = `gateway_unpaid` TERMINAL (tidak boleh nyasar ke bank fuzzy).
2. Uang settled tanpa panel → tampil `tidak_cocok` (`gateway_no_panel`) — sinyal uang-masuk-tanpa-record.
3. Satu relasi PANEL_BANK dengan `reason_code` berbeda (bukan split relasi — split bikin `_matched_money` double-count).
4. Pair ambigu (≥2 kandidat identitas BEDA, skor seri) → perlu_tinjau tanpa konsumsi; deposit berulang user sama BUKAN ambigu.
5. Pair tinjau (weak_name): uang tetap dikonsumsi & dihitung matched — konservatif, memaksa review.
6. Re-match: otomatis setelah upload (tanpa klik); baris UNPAID/terminal ikut dievaluasi ulang (file gateway baru bisa membawa status PAID dengan row_hash baru).
7. Tanggal reconcile: prefill otomatis hari berikutnya; tanggal kosong (= telan semua data) harus dikonfirmasi modal.

## Arsitektur

### Matching waterfall (`_MoneyMatcher.match`)
- **Pass 1 — kunci eksak gateway** (SETTLED-only via `raw["Payment Status"]`): `ticket_no` → fallback `reference`.
  Hasil terminal: `gateway_ticket`/`gateway_reference` (cocok), `gateway_amount_mismatch`, `gateway_unpaid`.
  Orphan settled → `gateway_no_panel`.
- **Pass 2 — bank fuzzy** hanya untuk sisa panel: blok nominal → window tanggal searah (bank ≥ panel, ≤ `date_window_days`)
  → **`dest_account`** (nomor tujuan WD; ekstraksi BCA `- - <hp>`, BRI `BFST/BRIVA`, panel `Player Bank` segmen-3;
  normalisasi digits-only strip 62/0, min 9 digit) mengalahkan skor nama → username exact → fuzzy nama.
  Tie ambigu hanya bila identitas berbeda ≥2.

### Konsumsi & window (`run_batch`)
- Window sisi uang dilebarkan `_widen_dto` (reuse `date_window_days`) di completeness + sides → T+1 kandidat masuk.
- Konsumsi saat sukses saja; **spillover**: uang luar-window yang BERPASANGAN ikut dikunci; orphan dibiarkan aktif untuk batch besok.
- `include` dipersist di `ReconBatch.include` (None = semua) — prasyarat recompute summary yang akurat.
- Tanggal string dari web/CLI dikoersi `_as_date` di semua titik masuk (bug: `str + timedelta` crash — reconcile harian dari web tak pernah jalan sebelum ini).

### Re-match (`rematch_batch`) + auto re-match
- Pool = uang AKTIF di window asli batch (hormati include); matcher dipakai ulang utuh → verdict konsisten.
- Update `MatchResult` in-place (suffix " (re-match)"), konsumsi ke batch LAMA → atribusi tanggal balik gratis
  (agregasi pair-based `_matched_money`), summary run+batch dihitung ulang (`_aggregate_batch(batch=...)`:
  baris milik batch sendiri tetap dihitung — tanpa ini gross kolaps ke 0 pasca-konsumsi).
- Atomic, idempotent, tidak mencuri baris batch lain, tidak membuat MatchResult baru.
- **Auto**: `_auto_rematch` jalan di commit upload sumber uang; kandidat = batch ber-tidak_cocok yang window-nya
  overlap rentang tanggal baris baru, urut TERTUA (maks 10); hanya yang menghasilkan dilaporkan.

### UX ritual harian
```
Sore hari D:
1. Lempar folder/zip hari D ke dropzone (drag-drop; pilihan menumpuk; zip diekstrak; junk dilewati)
2. Auto re-match menutup ekor batch D-1 (flash per batch)
3. Reconcile — tanggal sudah terisi hari D-… berikutnya; kosong = konfirmasi modal
```

## Hasil terukur (staging K25, sample 27–29 Juni)

- Overhaul TX-ID (dataset 3-hari digabung): cocok 4.009 → **6.738**, tinjau 2.798 → **55**, DP selisih 165,9jt → **1,29jt**.
- Dest-key WD: tinjau 904 → **422**, +417 cocok `bank_dest`.
- Simulasi ritme harian penuh (per-hari 27/28/29): hari 28 auto re-match menutup **238** baris batch-27
  (WD selisih 32,2jt → 4,3jt); hari 29 menutup **435** baris batch-28 (tidak 489 → 54).
- Ekor 29-malam (±705 WD) menunggu file 30-06 — perilaku benar, bukan bug.

## Gap yang diketahui (backlog di plan)

- Re-match belum meliputi PANEL_BRACKET (ekor bracket tak bisa sembuh tanpa hapus batch).
- Baris PANEL susulan in-window tidak diadopsi ke batch lama (semi-orphan; menggeser gross recompute diam-diam).
- Recompute summary jalan walau terpasang=0 (drift kecil tanpa laporan).
- Mayoritas hasil re-match masuk perlu_tinjau (weak_name, mutasi nama-doang) → butuh workflow review massal.
- Race sempit match-read → consume-UPDATE bisa meng-inflate stats (app single-auditor; diterima).
