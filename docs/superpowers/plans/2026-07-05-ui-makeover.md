# UI/UX Makeover v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete visual makeover of the Truth-Auditor app shell + 5 core screens (dashboard, upload, reconcile, batch_detail, run_detail) onto a token-driven pastel design system, with additive view upgrades (audit-health KPIs, structured healing report, htmx partial filters) — engine untouched.

**Architecture:** One vendored `app.css` (`@layer tokens/base/components/utilities`, 3-tier custom properties), vendored htmx 2.0.4 + GSAP + Lucide sprite (zero external origins), native `<dialog>` modal shells with the existing `data-confirm` JS contract kept verbatim. View changes only in `web/views.py` (dashboard context, `_auto_rematch` structured return via session stash, `HX-Request` partial branch in `run_detail`).

**Tech Stack:** Django 5.2 templates, vanilla CSS (no build step), htmx 2.0.4, GSAP 3.12.x, WhiteNoise manifest static.

**Spec:** `docs/superpowers/specs/2026-07-05-ui-makeover-design.md` — palette/type/table tokens live there; this plan references token names.

## Global Constraints

- UI copy in Indonesian. Code comments Indonesian (match codebase).
- NO build step, NO node, NO new Python deps. Assets vendored under `web/static/web/`.
- Palette/typography exactly per spec table (canvas `#E9EAF4`, coral-600 `#F4756B` decorative-only, coral-700 `#D9392D` CTA, status `#157A4E`/`#B4231C`/`#9A6400`; Zodiak/Supreme/IBM Plex Mono, no Google Fonts).
- Contracts that MUST survive (tests assert most of them): upload `action=analyze|commit` + parallel arrays `staged/parser_key/flow/password` one value per row in DOM order + single `provider`; `data-confirm`/`data-confirm-count`/`{n}`; `id="confirm-modal"`; `form="bulkform"` and `form="jalankan-form"` attribute linking; `readonly tabindex="-1"` on non-password preview inputs; empty-date guard toggling `data-confirm`; pengingat-toko copy + credits (tests_login_popup); RBAC `toko__in=tokos_for(...)`.
- `USE_TZ=False`; engine date params stay strings at web entry.
- After every template edit: restart runserver if smoke-testing (cached loader).
- Commit after each task; messages in Indonesian like the existing history.

---

### Task 1: Vendor JS assets (htmx 2.0.4, GSAP) and drop CDN dependence later

**Files:**
- Create: `web/static/web/js/htmx.min.js`, `web/static/web/js/gsap.min.js`

**Interfaces:**
- Produces: static paths `web/js/htmx.min.js`, `web/js/gsap.min.js` used by Task 4's `app_base.html`.

- [ ] **Step 1: Download pinned assets**

```bash
cd <worktree-root>
curl -fsSL https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js -o web/static/web/js/htmx.min.js
curl -fsSL https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.7/gsap.min.js -o web/static/web/js/gsap.min.js
head -c 100 web/static/web/js/htmx.min.js && echo && head -c 100 web/static/web/js/gsap.min.js
```
Expected: both files non-empty, first bytes look like minified JS (no HTML error page).

- [ ] **Step 2: Verify Django can resolve them**

```bash
source .venv/bin/activate
python manage.py findstatic web/js/htmx.min.js web/js/gsap.min.js
```
Expected: two absolute paths found.

- [ ] **Step 3: Commit**

```bash
git add web/static/web/js/
git commit -m "chore(web): vendor htmx 2.0.4 + gsap 3.12.7 (persiapan lepas CDN)"
```

---

### Task 2: Lucide icon sprite

**Files:**
- Create: `web/templates/web/_icon_sprite.html`
- Create: `scripts/build_icon_sprite.py` (committed for regeneration)

**Interfaces:**
- Produces: `<symbol id="i-<name>">` for names: `layout-dashboard, upload, list, git-compare, users, store, check, x, flag, chevron-right, chevron-down, log-out, circle-alert, receipt, landmark, wallet, file-text, file-spreadsheet, file-archive, download, calendar-check, sparkles, rotate-cw, trash-2, lock, search, arrow-right, folder-open, alert-triangle, activity`. Usage: `<svg class="ic"><use href="#i-upload"/></svg>`.

- [ ] **Step 1: Write generator script**

```python
# scripts/build_icon_sprite.py
"""Bangun sprite Lucide → web/templates/web/_icon_sprite.html.
Jalankan manual saat menambah ikon; hasilnya di-commit (tanpa build step runtime)."""
import re
import urllib.request

ICONS = [
    "layout-dashboard", "upload", "list", "git-compare", "users", "store",
    "check", "x", "flag", "chevron-right", "chevron-down", "log-out",
    "circle-alert", "receipt", "landmark", "wallet", "file-text",
    "file-spreadsheet", "file-archive", "download", "calendar-check",
    "sparkles", "rotate-cw", "trash-2", "lock", "search", "arrow-right",
    "folder-open", "alert-triangle", "activity",
]
VER = "0.469.0"
parts = ['<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">']
for name in ICONS:
    url = f"https://unpkg.com/lucide-static@{VER}/icons/{name}.svg"
    svg = urllib.request.urlopen(url).read().decode()
    inner = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1).strip()
    parts.append(f'<symbol id="i-{name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">{inner}</symbol>')
parts.append("</svg>")
open("web/templates/web/_icon_sprite.html", "w").write("\n".join(parts) + "\n")
print(f"OK — {len(ICONS)} ikon")
```

- [ ] **Step 2: Run it, eyeball output**

```bash
python scripts/build_icon_sprite.py && head -3 web/templates/web/_icon_sprite.html && grep -c "<symbol" web/templates/web/_icon_sprite.html
```
Expected: `OK — 30 ikon`, grep count 30. If any icon 404s, check the name on lucide.dev and substitute (e.g. `store` may be `store` or `building-2` depending on version — use whichever resolves).

- [ ] **Step 3: Commit**

```bash
git add scripts/build_icon_sprite.py web/templates/web/_icon_sprite.html
git commit -m "feat(web): sprite ikon Lucide vendored (30 simbol, stroke 1.75)"
```

---

### Task 3: `app.css` design system

**Files:**
- Create: `web/static/web/css/app.css`

