# NeXa — Finance & Customs Analyzer

NeXa is a local Streamlit application for LOGIWIX LLC / ENRETAG LLC that reconciles
FedEx shipping/customs invoices against customer billing to produce accurate
profitability numbers, and tracks disputes and refunds. It replaced a hand-built,
formula-driven Excel workbook that the business still keeps as a parallel export
(see "Excel companion" below) — NeXa is now the source of truth, not the Excel file.

The primary user (Cagla Arslan) is non-technical. UI copy, code, comments, and
commit messages are in English; conversation with the user is in Turkish.

## Running it

```
cd FinanceCustomsAnalyzer
.\venv\Scripts\python.exe -m streamlit run app.py --server.port 8501 --server.headless true
```

`Start NeXa.bat` does the same for the user directly. The app is a single Streamlit
process — after editing any `core/*.py` module, the running server must be **fully
restarted** (stop + relaunch), not just refreshed in the browser: Streamlit's
hot-reload does not reliably pick up submodule changes. Pure `app.py` edits usually
hot-reload on a browser refresh alone.

## Architecture

- **`app.py`** (~2,800 lines) — the entire UI. One Streamlit script, multi-page via
  a sidebar `st.radio` driven by `NAV_PAGES` (list of `(key, label)`) and
  `NAV_LABEL_TO_KEY`. `CORE_NAV_KEYS` controls which pages show by default; the
  "Show all pages" sidebar toggle reveals the rest. Each page is one
  `if current_page == "...":` / `elif` branch in a single long dispatch chain.
  Shared grid rendering goes through two helpers: `render_excel_grid()` (the
  full-featured AG-Grid wrapper — filters, currency/percent formatting, pinned
  selection-aware TOTAL row, checkbox columns, alert renderers) and the lighter
  `render_invoice_type_grid()` (single-select invoice lookup lists).
- **`core/`** — all business logic and persistence, framework-agnostic (no
  Streamlit imports), so it can be unit-tested and reused outside the UI:
  - `database.py` — SQLite connection + schema. `init_db()` creates tables with
    `CREATE TABLE IF NOT EXISTS`; schema evolution happens via `_ensure_columns()`
    (idempotent `ALTER TABLE ADD COLUMN`), not migrations. Every module that
    touches the DB calls `init_db(connection)` first.
  - `analytics.py` — the financial engine. `enrich_boxes_for_display()` is the
    base display-only enrichment (Multi-box Duty/Shipping allocation, waiting-period
    logic); `compute_profit_calculation()` layers the Actual-only P&L model on top
    (see "Financial model" below); `compute_fedex_reconciliation()` /
    `compute_customer_invoice_reconciliation()` / `compute_customer_profitability()`
    build on that. Benchmark/above-average/data-quality checks (`compute_benchmarks`,
    `compute_above_average_boxes`, `compute_data_issues`) are the older,
    still-live rule set ported from the original Excel's "Ortalamalar" /
    "Ortalama Üzeri Faturalar" / "Veri Kontrolü" sheets.
  - `ingest.py` — FedEx invoice PDF ingestion (via `pdf_parser.py`), including the
    multi-box group-amount-splitting logic.
  - `box_import.py`, `customer_invoice_import.py`, `legacy_import.py` — bulk
    import paths (Excel/CSV) for box records and customer invoices. None of them
    ever overwrites a real value, but they differ: `box_import.import_boxes`
    **skips** a row whose tracking_id already exists (it does *not* fill NULL
    fields — so a minimal box row created earlier by PDF ingestion never gets its
    customer/country filled by a later box import); `customer_invoice_import`
    appends lines and then fills a box's fees only while *both* fee columns are
    NULL; `legacy_import` functions **DELETE and replace** whole tables (not
    reachable from the UI — script-only, never run them on the live DB casually).
  - `review.py` — invoice approval status (`invoice_review` table) and the dispute
    (`disputed_items`) lifecycle: `add_disputed_items` (upsert, reactivates a
    cancelled dispute), `cancel_disputed_items` (soft-cancel with optional reason,
    keeps history), `remove_disputed_item`/`remove_disputed_invoice` (hard delete,
    used only for the Boxes-page Case-checkbox uncheck path).
  - `refunds.py` — the Refund Management module (`refunds` table), independent of
    the FedEx dispute workflow: disputes claw back money *from FedEx*; refunds give
    money *back to a customer*.
  - `data_cleanup.py` — one-off/reusable data-quality fixers (shipment-type
    canonicalization, etc.), not part of the request/response cycle.
  - `config.py` — business constants: `INVOICE_WAITING_PERIOD_DAYS` (14),
    `ABOVE_AVERAGE_THRESHOLD_PERCENT` (0.20), `HIGH_INVOICE_WARNING_USD` (750),
    `MINIMUM_SAMPLE_SIZE_FOR_AVERAGE` (3), `NO_DUTY_COUNTRIES` ({US, AU}),
    `CANADA_SHIPPING_RATE_CARD` (negotiated per-box rate by Multi group size).
