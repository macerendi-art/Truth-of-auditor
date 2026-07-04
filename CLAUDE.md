# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Truth of Auditor** — a Django 5.2 app that reconciles a betting/credit operator's records across four kinds of sources: the **Panel** (site's own DP/WD history), the **Bracket** (agent ledger), **Banks**, and payment **Gateways** (QR/e-wallet). It ingests exported files (xlsx/csv/pdf/zip, some encrypted), normalizes every row into one canonical `Transaction`, then matches credit-side records against money-side records to surface discrepancies (selisih). UI and code comments are in Indonesian; keep that convention.

**The product goal is a "no-thinking" daily ritual for the auditor.** Mutation exports lag one night: the file uploaded on day D contains D-1-night settlements (carrying their original transaction date) plus D-daytime rows, so every daily batch is born with a night-tail of `tidak_cocok` rows whose money arrives in tomorrow's upload. The flow is built around healing that tail automatically:

1. **Upload** the day's folder/zip → files auto-detected, and **auto re-match** immediately pairs the new money rows into older batches' `tidak_cocok` tails (flash reports per batch; money is consumed into the OLD batch, so selisih lands on the correct date).
2. **Reconcile** — the date field is pre-filled with the next un-reconciled day (empty dates = "swallow ALL data" and is intercepted by a confirm modal).
3. Yesterday's batch heals today; today's night-tail waits for tomorrow. The same mechanism closes monthly statements (e.g. BNI available once a month) without deleting batches.

## Commands

The virtualenv is at `.venv`. Activate it first: `source .venv/bin/activate`.

```bash
python manage.py test                         # run all tests (~368)
python manage.py test web.tests_reconcile     # one module
python manage.py test web.tests_reconcile.SomeTestCase.test_x   # one test
python manage.py runserver                     # dev server (sqlite, DEBUG=True)
python manage.py migrate                        # apply migrations (includes seed data)

# CLI equivalents of the core pipeline (useful for debugging without the UI):
python manage.py ingest <parser_key> <file_path> [--flow dp|wd] [--password ...]
python manage.py match <panel_bracket|panel_bank|bracket_bank> [--from YYYY-MM-DD] [--to YYYY-MM-DD]
```

Reference data (SourceTypes, the "Default" ToleranceProfile, seeded Tokos) is created by **data migrations**, not fixtures — a fresh `migrate` gives you a working DB. Tests rely on these seeds existing.

## Architecture: the ingest → match → re-match pipeline

### 1. Ingest (`sources/`) — heterogeneous files → canonical `Transaction`

- **Web upload is two-phase** (`web/views.py upload`): `action=analyze` stages files to `media/staging/` + detects parser per file (confirm asked only when confidence < 0.8); `action=commit` ingests the staged paths (parallel arrays `staged/parser_key/flow/password`). **Zip archives are extracted server-side at analyze** (each member becomes a normal preview row; guards: max 200 files / 200MB, password-protected zips rejected; `.xlsx` is NOT extracted — the check is by `.zip` extension, since xlsx is also a PK archive). A folder picker (`webkitdirectory`) and drag-drop (including folder traversal via `webkitGetAsEntry`) feed the same input; selections accumulate across picks. Junk is skipped on every path (`_is_junk_name`: dotfiles, `~$` locks, `__MACOSX`, extensions without a parser) and reported in the flash.
- **`sources/detect.py`** `detect_source(path, filename)` sniffs header tokens / extension and returns ranked `{parser_key, confidence}`.
- **`sources/services.py`** `ingest(parser_key, file_path, ...)` is the single entry point: picks the parser from the `PARSERS` dict, decrypts first if the file is an encrypted xlsx (OLE2 magic bytes → `msoffcrypto`, Mandiri e-statements), runs it, and bulk-creates `Transaction` rows inside one atomic block.
- **`sources/parsers/`** one class per format (`panel`, `bracket`, `banks.py` → BRI/BCA-CSV/Mandiri, `bca_pdf`, `gateways.py` → NXPay/QRFlyer). Each subclasses `BaseParser` and returns a list of dicts whose keys **exactly match `Transaction` fields**. Shared helpers (decimal/date parsing for `intl` and `id` formats, ticket/ref regexes, `clean_name`, `row_hash`, `normalize_dest`) live in **`sources/parsers/base.py`**.
- **Idempotency:** every row gets a `row_hash`. `ingest` skips hashes that already exist for that `(source_type, toko)`, so re-importing the same or overlapping files is safe (a fully-duplicate file yields an Upload with 0 new rows).