**Interfaces:**
- Produces: every class name currently used by templates (`.side .topbar .content .page-head .grid .cols-* .card .stat .badge .btn .field .row .twrap .table-wrap .pad0 .mono .num .pager .tabs .msg .reveal .dz .toko-pick .muted .faint .r`), restyled onto tokens; plus NEW components consumed by later tasks: `.kpi-hero`, `.bucket-bar`, `.spark`, `.donut`, `.file-row`, `.file-chip`, `.conf-meter`, `.healing-card`, `.icon-pill`, `.row-actions`, `.btn.danger`, `.btn.block`, `.date-hero`, `.summary-line`, `.skeleton`, `.htmx-indicator` styling, `dialog.modal` + `::backdrop`.

- [ ] **Step 1: Write the file**

Full content — tokens exactly per spec §palet/§tipografi. Structure (write all four layers in one file, ~600 lines):

```css
/* Truth of Auditor — design system. Token 3 tingkat; @layer tanpa build step.
   Palet & aturan AA: docs/superpowers/specs/2026-07-05-ui-makeover-design.md */
@layer tokens, base, components, utilities;

@layer tokens {
  :root {
    /* Tier 1 — primitif */
    --canvas:#E9EAF4; --canvas-alt:#DFE0EF;
    --surface:#FFFFFF; --surface-alt:#F6F6FB;
    --border:#E4E5F0; --border-strong:#D3D5E8;
    --text-primary:#20223A; --text-secondary:#565A73; --text-muted:#8A8DA6;
    --coral-500:#F98D84; --coral-600:#F4756B; --coral-700:#D9392D;
    --coral-text:#C23B30; --coral-tint:#FDEBEA;
    --navy-900:#1B1E3D; --navy-800:#232759; --navy-700:#2D3282; --navy-600:#3D42A0; --navy-tint:#EDEEF9;
    --periwinkle:#8B93E8; --periwinkle-text:#4B52B0; --periwinkle-tint:#EEEFFC;
    --orange-500:#F5A45C;
    --ok-700:#157A4E; --ok-tint:#E6F6EE;
    --bad-700:#B4231C; --bad-tint:#FCEAE9;
    --warn-700:#9A6400; --warn-tint:#FDF3E0;
    --sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:16px; --sp-5:20px;
    --sp-6:24px; --sp-7:32px; --sp-8:40px; --sp-9:48px; --sp-10:64px;
    --radius-card:20px; --radius-lg:16px; --radius-md:12px; --radius-input:10px; --radius-pill:999px;
    --shadow-1:0 1px 2px rgba(27,30,61,.05),0 1px 1px rgba(27,30,61,.03);
    --shadow-2:0 8px 24px -8px rgba(27,30,61,.10);
    --shadow-3:0 20px 40px rgba(27,30,61,.10),0 8px 16px -4px rgba(27,30,61,.06);
    --font-display:'Zodiak',Georgia,serif;
    --font-body:'Supreme',system-ui,sans-serif;
    --font-mono:'IBM Plex Mono',ui-monospace,'SF Mono',Menlo,Consolas,monospace;
    /* Tier 2 — semantik (dipisah dari coral: semantik audit ≠ aksen brand) */
    --bg:var(--canvas); --panel:var(--surface); --panel-2:var(--surface-alt);
    --ink:var(--text-primary); --muted:var(--text-secondary); --faint:var(--text-muted);
    --line:var(--border); --line-2:var(--border-strong);
    --accent:var(--coral-600); --accent-solid:var(--coral-700);
    --ok:var(--ok-700); --ok-bg:var(--ok-tint);
    --warn:var(--warn-700); --warn-bg:var(--warn-tint);
    --bad:var(--bad-700); --bad-bg:var(--bad-tint);
    /* Tier 3 — knob komponen */
    --card-pad:var(--sp-5);
    --table-cell-pad-y:11px; --table-cell-pad-x:16px;
    --btn-bg:var(--surface); --btn-ink:var(--ink);
  }
}
```

then `@layer base` (reset, body flex shell on `--bg`, `a`, headings on `--font-display`, `label/input/select` on `--radius-input` with `--navy-600` focus ring), `@layer components` (each component nested; port EVERY selector from the old inline block, retheme to tokens):

- `.side` — `--navy-900` bg, white/`rgba(255,255,255,.55)` text, `.link.active` = `--coral-700` pill (radius-pill, white label) + 3px `--coral-600` left rail glow, brand logo chip coral gradient.
- `.topbar` — `rgba(233,234,244,.85)` + blur, crumb `--text-secondary`.
- `.card` radius-card, shadow-2, pad `--card-pad`; `.card h3` Supreme 700 15.5px.
- `.stat` — `.v` uses `--font-display` (Zodiak) 30px for hero variant `.kpi-hero .v`, else Supreme 700 26px; `.ic` chips use tint tokens (`.g`→ok, `.a`→warn, `.r`→bad, default periwinkle-tint/periwinkle-text).
- `.badge` — pill, tint bgs; `.badge.ok/.warn/.bad` on `-700`+`-tint` pairs; `.badge.src` navy-tint/navy-700.
- `.btn` — pill radius, Supreme 600 14px; `.btn.primary{--btn-bg:var(--accent-solid);color:#fff}` (coral-700 for AA); `.btn.danger{--btn-bg:var(--bad-700);color:#fff}`; `.btn.block{width:100%;justify-content:center;padding:14px}`; `.btn.sm`, `.btn.ghost` as before.
- tables — `.twrap,.table-wrap{overflow-x:auto;border:1px solid var(--border-strong);border-radius:var(--radius-md)}`; `thead th{position:sticky;top:0;z-index:2;background:var(--surface-alt);color:var(--text-secondary);font-size:11px;text-transform:uppercase;letter-spacing:.06em;padding:10px var(--table-cell-pad-x)}`; `tbody td{padding:var(--table-cell-pad-y) var(--table-cell-pad-x);border-bottom:1px solid var(--border)}`; `tbody tr:hover{background:var(--surface-alt)}`; `.sticky-col th:first-child,.sticky-col td:first-child{position:sticky;left:0;background:var(--surface);z-index:1;box-shadow:4px 0 8px -4px rgba(27,30,61,.08)}`; `table.flush`, `.pad0` (no `!important` — utilities layer wins by layer order).
- `.tabs a` pills; active = navy-700 bg white text (NOT coral — tabs are filters, not CTAs).
- `.msg` on tint tokens.
- `.dz` + `.dz-over` (border-color `--coral-600`, bg `--coral-tint`, lift shadow-2).
- NEW: `.bucket-bar{display:flex;height:10px;border-radius:var(--radius-pill);overflow:hidden;background:var(--border)} .bucket-bar span{transition:width .5s ease} .bucket-bar .s-ok{background:var(--ok-700)} .s-warn{background:var(--warn-700)} .s-bad{background:var(--bad-700)}`
- NEW: `.spark{width:120px;height:32px} .spark polyline{fill:none;stroke:var(--periwinkle-text);stroke-width:2}`
- NEW: `.donut{width:76px;aspect-ratio:1;border-radius:50%;background:conic-gradient(var(--donut-stops,var(--ok-700) 0 100%));position:relative} .donut::after{content:"";position:absolute;inset:12px;border-radius:50%;background:var(--surface)}` (stops injected via inline `--donut-stops`).
- NEW upload: `.file-row` (grid: chip | name+path | size | remove), `.file-chip` 28px radius-input tinted per type (`.t-xlsx` ok, `.t-csv` periwinkle, `.t-pdf` bad, `.t-zip` warn, `.t-skip` muted+strike), `.conf-meter{height:4px;border-radius:999px;background:var(--border);width:64px} .conf-meter i{display:block;height:100%;border-radius:999px}` with `.hi`(ok)/`.mid`(warn)/`.lo`(bad), `tr.needs-confirm td:first-child{box-shadow:inset 3px 0 var(--warn-700)}`, `.pw-lock input` red-tinged border until `:not(:placeholder-shown)`.
- NEW: `.healing-card` (ok-tint bg, ok border, rows w/ mono deltas, `del` muted strike + arrow), `.summary-line` dot-separated status counts.
- NEW: `.icon-pill{width:26px;height:26px;border-radius:999px;display:inline-grid;place-items:center}` + tint variants; `.row-actions{opacity:.35;transition:opacity .12s}` `tr:hover .row-actions,tr:focus-within .row-actions{opacity:1}`.
- NEW: `dialog.modal{border:none;border-radius:var(--radius-lg);box-shadow:var(--shadow-3);padding:26px;max-width:460px;width:calc(100% - 40px)} dialog.modal::backdrop{background:rgba(27,30,61,.55);backdrop-filter:blur(4px)}` + keep `@keyframes reminder-in` w/ reduced-motion guard.
- NEW: `.htmx-indicator{opacity:0;transition:opacity .15s} .htmx-request .htmx-indicator{opacity:1} .htmx-request#result-table{opacity:.5;pointer-events:none}`; `.skeleton` shimmer w/ reduced-motion off.
- `.date-hero{background:var(--navy-tint);border:1px solid var(--border-strong);border-radius:var(--radius-lg);padding:var(--sp-4)}`.

