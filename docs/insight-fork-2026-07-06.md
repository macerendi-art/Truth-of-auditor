# Insight dari fork Sabianhk — untuk direview agen/tim (2026-07-06, REVISI 2026-07-14)

Dokumen ini ditulis untuk DIBACA OLEH AGEN (Claude Code / LLM) yang bekerja di repo ini,
sebagai bahan rencana revisi. Semua klaim di bawah adalah temuan yang kami yakini penuh,
teruji di data staging nyata (toko OKE25, 27–29 Juni 2026, ±16k baris panel/hari, Postgres
Railway). Estetika/selera TIDAK dinilai di sini.

> **REVISI 2026-07-14** — main kalian maju pesat (matcher v2 multi-pass + anchor utama +
> NAME_REVIEW_FLOOR + carry-over/retro + parser RPay/QHoki/COR + perf). Tiap klaim kini
> diberi **Status** supaya dokumen tidak menyesatkan: mana yang SUDAH kalian jawab (dan
> versi fork-nya kami DROP), mana yang di-PORT ulang di branch `fix/matcher-quality`
> (dibangun ulang di atas main baru), mana yang masih terbuka.

## Protokol konsumsi (untuk agen pembaca)

1. JANGAN adopsi buta. Tiap klaim menyertakan **cara falsifikasi** — jalankan dulu di
   codebase kalian; adopsi hanya bila terbukti.
2. Klaim bertanda `[PR#6]` tersedia sebagai kode + tes di PR #6
   (`Sabianhk:fix/matcher-quality`, kini DI-REBASE ke atas main baru kalian; fitur yang
   sudah kalian jawab sendiri DIBUANG dari branch itu — lihat Status per klaim).
3. Klaim bertanda `[PR#4]` tersedia di PR #4 untuk diadaptasi selektif (pola PR #5).
4. Konteks pembanding AWAL: engine kalian yang kami baca saat dokumen ini pertama ditulis
   = commit d0730c8. Status revisi merujuk main kalian per 2026-07-14 (f2016bf).

---

## K1 — BUG: gateway UNPAID bisa jadi COCOK (prioritas tertinggi)

**Status 2026-07-14: MASIH VALID di main baru → DIPERBAIKI di branch ini.** Pass 0/0b
kalian join ticket/reference gateway tanpa membaca status; parser QRFlyer/NXPay tetap
menelan semua baris. Branch ini menambah gate settle: baris ber-status
UNPAID/FAILED/EXPIRED/… keluar dari semua pool; tiket dikenal tapi tak settle → terminal
`gateway_unpaid` (BUKAN no_money — uang belum masuk itu FAKTA, jangan carried menunggu
settlement); gross & kategori uang tanpa pasangan (kategori baru `e`) ikut dikoreksi.
Fail-open untuk status kosong/tak dikenal (QHoki/RPay/COR sudah menyaring saat parse).

**Klaim.** `_MoneyMatcher.match` pass-0 join tiket gateway TANPA membaca
`Payment Status`. Parser gateway (`sources/parsers/gateways.py`) menelan SEMUA baris —
status hanya disimpan di `description`/`raw`. Akibat: QR UNPAID/FAILED ber-tiket sah
dipasangkan COCOK → uang yang tak pernah masuk dihitung masuk → selisih riil TERSEMBUNYI.
Ini kebalikan tujuan audit: false-negative pada sinyal terpenting.

**Bukti.** Di data OKE25 baris UNPAID nyata ada (export QR FLYER kolom `Payment Status`
berisi nilai non-PAID). Di fork, sebelum gate settle dipasang, baris ini menyeberang ke
fuzzy bank dan mencemari hasil.

**Falsifikasi.** Ingest file `MUTASI DP QR FLYER` mentah → cari baris `Payment Status`
!= PAID/Success yang tiketnya ada di panel → jalankan run → cek bucket-nya. Kalau COCOK,
klaim terbukti. (Tes reproduksi: `reconciliation/tests_gateway_gate.py`.)

**Risiko sisa (catat):** `row_hash` QRFlyer tidak memuat status — baris yang kemarin
UNPAID lalu muncul lagi SETTLED di export berikutnya akan terskip dedup (raw tetap
UNPAID). `gateway_unpaid` terminal memaksa auditor mengeceknya manual, jadi tak senyap,
tapi flip otomatis belum ada.

## K2 — Floor bukti identitas (skor < 55 = bukan pasangan) `[PR#6]`

**Status 2026-07-14: SUDAH DIJAWAB main baru → versi fork DI-DROP.** Kalian memasang
`NAME_REVIEW_FLOOR = 60` (engine.py): pita [60..threshold) → `perlu_tinjau name_partial`
dengan assignment global anti-curi, di bawah floor → `no_money` + detail "menunggu
settlement" (`NO_MONEY_WAIT_DETAIL`). Pass 3 kalian tak lagi greedy. Semantik setara
`_WEAK_FLOOR` fork (nilai 60 vs 55 = kalibrasi `validate_brands` kalian — lebih baik,
berbasis data). Tak ada yang perlu di-port.