To add a new source format: write a parser subclass, register it in `PARSERS` (`services.py`), and add a detection signature in `detect.py`.

### 2. Match (`reconciliation/engine.py`) — the reconciliation logic

- **Matchers are pluggable** via `MATCHERS` keyed by `MatchRun.Relation`. `PanelBracketMatcher` joins on **Ticket Number** (strong key, no date lag). `_MoneyMatcher` (→ `PanelBankMatcher`, `BracketBankMatcher`) is a **per-row waterfall**:
  - **Pass 1 — gateway exact key**: panel `ticket_no` (QR TX-ID like `D1761515`, generated by the gateway and present on both sides) → fallback `reference`, against **SETTLED gateway rows only** (`_gw_settled` reads `raw["Payment Status"]`/`raw["Status"]`). Outcomes are terminal: `gateway_ticket`/`gateway_reference` (cocok), `gateway_amount_mismatch`, `gateway_unpaid` (tidak_cocok — an UNPAID QR must not fall through to bank fuzzy). Orphan settled gateway money with no panel row → `gateway_no_panel` (money arrived without a record — real audit signal).
  - **Pass 2 — bank fuzzy** on the residual panel rows only: block by rounded absolute amount, directed date window (bank ≥ panel, within `date_window_days`), then **`dest_account` strong key** (WD destination number extracted from bank mutation text vs panel `Player Bank` third segment; beats name score) → username exact → fuzzy name (`rapidfuzz`, tolerant of bank truncation). A score tie is `ambiguous_multi` (perlu_tinjau, no consumption) **only when the tied candidates are ≥2 distinct identities** — repeat deposits by the same player pair greedily.