`@layer utilities`: `.muted .faint .num .mono{font-variant-numeric:tabular-nums;font-feature-settings:"tnum"} .id-mono,.amount{font-family:var(--font-mono);font-size:.96em} .r{text-align:right} .grid/.cols-*` w/ same breakpoints, `.pad0{padding:0;overflow:hidden}`.

- [ ] **Step 2: Sanity check**

```bash
python -c "css=open('web/static/web/css/app.css').read(); assert css.count('{')==css.count('}'), 'kurung tak seimbang'; print('OK', len(css.splitlines()), 'baris')"
python manage.py findstatic web/css/app.css
```

- [ ] **Step 3: Commit**

```bash
git add web/static/web/css/app.css
git commit -m "feat(web): app.css — design system token 3 tingkat (@layer, palet coral/navy/lavender)"
```

---

### Task 4: Rewire `app_base.html` (shell)

**Files:**
- Modify: `web/templates/web/app_base.html` (full rewrite of head + sidebar + modals + scripts; content blocks unchanged)
- Test: existing suite (shell renders in every view test) + `web/tests_confirm_modal.py`, `web/tests_login_popup.py` must stay green.

**Interfaces:**
- Consumes: Task 1 JS files, Task 2 sprite, Task 3 CSS.
- Produces: blocks `title/head/crumb/content/scripts` unchanged; `data-confirm` contract unchanged; `id="confirm-modal"` now a `<dialog class="modal">`.

Key edits (keep everything not listed):

1. Head: remove Google Fonts preconnect+link, unpkg htmx, cdnjs gsap, Lenis. Add:
```html
<link rel="stylesheet" href="{% static 'web/css/fonts.css' %}">
<link rel="stylesheet" href="{% static 'web/css/app.css' %}">
<script src="{% static 'web/js/htmx.min.js' %}" defer></script>
<script src="{% static 'web/js/gsap.min.js' %}" defer></script>
```
Delete the whole inline `<style>` block.
2. After `<body>`: `{% include "web/_icon_sprite.html" %}`.
3. Sidebar/topbar markup: same structure/links/`{% if is_admin_user %}`/who-logout, but every inline `<svg viewBox...>...</svg>` → `<svg class="ic" width="18" height="18"><use href="#i-layout-dashboard"/></svg>` (upload→`i-upload`, transaksi→`i-list`, rekonsiliasi→`i-git-compare`, pengguna→`i-users`, toko→`i-store`, brand→`i-activity`, toko-pick→`i-store`, keluar arrow stays text).
4. Reminder toko: same copy/credits/select form (tests assert text), wrapped in `<dialog class="modal" id="reminderOverlay">`; script: `dlg.showModal()` on load, close button + `close` event → `dlg.close()`; remove overlay-click-hide logic in favor of `dlg.addEventListener('click', e=>{ if(e.target===dlg) dlg.close(); })`.
5. Confirm modal: `<dialog class="modal" id="confirm-modal">` — same inner ids (`confirm-modal-title/-msg/-ok/-cancel`), same kicker/copy. JS: keep `buildMsg`, submit-capture delegation, `dataset.confirmed`, `{n}` — only `open()` → `overlay.showModal()`, `close()` → `overlay.close()`; Esc handled natively (keep `cancel` event listener to reset `pending`). The comment block `{% comment %}…{% endcomment %}` stays.
6. Base script: DELETE Lenis init + magnetic-buttons block. KEEP reduced-motion flag, `countUp`, `.reveal` GSAP stagger (guard `window.gsap` — scripts now `defer`, run block on `DOMContentLoaded`).

- [ ] **Step 1: Apply edits** (full rewrite per above)
- [ ] **Step 2: Run shell-touching tests**

```bash
python manage.py test web.tests_confirm_modal web.tests_login_popup web.tests_auth web.tests_scope -v1
```
Expected: PASS (fix markup until green — assertions: `id="confirm-modal"`, `data-confirm`, no literal `#}` rendered, pengingat copy).

- [ ] **Step 3: Full suite**