- **`data/finance_customs.db`** — the one SQLite database. Tables: `boxes` (the
  central fact table, one row per physical box/shipment), `shipment_charges` (raw
  per-line FedEx PDF charges), `invoices` (FedEx invoice headers), `products`,
  `customer_invoices` (what was billed to end customers), `invoice_review`,
  `disputed_items`, `refunds`, `legacy_fedex_invoice_raw`.

## Financial model (read this before touching money math)

Fixed with the user on 2026-09-19 — **do not reintroduce an "estimated/accrued
cost" into the Actual profit numbers**, that was deliberately rejected:

1. **No customer invoice on that box → the box is entirely excluded** from
   revenue, cost, and profit (all zero) — but it is never deleted, only marked
   `revenue_status="Not Invoiced"` / `profit_calculation_status="Excluded - Customer
   Invoice Missing"` and stays visible everywhere (Dashboard, Reconciliation).
   A box whose fee columns are both a literal `0.0` (not NULL) is treated the same
   as "no invoice" — a real invoice here is never actually $0 (see
   `compute_profit_calculation`'s `has_customer_invoice` check).
2. **Customer invoice present, FedEx invoice not yet received → still included**,
   at `Revenue = customer invoice`, `FedEx Cost = 0`, `Profit = Revenue`. The
   14-day waiting window (`INVOICE_WAITING_PERIOD_DAYS`) only relabels
   `fedex_status` between `"Invoice Expected"` and `"Invoice Overdue"` — it never
   zeroes, estimates, or otherwise changes the cost.
3. **Both present → real numbers**, `Profit = Revenue - Actual FedEx Cost`. As soon
   as a real FedEx invoice lands, it replaces the $0 placeholder automatically on
   the next computation — nothing is cached forward.
4. **FedEx cost on a box with no customer invoice** is real money the company
   spent and must never disappear from the books — it is tracked separately as
   `fedex_cost_excluded_no_invoice`, visible in FedEx Reconciliation, but
   deliberately kept out of that box's own profit.
5. **FedEx invoice line with no matching box at all** → `Unallocated FedEx Cost`
   (`compute_unallocated_fedex`), tracked and shown, never silently dropped.
6. **Reconciliation identity that must always hold:**
   `Total FedEx Invoice == FedEx Cost Included + Excluded (no customer invoice) +
   Unallocated + Unmatched Second Invoice` — every dollar FedEx ever billed lands
   in exactly one of these four buckets, never two, never zero.
   `compute_fedex_reconciliation()` computes `total_fedex_invoice` as the *sum of
   the four buckets* (true by construction), not independently from
   `shipment_charges` — that was tried while fixing H-1 (2026-09-22) and reverted,
   because `shipment_charges` only reflects PDF-ingested costs: ~845 boxes
   ($103k+ raw) carry a real FedEx cost entered through other paths (manual/bulk
   historical import, the legacy Excel migration) with no `shipment_charges` row
   at all for their tracking_id. `unmatched_second_invoice`
   (`compute_unmatched_second_invoice`) is the fourth bucket, added 2026-09-22 for
   H-1: a real charge line whose tracking_id matches a box but whose
   invoice_number differs from the one already recorded on that box for the same
   charge type (Duty/Shipping) — a second/adjustment invoice that the box-sync
   logic correctly refuses to overwrite, so its money used to vanish from every
   bucket instead of landing in one.
7. **Excel and NeXa must always agree.** Excel's `Kutular`/`Dashboard` sheets are
   regenerated *from* NeXa's SQLite DB via one-off scripts (not checked into this
   repo — built ad hoc in the scratchpad when asked), using these exact same
   `core/analytics.py` functions, so the two can never silently diverge. If the
   user has hand-edited the live Excel file (they do this — see below), treat
   *that* edited file as authoritative for whatever they changed and regenerate
   the Dashboard sheet from its live data rather than overwriting their edits from
   the DB.

