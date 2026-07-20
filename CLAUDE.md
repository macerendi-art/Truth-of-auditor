# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Truth of Auditor** — a Django 5.2 app that reconciles a betting/credit operator's records across four kinds of sources: the **Panel** (site's own DP/WD history), the **Bracket** (agent ledger), **Banks**, and payment **Gateways**. It ingests exported files (xlsx/csv/pdf, some encrypted), normalizes every row into one canonical `Transaction`, then matches credit-side records against money-side records to surface discrepancies. UI and code comments are in Indonesian; keep that convention.

## Commands

The virtualenv is at `.venv`. Activate it first: `source .venv/bin/activate`.

```bash
python manage.py test                         # run all tests (~850)
python manage.py test web.tests_reconcile     # one module
python manage.py test web.tests_reconcile.SomeTestCase.test_x   # one test
python manage.py runserver                     # dev server (sqlite, DEBUG=True)
python manage.py migrate                        # apply migrations (includes seed data)

# CLI equivalents of the core pipeline (useful for debugging without the UI):
python manage.py ingest <parser_key> <file_path> [--flow dp|wd] [--password ...]
python manage.py match <panel_bracket|panel_bank|bracket_bank> [--from YYYY-MM-DD] [--to YYYY-MM-DD]

# Fase-0 harness: ingest a folder of real exports + auto daily batches + match-rate report.
# Use this to calibrate matcher changes against real data BEFORE shipping.
python manage.py validate_brands --dir <folder> --toko <mul|g25|mxw|...> --flow-from-name
```

Reference data (SourceTypes, the "Default" ToleranceProfile, seeded Tokos) is created by **data migrations**, not fixtures — a fresh `migrate` gives you a working DB. Tests rely on these seeds existing.

To run anything against a throwaway DB (calibration, repros) without touching the dev DB, point `DATABASE_URL` at a scratch sqlite file: `DATABASE_URL=sqlite:////tmp/scratch.sqlite3 python manage.py migrate && ... validate_brands ...`.

## Architecture: the ingest → match pipeline

Everything flows through two stages. Understanding these two modules explains most of the codebase.

### 1. Ingest (`sources/`) — heterogeneous files → canonical `Transaction`

- **`sources/detect.py`** `detect_source(path, filename)` sniffs header tokens / extension and returns ranked `{parser_key, confidence}`. The web upload flow auto-detects, and only asks the user to confirm when confidence < 0.8.
- **`sources/services.py`** `ingest(parser_key, file_path, ...)` is the single entry point: picks the parser from the `PARSERS` dict, decrypts first if the file is an encrypted xlsx (OLE2 magic bytes → `msoffcrypto`, Mandiri e-statements), runs it, and bulk-creates `Transaction` rows inside one atomic block.
- **`sources/parsers/`** one class per format (`panel`, `bracket`, `banks.py` → BRI/BCA-CSV/Mandiri, `bca_pdf`, `gateways.py` → NXPay/QRFlyer/RPay/QHoki, `cor.py` → COR/Gacor25 panel-bank/QRIS/QRIS-WD). Each subclasses `BaseParser` and returns a list of dicts whose keys **exactly match `Transaction` fields**. Shared parsing helpers (decimal/date parsing for both `intl` and `id` number formats, ticket/ref regexes, `clean_name`, `row_hash`, the styles-tolerant `read_xlsx_rows`) live in **`sources/parsers/base.py`**.
- **Idempotency:** every row gets a `row_hash` (stable hash of key fields). `ingest` skips hashes that already exist for that `(source_type, toko)`, so re-importing the same file is safe. Skipped rows are additionally **linked** to the new upload via `Upload.duplicate_transactions` (M2M) — bank exports are often rolling/overlapping, and this link is what lets the Mutasi Bank per-file filter reconstruct the file's full content (uploads from before the field exist without links and fall back to attributed-rows-only).

To add a new source format: write a parser subclass, register it in `PARSERS` (`services.py`), and add a detection signature in `detect.py`.

### 2. Match (`reconciliation/engine.py`) — the reconciliation logic

