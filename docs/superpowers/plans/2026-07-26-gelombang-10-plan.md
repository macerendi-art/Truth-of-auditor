# Gelombang 10 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Eksekusi task-per-task, TDD, commit per task.

**Goal:** 9 fitur/perbaikan permintaan end user (Vigor/TM Gaming + Rekap Bulanan + Semua Toko + IP Allowlist) → rilis v1.11.0.

**Architecture:** lihat `docs/superpowers/specs/2026-07-26-gelombang-10-design.md` (temuan + keputusan). Repo = worktree `/Users/macads/Truth-of-auditor/.claude/worktrees/loving-joliot-2aa399`, venv `/Users/macads/Truth-of-auditor/.venv`.

## Global Constraints

- Bahasa UI/komentar Indonesia. Konvensi UI: kerangka halaman `web/templates/web/biaya_admin.html`; sidebar `app_base.html:457-517`; `{# #}` satu baris saja (dijaga `web/tests_template_hygiene.py`).
- Aturan anchor SUCI: pasangan hanya pada anchor identitas UTAMA (ticket/reference/HP/rekening/username/nama); nominal+tanggal hanya PENDUKUNG.
- Larangan loop query per-toko pada jalur multi-toko (~24 toko; pelajaran 1,5 dtk di `web/views.py:1748-1749`).
- Layering: `reconciliation` tidak boleh import `web`.
- Migrasi: web 0002 (rekap) SEBELUM web 0003 (allowed_ip); sources 0011+0012. Semua additive & reversibel; JANGAN sentuh data produksi.
- Test runner: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test <modul>`; suite penuh sebelum push.
- Commit per task (git add file spesifik, JANGAN -A; jangan commit db.sqlite3/.claude/staticfiles). Push origin/main fast-forward setelah Task 12.
- Angka verifikasi kunci COR 23-07: DP username+|nominal| 8538/8549, WD 1542/1560; WD UUID 265/265; DP UUID 8338/8338; rekening 229/229.

---

### Task 1: OTH → bank asli + backfill

**Files:** Modify `sources/parsers/cor.py`, `sources/tests_cor.py`; Create `sources/management/commands/backfill_oth_bank.py`.

**Interfaces:** `resolve_oth_bank(code: str, name: str) -> str` (module-level, cor.py) — `"OTH"` + name berpola `…/ WITHDRAW BCA` (atau DEPOSIT) → `"BCA"`; selain itu kembalikan `code` apa adanya. Regex: `_OTH_EMBED_RE = re.compile(r"/\s*(?:WITHDRAW|DEPOSIT)\s+([A-Z][A-Z0-9 ]*?)\s*$", re.IGNORECASE)` (bank bisa >1 kata? data riil: BCA/BNI/BRI satu kata — grup tanpa spasi cukup: `([A-Z][A-Z0-9]+)`).

**Steps:**
1. Tes gagal dulu di `sources/tests_cor.py`: (a) WD `From Bank` = `"OTH - 4840394374 - IGNATIUS IVAN / WITHDRAW BCA"` → row `bank_title=="BCA"`, `raw["From Bank"]` tak berubah, `raw["Bank Title"]=="BCA|IGNATIUS IVAN / WITHDRAW BCA|4840394374"`; (b) varian DEPOSIT; (c) non-OTH tak tersentuh; (d) OTH tanpa bank tetap `"OTH"`; (e) `kelas_metode("wd","BCA")==kelas_metode("wd","OTH")=="Bank"` (pin, dari `web.channels`).
2. Implement di `CORPanelBankParser.parse` (dan cabang WD `cor_panel_qris` bila triplet-nya bisa OTH — cek): setelah `parse_bank_triplet(oper_raw)`, `op_code_eff = resolve_oth_bank(op_code, op_name)`; pakai utk `raw["Bank Title"]` sintetis + `derive_bank_fields`. Kolom export asli di raw byte-identik; row_hash input tak berubah.
3. Command `backfill_oth_bank` (opsi `--toko <key>`, `--dry-run`): query `Transaction.objects.filter(source_type__key="panel", bank_title="OTH")`, hitung ulang dari segmen tengah `raw["Bank Title"]`, update kolom `bank_title` saja, print `diperiksa/diubah/dilewati`. Idempoten (run ke-2 = 0 perubahan). Tes command: baris lama OTH → run 2× → 1 update; --dry-run tanpa tulis.
4. `python manage.py test sources.tests_cor sources` hijau → commit `fix(cor): bank title OTH …`.

### Task 2: BRI counterparty + fallback tampilan

**Files:** Modify `sources/parsers/banks.py`, `web/views.py` (`_resolve_wallet_names` ±:1279-1303), tes parser BRI yang ada + tes halaman mutasi bank.

**Interfaces:** `NBMB_RE = re.compile(r"NBMB (.+?) TO (.+?)(?: ESB|$)")` konstanta modul banks.py (satu sumber; view import ini).

**Steps:**
1. Tes gagal: parser BRI atas `"NBMB Cantika Irsad TO DHAVIT PEBRIYANTO"` (tanpa ESB) → counterparty terisi sesuai arah uang; bentuk lama ber-ESB tetap identik; BRIVA tetap kosong.
2. Ganti regex di banks.py:156-158 dengan `NBMB_RE` (perilaku lama: lazy group berhenti di ` ESB` pertama — pertahankan).
3. Fallback view: di `_resolve_wallet_names`, sebelum jalur phone, bila `counterparty` kosong dan `raw.get("DESK_TRAN")` match `NBMB_RE` → set atribut display yang sudah dirender template (`r.player_name`) = sender bila `money_delta>0` else receiver. Tes render `/mutasi-bank/`: baris lama counterparty kosong + DESK_TRAN tanpa-ESB → nama tampil; BRIVA → "—".
4. Suite `sources` + tes mutasi hijau → commit `fix(bri): nama lawan transaksi …`.

### Task 3: Engine pass 0c — join rekening (UNO WD)

**Files:** Modify `reconciliation/engine.py` (hanya `_MoneyMatcher.match` + helper kecil), `web/templatetags/web_extras.py` (REASON_LABELS `"account"` + `"account_amount"` bila dipakai); Create `reconciliation/tests_account_join.py` (tiru gaya `tests_reference_join.py`).

**Design keras:**
- Helper `_norm_acct_digits(s)`: buang non-digit, `lstrip("0")`, buang prefix `62`, `lstrip("0")`; hasil < 6 digit → `""` (jangan diindeks).
- Build indeks dalam loop `for b in right` yang ada: hanya `b.source_type.key=="gateway"`, kunci dari `(b.raw or {}).get("AccountNumber","")`.
- Pass 0c persis setelah pass 0b: untuk `p` belum matched, kunci `pp = _panel_phone(p)` (cache `p._phone` yang ada); kandidat `gw_acct.get(pp)` urut |delta tanggal|; guard arah uang; **hanya `diff == 0`** → `emit(COCOK, 100, "account")`. Non-exact TIDAK dipasangkan di 0c (jatuh ke pass 1/2).
- Perluas `blocked`: `panel_accts = {…}`; gateway ber-AccountNumber yang tak dikenal panel → blocked (cermin semantik ticket/ref).

**Tests:** pairing dasar; pemain sama 2 WD (500k & 750k) ke rekening sama → masing-masing ke nominal persisnya; normalisasi 0/62; pass 0b menang duluan; klausa blocked → `no_panel` bukan fuzzy; **zero-diff Nexus** (skenario tanpa AccountNumber → bucket identik). `python manage.py test reconciliation` penuh. Commit `feat(engine): pass 0c join rekening UNO`.

### Task 4: Panel↔Bracket mode username

**Files:** Modify `reconciliation/engine.py` (`PanelBracketMatcher` ±:264-313; gerbang `run_batch` ±:1039-1047), `web/templatetags/web_extras.py` (`"username_amount"`), `web/templates/web/batch_detail.html` (±:161), `reconciliation/tests_bracket_cor.py` (TULIS ULANG 2 tes pin secara sadar), tambah pin-down test parser FR COR di `sources/`.

**Design keras:**
- `sides()`: hapus `.exclude(ticket_no="")` sisi bracket.
- `match()` dua cabang: `ticket_mode = any(p.ticket_no for p in left) or not right or not left`. Cabang ticket: **statement pertama** `right = [b for b in right if b.ticket_no]` → hasil Nexus byte-identik. Cabang username: kunci `(username.strip().lower(), int(abs(money_delta atau amount)), arah)` — arah dari panel `jenis` vs tanda `money_delta` bracket; indeks bracket per kunci urut tanggal; tiap baris panel ambil kandidat unused ter-dekat dalam `tol.date_window_days` (jendela simetris); pasang → `COCOK, 100, "username_amount"`; panel sisa → `TIDAK, "no_bracket"`; bracket sisa **hanya jenis depo/wd** → `no_panel`; baris FR lain (bonus/admin/pending) → tanpa hasil.
- `summary`: set `mode` ("ticket"/"username"); putuskan `right` yang dilaporkan = jumlah baris relevan mode tsb (cek dampak `_bracket_overlap_warning` dan pin dengan tes).
- Gerbang run_batch: `panel_has_ticket` → `panel_in_scope` (queryset sama tanpa exclude ticket); `skipped` back-compat + `summary["skipped_detail"]["panel_bracket"]` berisi alasan spesifik; template batch_detail: render detail bila ada, fallback copy lama.
- Username = anchor UTAMA (konsisten aturan anchor; preseden RPay `Customer Username`).

**Tests:** end-to-end mode username (pasangan, duplikat nominal 1:1 nearest-date, no_bracket, no_panel depo/wd saja, bonus tanpa hasil); regresi Nexus campuran (ticketed + bonus tanpa ticket → hasil identik lama); run_batch COR: relasi JALAN + `summary["mode"]=="username"`; skip baru bila bracket benar-benar absen (detail "data tidak ada"); jendela H+1. Suite `reconciliation` penuh. Commit `feat(engine): Panel↔Bracket mode username utk panel tanpa ticket`.

### Task 5: Kalibrasi data riil COR

Orkestrator (bukan subagent). Zip sudah diekstrak di scratchpad (`<scratchpad>/cor2307/23/`). Jalankan:
```
DATABASE_URL=sqlite:///<scratchpad>/cal.sqlite3 python manage.py migrate
DATABASE_URL=sqlite:///<scratchpad>/cal.sqlite3 python manage.py validate_brands --dir <scratchpad>/cor2307/23 --toko g25 --flow-from-name
```
Lolos bila: panel_bracket jalan, cocok ≥ ~98% sisi kecil; panel_bank tidak turun vs baseline (jalankan baseline dulu di DB scratch kedua dari commit sebelum Task 3 bila belum tercatat); OTH → bank asli tampil. File Mandiri terkunci password → lewati (catat).

### Task 6: Kartu Ringkasan Bracket dashboard

**Files:** Modify `web/breakdown.py`, `web/views.py` (dashboard ±:256), `web/templates/web/dashboard.html` (sisip di :77); Create `web/tests_dashboard_bracket.py`.

**Interfaces:** `ringkas_bracket_hari(toko, tanggal, dengan_koreksi=True) -> dict|None` → `{"dp": {"n","v"}, "wd": {"n","v"}, "net", "total_n"}`; None bila tak ada baris bracket tanggal itu.

**Steps:** 1 query grouped (`KeyTextTransform` Kategori+Bank, `values`, `Sum(money_delta)`, `Count`), slug via `_slug_kategori` di Python (menangani `withdraw`→`withdrawal`); DP=Σ`deposit`, WD=|Σ`withdrawal`|, `pending dp` & lainnya keluar; overlay FRKoreksi kolom deposit/withdrawal (aturan skip-akun-absen `_apply_koreksi`, breakdown.py:107). View: `bracket_sum = ringkas_bracket_hari(active, last.recon_date)` guard None. Template: kartu `.bstrip` klon `.pstrip` (style scoped inline, card reveal, 3 ubin, header "Ringkasan Bracket — <tgl>", subjudul basis FR, link ke `{% url 'bracket_breakdown' %}?date=`), disembunyikan bila None. **Tes tie-out**: seed FR 2 akun + pending dp + ejaan `withdraw` + 1 FRKoreksi → hasil == `bracket_breakdown(toko,d)["total"]` deposit/withdraw; koreksi akun absen diabaikan; render dashboard; Δquery ≤ 2. Commit `feat(dashboard): kartu Ringkasan Bracket`.

### Task 7: Toko.panel

**Files:** Modify `sources/models.py`, `web/admin_views.py` (`kelola_toko`), `web/templates/web/kelola/toko.html`, `web/context_processors.py`, `web/templates/web/app_base.html` (kedua picker); Create `sources/migrations/0011_toko_panel.py` + `0012_seed_toko_panel.py`; extend `sources/tests_toko.py` + tes picker web.

**Interfaces:** `Toko.PANEL_NEXUS/PANEL_VIGOR/PANEL_TMG = "nexus"/"vigor"/"tm_gaming"`; `panel = CharField(max_length=20, choices=PANEL_CHOICES, default=PANEL_NEXUS)`; context `tokos_grouped: list[(label, [toko])]` (dibangun dari list `tokos` yang sudah difetch — 0 query ekstra; hanya grup non-kosong).

**Steps:** migrasi field + data (by key: slo→vigor; w25,g25→tm_gaming; else nexus; reverse → nexus semua); `kelola_toko` create wajib `panel` valid (`dict(Toko.PANEL_CHOICES)`) + action `"panel"` per baris + `catat("ubah_panel_toko", …)`; kolom badge di toko.html; kedua `<select name="toko_id">` pakai `<optgroup>` bila >1 grup, else flat. Tes: hasil migrasi data per key; create+validasi+audit; render optgroup; flat bila 1 grup. JANGAN sentuh engine/matcher. Commit `feat(toko): kategori panel Nexus/Vigor/TM Gaming`.

### Task 8: Rekap Bulanan — model + modul

**Files:** Modify `web/models.py`; Create `web/migrations/0002_rekap_bulanan.py`, `web/rekap.py`, `web/tests_rekap.py`.

**Interfaces (kontrak utk Task 9):**
- `RekapManual(toko FK CASCADE related_name="rekap_manual", periode DateField [tgl 1], field CharField(64) TANPA choices, nilai Decimal(18,2), catatan Text blank, dibuat_oleh FK SET_NULL)` + UniqueConstraint (toko,periode,field) `uniq_rekap_manual`. `RekapPenyebab(toko, periode, label CharField(100), nilai Decimal(18,2), urutan PositiveSmallInt default 0)` ordering (urutan,id).
- `web/rekap.py`: `FIELDS` registry (slug, label, seksi 1-4, kind manual/auto/carry/computed, arah tanda) meniru Excel end user: s1 `wl, akuran, bonus_harian, bonus_mingguan, lucky_draw, pulsa, admin, admin_qris, total_cost, other_income, mistake → net_profit`; s2 `wallet_balance_lalu, dp, wd, bonus, lucky_draw_2, wl_ref → sisa_dana_member`; s3 `titip_saldo_awal, dana_lebih_lalu_ref, dana_tampung_pusat, net_profit_ref, akuran_ref, oasis, bank_dp, qris, bank_lain, bank_wd, tampung_web, bank_beku, mistake_belum_cost, total_wallet_live, hutang_web, piutang_web, akuran_lalu, pdp_bulan_ini, pdp_klaim, claim_pdp_lalu, expired_dana_pending → total_dana_lebih`; s4 `dana_lebih_lalu, selisih, penyebab_total, different, dana_lebih_fnc, selisih_fnc`.
- `rekap_bulanan(toko, year, month, _carry=True) -> {"periode", "sections":[{"no","judul","rows":[{"slug","label","kind","nilai","sumber","auto","manual"}]}], "penyebab":[…], "totals":{…}}`.

**Sumber auto (1 query per sumber, rentang bulan penuh):** bonus per kategori dari `rekonsiliasi_bonus(toko,dari,sampai)["ringkas"]["kategori"]` (klasifikasi nama kategori keyword harian/mingguan/lucky; nilai = sisi panel cocok+panel_only); kategori FR grouped sekali (`beban admin bank`; `beban admin qris`+`beban other expense`; `pending dp`); DP/WD & FNC dari Sum Transaction panel langsung (`jenis in (depo,wd)`, `is_duplicate=False`, `posted_date` dalam bulan — BUKAN summary batch, alasan didokumenkan); hutang/piutang dari `hutang_piutang` totals. Carry: rekursif depth-1 (`wallet_balance_lalu` ← `sisa_dana_member` bulan lalu; `dana_lebih_lalu` ← `total_dana_lebih` bulan lalu; `akuran_lalu` ← manual `akuran` bulan lalu; depth 0 dalam rekursi = manual rows saja). Manual menimpa auto; `sumber` mencatat pemenang. Rumus semua di modul.

**Tests:** tie-out per baris auto vs modul asal; override manual + provenance; carry depth-1; bulan kosong aman; unique constraint. Commit `feat(rekap): model + modul rekap bulanan`.

### Task 9: Rekap Bulanan — halaman

**Files:** Modify `web/views.py`, `web/urls.py`, `web/templates/web/app_base.html` (menu Laporan setelah "Ringkasan Bulanan"); Create `web/templates/web/rekap_bulanan.html`, `web/templates/web/_rekap_edit_form.html`, `web/tests_rekap_page.py`.

**Steps:** view `rekap_bulanan_page` (`_active_toko` guard, `?month=YYYY-MM` ala monthly), 4 kartu seksi kerangka `biaya_admin.html` (tabel `selectable`, baris computed tebal); edit manual = popup HTMX klon `fr_koreksi_form/simpan` (COPY ladder validasi desimal views.py:1562-1577; validasi `field` terhadap slug manual/carry `FIELDS`; `update_or_create`; `catat("rekap_manual", …)`; re-render seksi via oob); penyebab: POST add/delete + `<datalist>` saran (Auto Pulsa, Delete transaksi deposit, Mistake credit, Salah tujuan bank) + `catat`; badge provenance auto/manual/computed (title oleh/waktu/nilai asli). URL names: `rekap_bulanan`, `rekap_edit_form`, `rekap_edit_simpan`, `rekap_penyebab_simpan`. Tes: render 4 seksi, edit persist+audit+override, slug/nilai invalid 400, penyebab CRUD, scoping toko. Commit `feat(rekap): halaman /rekap-bulanan/`.

### Task 10: IP Allowlist

**Files:** Modify `web/models.py`, `web/middleware.py`, `truth_auditor/settings.py`, `web/access.py`, `web/admin_views.py`, `web/urls.py`, `web/templates/web/app_base.html` (menu Admin "Akses IP"); Create `web/migrations/0003_allowed_ip.py`, `web/templates/web/kelola/ip.html`, `web/templates/web/ip_block.html`, `web/tests_ip_allowlist.py`.

**Design keras:** `AllowedIP(label CharField(100), cidr CharField(64), aktif Bool default True, dibuat_oleh FK SET_NULL)`. `is_ip_gated(user)` di access.py = authenticated ∧ ¬is_admin ∧ role∈(auditor,supervisor). Middleware urutan cek: ¬gated→pass; prefix static/media & path logout→pass; entries aktif kosong→pass (dorman); `peer=_client_ip`; `_ip_is_internal(peer)`→pass; `via_cf=_via_cloudflare(peer)`; `ip=_real_client_ip(request,via_cf)`; `_ip_in_allowlist(ip,entries)`→pass; else 403 `ip_block.html` (klon shell geo_block: mandiri, tampilkan IP, ajakan hubungi admin, link logout) + `catat(user,"ip_blokir",ip)` sekali per sesi (flag session `ip_block_logged`). Posisi MIDDLEWARE: setelah `ForcePasswordChangeMiddleware` (Auth→GeoBlock→ForcePassword→IPAllowlist) — pin dengan tes. `/kelola/ip/`: list+create+toggle+delete, pola manual-POST `kelola_toko`, validasi `ipaddress.ip_network(v,strict=False)`, audit.

**Tests (tiru tests_geoblock):** dorman; matriks peran (admin/superuser bebas; auditor & supervisor terblokir dari IP asing, lolos via IP persis & via CIDR; entri nonaktif diabaikan); XFF paling-kiri; header Envoy/CF spoof dari peer non-CF diabaikan; peer CF + CF-Connecting-IP dipakai; internal/loopback lolos; logout bisa diakses saat terblokir; 403 memuat IP; audit sekali; anonymous tak tersentuh; interplay must_change_password (redirect ganti-password tetap kena gerbang IP — pin). Commit `feat(akses): allowlist IP auditor/supervisor`.

### Task 11: Semua Toko + ceklis hutang

**Files:** Modify `web/views.py` (`_active_toko`, `set_toko`, dashboard, `hutang_piutang`, helper `_toko_scope`), `web/context_processors.py`, `web/templates/web/app_base.html`, `web/templates/web/hutang_piutang.html`, `web/hutang.py`; Create `web/templates/web/dashboard_all.html`, `web/tests_semua_toko.py`.

**Commit 1 (guard):** `_active_toko`: `tid=="all"` → `return allowed.first()`; `set_toko`: terima `"all"` hanya `is_admin` → session `"all"`, non-admin diabaikan. Tes: sesi "all" tak crash di halaman mana pun (smoke-loop SEMUA route single-toko sebagai admin, assert 200/302 wajar).

**Commit 2 (context+picker+bar):** context processor: `semua = active_id=="all" and is_admin(user)`; `active_toko` TETAP toko fallback; `semua_toko` flag; `pending_review_count` `toko__in` saat semua (1 query); kedua picker prepend `<option value="all">Semua Toko</option>` hanya `is_admin_user`, selected via flag. Bar notifikasi di app_base bila `semua_toko` ∧ ¬`semua_toko_page`: "Mode Semua Toko aktif — halaman ini menampilkan <b>{{ active_toko.name }}</b>."

**Commit 3 (dashboard all):** cabang awal `if semua:` render `dashboard_all.html` (context `semua_toko_page=True`): fetch semua ReconBatch ber-recon_date sekali (values) → pilih terakhir per toko di Python; strip Panel+Metode = 1 agregat `consumed_by_batch_id__in=last_ids` (+`breakdown_metode` queryset sama); strip Bracket = 1 query `toko__in`+`posted_date__in` grouped (toko,tanggal,Kategori) lalu saring pasangan (toko,tgl-akhirnya) di Python; kalender status terburuk per hari; tabel per-toko (nama, tgl batch, DP, WD, selisih, tinjau [1 agregat], tombol POST set_toko per baris); tren/Kerjakan-hari-ini/Uang-periksa v1 disembunyikan + hint. Tes: jumlah == Σ panel_sum per toko; `assertNumQueries` konstanta tetap.

**Commit 4 (hutang):** `hutang_piutang(toko_atau_list, …)` terima list (`toko__in`; jalur tunggal byte-identik; baris multi-mode bawa nama toko); view mode semua: `GET.getlist("toko")` default semua; template: baris ceklis toko auto-submit (khusus mode semua) + kolom Toko. Tes: default semua, subset, kolom, non-admin tanpa ceklis, single-toko identik.

Commit msg: `feat(admin): mode Semua Toko + ceklis hutang`.

### Task 12: Rilis v1.11.0

Prepend `Rilis("1.11.0", <tanggal ship>, "<nama>", MINOR, sorotan=(≥3 bahasa bisnis: dukungan penuh Vigor/TM Gaming [Panel↔Bracket username, kartu Ringkasan Bracket, join rekening UNO, OTH, nama BRI], Rekap Bulanan, Mode Semua Toko + gembok IP))` + `python manage.py changelog` + commit keduanya. Suite penuh. Update CLAUDE.md seperlunya (fitur baru; koreksi baris Envoy geo-block yang basi). Push origin/main (fetch+rebase dulu). Laporan akhir + template BRI + angka kalibrasi + tanya deploy.