The Dashboard, Reconciliation, and Customer Profitability sections of `app.py` are
all built on `compute_profit_calculation()`'s output (`revenue`, `actual_fedex_cost`,
`fedex_cost_excluded_no_invoice`, `actual_profit`, `revenue_status`, `fedex_status`,
`profit_calculation_status`). The **older** `enrich_boxes_for_display()` fields
(`fedex_total_cost` as `"Bekliyor"` string / forced-zero, `profit_loss`) are still
used by the Boxes/Above-Average/Disputes pages' own logic (Case checkboxes, alert
flags, benchmarks) — don't conflate the two models when editing either.

## Tests

`pytest` (see `requirements-dev.txt`) runs `tests/` — pure-function tests of the
financial model plus a read-only invariant check against the live DB (opened with
`mode=ro`, skipped if absent). Tests marked `xfail(strict=True)` pin down known,
not-yet-fixed bugs from `docs/NEXA_HEALTH_REPORT.md`; fixing one makes its test
fail until the marker is removed — that is intentional.

```
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\venv\Scripts\python.exe -m pytest tests
```

Note: `compute_fedex_reconciliation`'s `total_fedex_invoice` is the *sum of its
four buckets* (see Financial model item 6), so the identity holds by
construction — it does not by itself prove that every billed charge line
landed in a bucket.

## Excel companion

The user keeps `Enretag Kar&Zarar.xlsx` (project root; filename changes over time,
check current directory listing) as a parallel view, sometimes hand-edited directly
(row deletions, renames) rather than through NeXa. When asked to update it: read the
*live* file first, diff for manual edits before regenerating anything, and always
back up (`<name>_backup_<timestamp>.xlsx`) before overwriting. Its `Kutular` sheet
carries the same 30-column shape the DB produces (original legacy columns + the
Actual-only financial columns from item 6 below); its Dashboard sheet embeds a
formula-driven (SUMIFS/COUNTIFS, single filter-cell) customer P&L pivot that mirrors
the NeXa Reconciliation/Customer Profitability numbers exactly.

`docs/proje-planlama/` contains a separate, **not-implemented** planning package for
a hypothetical standalone "Enretag Finans Platformu" that would consume a read-only
NeXa data export — this is an exploratory proposal, not part of NeXa's own
architecture or roadmap. Don't treat it as a description of NeXa itself.

## Development rules

- Understand before you improve — a rule that looks like a shortcut (a mixed-type
  column, a skip-vs-fill import distinction, a hardcoded threshold) is usually an
  encoded business decision, not an oversight. Confirm why before changing it.
- Prefer the smallest safe change over a rewrite. Reuse existing helpers
  (`render_excel_grid`, `enrich_boxes_for_display`, `compute_profit_calculation`,
  `core.dates.parse_dates`) rather than introducing a parallel pattern.
- Never change financial *meaning* (a formula, a classification rule, an
  inclusion/exclusion criterion) without explicit user approval, and always
  present: current calculation → current business rule → new proposal →
  affected records (queried, not estimated) → risk → test method.
- Never run `DROP`, `TRUNCATE`, a bulk/unscoped `DELETE`, a destructive
  migration, or touch historical financial data without the user approving that
  *specific* operation after seeing its exact blast radius (row count, dollar
  amount, affected entities) — a general plan approval does not cover this.
- Take a fresh read of a file before editing it if there's any chance another
  session/process has touched this project since you last read it (this project
  has, in practice, been worked on by more than one Claude session in parallel —
  see the note at the end of this file).

## Testing rules

See "Tests" above for how to run the suite. In addition: don't claim something
was tested if it wasn't actually run or checked, and don't claim something was
fixed if the file wasn't actually changed — say plainly when a check is a manual
inspection rather than an automated test. `xfail(strict=True)` tests intentionally
pin down known, not-yet-approved bugs; a fix should make its test start failing
(remove the marker then), not be treated as passing-therefore-irrelevant.

## UI/UX principles