**Klaim (historis).** `token_set_ratio` memberi ~40 untuk nama beda total. Pass-3 lama
(weak_name greedy) mengunci uang ke pasangan tanpa bukti; di arsitektur carry-over
efeknya lebih buruk: uang terkunci pasangan sampah tak bisa dipakai flip
`late_settlement` pemilik sejatinya.

## K3 — `dest_account` persisted > regex on-the-fly `[PR#6]`

**Status 2026-07-14: SUDAH DIJAWAB main baru dengan pendekatan lain → skema persisted
DI-DROP.** `_panel_phone`/`_money_phones` + `_BRIVA_RE` kalian adalah SUPERSET recall
dari ekstraksi presisi fork (BCA `- - <hp>`, BRI BFST/BRIVA, Mandiri ekor Keterangan,
Panel segmen-3), plus penanganan kode kanal BRIVA yang fork tak punya. Memaksakan field
persisted sekarang tidak menambah nilai; alias historis (K4) membaca nomor dari raw
historis via `_phones_from`. Catatan kecil yang MASIH berlaku: nomor transien tak bisa
di-index/di-audit dari UI (auditor tak melihat kunci yang dipakai) — kandidat perbaikan
terpisah bila kebutuhan audit muncul, bukan prasyarat matcher.

**Falsifikasi (tetap relevan).** Cari mutasi yang `_money_phones`-nya menghasilkan >1
nomor; cek berapa yang bukan nomor tujuan (referensi/VA internal).

## K4 — Alias historis: matcher yang belajar `[PR#6]`

**Status 2026-07-14: TAK ADA PADANAN di main baru → DI-PORT ulang di branch ini
(adaptasi).** Bukti = MatchResult COCOK ber-reason `amount+date+name` / `amount_fee` /
`alias_history` / `late_settlement` / `manual_override` (keputusan reviewer ikut
mengajar — tandai sekali, besok otomatis). Kandidat pass 1 yang cocok peta → skor min
95, reason `alias_history`; identitas persis 100 tetap `amount+date+name`. Self-healing:
tanpa tabel baru, hapus batch = alias hilang.

**Klaim.** Pemain memakai rekening pinjaman BERULANG. Peta
`username → {nama rekening, nomor} yang pernah COCOK` menaikkan match berulang ke
skor 95 tanpa melonggarkan fuzzy untuk pasangan tanpa sejarah.

**Bukti.** Staging fork: hari-1 = 110 match alias, hari-2 = 182; kontribusi ±28jt
penyusutan selisih WD per hari.

## K5 — DP Pulsa harus keluar dari jalur fuzzy `[PR#6]`

**Status 2026-07-14: TAK ADA PADANAN di main baru → DI-PORT di branch ini.** Di
arsitektur carry-over kalian dampaknya persis seperti diklaim: DP pulsa jadi carried
"menunggu settlement" SELAMANYA (mencemari `pending_settlement_count`) atau dipasangkan
fuzzy ke uang orang lain. Pass 0a → `perlu_tinjau pulsa_manual`, terminal, tanpa
mengambil uang siapa pun; deteksi via field `bank_title` kalian (fallback raw).

**Klaim.** Deposit pulsa (raw `Bank Title` = `TELKOMSEL/AXIS/XL (AUTO)`, `Player Bank`
kosong, fee 20–24%) uangnya TIDAK PERNAH lewat bank/gateway. Volume nyata: 13 baris/hari
di OKE25.

## K6 — Baris "Biaya …" Mandiri harus `jenis="admin"`

**Status 2026-07-18: SUDAH DIJAWAB main** — paket C (`sources/parsers/fee_rules.py`,
`is_admin_fee("mandiri", ...)` = startswith("BIAYA"), commit 407a2eb + tes
MandiriParser-level a7f60d3, 18 Jul) memakai rule yang persis sama dengan port fork,
plus kalibrasi 8.937 baris legacy — cakupannya lebih luas (BRI ATMSTRPRM/BFST/BRIVA
ikut). Commit fork `is_mandiri_fee` DI-DROP dari PR #6 saat rebase: redundan total.

**Falsifikasi.** `grep` hasil ingest e-statement Mandiri: baris Keterangan berawalan
"Biaya" ber-jenis apa.

## K7 — Window Default 1 hari BUTA WEEKEND (berlaku juga di carry-over kalian)

**Status 2026-07-14: MASIH TERBUKA di main baru** (seed `Default.date_window_days=1`,
`reconciliation/migrations/0002_seed_tolerance.py`). SENGAJA tidak diubah di branch ini —
menaikkan window mengubah kalibrasi seluruh matcher & carry; keputusan tim + data
`validate_brands`, bukan port mekanis.

**Klaim.** WD Sabtu settle Senin (delta 2 hari). Di engine kalian `kandidat(hi=window)`
menolak delta 2 → baris carried Sabtu TIDAK PERNAH flip walau uangnya sudah tiba Senin —
pending permanen (lalu expire senyap ke batch asal). Fork menaikkan Default → 2 via data
migration; angka membaik tanpa efek samping (496 tes fork hijau).

