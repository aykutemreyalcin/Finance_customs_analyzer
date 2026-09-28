---
name: nexa-professionalization
description: Detailed audit checklist and methodology for turning NeXa (Finance & Customs Analyzer) into a coherent, production-quality warehouse management product — UI/UX and design-system consistency, navigation/information architecture, architecture, code quality, database structure, business logic, financial calculation integrity, security, performance, and technical debt. Load this before auditing, reviewing, or redesigning any part of NeXa.
---

# NeXa Professionalization — Methodology

This is the "how to analyze and professionalize" companion to the
`nexa-professionalizer` agent's "who, when, and under what constraints." Read
`CLAUDE.md` at the project root first — architecture and financial-model facts
live there; this skill won't repeat them, only reference them.

Treat the checklist below as a menu scoped to what was actually asked, but stay
alert to findings outside that scope — mention them for a later round rather
than fixing them unasked or ignoring them.

## How to actually look at NeXa, not just read its code

A code-only review will miss real UX and consistency problems. Before writing
any finding about UI/UX, navigation, or component consistency:

1. Start the app (`Start NeXa.bat` or the venv/Streamlit command in CLAUDE.md)
   and open it in the browser pane.
2. Visit every page reachable from the sidebar (toggle "Show all pages" on to
   see the non-core ones too), in a normal user session with real data loaded.
3. Screenshot or read the DOM of each page's key states: default load, a filter
   applied, an empty-result state, a grid with a selection made, any
   form/expander opened.
4. Only then write findings — anchor each one to what was actually observed
   (a screenshot, a read_page dump, specific coordinates/copy), not a guess
   about what Streamlit "probably" renders.

## 1. UI/UX audit dimensions

For each, look across **all** pages, not just one, and specifically hunt for the
same function rendered differently in two places (that's the highest-value
finding this kind of audit can produce):

- **Visual hierarchy** — is the single most important number/status on a screen
  actually the most visually prominent thing on it, or is it competing with six
  equally-weighted `st.metric` cards?
- **Navigation / sidebar** — `NAV_PAGES` order, `CORE_NAV_KEYS` grouping, whether
  related tasks (e.g. Disputes and Refunds) sit next to each other, how many
  clicks from login to the most common task.
- **Dashboard** — KPI selection, ordering, whether it answers "is everything ok"
  at a glance for someone who does this daily.
- **Tables** (AG-Grid via `render_excel_grid`/`render_invoice_type_grid`) — column
  width policy (fixed via `column_width` vs. fit-to-content — currently
  inconsistent across pages), filter-row presence, currency/percent formatting
  coverage (`CURRENCY_COLUMNS`/`PERCENT_COLUMNS` — a new money column not added
  to that set silently renders as a raw float), pinned TOTAL row, row banding,
  alert renderers (duty/shipping warning triangles) — same visual language
  everywhere a "this number is unusually high" signal is needed.
- **Filters** — multiselect vs. selectbox choice consistency, default states,
  whether "Clear filters" is available everywhere a filter row exists.
- **Search** — AG-Grid's per-column floating filter is the only search
  mechanism today; is that sufficient for the volumes involved (thousands of
  boxes)?
- **Forms** (Add Refund, Add customer boxes, etc.) — field grouping, validation
  feedback, required-vs-optional clarity, autofill behavior (the tracking-number
  lookup in Refunds is a good existing pattern — check whether other forms that
  could benefit from it have it).
- **Buttons** — is "Save"/"Add"/"Cancel"/"Approve" the same visual weight, color,
  and label pattern everywhere it appears, or does e.g. "Cancel selected Case(s)"
  vs. a plain "Clear filters" button read as inconsistent styling for
  destructive-vs-neutral actions?
- **Cards** — `st.metric` usage: consistent formatting (`$X,XXX.XX` vs. raw
  percent vs. count) across every KPI row.
- **Modals/dialogs** — Streamlit has no true modal; check whether `st.expander`
  is used consistently for "optional, out of the way" content vs. inline forms
  for "always visible" content.
- **Notifications** — `st.success`/`st.info`/`st.error` usage consistency: same
  situations get the same message type everywhere (e.g. an empty-result list
  should always be `st.success`/`st.info`, never silently blank).
- **Status indicators** — dispute "(Waiting)" red text, above-average warning
  triangles, `Approved` checkboxes, `revenue_status`/`fedex_status`/
  `profit_calculation_status` text values: is the visual vocabulary for
  "this needs attention" consistent app-wide, or does each page invent its own?