NeXa is a warehouse operations tool used at volume, by one non-technical person,
against a live SQLite database with thousands of rows per screen. Design and
review decisions should optimize for: fast task completion, easy data-finding,
low mis-click risk (especially on money-moving actions — Approve, Cancel Case,
Add Refund), clear status at a glance, consistency across screens, and
learnability — not decoration. Concretely:

- The same function (a save action, a status badge, a warning indicator, a
  filter row) should look and behave identically everywhere it appears. A
  screen-by-screen audit should specifically hunt for places this has drifted.
- Information density should serve fast scanning at this data volume, not just
  "fit more on screen" — column widths, row height, and filter placement matter
  more here than in a typical low-volume business app.
- Don't copy another product's design wholesale; NeXa's own design system (navy
  `#1F4E79` primary, the existing AG-Grid/metric-card conventions) should be
  made explicit and extended deliberately, not replaced.
- A destructive or money-moving action should require confirmation proportional
  to how hard it is to undo (compare: soft `cancel_disputed_items` vs. hard
  `remove_disputed_item` — the two are not equally reversible and shouldn't
  necessarily require the same confirmation weight).

## Professionalization workflow

When asked to audit, review, harden, or "professionalize" NeXa as a whole (as
opposed to a single already-diagnosed fix), use the `nexa-professionalizer`
agent (`.claude/agents/nexa-professionalizer.md`) and its
`nexa-professionalization` skill (`.claude/skills/nexa-professionalization/SKILL.md`).
Short version of the workflow they define: **AUDIT** (read-only, findings only)
→ **PLAN** (Problem/Evidence/Root Cause/Impact/Risk/Proposed Solution/Files/Tests,
presented for approval) → **IMPLEMENT** (only the approved scope) → **TEST** →
**REPORT**. A full professionalization pass works through Discovery, UX/UI Audit,
Design System, Navigation & IA, Critical Screens, Component Consistency, Code
Quality, Database & Business Logic, Testing, Performance, Security, and Final
Product Review, one phase at a time, reporting after each.

## Conventions and known gotchas

- **Derived-only computation**: allocation/enrichment results (Multi-box Duty
  split, Actual/Excluded/Unallocated classification, etc.) are never written back
  to `boxes` — always recomputed at display time from raw columns. This keeps the
  raw historical record intact and Excel/NeXa reconcilable.
- **AG-Grid row identity**: any grid whose underlying dataframe can change shape
  between reruns (filtering, selecting/deselecting an invoice, etc.) must set
  `getRowId` (by a real DB `id`/unique key, or `invoice_no` when the grid has no
  `id` column) in `render_excel_grid()` / `render_invoice_type_grid()`. Without
  it, ag-grid tracks rows by position and a size change can misattribute a stale
  checkbox state to the wrong row — this caused a real bug where unchecking a
  box's Case checkbox silently failed, and a second, more serious one (found and
  fixed 2026-09-22): Disputes' Cases grid (`disputes_case_review_grid`) had no
  `id` column and its row set shrinks every time a case gets Approved (then
  `st.rerun()`s) — without `getRowId`, a stale 'Approved: true' could land on
  whatever row slid into that position after the shrink, including a row with a
  NULL `invoice_no`. `set_invoice_review_status`'s `ON CONFLICT(invoice_no)`
  never matches two NULLs in SQLite, so every one of those inserted a fresh
  garbage row instead of updating — **16,254 NULL-`invoice_no` rows** had
  accumulated in `invoice_review` by the time this was found. Fixed by (1) giving
  `render_excel_grid` a `getRowId` fallback keyed on `invoice_no` when there's no
  `id` column, and (2) a defensive guard in both `apply_approved_checkbox` (app.py)
  and `set_invoice_review_status` (core/review.py) that skips a NULL/NaN
  `invoice_no` outright — belt-and-suspenders, since either fix alone would have
  been enough. The 16,254 garbage rows themselves are still sitting in the live
  DB, cleanup pending the user's explicit approval (bulk DELETE — see Database
  safety above). Also strip the pinned TOTAL row's row(s) — they have no `id` —
  before any `.astype(int)` cast on the returned grid data.
- **AG-Grid + Streamlit checkbox round-trips**: `tracking_id` and other
  purely-numeric-looking TEXT columns can come back from the JS round-trip
  coerced to a different type (e.g. int) — normalize explicitly
  (`.astype(str)`/`.astype(int)` as appropriate) before comparing across reruns.