```bash
python manage.py test
```
Expected: all ~368 pass.

- [ ] **Step 4: Commit**

```bash
git add web/templates/web/app_base.html
git commit -m "feat(web): shell baru — app.css + sprite + dialog native, lepas CDN/Lenis/magnetik"
```

---

### Task 5: Dashboard — audit-health context + template

**Files:**
- Modify: `web/views.py:82-103` (dashboard) + add `_dashboard_health(toko)` helper above it
- Modify: `web/templatetags/web_extras.py` (add `sparkline_points` filter)
- Modify: `web/templates/web/dashboard.html`
- Test: Create `web/tests_dashboard_health.py`

**Interfaces:**
- Consumes: `_saran_tanggal(toko)` (exists, `web/views.py:232`), `ReconBatch.summary` dict shape (`dp/wd.selisih`, `buckets.*`).
- Produces: context keys `health = {selisih_terbuka:int, ekor_terbuka:int, buckets_agg:{cocok,perlu_tinjau,tidak_cocok}, selisih_trend:list[7 int], saran_tanggal:date|None, hari_tertunda:int}`; template filter `sparkline_points(values, width=120) -> "x,y x,y …"`.

- [ ] **Step 1: Write failing tests**

```python
# web/tests_dashboard_health.py
"""KPI kesehatan audit di dashboard: selisih terbuka, ekor, tren, saran tanggal."""
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from reconciliation.models import ReconBatch, ToleranceProfile
from web.models import Toko  # sesuaikan import bila Toko ada di app lain (cek models)
from web.templatetags.web_extras import sparkline_points


def _batch(toko, tol, d, dp_selisih=0, wd_selisih=0, tidak=0):
    return ReconBatch.objects.create(
        toko=toko, tolerance=tol, date_from=d, date_to=d,
        summary={
            "dp": {"selisih": dp_selisih}, "wd": {"selisih": wd_selisih},
            "buckets": {"cocok": 5, "perlu_tinjau": 1, "tidak_cocok": tidak},
        },
    )


class DashboardHealthTests(TestCase):
    def setUp(self):
        self.toko = Toko.objects.first()  # seed migration
        self.user = User.objects.create_superuser("admin", password="x")
        self.client.force_login(self.user)
        s = self.client.session
        s["active_toko_id"] = self.toko.id
        s.save()
        self.tol = ToleranceProfile.objects.get(name="Default")

    def test_health_context(self):
        today = date.today()
        _batch(self.toko, self.tol, today - timedelta(days=1), dp_selisih=4200, tidak=3)
        _batch(self.toko, self.tol, today - timedelta(days=2), wd_selisih=-500)
        r = self.client.get(reverse("dashboard"))
        h = r.context["health"]
        self.assertEqual(h["selisih_terbuka"], 4700)  # |4200| + |-500|
        self.assertEqual(h["ekor_terbuka"], 1)
        self.assertEqual(h["buckets_agg"]["cocok"], 10)
        self.assertEqual(len(h["selisih_trend"]), 7)
        self.assertEqual(h["selisih_trend"][-2], 4200)  # kemarin
        self.assertContains(r, "Selisih terbuka")

    def test_health_kosong(self):
        r = self.client.get(reverse("dashboard"))
        h = r.context["health"]
        self.assertEqual(h["selisih_terbuka"], 0)
        self.assertEqual(h["ekor_terbuka"], 0)


class SparklineTests(TestCase):
    def test_points(self):
        pts = sparkline_points([0, 10, 5])
        pairs = pts.split()
        self.assertEqual(len(pairs), 3)
        self.assertTrue(all("," in p for p in pairs))

    def test_kosong(self):
        self.assertEqual(sparkline_points([]), "")
```

NOTE: check real import for `Toko` and `ReconBatch` field requirements (`tolerance` nullable?) — adjust factory to the actual model (`python manage.py shell` or read `reconciliation/models.py`) BEFORE running. The assertion values are the contract.

- [ ] **Step 2: Run — expect FAIL** (`KeyError: 'health'` / ImportError sparkline_points)

```bash
python manage.py test web.tests_dashboard_health -v1
```

- [ ] **Step 3: Implement**

`web/templatetags/web_extras.py` append:

```python
@register.filter
def sparkline_points(values, width=120):
    """List angka → string points polyline SVG (viewBox 0 0 {width} 32)."""
    values = list(values or [])
    if not values:
        return ""
    h, pad = 32, 2
    vmax = max(values) or 1
    step = width / max(len(values) - 1, 1)
    return " ".join(
        f"{i * step:.1f},{h - pad - (v / vmax) * (h - 2 * pad):.1f}"
        for i, v in enumerate(values)
    )
```

`web/views.py` — add helper (uses `date` — extend the existing `from datetime import timedelta` import) and wire into `dashboard` ctx:

```python
def _dashboard_health(toko):
    """KPI kesehatan audit: agregat ringan dari summary 30 batch terakhir."""
    recent = list(ReconBatch.objects.filter(toko=toko).order_by("-id")[:30])
    selisih_total, ekor = 0, 0
    buckets = {"cocok": 0, "perlu_tinjau": 0, "tidak_cocok": 0}
    for b in recent:
        s = b.summary or {}
        sel = abs((s.get("dp") or {}).get("selisih") or 0) + abs((s.get("wd") or {}).get("selisih") or 0)
        selisih_total += sel
        bk = s.get("buckets") or {}
        if (bk.get("tidak_cocok") or 0) > 0:
            ekor += 1
        for k in buckets:
            buckets[k] += bk.get(k) or 0
    today = date.today()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    per_day = dict.fromkeys(days, 0)
    for b in recent:
        if b.date_to in per_day:
            s = b.summary or {}
            per_day[b.date_to] += abs((s.get("dp") or {}).get("selisih") or 0)
            per_day[b.date_to] += abs((s.get("wd") or {}).get("selisih") or 0)
    saran = _saran_tanggal(toko)
    return {
        "selisih_terbuka": selisih_total,
        "ekor_terbuka": ekor,
        "buckets_agg": buckets,
        "selisih_trend": [per_day[d] for d in days],
        "saran_tanggal": saran,
        "hari_tertunda": max((today - saran).days + 1, 0) if saran else 0,
    }
```

ctx: `"health": _dashboard_health(active),`.

Template `dashboard.html`: replace the 4 count-cards grid with the health strip; keep Tier-2 sections (source bars restyled with `.bucket-bar`-like track, runs list + `.bucket-bar` per run, uploads table):