**Falsifikasi.** Ambil WD Sabtu apa pun yang uangnya tampak di mutasi Senin; telusuri
kenapa carried-nya tak pernah flip.

**Catatan UI terkait:** label dropdown toleransi `(±N hari)` menyesatkan dua kali:
window-nya SEARAH (uang telat, bukan maju-mundur), dan begitu Default=2 dia kembar dengan
Longgar (pembeda asli Longgar = toleransi nominal 10rb + fuzzy 75, tak pernah tampil).

## K8 — Skala: rekonsiliasi sinkron di request akan timeout

**Status 2026-07-14: SEBAGIAN DIJAWAB.** Main baru menambah gunicorn 2 worker × 4 thread
(435392d) + serangkaian perf fix query (320a36a, fad4435, b008974) — tapi
`run_batches_auto` tetap sinkron di request web. Klaim tetap relevan untuk re-run
multi-hari dataset ±16k baris/hari; pola fork: >20k baris aktif → placeholder batch +
thread background + status polling + `select_for_update` per-Toko. `[PR#4]`

## K9 — Hardening yang kalian tunda + 2 gotcha Railway yang PASTI menggigit `[PR#4]`

**Status 2026-07-14: CDN SUDAH DIJAWAB** — vendor JS + font kini self-host (2d74116),
poin supply-chain/CDN kami tidak berlaku lagi. **Masih terbuka:** django-axes, `/healthz`
+ healthcheckPath, CSP ketat, CI GitHub Actions (belum ada `.github/workflows/` di main
per revisi ini). Gotcha Railway tetap:
- **django-axes**: `REMOTE_ADDR` = IP LB internal `100.64.x` yang BERBEDA TIAP REQUEST →
  lockout tak pernah akumulasi; wajib `AXES_CLIENT_IP_CALLABLE` yang ambil hop terakhir
  `X-Forwarded-For`.
- **/healthz + healthcheckPath**: healthcheck Railway memakai Host
  `healthcheck.railway.app` TANPA X-Forwarded-Proto → wajib masuk `ALLOWED_HOSTS` +
  exempt dari SSL-redirect, kalau tidak SEMUA deploy gagal.

## K10 — Upload 2-fase kalian BUTUH volume di Railway

**Status 2026-07-14: MASIH BERLAKU** (file parkir di `media/staging/` antara analyze dan
commit). Filesystem Railway EPHEMERAL: tanpa volume ter-mount di `/app/media`, file
staging lenyap saat restart/redeploy antara dua request → `[Errno 2] No such file`. Fork
sudah kena persis ini; solusi: volume single-attach (`numReplicas=1`) + sweeper file
staging yatim >24 jam.

## K11 — Minor UX yang objektif

**Status 2026-07-14: SUDAH DIJAWAB sebagian besar.** `REASON_LABELS` di
`web/templatetags/web_extras.py` kalian sudah ada (dan branch ini menambahkan label
reason barunya: `alias_history`, `pulsa_manual`, `gateway_unpaid`, kategori uang `e`).
Detail `name_partial` kalian sudah memuat skor + kanal wallet. Fragmen htmx tabel hasil:
tetap saran `[PR#4]` bila halaman run terasa berat.

---

## Yang TIDAK kami klaim (kejujuran = kredibilitas dokumen ini)

- **Carry-over vs re-match**: dua jawaban valid untuk soal yang sama; kalian sudah
  memutuskan carry-over sebagai kanon — PR #6 (rebase) dibuat menghormati itu.
- **Auto-split per tanggal-panel + verifikasi jangkar**: milik kalian LEBIH BAIK daripada
  saran-tanggal fork (menghapus satu kelas human-error). Kami berencana meniru.
- **Assignment global urut skor (pass-1) + NAME_REVIEW_FLOOR + NO_MONEY_WAIT_DETAIL**:
  jawaban kalian untuk K2 lebih menyeluruh daripada greedy+floor fork — kami adopsi,
  versi fork dibuang.
- **`_panel_phone`/`_money_phones` + `_BRIVA_RE`**: jawaban kalian untuk K3 — recall
  lebih tinggi dari ekstraksi presisi fork; kami adopsi (lihat catatan audit di K3).
- **`amount_fee` near-miss, `_route_ok` pemilik-file, klasifikasi uang yatim a/b/c/d,
  kunci kanal gateway, halaman Antrean Tinjau**: ide bagus milik kalian; tak ada padanan
  fork.
- **Estetika** (biru kokpit vs paper ledger): selera, di luar scope.

## Ringkasan bukti staging fork (sesudah semua item di atas terpasang)

Hari-27 file lengkap: 15.379 cocok / 97 tinjau / 392 tidak-cocok = 96,9% otomatis;
bracket via tiket 7.914/7.919; DP via kunci gateway 97–98%; no_money residual turun
397→197; tinjau 552→74. Suite fork: 496 tes hijau. (Angka era arsitektur lama fork —
indikatif arah, bukan benchmark arsitektur carry-over kalian.)