- **Matchers are pluggable** via the `MATCHERS` dict keyed by `MatchRun.Relation`. `PanelBracketMatcher` joins on **Ticket Number** (strong key). `_MoneyMatcher` (→ `PanelBankMatcher`, `BracketBankMatcher`) is multi-pass.
- **The anchor rule (core domain decision, do not regress):** a pair may only form on a PRIMARY anchor — exact ticket (pass 0), exact gateway `reference` e.g. QRIS UUID (pass 0b), phone/VA/account-number match or exact username or fuzzy name ≥ `fuzzy_threshold` 85 (pass 1, global score-ordered assignment), near-miss on strong identity (pass 2: small fee diff / money H-1), or name in the review band `NAME_REVIEW_FLOOR`(60)–84 → `perlu_tinjau` `name_partial` (pass 3). **Amount+date are SUPPORTING anchors only** — required (they block candidates) but never sufficient; identity < 60 means NO pair (`no_money`) so the row can wait for next-day settlement. Amount blocking uses rounded absolute value; the date window is directed (money ≥ credit date).
- Each match produces a `MatchResult` in one of three buckets: `cocok`, `tidak_cocok`, `perlu_tinjau` — plus pseudo-views in the UI: `no_panel` rows (money with no panel trace, `left=None`) are counted/displayed separately from `tidak_cocok` so `cocok+perlu_tinjau+tidak_cocok == panel row count` per run. Reason codes map to UI labels in `web/templatetags/web_extras.py` `REASON_LABELS` (keep old codes like `weak_name` there — historical rows still render).
- **`run_batch(toko, ...)`** is the top-level orchestrator the UI calls: checks completeness, runs the applicable relations, aggregates DP/WD totals, and — **only on success, as the last step** — "consumes" the transactions by setting `consumed_by_batch`. Consumed rows are excluded from future completeness/matching (`_active()` filters `consumed_by_batch__isnull=True`); deleting a batch frees them again (`SET_NULL`). The whole run is wrapped in `transaction.atomic()`, so a failed run rolls back completely (no orphan batch, nothing consumed).
- **Daily runs & late settlement:** the web always passes `recon_date` (one batch per `(toko, recon_date)`, guarded by view + unique constraint; redoing a date = delete the old batch first). On success, unmatched credit rows (`tidak_cocok`/`no_money`) still inside `date_window_days` are **not** consumed — they stay active "menunggu settlement". The next day's run matches them against newly-uploaded money rows; a hit **flips the original MatchResult in its home batch** (`reason_code="late_settlement"`, marked `resolved_by_batch`, home summary recomputed via `refresh_batch_summary`) and the credit row is consumed into its home batch. Carried rows never create new results in the resolving batch and are excluded from its gross totals (shown separately as "Settlement tertunda"). Unmatched carried rows past the window expire quietly into their home batch (recorded in `summary["late_settlement"]["expired"]`). Deleting a resolving batch calls `revert_late_settlements` first, restoring flips and reactivating carried/expired rows. **Retro write-back:** brand-new rows dated D < recon_date whose date already has a batch are written back to that batch (results into its runs, gross totals incremented via `_add_retro_gross`, consumed there); the current batch only notes them in `summary["retro"]`.
- The `include` dict threads through every matcher/aggregator to let a run opt specific sources in/out (panel_dp, panel_wd, bracket, bank, gateway). `include=None` means "all", the legacy behavior.

### 3. Read-only reporting views (`web/`)

Several pages aggregate existing rows **query-time — no new tables or migrations**, so they apply retroactively to production data and never touch the engine. Each has a pure aggregation module (unit-tested without rendering) called by a thin view. The one exception is the Control Bracket breakdown, which now carries a single write table, `web.models.FRKoreksi`: an overlay that corrects one cell (identified by toko/tanggal/account/kolom) without touching the underlying `Transaction` data — totals and Selisih Kontrol are recomputed from the corrected values on render, and every save/delete is logged to `AuditLog` (`fr_koreksi`/`fr_koreksi_hapus`).

