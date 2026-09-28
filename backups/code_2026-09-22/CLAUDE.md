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
    import paths (Excel/CSV) for box records and customer invoices, each following
    a **smart-merge convention**: insert new rows, fill only currently-NULL fields
    on existing rows, never overwrite a real value.
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
   Unallocated` — every dollar FedEx ever billed lands in exactly one bucket, never
   two, never zero. `compute_fedex_reconciliation()` computes all three from the
   same pass so this can't drift.
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

## Conventions and known gotchas

- **Derived-only computation**: allocation/enrichment results (Multi-box Duty
  split, Actual/Excluded/Unallocated classification, etc.) are never written back
  to `boxes` — always recomputed at display time from raw columns. This keeps the
  raw historical record intact and Excel/NeXa reconcilable.
- **AG-Grid row identity**: any grid whose underlying dataframe can change shape
  between reruns (filtering, selecting/deselecting an invoice, etc.) must set
  `getRowId` (by a real DB `id`/unique key) in `render_excel_grid()` /
  `render_invoice_type_grid()`. Without it, ag-grid tracks rows by position and a
  size change can misattribute a stale checkbox state to the wrong row — this
  caused a real bug where unchecking a box's Case checkbox silently failed. Also
  strip the pinned TOTAL row's row(s) — they have no `id` — before any
  `.astype(int)` cast on the returned grid data.
- **AG-Grid + Streamlit checkbox round-trips**: `tracking_id` and other
  purely-numeric-looking TEXT columns can come back from the JS round-trip
  coerced to a different type (e.g. int) — normalize explicitly
  (`.astype(str)`/`.astype(int)` as appropriate) before comparing across reruns.
- **`fedex_total_cost` is a mixed-type column** (`float` or the literal string
  `"Bekliyor"`) — this is intentional (see financial model above) but means naive
  `pd.to_numeric` / Arrow serialization will choke on it; existing code already
  guards this (`errors="coerce"`), preserve that pattern in new code that touches
  the column.
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