- **`fedex_total_cost` is a mixed-type column** (`float` or the literal string
  `"Bekliyor"`) — this is intentional (see financial model above) but means naive
  `pd.to_numeric` / Arrow serialization will choke on it; existing code already
  guards this (`errors="coerce"`), preserve that pattern in new code that touches
  the column.
- **Dates: always parse through `core.dates.parse_dates()`**, never a bare
  `pd.to_datetime(..., errors="coerce")` — that infers one format from the first
  value and silently NaTs the rest (bug C-1, fixed 2026-09-22: 741 boxes had
  fallen out of every date filter). Slash dates are month/day/year (user-confirmed).
  Canonical stored shapes: `boxes.ship_date` = `YYYY-MM-DD 00:00:00`,
  `customer_invoices` dates = QuickBooks `M/D/YYYY`; all write paths (PDF ingest,
  box import/manual add, customer/MOSAIC import, Data Quality edit) normalize via
  `to_box_ship_date()` / `to_customer_invoice_date()`. One-off rewrite of existing
  rows: `scripts/data_migration/normalize_dates.py` (dry run by default).
  Applied to the live DB on 2026-09-22 after the user's approval (backup:
  `data/backups/finance_customs_backup_20260922_202302_before_date_normalize.db`).
- **Never write the live SQLite file in place from the Cowork VM mount**: the mount
  forbids deleting files, so SQLite can't remove its `-journal` at commit ("disk I/O
  error") and leaves a hot journal behind. Instead: copy the DB to VM scratch, run
  the write there, verify, check the live file's hash is unchanged, then `cp` the
  result back over it (and make sure no `-journal` sits next to it first).
- **Customer short-code canonicalization** (e.g. `"ZL"` → `"ZYTARA LLC"`) is a
  user-confirmed mapping table, built up over many rounds — never guess or invent
  a target name for an unmapped code (`PP`, `ENRESHIP` are still deliberately
  unmapped). A `"-RETURN"`-suffixed code is a distinct entity from its base code
  unless the user explicitly says to merge it.
- **Never overwrite a real value with a blank/placeholder during import** — the
  `"Manuel Order"` box-number convention is only used when the user explicitly
  says a record's box number is genuinely missing, never inferred.
- **Destructive DB actions** (bulk DELETE, dropping/cancelling many disputes,
  deleting boxes) always get a blast-radius investigation (exact row count, dollar
  amount, affected entities) presented to the user *before* running, even when the
  requested criteria are unambiguous — this project's history includes several
  large bulk actions (a 36-group invoice backfill, a 1,170-dispute time-barred
  cancellation) that were only executed after the user saw the numbers and said
  "onaylıyorum" (approved).
- **`.streamlit/config.toml`'s `[server] address` must be `"127.0.0.1"`, not
  `"localhost"`** (fixed 2026-09-22, right after M-3 introduced this): on this
  Windows machine, binding to the hostname `"localhost"` leaves the browser's
  own DNS resolution free to pick a different address (IPv6 `::1` vs. IPv4
  `127.0.0.1`) than the one Streamlit actually bound, which intermittently
  refused the connection / dropped the `_stcore/stream` WebSocket. The literal
  IP has the same network-exposure protection as `"localhost"` (still only
  reachable from this machine) without the resolution ambiguity.
- **A row id read out of a pandas DataFrame is a `numpy.int64`, not a plain
  `int` — cast it before using it in a sqlite3 `WHERE id = ?` bind.** sqlite3
  doesn't recognize `numpy.int64` as an INTEGER parameter; it neither raises
  nor matches any row, so the `UPDATE`/`DELETE` silently affects zero rows and
  commits successfully with nothing changed. Found 2026-09-22 while fixing M-5:
  the Data Quality page's "Edit box" form had never actually saved anything (no
  error, no effect) because `update_box_fields` received `selected_issue["id"]`
  un-cast. Fixed by casting inside `update_box_fields` itself
  (`int(box_id)`), so every caller is protected, not just this one call site.
  The Refund Management delete path already did this correctly
  (`delete_refund(int(row["id"]))`) — that's the pattern to follow anywhere
  else a DataFrame-sourced id reaches a bind parameter.