```html
<div class="grid cols-4">
  <div class="card stat kpi-hero reveal">
    <div class="top"><span class="k">Selisih terbuka</span>
      <span class="ic {% if health.selisih_terbuka %}r{% else %}g{% endif %}"><svg class="ic" width="19" height="19"><use href="#i-circle-alert"/></svg></span></div>
    {% if health.selisih_terbuka %}
      <div class="v num amount" style="color:var(--bad)" data-count="{{ health.selisih_terbuka }}">{{ health.selisih_terbuka|intcomma }}</div>
    {% else %}
      <div class="v" style="color:var(--ok)">Balanced ✓</div>
    {% endif %}
    <svg class="spark" viewBox="0 0 120 32" aria-label="tren selisih 7 hari"><polyline points="{{ health.selisih_trend|sparkline_points }}"/></svg>
  </div>
  <div class="card stat reveal">
    <div class="top"><span class="k">Belum direkonsiliasi</span>
      <span class="ic a"><svg class="ic" width="19" height="19"><use href="#i-calendar-check"/></svg></span></div>
    <div class="v num" data-count="{{ health.hari_tertunda }}">{{ health.hari_tertunda }}</div>
    {% if health.saran_tanggal %}<a class="btn sm primary" href="{% url 'reconcile' %}">Rekonsiliasi {{ health.saran_tanggal|date:"d/m" }} →</a>{% endif %}
  </div>
  <div class="card stat reveal">
    <div class="top"><span class="k">Batch ekor terbuka</span>
      <span class="ic a"><svg class="ic" width="19" height="19"><use href="#i-rotate-cw"/></svg></span></div>
    <div class="v num" data-count="{{ health.ekor_terbuka }}">{{ health.ekor_terbuka }}</div>
  </div>
  <div class="card stat reveal">
    <div class="top"><span class="k">Kesehatan bucket</span></div>
    {% with b=health.buckets_agg %}{% with total=b.cocok|add:b.perlu_tinjau|add:b.tidak_cocok %}
    {% if total %}
    <div class="donut" style="--donut-stops:var(--ok-700) 0 {% widthratio b.cocok total 100 %}%,var(--warn-700) {% widthratio b.cocok total 100 %}% {% widthratio b.cocok|add:b.perlu_tinjau total 100 %}%,var(--bad-700) {% widthratio b.cocok|add:b.perlu_tinjau total 100 %}% 100%"></div>
    <div class="summary-line"><span class="badge ok plain">{{ b.cocok|intcomma }}</span><span class="badge warn plain">{{ b.perlu_tinjau|intcomma }}</span><span class="badge bad plain">{{ b.tidak_cocok|intcomma }}</span></div>
    {% else %}<p class="muted">Belum ada batch.</p>{% endif %}
    {% endwith %}{% endwith %}
  </div>
</div>
```
(`{% load web_extras %}` at top.) In "Rekonsiliasi Terkini" add under each run's badges:
```html
{% with s=run.summary %}{% with total=s.cocok|add:s.perlu_tinjau|add:s.tidak_cocok %}{% if total %}
<div class="bucket-bar" role="img" aria-label="{{ s.cocok }} cocok, {{ s.perlu_tinjau }} tinjau, {{ s.tidak_cocok }} tidak" style="margin-top:8px">
  <span class="s-ok" style="width:{% widthratio s.cocok total 100 %}%"></span><span class="s-warn" style="width:{% widthratio s.perlu_tinjau total 100 %}%"></span><span class="s-bad" style="width:{% widthratio s.tidak_cocok total 100 %}%"></span>
</div>{% endif %}{% endwith %}{% endwith %}
```
Source-bar fills switch `var(--grad)` → `var(--periwinkle)`.

- [ ] **Step 4: Tests pass**

```bash
python manage.py test web.tests_dashboard_health web.tests -v1 && python manage.py test
```

- [ ] **Step 5: Commit**

```bash
git add web/views.py web/templatetags/web_extras.py web/templates/web/dashboard.html web/tests_dashboard_health.py
git commit -m "feat(web): dashboard kesehatan audit — selisih terbuka, antrean hari, ekor, donat + sparkline"
```

---

### Task 6: Structured healing report (`_auto_rematch` + session stash + partial)

**Files:**
- Modify: `web/views.py:143-162` (`_auto_rematch`), `web/views.py:254-289` (upload commit branch), `web/views.py:475-489` (`rematch` view)
- Create: `web/templates/web/_healing_card.html`
- Modify: `web/templates/web/upload.html`, `web/templates/web/batch_detail.html` (render slot — full redesign of these templates lands in Tasks 7/9; here only the include hook + view wiring)
- Test: Create `web/tests_healing_report.py`

**Interfaces:**
- Consumes: `rematch_batch(batch, user=...) -> {"terpasang","cocok","perlu_tinjau","diperiksa"}`; `_rematch_candidates` (unchanged).
- Produces: `_auto_rematch(...) -> list[dict]` items `{level:"success"|"error", batch_pk:int, batch_no:int, terpasang:int, cocok:int, perlu_tinjau:int, selisih_before:int, selisih_after:int, error:str|None}`; session key `"healing_report"` (list, popped on next GET of upload/batch_detail); template partial `_healing_card.html` expecting `healing` list in context.

- [ ] **Step 1: Failing tests**