- **`web/breakdown.py`** (`/bracket/`, "Control Bracket per FR Account") and **`web/rekening.py`** (`/rekening/`, per bank/gateway account) pivot straight off `Transaction.raw` via `KeyTextTransform`. Both derive per-account opening/closing balance with the **order-independent** `_saldo_batas` (in `breakdown.py`): real FR/bank rows shuffle within the same minute and backdated entries make the `Jam` stamp lie, so a positional first/last balance is wrong — instead it matches the multiset of pre-balances (`balance − delta`) against balances; a broken/non-unique chain falls back to `(Jam, id)` so the inconsistency surfaces in the **"Selisih Kontrol"** column (ideally 0) rather than being hidden.
- **`web/hutang.py`** (`/hutang-piutang/`) lists bracket rows whose `Kategori` is Hutang/Piutang, across dates, with running totals — same query-time pattern, no overlay.
- **`web/biaya.py`** (`/biaya-admin/`, "Rincian Biaya") rolls up bank fee rows per channel (E-wallet/BI Fast/Transfer online) — rows tagged `jenis="admin"` plus legacy rows matched query-time via `is_admin_fee`, grouped by date + `source_label_full`.
- **`web/bonus.py`** (`/bonus/`, "Rekonsiliasi Bonus") matches panel bonus rows against bracket bonus rows query-time — key = username (lowercase, brand prefix stripped) + rounded amount + date, greedy 1:1 per key → buckets cocok/panel_only/bracket_only + per-kategori summary. Feeds off two dedicated SourceTypes `panel_bonus`/`bracket_bonus` (parsers in `sources/parsers/bonus.py`; panel "Credit Balance" export takes ONLY bonus-prefixed Description rows and skips the net-zero `Offset` twins; bracket "Non Credit Bonus" maps code **K-BLD → "Lucky Draw"**; panel `Amt.` is ×1000, bracket `Nominal` is full rupiah). These keys are invisible to `check_completeness`/matchers/consume — the bonus path can never disturb the daily DP/WD pipeline.
- **`web/monthly.py`** (`/bulanan/`) reads `ReconBatch.summary` as-is per day (use `money`/matched, **not** `money_gross` — gross can dwarf panel). **`web/settlement.py`** (`/settlement/`) lists still-waiting credit rows via the engine's `_carried_results`. **`web/exports.py`** builds the Excel workbooks for the Export page and per-run export.

> Note: despite its name, the `reports/` Django app is a dormant scaffold (empty models/views, no migrations, not URL-wired). All real reporting lives in `web/`. Don't add report code to `reports/`.

## Domain model conventions (critical, easy to get wrong)

All money is normalized to **rupiah** on the canonical `Transaction`. Sign and scale conventions:

- **`credit_delta`** = effect on the operator's credit ledger; **`money_delta`** = effect on real cash. A deposit is `money_delta > 0` / `credit_delta < 0`; a withdrawal is the reverse. Matching requires the two sides to share the same money direction.
- **Panel amounts are in thousands** — the panel parser multiplies by `SCALE = 1000` to reach rupiah. Don't double-apply. **Exception: COR (Gacor25) exports are already in full rupiah** — the `cor_*` parsers must NOT ×1000.
- **Per-brand exact keys on the money side** (prefer these over fuzzy): COR QRIS `Transaction ID` (UUID) == gateway `OrderId` → `reference`; MUL QRIS-HOKI `Whitelabel Transaction ID` == panel ticket; MXW QRFlyer `TXN ID` / NXPay `Ticket Number` == panel ticket; UNO QRIS-WD `Order ID (Merchant)` (UUID penuh) == panel Vigor/TMG WD `Transaction ID` (parser `cor_qris_wd_gateway`, REFUND rows dilewati). RPay (MUL/M77) sengaja TANPA `reference` — anchor = `Customer Username` == username panel; UUID hanya di `raw` karena Remarks panel Nexus terbukti tidak memuatnya (aturan blocked engine akan mengasingkan reference tak dikenal panel). BBS RafflesPay varian XLSX: DP `rpay_xlsx` (`Ticket Number` D... == panel; RRN hanya di raw, ada duplikat nyata) dan WD `rpay_wd_xlsx` (header dua-tingkat, `Ticket` W... == panel, hanya `Transfer=success`, `Disbursed Amount` = uang keluar). Some COR exports lack the xlsx `<dimension>` tag and have broken stylesheets — read them with the styles-tolerant raw reader in `sources/parsers/base.py`, not plain openpyxl.
- **Fee rows are tagged `jenis="admin"`** and deliberately excluded from WD money totals, matching, and completeness (they aren't real withdrawals): BCA `BIAYA TXN` rows, and BRI **BRIVA** fee rows (each BRIVA e-wallet WD pairs with an identical-description Rp1.000 debit twin, `is_briva_fee`). BRI `ATMSTRPRM…`@6500 / `BFST…`@2500 / `BRIVA…`@1000 and Mandiri `Biaya…` are now flagged via `sources/parsers/fee_rules.is_admin_fee` (used both by the parsers at ingest and, query-time, by the Rincian Biaya report for legacy rows ingested before the rule existed).
- **WD e-wallet via BRI (BRIVA)**: mutasi shows `BRIVA<channel code><phone>` glued together (DANA 88810, GOPAY 30135, OVO 88099, SHOPEEPAY 112, LINK AJA 91188) — the 16-18 digit run defeats the generic 9-15 digit phone scan, so `_money_phones` has a dedicated `_BRIVA_RE` that strips the code before phone matching. Client's channel-trace matrix ("TRANSAKSI KELUAR MUTASI WITHDRAW") is the source of truth for which bank→channel combos carry identity at all (e.g. BNI→GOPAY carries NO number — unmatchable by identity).
- Match keys on `Transaction`: `ticket_no` (panel `D…`/`W…`), `reference` (gateway), `username`, `counterparty` (bank sender/receiver name). Names are isolated per-source in the parser; the engine only normalizes + fuzzy-matches.
- `USE_TZ = False` — bank/panel timestamps are naive local (WIB, `Asia/Jakarta`). Don't introduce tz-aware datetimes.

## Access control (`web/access.py`)

RBAC is scoped **per Toko** (brand/site). `tokos_for(user)` is the single source of truth: admins/supervisors see all active Tokos; auditors see only `allowed_tokos`. The custom user model is `accounts.User` (roles: admin/supervisor/auditor; no public signup). The active Toko lives in the session (`active_toko_id`) and is injected into every template by the `web.context_processors.toko` context processor. Web views live in `web/views.py` (reconciliation flow) and `web/admin_views.py` (Toko/user management, deletes).

`web/middleware.py` `ForcePasswordChangeMiddleware` (registered right after `AuthenticationMiddleware`) gates **every** request for users flagged `must_change_password` → redirected to `/ganti-password/` until they change it (admins set the flag when creating a user or resetting someone else's password). Sensitive admin/account actions are written to `core.models.AuditLog` via `core.audit.catat`, which snapshots the actor's username so the trail survives a later user deletion (`/kelola/log/`, admin-only).

## Deployment

Railway (Nixpacks), config in `railway.json` / `Procfile`. Production is triggered by env: `DATABASE_URL` present → Postgres via `dj-database-url` (else sqlite); `RAILWAY_PUBLIC_DOMAIN` auto-populates `ALLOWED_HOSTS` + `CSRF_TRUSTED_ORIGINS`; `DEBUG=False` turns on the SSL/HSTS/secure-cookie block. Static files served by WhiteNoise (compressed manifest storage). Start command runs `collectstatic` + `migrate` + gunicorn.

## Working notes

- Design specs and implementation plans for completed features live in `docs/superpowers/{specs,plans}/` — check there for intent behind non-obvious decisions.
- `db.sqlite3` is the local dev DB and is **gitignored** (contains real working data — never commit it). Git worktrees don't have it; copy it from the main checkout + `migrate` if a preview needs real data.
- Tests that GET-render a template extending `web/base.html` need a `collectstatic`-generated `staticfiles.json` manifest (WhiteNoise `CompressedManifestStaticFilesStorage`), which is **gitignored**. Fresh worktrees/CI fail such tests with `ValueError: Missing staticfiles manifest entry for ...` until you run `python manage.py collectstatic --noinput` once. Same class of gap as `db.sqlite3`.
- **Git flow:** commit per work chunk AND push to `origin/main` (fast-forward only, never force). A teammate (`sabian`) also lands on main — always `git fetch` + rebase before pushing.
- **Pushing does NOT deploy.** Deploys are manual: `railway up --ci` run from the main checkout `/Users/macads/Truth-of-auditor` after fast-forwarding it to `origin/main` (running it from a worktree ships a stale tree). Never deploy without explicit confirmation — this is a live financial app.
- Django 5.2 keeps the cached template loader on even in DEBUG — restart the dev server after editing templates before concluding an edit "didn't work".