- Buckets: `cocok`, `tidak_cocok`, `perlu_tinjau`. `reason_code` distinguishes why (UI labels via `web_extras.reason_label`).
- **`run_batch(toko, ...)`** orchestrates: completeness check (money-side window widened by `_widen_dto` so T+1 settlements count), runs applicable relations, aggregates (pair-based `_matched_money` → date attribution follows the PANEL date automatically), then — **only on success, as the last step** — consumes in-window transactions (`consumed_by_batch`) plus **spillover**: out-of-window money rows that got paired (prevents tomorrow's batch double-matching them). Unmatched orphans stay active for future batches. Deleting a batch frees its rows (`SET_NULL`). The `include` dict (which sources participate) is **persisted on `ReconBatch.include`** — required for correct summary recomputes later; `None` = all (legacy).
- **Dates**: entry points (`run_batch`/`run_match`/`check_completeness`) coerce string dates via `_as_date` — web POST sends `"YYYY-MM-DD"` strings; never assume `date` objects.

### 3. Re-match (`rematch_batch`) — healing old batches without deleting them

`rematch_batch(batch)` re-runs the matcher for a batch's `tidak_cocok` rows (PANEL_BANK only, v1) against the currently-**active** money pool in the batch's original widened window, honoring `batch.include`. Matches update the `MatchResult` **in place** (reason_detail gets a `" (re-match)"` suffix), consume the money into the **old** batch, and recompute run + batch summaries. Atomic, idempotent, never steals rows consumed by another batch, never creates new MatchResults. `_aggregate_batch(batch=...)` counts rows consumed by the batch itself (without this, recompute-after-consume collapses gross to 0).

**Auto re-match** (`web/views.py _auto_rematch`): after any money-source upload commit, candidate batches (`_rematch_candidates`: has tidak_cocok, window overlaps the new rows' date range, oldest first, max 10) are re-matched automatically; only batches with results are reported. The manual "⟳ Re-match" button on batch_detail remains.

Known v1 gaps: PANEL_BRACKET tails can't heal via re-match; late-arriving in-window PANEL rows are not adopted into old batches (they silently shift recomputed gross).

## Domain model conventions (critical, easy to get wrong)

All money is normalized to **rupiah** on the canonical `Transaction`. Sign and scale conventions:

- **`credit_delta`** = effect on the operator's credit ledger; **`money_delta`** = effect on real cash. A deposit is `money_delta > 0` / `credit_delta < 0`; a withdrawal is the reverse. Matching requires the two sides to share the same money direction.
- **Panel amounts are in thousands** — the panel parser multiplies by `SCALE = 1000` to reach rupiah. Don't double-apply.
- **BCA fee rows** are tagged `jenis="admin"` and deliberately excluded from WD money totals (they aren't real withdrawals).
- Match keys on `Transaction`: `ticket_no` (panel/gateway `D…`/`W…` TX-ID), `reference` (gateway), `username`, `counterparty` (bank sender/receiver name), `dest_account` (normalized destination number: digits only, strip `62`/leading `0`, min 9 digits — `normalize_dest`). Names are isolated per-source in the parser; the engine only normalizes + fuzzy-matches.
- Panel `raw["Player Bank"]` format is `channel|nama|nomor` — segment 1 feeds the channel filter in run_detail, segment 3 feeds `dest_account`.
- `USE_TZ = False` — bank/panel timestamps are naive local (WIB, `Asia/Jakarta`). Don't introduce tz-aware datetimes.

## Web conventions

- Destructive actions use the reusable confirm modal in `app_base.html`: `<form data-confirm="...">` intercepted globally (never native `confirm()` — users suppress it); `{n}` substitution via `data-confirm-count="<selector>"`. The attribute can be toggled dynamically (see reconcile's empty-date guard).
- RBAC is scoped **per Toko** (`web/access.py tokos_for(user)`): admins/supervisors see all active Tokos; auditors only `allowed_tokos`. Every object lookup in views must filter `toko__in=tokos_for(request.user)` (or the active toko for admin deletes). Active toko lives in the session (`active_toko_id`), injected by the `web.context_processors.toko` context processor. Custom user model `accounts.User` (roles admin/supervisor/auditor; no public signup).
- Batch numbers shown to users are **per-toko positional** (count of `id <= pk` for that toko), not pks.
- Views live in `web/views.py` (upload/reconcile/rematch flow) and `web/admin_views.py` (Toko/user management, deletes).

## Deployment

Railway (Nixpacks), config in `railway.json` / `Procfile`. Production is triggered by env: `DATABASE_URL` present → Postgres via `dj-database-url` (else sqlite); `RAILWAY_PUBLIC_DOMAIN` auto-populates `ALLOWED_HOSTS` + `CSRF_TRUSTED_ORIGINS`; `DEBUG=False` turns on the SSL/HSTS/secure-cookie block. Static files via WhiteNoise. Start command runs `collectstatic` + `migrate` + gunicorn. **The staging deployment needs a volume mounted at `/app/media`** (upload staging files live on disk between analyze and commit; single-attach volume → keep `numReplicas=1`). Staging deploys go via `railway up` from the working tree (not GitHub-linked); superuser is seeded from `DJANGO_SUPERUSER_*` env.

## Gotchas that have already bitten

- Django ≥4.1 cached template loader + `runserver --noreload`: templates go stale — restart the server after template edits.
- `{# ... #}` template comments are SINGLE-LINE; multi-line comments need `{% comment %}` or they render as page text.
- JSON keys with spaces (`raw["Player Bank"]`) break `values_list("left__raw__Player Bank")` — "Column aliases cannot contain whitespace". Use `annotate(x=KeyTextTransform("Player Bank", "left__raw"))`; `filter(**{"left__raw__Player Bank__istartswith": ...})` is fine.
- A CSS rule like `.overlay{display:flex}` overrides the `[hidden]` attribute — pair it with `.overlay[hidden]{display:none}` or the invisible overlay eats all clicks.
- Engine date params arrive as strings from the web — already coerced at entry (`_as_date`), keep it that way for new entry points.

## Working notes

- Design specs and implementation plans for completed features live in `docs/superpowers/{specs,plans}/` — check there for intent behind non-obvious decisions (e.g. `specs/rematch-batch.md` for re-match semantics).
- `db.sqlite3` is committed and large (contains real working data); it is the local dev DB.
- After each work chunk, commit and push — the team pulls from GitHub.