- **Pagination** — AG-Grid's own virtualization/scroll vs. any manual `.head()`
  truncation — check for a silently-truncated list that should paginate or
  scroll instead.
- **Loading states** — Streamlit's default spinner is the only one in use;
  note anywhere a long computation runs with no feedback at all.
- **Empty states** — confirm every list/grid has an explicit empty-state message
  (many already do — e.g. "No boxes are missing shipment details" — check for
  ones that don't).
- **Error states** — what a user sees when an import file is malformed, a
  filter yields nothing, or (per the AG-Grid getRowId history) a checkbox
  interaction hits a bug — is it a stack trace, or a message a non-technical
  user can act on?
- **Responsive behavior** — Streamlit's default column layout at narrow widths;
  note anywhere a fixed-width grid or a wide row of columns breaks down.
- **Typography** — heading levels (`st.subheader` vs `st.header`) used
  consistently for the same conceptual level across pages.
- **Spacing** — consistent use of `st.columns` ratios, expander vs. inline,
  vertical rhythm between sections.
- **Color** — the navy `#1F4E79` brand color and any status colors (red for
  waiting/above-average, green for success) — are they the *only* colors in use,
  or has an ad hoc color crept in somewhere.
- **Icons** — sparse today (mostly text); note where an icon would remove
  ambiguity (e.g. distinguishing Duty vs. Shipping alerts at a glance) without
  adding noise.
- **Accessibility** — color-only status signals (red text) with no
  non-color redundant cue; contrast of the navy-on-white and white-on-navy
  combinations in use.
- **Keyboard usability** — Streamlit's inherent limits here; note anything
  actively worse than the Streamlit default (e.g. a grid interaction that
  requires precise mouse targeting because `getRowId` or similar wasn't set).
- **Information density** — this is a warehouse tool with thousands of rows per
  view; check that density serves *fast scanning*, not just "fits more on
  screen" — column widths, row height, and filter placement all matter more
  here than in a typical low-volume business app.

## 2. Design system extraction

NeXa doesn't currently have a written design system — it has organically
converged on some patterns (navy `#1F4E79` primary color, light-blue
`#D9E1F2` secondary fill, AG-Grid with `TableStyleMedium2`-family styling in the
Excel companion, `CURRENCY_FORMATTER`/`PERCENT_FORMATTER`/`COUNT_FORMATTER`
JsCode formatters, the metric-card KPI row pattern). The job here is to make
those explicit and find every place a screen deviates from them:

- **Color tokens** — enumerate every hex value actually used in `app.py` (search
  for `#` in style/fill strings) and in `.streamlit/config.toml`; flag any that
  isn't one of a small, deliberate palette.
- **Typography** — Streamlit's default font stack plus heading-level usage.
- **Spacing** — the `st.columns([...])` ratios in use; look for arbitrary,
  one-off ratios vs. a repeated small set.
- **Border radius / shadows** — Streamlit's default card styling
  (`st.metric`, `st.expander`) vs. any custom CSS injected via
  `unsafe_allow_html`/`GRID_CUSTOM_CSS` — check they agree.
- **Buttons, inputs, dropdowns** — Streamlit defaults vs. any custom override;
  document what exists today as the baseline before proposing changes.
- **Tables, badges, status colors** — as above (§1 Tables/Status indicators).
- **Cards, modals, notifications, icons** — as above.

Document the *current* system as Version 0 even if imperfect — a professionalization
pass should evolve it deliberately, not replace it wholesale with something
borrowed from another product.

## 3. Warehouse operations lens

NeXa's users work fast, at volume, with low tolerance for mis-clicks on
money-moving actions (Approve, Cancel Case, Add Refund). For every screen
touching **Customer, Box, Tracking, Shipment, Invoice, Payment, Refund,
Shipping, FedEx/UPS, Requests, Reports, Finance**, evaluate:

- Can the operator find a specific box/tracking/invoice in under a few seconds?
- Does the screen minimize navigation round-trips for a task that's done
  dozens of times a day (e.g. looking up an invoice, then checking its boxes,
  then opening a case — currently a single-page flow in Boxes; verify it stays
  that way as changes are proposed)?
  minimizes clicks?
- Is the financially-important number the visually loudest thing on the
  screen, or is it buried among equally-styled fields?
- Would a genuine mis-click (approving a case, cancelling a dispute, adding a
  refund) be easy to make, and is there a confirmation step proportional to its
  reversibility (compare: `cancel_disputed_items` is soft/reversible and has a
  lighter touch; a hard `remove_disputed_item` delete does not currently ask
  for confirmation — flag this kind of asymmetry).

## 4. Architecture, code quality, database, business logic, security, performance, testing, technical debt

Same technical dimensions as any backend audit — see the full detail in this
skill's prior version if present, or derive directly from `CLAUDE.md`'s
Architecture and Financial Model sections. In summary, check:

- **Architecture**: `app.py` page-dispatch chain has no orphaned `elif` left
  behind after a page removal; `core/*.py` stays framework-agnostic.
- **Code quality**: duplication that should call a shared helper instead; dead
  code (unused imports/session-state keys/CSS); comments explain *why*, not
  *what*.
- **Database**: `_ensure_columns()` calls match actual usage; null-vs-zero
  handling matches the financial model's "0.0 fee columns mean no invoice"
  rule; only parametrized SQL (`?` placeholders), never string-built.
- **Business logic**: Multi-box Duty/Shipping allocation, `NO_DUTY_COUNTRIES`,
  `CANADA_SHIPPING_RATE_CARD`, Shipping-first dispute priority — all still
  respected by any new code path.
- **Financial integrity**: verify the reconciliation identity on the live DB —

  ```python
  from core.analytics import enrich_boxes_for_display, compute_profit_calculation, compute_fedex_reconciliation
  import sqlite3, pandas as pd
  conn = sqlite3.connect("data/finance_customs.db")
  boxes = pd.read_sql("SELECT * FROM boxes", conn)
  charges = pd.read_sql("SELECT * FROM shipment_charges", conn)
  profit = compute_profit_calculation(enrich_boxes_for_display(boxes))
  recon = compute_fedex_reconciliation(profit, charges)
  assert abs(recon["total_fedex_invoice"] - (recon["included"] + recon["excluded_no_customer_invoice"] + recon["unallocated"])) < 0.01
  ```
  A box `Excluded - Customer Invoice Missing` must contribute exactly `0` to
  every sum. No "estimated/accrued cost" may appear in `actual_profit` (rejected
  2026-09-19 — see CLAUDE.md).
- **Security**: no `eval`/`exec` on file-derived content; parametrized SQL only;
  file paths from Streamlit's uploader or fixed config, never concatenated from
  unsanitized input.
- **Performance**: vectorized pandas over per-row Python loops on the `boxes`
  table (thousands of rows); `st.cache_data` used deliberately, with a stated
  TTL reason when the computation depends on "today."
- **Testing**: there is currently no automated test suite — say so plainly,
  don't imply coverage that doesn't exist. `core/analytics.py`'s pure functions
  are the highest-value, lowest-effort target if the user approves adding tests.
- **Technical debt**: track known items (no test suite; `app.py` is a single
  ~2,800-line dispatch chain; two coexisting financial models — the older
  `enrich_boxes_for_display` fields and the newer Actual-only
  `compute_profit_calculation` model — intentional per CLAUDE.md but worth
  eventually consolidating if the user wants that).

## Severity rubric

Use this scale in every PLAN and REPORT so severity is comparable across audits:

- **Critical** — real/possible financial-number corruption, data loss, or an
  exploitable security hole. Surface immediately, don't wait for the full audit
  to finish.
- **High** — a bug producing a wrong result or silently dropping real data in a
  reachable, non-edge-case path; or a UX problem that causes real, observed
  operational errors (e.g. a destructive action one click away from a routine
  one, with no differentiation).
- **Medium** — a real bug/inconsistency that's edge-case or low-frequency; a
  meaningful maintainability, consistency, or usability gap.
- **Low** — cosmetic, stylistic, or a nice-to-have with no current observed
  impact.

Every finding needs: concrete evidence (file:line, or an observed screen state),
a specific failure/friction scenario (not "this could be a problem" — show the
input/state that breaks or slows things down), and severity with a one-line
justification.

## Report format

Every finding, in PLAN or REPORT output: **Problem / Evidence / Impact / Risk /
Recommendation / Files / Action / Test**. Say plainly when something is
estimated rather than measured. Never claim a test ran if it didn't, or a fix
was applied if the file wasn't changed.