```python
# web/tests_healing_report.py
"""_auto_rematch mengembalikan data terstruktur; panel healing dirender dari session."""
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

# setUp: pakai pola factory yang sama dgn tests_dashboard_health (toko seed, admin login,
# batch dgn summary tidak_cocok>0 dan window kemarin). Baca tests_reconcile.py untuk
# helper pembuatan Transaction bila perlu upload uang sungguhan; di sini cukup mock.


class AutoRematchShapeTests(TestCase):
    def test_return_terstruktur(self):
        from web.views import _auto_rematch
        # siapkan batch kandidat + money_uploads dummy, mock rematch_batch:
        with patch("web.views.rematch_batch", return_value={"terpasang": 3, "cocok": 2, "perlu_tinjau": 1, "diperiksa": 5}):
            with patch("web.views._rematch_candidates", return_value=[(self.batch, 1)]):
                out = _auto_rematch(self.toko, ["dummy"], user=None)
        self.assertEqual(len(out), 1)
        d = out[0]
        self.assertEqual(d["level"], "success")
        self.assertEqual(d["terpasang"], 3)
        self.assertIn("selisih_before", d)
        self.assertIn("selisih_after", d)
        self.assertEqual(d["batch_pk"], self.batch.pk)

    def test_healing_panel_dirender_dari_session(self):
        s = self.client.session
        s["healing_report"] = [{"level": "success", "batch_pk": self.batch.pk, "batch_no": 1,
                                "terpasang": 3, "cocok": 2, "perlu_tinjau": 1,
                                "selisih_before": 4200, "selisih_after": 0}]
        s.save()
        r = self.client.get(reverse("upload"))
        self.assertContains(r, "tanggal aslinya")   # kalimat edukasi D-1
        self.assertContains(r, "Batch #1")
        # sekali render → habis
        r2 = self.client.get(reverse("upload"))
        self.assertNotContains(r2, "Batch #1 ")
```
(Fill `setUp` with the same seed/batch factory as Task 5's test file — copy it, keep values consistent.)

- [ ] **Step 2: Run — FAIL** (`_auto_rematch` returns tuples; no panel markup)

- [ ] **Step 3: Implement**

`_auto_rematch` — new body (docstring updated; message strings move into template):

```python
def _auto_rematch(toko, money_uploads, user=None):
    """Re-match otomatis batch kandidat setelah upload sumber uang — tanpa klik.

    Kembalikan list dict terstruktur (level, batch, delta selisih) untuk panel
    laporan penyembuhan. Error per-batch dilaporkan tapi tidak menggagalkan upload."""
    def _sel(b):
        s = b.summary or {}
        return abs((s.get("dp") or {}).get("selisih") or 0) + abs((s.get("wd") or {}).get("selisih") or 0)

    out = []
    for batch, no in _rematch_candidates(toko, money_uploads):
        before = _sel(batch)
        try:
            stats = rematch_batch(batch, user=user)
        except Exception as e:  # noqa: BLE001 - upload jangan ikut gagal
            out.append({"level": "error", "batch_pk": batch.pk, "batch_no": no, "error": str(e)})
            continue
        if stats["terpasang"]:
            batch.refresh_from_db()
            out.append({
                "level": "success", "batch_pk": batch.pk, "batch_no": no,
                "terpasang": stats["terpasang"], "cocok": stats["cocok"],
                "perlu_tinjau": stats["perlu_tinjau"],
                "selisih_before": before, "selisih_after": _sel(batch),
            })
    return out
```

Upload commit branch: replace the flash loop:
```python
        healing = _auto_rematch(active, money_uploads, user=request.user)
        for h in healing:
            if h["level"] == "error":
                messages.error(request, f"Re-match otomatis Batch #{h['batch_no']} gagal: {h['error']}")
        if any(h["level"] == "success" for h in healing):
            request.session["healing_report"] = [h for h in healing if h["level"] == "success"]
        return redirect("upload")
```
Upload GET/analyze renders: add to both `render` ctx dicts `"healing": request.session.pop("healing_report", None),` (pop = one-shot).

`rematch` view: same stash so manual re-match uses the same card:
```python
    stats = rematch_batch(batch, user=request.user)
    if stats["terpasang"]:
        batch.refresh_from_db()
        no = ReconBatch.objects.filter(toko=batch.toko, id__lte=batch.id).count()
        request.session["healing_report"] = [{
            "level": "success", "batch_pk": batch.pk, "batch_no": no,
            "terpasang": stats["terpasang"], "cocok": stats["cocok"],
            "perlu_tinjau": stats["perlu_tinjau"],
            "selisih_before": None, "selisih_after": None,
        }]
    else:
        messages.info(request, "Tidak ada baris baru yang bisa dipasangkan.")
    return redirect("batch_detail", pk=batch.pk)
```
(`selisih_before=None` → template hides the delta arrow; capture-before would require moving the read above `rematch_batch` — do that: `before = _sel_of(batch)` inline, mirroring `_auto_rematch`. Extract tiny module-level helper `_selisih_abs(batch)` used by both to stay DRY.)
`batch_detail` view ctx: add `"healing": request.session.pop("healing_report", None),`.

`_healing_card.html`:
```html
{% load humanize %}
{% if healing %}
<div class="healing-card reveal card">
  <div class="h-row"><h3><svg class="ic" width="16" height="16"><use href="#i-sparkles"/></svg> Batch lama tersembuhkan</h3></div>
  {% for h in healing %}
  <div class="heal-row">
    <a href="{% url 'batch_detail' h.batch_pk %}"><b>Batch #{{ h.batch_no }}</b></a>
    <span class="badge ok plain">+{{ h.cocok|intcomma }} cocok</span>
    {% if h.perlu_tinjau %}<span class="badge warn plain">+{{ h.perlu_tinjau|intcomma }} tinjau</span>{% endif %}
    {% if h.selisih_before is not None %}
    <span class="num amount">selisih <del class="faint">{{ h.selisih_before|intcomma }}</del> → {% if h.selisih_after == 0 %}<b style="color:var(--ok)">0 ✓</b>{% else %}<b>{{ h.selisih_after|intcomma }}</b>{% endif %}</span>
    {% endif %}
    <a class="btn sm ghost" href="{% url 'batch_detail' h.batch_pk %}">Lihat →</a>
  </div>
  {% endfor %}
  <p class="faint" style="font-size:12.5px;margin:10px 0 0">ℹ Uang yang baru diupload dicocokkan ke batch lama — selisih tercatat di <b>tanggal aslinya</b>, bukan hari ini.</p>
</div>
{% endif %}
```
Include `{% include "web/_healing_card.html" %}` at top of content block in `upload.html` and `batch_detail.html`.

- [ ] **Step 4: Tests pass + full suite**

```bash
python manage.py test web.tests_healing_report && python manage.py test
```

- [ ] **Step 5: Commit**

```bash
git add web/views.py web/templates/web/_healing_card.html web/templates/web/upload.html web/templates/web/batch_detail.html web/tests_healing_report.py
git commit -m "feat(web): laporan penyembuhan terstruktur — _auto_rematch dict + panel per-batch (delta selisih)"
```

---

### Task 7: Upload screen redesign

**Files:**
- Modify: `web/templates/web/upload.html`
- Test: `web/tests_upload.py`, `web/tests_upload_zip.py`, `web/tests_confirm_modal.py` stay green.

**Interfaces:**
- Consumes: `.file-row/.file-chip/.conf-meter/.pw-lock/.summary-line` CSS (Task 3), sprite icons.
- Produces: same form contracts; new JS keeps globals/function names local (IIFE unchanged pattern).

Changes (keep the accumulator/folder-traversal JS intact; only `render()` and markup change):

1. Dropzone: icon via sprite; dragover copy swap (`data-idle-copy`/`data-over-copy`, JS toggles textContent on dragenter/leave — 4 lines added).
2. `render()` builds `.file-row` list into `#flist` (now a `<div class="file-list">`): per file — chip class by extension (`t-xlsx/t-csv/t-pdf/t-zip/t-skip` via `_is_junk`-mirroring ext check in JS), name + `webkitRelativePath` faint second line, size (`(f.size/1048576).toFixed(1)+' MB'` or KB), remove button that rebuilds `DataTransfer`:
```js
function hapusIdx(i){
  var keep=new DataTransfer();
  [].forEach.call(store.files,function(f,idx){ if(idx!==i) keep.items.add(f); });
  store=keep; render();
}
```
Button label `Analisa {n} File →` updated inside `render()`. GSAP row-enter tween (`gsap.from(row,{height:0,opacity:0,y:-6,duration:.28})`) guarded by `window.gsap && !reduce`.
3. Analyze submit → busy state: `btn.disabled=true; btn.textContent='Menganalisa…'` on form `submit` listener.
4. Preview table: add above it `<p class="summary-line">{{ n_siap }} siap · {{ n_cek }} perlu dicek · {{ n_pwd }} perlu password</p>` — compute in template with `{% widthratio %}`-free approach: simplest is three `{% for %}` counters via `{{ preview|length }}` and template filter? NO — compute in view is cleaner: in `upload` analyze branch add
```python
        n_cek = sum(1 for p in preview if p["needs_confirm"])
        n_pwd = sum(1 for p in preview if p["needs_password"])
        # ctx: "n_siap": len(preview) - n_cek - n_pwd, "n_cek": n_cek, "n_pwd": n_pwd,
```
Rows: `{% if p.needs_confirm %}class="needs-confirm"{% endif %}`; confidence cell:
```html
<td><span class="conf-meter"><i class="{% if p.confidence >= 80 %}hi{% elif p.confidence >= 60 %}mid{% else %}lo{% endif %}" style="width:{{ p.confidence }}%"></i></span> <span class="num">{{ p.confidence }}%</span></td>
```
Password cell: keep EXACT `readonly tabindex="-1"` attrs for non-password rows (test asserts); needs_password rows wrapped `<span class="pw-lock"><svg class="ic" width="14" height="14"><use href="#i-lock"/></svg><input …></span>`.
5. Riwayat table + bulk delete: markup unchanged except badges/buttons pick up new CSS automatically; delete buttons get `<use href="#i-trash-2"/>` icons.

- [ ] **Step 1: Apply template + small view counters**
- [ ] **Step 2: Tests**

```bash
python manage.py test web.tests_upload web.tests_upload_zip web.tests_confirm_modal && python manage.py test
```

- [ ] **Step 3: Commit**

```bash
git add web/templates/web/upload.html web/views.py
git commit -m "feat(web): upload — daftar file staged (hapus per baris), meter keyakinan, status sibuk"
```

---

### Task 8: Reconcile screen redesign

**Files:**
- Modify: `web/templates/web/reconcile.html`
- Test: `web/tests_reconcile_ux.py`, `web/tests_reconcile.py`, `web/tests_batch_filter.py` stay green.

Changes:
1. Right card: date fields wrapped in `.date-hero` when `tanggal_disarankan` with badge `✨ disarankan`; button `▶ Jalankan Rekonsiliasi` gets `class="btn primary block"` + `id="jalankan-btn"`.
2. Extend existing `sync()`:
```js
  var btn=document.getElementById('jalankan-btn'), asli=btn.textContent;
  function sync(){
    var kosong=!df.value && !dt.value;
    if(kosong){ f.setAttribute('data-confirm','Tanggal kosong = rekonsiliasi SEMUA data aktif (semua tanggal digabung jadi satu batch). Lanjutkan?'); }
    else { f.removeAttribute('data-confirm'); delete f.dataset.confirmed; }
    btn.classList.toggle('danger', kosong);
    btn.classList.toggle('primary', !kosong);
    btn.textContent = kosong ? '⚠ Jalankan SEMUA data' : asli;
  }
```
3. Kelengkapan rows: status dot badges as-is; disabled checkboxes get `title="Sumber kosong — upload dulu untuk mengaktifkan"`.
4. Live recap line under button: `<p class="faint" id="recap"></p>` + JS counting `input[name^=inc_]:checked` (listen `change` on document) and echoing date.
5. Riwayat Batch table: add bucket-bar column? NO (summary lacks per-batch cocok/tinjau/tidak triple? it has `b.summary.buckets` — yes): add `.bucket-bar` mini in Cocok column using `b.summary.buckets` triple, same snippet as dashboard.

- [ ] **Step 1: Apply**
- [ ] **Step 2: Tests**

```bash
python manage.py test web.tests_reconcile_ux web.tests_reconcile web.tests_batch_filter && python manage.py test
```
(`tests_reconcile_ux` asserts the toggle script exists — keep `data-confirm` string identical.)

- [ ] **Step 3: Commit**

```bash
git add web/templates/web/reconcile.html
git commit -m "feat(web): reconcile — panel tanggal hero, tombol bahaya saat tanggal kosong, rekap live"
```

---

### Task 9: run_detail htmx partials + table upgrades

**Files:**
- Create: `web/templates/web/_run_table.html`
- Modify: `web/templates/web/run_detail.html`, `web/templates/web/_result_row.html`, `web/views.py:493-540`
- Test: Create `web/tests_run_partial.py`; `web/tests_run_channel_filter.py`, `web/tests_run_columns.py`, `web/tests_consume_ui.py` stay green.

**Interfaces:**
- Produces: `_run_table.html` = tabs-state-independent fragment `<div id="result-table">…table + pager…</div>`; view returns it alone when `HX-Request` header present.

- [ ] **Step 1: Failing test**

```python
# web/tests_run_partial.py
"""Filter bucket/channel run_detail via htmx: HX-Request → fragmen tabel saja."""
from django.urls import reverse
# setUp: reuse pola tests_run_channel_filter.py (baca file itu, salin factory run+results)


class RunPartialTests(...):
    def test_hx_request_dapat_fragmen(self):
        url = reverse("run_detail", args=[self.run.pk])
        r = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertContains(r, 'id="result-table"')
        self.assertNotContains(r, "<aside")          # tanpa shell
        self.assertNotContains(r, "page-head")

    def test_tanpa_hx_tetap_full_page(self):
        r = self.client.get(reverse("run_detail", args=[self.run.pk]))
        self.assertContains(r, "<aside")
        self.assertContains(r, 'id="result-table"')
```

- [ ] **Step 2: FAIL run**
- [ ] **Step 3: Implement**

View, before final `render`:
```python
    if request.headers.get("HX-Request"):
        return render(request, "web/_run_table.html", ctx)
```
`_run_table.html` = moved card+table+pager markup from `run_detail.html`, wrapped in `<div id="result-table">`; pager links become `hx-get` same URL + `hx-target="#result-table" hx-swap="outerHTML" hx-push-url="true"`. `run_detail.html` includes it (`{% include "web/_run_table.html" %}`) and converts both tab strips to:
```html
<a hx-get="?bucket=cocok{% if channel %}&channel={{ channel|urlencode }}{% endif %}" hx-target="#result-table" hx-swap="outerHTML" hx-push-url="true" href="?bucket=cocok..." class="...">Cocok</a>
```
(keep `href` fallback for no-JS). Add `hx-indicator="#result-table"` on the tab container. Table gets `class="sticky-col"`. KPI stat cards restyled (ok/warn/bad `.v` colors already tokened).
`_result_row.html`: status cell → icon-pill + label:
```html
<td><span class="icon-pill {% if r.bucket == 'cocok' %}ok{% elif r.bucket == 'perlu_tinjau' %}warn{% else %}bad{% endif %}"><svg class="ic" width="13" height="13"><use href="{% if r.bucket == 'cocok' %}#i-check{% elif r.bucket == 'perlu_tinjau' %}#i-flag{% else %}#i-x{% endif %}"/></svg></span> <span class="badge {% if r.bucket == 'cocok' %}ok{% elif r.bucket == 'perlu_tinjau' %}warn{% else %}bad{% endif %} plain">{{ r.get_bucket_display }}</span></td>
```
Action buttons wrapped `<div class="row-actions" style="display:flex;gap:6px;justify-content:center">` (hover/focus opacity). `hx-headers` CSRF stays.
CHECK: `tests_run_columns.py`/`tests_consume_ui.py` may assert old status markup — run and adapt assertions ONLY if they tested styling, never behavior.

- [ ] **Step 4: Tests pass + full suite**

```bash
python manage.py test web.tests_run_partial web.tests_run_channel_filter web.tests_run_columns web.tests_consume_ui && python manage.py test
```

- [ ] **Step 5: Commit**

```bash
git add web/templates/web/_run_table.html web/templates/web/run_detail.html web/templates/web/_result_row.html web/views.py web/tests_run_partial.py
git commit -m "feat(web): run_detail — swap parsial htmx (push-url), kolom status beku, aksi hover"
```

---

### Task 10: batch_detail redesign

**Files:**
- Modify: `web/templates/web/batch_detail.html`
- Test: `web/tests_polish.py`, `web/tests_batch_number.py`, `web/tests_delete.py` stay green.

Changes:
1. Healing card include already at top (Task 6).
2. Bucket summary card: add `.bucket-bar` (3 segments from `s.buckets`, same snippet), badges beneath.
3. DP/WD cards: amounts get `class="num amount"` (mono); selisih row keeps badge logic; add `.h-row` headers with `landmark`/`wallet` icons.
4. Re-match button: stays a normal POST form (redirect returns with healing card — Task 6 wired it); label `<svg class="ic"…><use href="#i-rotate-cw"/></svg> Re-match`.
5. Relasi table: per-run `.bucket-bar` under the relation name; Detail/Excel buttons iconed (`chevron-right`, `download`).

- [ ] **Step 1: Apply**
- [ ] **Step 2: Tests**

```bash
python manage.py test web.tests_polish web.tests_batch_number web.tests_delete && python manage.py test
```

- [ ] **Step 3: Commit**

```bash
git add web/templates/web/batch_detail.html
git commit -m "feat(web): batch_detail — bucket-bar, angka mono, kartu penyembuhan"
```

---

### Task 11: Whole-app smoke + visual QA

**Files:** none new (fixes as found)

- [ ] **Step 1: Full suite**

```bash
python manage.py test
```
Expected: all pass.

- [ ] **Step 2: Manual smoke with real dev DB**

```bash
python manage.py runserver 8137 --noreload &
```
Screenshot/eyeball every screen (dashboard, upload idle+staged+preview, reconcile, batch_detail, run_detail each bucket tab, transactions, kelola/toko, kelola/users, login) — transactions/kelola must remain *usable* under the new shell (old content classes all exist in app.css). Use browser tooling (gstack-browse) or manual. Checklist:
- [ ] No unstyled element / missing icon (broken `<use>` shows empty box)
- [ ] Sticky thead + frozen col scroll correctly inside `.twrap`
- [ ] Confirm modal opens/cancels/OK-submits (delete upload, empty-date reconcile)
- [ ] Toko reminder dialog opens on login, closes
- [ ] htmx tab swap keeps URL (back button works), review ✓/⚑ row swap intact
- [ ] Reduced-motion: toggle OS setting → no GSAP/count-up
- [ ] Kill server after.

- [ ] **Step 3: Commit fixes**

```bash
git add -A && git commit -m "fix(web): polish hasil smoke visual"
```

---

### Task 12: Staging deploy (Railway)

- [ ] **Step 1: Push branch** (worktree branch, e.g. `feat/ui-makeover-v1`) to origin.
- [ ] **Step 2: Deploy** — per CLAUDE.md staging goes via `railway up` from the working tree (volume at `/app/media`, `numReplicas=1`). Deploy from the worktree to the staging service (or a fresh service if told to keep current staging intact) and verify `collectstatic` hashed `app.css`.
- [ ] **Step 3: Verify live** — login, dashboard health strip renders, upload analyze works (staging volume), report URL to user.

---

## Self-Review Notes

- Spec coverage: shell(T4), tokens(T3), icons(T2), vendor(T1), dashboard(T5), healing(T6), upload(T7), reconcile(T8), run_detail(T9), batch_detail(T10), smoke(T11), deploy(T12). Spec's "hx-post in-place re-match" implemented as POST→redirect + session healing card (documented deviation: avoids stale summary numbers; same UX outcome).
- Types consistent: `healing` list[dict] keys identical across `_auto_rematch`, `rematch`, `_healing_card.html`, tests.
- Test factories in T5/T6/T9 must be adapted to real model fields — step text says to read the neighboring test modules first; assertion values are the contract.
