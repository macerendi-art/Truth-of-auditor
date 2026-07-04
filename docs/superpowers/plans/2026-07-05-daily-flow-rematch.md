# Flow Harian Tanpa Mikir — Implementation & Build Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auditor menjalankan rekonsiliasi harian tanpa mikir: lempar folder/zip → sistem memasangkan mutasi susulan ke batch lama otomatis → reconcile dengan tanggal yang sudah disarankan. Ekor malam T+1 dan statement bulanan sembuh tanpa hapus batch.

**Architecture:** lihat `docs/superpowers/specs/2026-07-05-daily-flow-rematch-design.md` (keputusan produk + waterfall + re-match) dan `specs/rematch-batch.md` (semantik re-match).

**Tech Stack:** Django 5.2, function views + manual `request.POST`, template extend `web/app_base.html`, `django.test.TestCase`, TDD ketat (red → green per task).

## Global Constraints

- Python: `.venv/bin/python`; suite penuh hijau di akhir tiap task (`python manage.py test`, baseline sekarang **368 OK**).
- Copy UI & komentar bahasa Indonesia. Commit conventional ber-scope, diakhiri `Co-Authored-By`.
- Uang di `Transaction` sudah rupiah (Panel ×1000 di parser) — jangan skala ulang. `USE_TZ=False`.
- Titik masuk engine WAJIB koersi tanggal string (`_as_date`) — web POST mengirim `"YYYY-MM-DD"`.
- Matching tak boleh lintas-toko; setiap lookup view difilter `tokos_for(request.user)`.

---

## Fase A — SELESAI (commit di `fix/t1-settlement-matching`, PR #2)

- [x] A1. Window T+1: `_widen_dto` di completeness + `sides`, konsumsi spillover, tie ambigu → tinjau (`8a728af` dst; 5 test `T1SettlementTests`)
- [x] A2. Tie ambigu hanya antar identitas BEDA — deposit berulang user sama pair greedy (`8a728af`)
- [x] A3. Waterfall QR TX-ID: Pass 1 kunci eksak gateway SETTLED-only + outcome terminal; Pass 2 bank fuzzy residual (`e439ed7`; 11 test `GatewayTicketMatchTests`)
- [x] A4. `dest_account`: migration transactions 0004, `normalize_dest`, ekstraksi BCA/BRI/panel, dest-key menang di Pass 2 (`dc0ed04`; 23+6 test)
- [x] A5. UI: tabel run ringkas 6 kolom (`cb2b440`), filter channel bertingkat + `KeyTextTransform` (`efd941c`), bulk delete upload (`8910b12`), modal konfirmasi reusable ganti `confirm()` native (`66d5420`, `d60a640`)
- [x] A6. `rematch_batch`: pool aktif window asli, update in-place, konsumsi ke batch lama, `ReconBatch.include` (migration recon 0004), `_aggregate_batch(batch=)` (`b6e12ad`+`b856132`; 15 test)
- [x] A7. Auto re-match pasca-upload + saran tanggal + konfirmasi tanggal-kosong (`8e155a7`; 11 test)
- [x] A8. Bug: koersi tanggal string di engine — reconcile harian dari web crash `str + timedelta` (`573bafb`; 2 test)
- [x] A9. Upload zip (ekstrak server-side + guard bom) & folder (webkitdirectory), junk filter semua jalur (`61a950b`; 7 test)
- [x] A10. Drag-drop file/folder + pilihan menumpuk (DataTransfer store) + tombol bersihkan (`3118037`)
- [x] A11. Verifikasi: simulasi ritme harian penuh di staging (view asli via test Client) — angka di design spec

## Fase B — Backlog build plan (urutan saran; belum dikerjakan)

### Task B1: Re-match untuk PANEL_BRACKET

Ekor bracket sekarang permanen (file FR bisa geser hari; simulasi: 7.929 `no_bracket` di batch-27).

**Files:** `reconciliation/engine.py` (rematch_batch: iterasi runs PANEL_BRACKET, pool bracket aktif via `PanelBracketMatcher.sides`), `reconciliation/tests_rematch.py`, `web/views.py` (`_rematch_candidates`: sumber bracket juga memicu kandidat).

**Steps:**
- [ ] Test: batch dengan ekor `no_bracket` + file bracket susulan → re-match memasangkan by ticket, konsumsi bracket ke batch lama, summary terkoreksi; idempotent; tak mencuri bracket batch lain.
- [ ] Implement: generalisasi rematch per-relasi (map relation → matcher + pool); auto re-match memicu juga saat upload bracket.
- [ ] Full suite hijau; commit `feat(recon): re-match relasi panel_bracket`.

### Task B2: Adopsi baris PANEL susulan ke batch lama

Baris panel in-window yang datang belakangan jadi semi-orphan (menggeser gross recompute tanpa jejak di daftar hasil).

**Steps:**
- [ ] Test: panel baru dated in-window batch lama → re-match membuat MatchResult baru (bucket sesuai matcher; `no_money` bila tak ada uang), panel dikonsumsi ke batch, summary konsisten.
- [ ] Implement di `rematch_batch` (fase adopsi sebelum matching); laporkan di stats (`diadopsi`).
- [ ] Guard: hanya sumber yang di-include; jangan adopsi baris milik batch lain.

### Task B3: Workflow review massal untuk perlu_tinjau — SELESAI sebagian

- [x] Checkbox per baris (nempel sel Aksi, bukan kolom baru — index kolom test aman) + master "pilih semua" + bar aksi massal `review_bulk` (POST, RBAC `tokos_for`, `manual_override`, `ReviewAction` per baris, modal konfirmasi {n}). GOTCHA: modal pakai `form.submit()` yang membuang name/value tombol → `action` via hidden input diisi saat klik.
- [ ] Saran heuristik: kelompokkan tinjau by (identitas, pola nominal) — "setujui semua pasangan nama X (n baris)".

### Task B4: Label ekor vs selisih beneran — SELESAI sebagian

- [x] Derivasi `_pending_t1` (no_money + occurred_at == date_to window + jam ≥ 17): badge "⏳ menunggu mutasi H+1" per baris di run_detail + banner hitungan di batch_detail. UI-derived, TANPA perubahan skema summary.
- [ ] Dashboard: pisahkan "money at risk" dari "menunggu settlement".

### Task B5: Background job untuk run besar

Engine O(N×M) sinkron di request (audit perf 2026-07-03) — 100k+ baris akan timeout gunicorn.

**Steps:**
- [ ] Ekstrak eksekusi `run_batch`/`rematch_batch` ke job (opsi ringan: `threading` + status di ReconBatch; opsi penuh: RQ/Celery + Redis di Railway).
- [ ] UI polling status batch (HTMX) + guard tombol ganda.

### Task B6: Rapikan sisa kecil

- [ ] `bank_dest` + reason baru (`gateway_*`) lengkap di `reason_label` map.
- [ ] Ekstraksi `dest_account` untuk Mandiri (±18 baris/hari).
- [ ] Stats re-match: laporkan juga flip `ambiguous_multi` (sekarang silent) + jangan recompute bila nol perubahan (hindari drift diam-diam).
- [ ] Upload duplikat penuh (0 baris baru): tampilkan bedge "duplikat" di riwayat upload.

## Verification (tiap fase B)

```bash
.venv/bin/python manage.py test          # full suite hijau
# smoke staging: railway up dari cwd → poll deployment SUCCESS → cek flow di UI
```
