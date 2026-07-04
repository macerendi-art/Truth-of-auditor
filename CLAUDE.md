# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Truth of Auditor** — a Django 5.2 app that reconciles a betting/credit operator's records across four kinds of sources: the **Panel** (site's own DP/WD history), the **Bracket** (agent ledger), **Banks**, and payment **Gateways**. It ingests exported files (xlsx/csv/pdf, some encrypted), normalizes every row into one canonical `Transaction`, then matches credit-side records against money-side records to surface discrepancies. UI and code comments are in Indonesian; keep that convention.

## Commands

The virtualenv is at `.venv`. Activate it first: `source .venv/bin/activate`.

```bash
python manage.py test                         # run all tests (31 test modules)
python manage.py test web.tests_reconcile     # one module
python manage.py test web.tests_reconcile.SomeTestCase.test_x   # one test
python manage.py runserver                     # dev server (sqlite, DEBUG=True)
python manage.py migrate                        # apply migrations (includes seed data)

# CLI equivalents of the core pipeline (useful for debugging without the UI):
python manage.py ingest <parser_key> <file_path> [--flow dp|wd] [--password ...]
python manage.py match <panel_bracket|panel_bank|bracket_bank> [--from YYYY-MM-DD] [--to YYYY-MM-DD]
```

Reference data (SourceTypes, the "Default" ToleranceProfile, seeded Tokos) is created by **data migrations**, not fixtures — a fresh `migrate` gives you a working DB. Tests rely on these seeds existing.

## Architecture: the ingest → match pipeline

Everything flows through two stages. Understanding these two modules explains most of the codebase.

### 1. Ingest (`sources/`) — heterogeneous files → canonical `Transaction`

- **`sources/detect.py`** `detect_source(path, filename)` sniffs header tokens / extension and returns ranked `{parser_key, confidence}`. The web upload flow auto-detects, and only asks the user to confirm when confidence < 0.8.
- **`sources/services.py`** `ingest(parser_key, file_path, ...)` is the single entry point: picks the parser from the `PARSERS` dict, decrypts first if the file is an encrypted xlsx (OLE2 magic bytes → `msoffcrypto`, Mandiri e-statements), runs it, and bulk-creates `Transaction` rows inside one atomic block.
- **`sources/parsers/`** one class per format (`panel`, `bracket`, `banks.py` → BRI/BCA-CSV/Mandiri, `bca_pdf`, `gateways.py` → NXPay/QRFlyer). Each subclasses `BaseParser` and returns a list of dicts whose keys **exactly match `Transaction` fields**. Shared parsing helpers (decimal/date parsing for both `intl` and `id` number formats, ticket/ref regexes, `clean_name`, `row_hash`) live in **`sources/parsers/base.py`**.
- **Idempotency:** every row gets a `row_hash` (stable hash of key fields). `ingest` skips hashes that already exist for that `(source_type, toko)`, so re-importing the same file is safe.

To add a new source format: write a parser subclass, register it in `PARSERS` (`services.py`), and add a detection signature in `detect.py`.

### 2. Match (`reconciliation/engine.py`) — the reconciliation logic

- **Matchers are pluggable** via the `MATCHERS` dict keyed by `MatchRun.Relation`. `PanelBracketMatcher` joins on **Ticket Number** (strong key). `_MoneyMatcher` (→ `PanelBankMatcher`, `BracketBankMatcher`) blocks by rounded absolute amount, then filters by directed date window + username/fuzzy-name score (`rapidfuzz`, tolerant of bank-truncated names).
- Each match produces a `MatchResult` in one of three buckets: `cocok` (matched), `tidak_cocok` (no match), `perlu_tinjau` (amount/name weak → needs human review).
- **`run_batch(toko, ...)`** is the top-level orchestrator the UI calls: checks completeness, runs the applicable relations, aggregates DP/WD totals, and — **only on success, as the last step** — "consumes" the transactions by setting `consumed_by_batch`. Consumed rows are excluded from future completeness/matching (`_active()` filters `consumed_by_batch__isnull=True`); deleting a batch frees them again (`SET_NULL`). If anything above throws, consumption never happens, so a failed run leaves data untouched.
- The `include` dict threads through every matcher/aggregator to let a run opt specific sources in/out (panel_dp, panel_wd, bracket, bank, gateway). `include=None` means "all", the legacy behavior.

## Domain model conventions (critical, easy to get wrong)

All money is normalized to **rupiah** on the canonical `Transaction`. Sign and scale conventions:

- **`credit_delta`** = effect on the operator's credit ledger; **`money_delta`** = effect on real cash. A deposit is `money_delta > 0` / `credit_delta < 0`; a withdrawal is the reverse. Matching requires the two sides to share the same money direction.
- **Panel amounts are in thousands** — the panel parser multiplies by `SCALE = 1000` to reach rupiah. Don't double-apply.
- **BCA fee rows** are tagged `jenis="admin"` and deliberately excluded from WD money totals (they aren't real withdrawals).
- Match keys on `Transaction`: `ticket_no` (panel `D…`/`W…`), `reference` (gateway), `username`, `counterparty` (bank sender/receiver name). Names are isolated per-source in the parser; the engine only normalizes + fuzzy-matches.
- `USE_TZ = False` — bank/panel timestamps are naive local (WIB, `Asia/Jakarta`). Don't introduce tz-aware datetimes.

## Access control (`web/access.py`)

RBAC is scoped **per Toko** (brand/site). `tokos_for(user)` is the single source of truth: admins/supervisors see all active Tokos; auditors see only `allowed_tokos`. The custom user model is `accounts.User` (roles: admin/supervisor/auditor; no public signup). The active Toko lives in the session (`active_toko_id`) and is injected into every template by the `web.context_processors.toko` context processor. Web views live in `web/views.py` (reconciliation flow) and `web/admin_views.py` (Toko/user management, deletes).

## Deployment

Railway (Nixpacks), config in `railway.json` / `Procfile`. Production is triggered by env: `DATABASE_URL` present → Postgres via `dj-database-url` (else sqlite); `RAILWAY_PUBLIC_DOMAIN` auto-populates `ALLOWED_HOSTS` + `CSRF_TRUSTED_ORIGINS`; `DEBUG=False` turns on the SSL/HSTS/secure-cookie block. Static files served by WhiteNoise (compressed manifest storage). Start command runs `collectstatic` + `migrate` + gunicorn.

## Working notes

- Design specs and implementation plans for completed features live in `docs/superpowers/{specs,plans}/` — check there for intent behind non-obvious decisions.
- `db.sqlite3` is committed and large (contains real working data); it is the local dev DB.
- After each work chunk, commit and push — the team pulls from GitHub.
