import datetime
import json

import numpy as np
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, ColumnsAutoSizeMode, GridOptionsBuilder, GridUpdateMode
from st_aggrid.shared import JsCode

CURRENCY_FORMATTER = JsCode(
    """
    function(params) {
        if (params.value === null || params.value === undefined || params.value === '') { return ''; }
        var num = Number(params.value);
        if (isNaN(num)) { return params.value; }
        return '$' + num.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    }
    """
)

PERCENT_FORMATTER = JsCode(
    """
    function(params) {
        if (params.value === null || params.value === undefined || params.value === '') { return ''; }
        var num = Number(params.value);
        if (isNaN(num)) { return params.value; }
        return num.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '%';
    }
    """
)

COUNT_FORMATTER = JsCode(
    """
    function(params) {
        if (params.value === null || params.value === undefined || params.value === '') { return ''; }
        var num = Number(params.value);
        if (isNaN(num)) { return params.value; }
        return num.toLocaleString('en-US');
    }
    """
)

from core.analytics import (
    PROFIT_EXCLUDED_NO_INVOICE,
    PROFIT_INCLUDED,
    compute_above_average_boxes,
    compute_benchmarks,
    compute_customer_invoice_reconciliation,
    compute_customer_profitability,
    compute_data_issues,
    compute_duty_above_average_flag,
    compute_fedex_reconciliation,
    compute_profit_calculation,
    compute_shipping_above_average_flag,
    enrich_boxes_for_display,
    flag_shipping_rate_alerts,
    normalize_shipment_type,
)
from core.box_import import add_single_box, import_boxes, read_box_import_file
from core.customer_invoice_import import (
    build_customer_invoice_export,
    import_customer_invoices,
    import_mosaic_handling_invoices,
    read_customer_invoice_file,
    read_mosaic_handling_file,
)
from core.database import get_connection, init_db, update_box_fields
from core.ingest import ingest_pdf_bundle
from core import review
from core.review import (
    add_disputed_items,
    cancel_disputed_items,
    get_disputed_items_df,
    get_invoice_review_map,
    remove_disputed_item,
    set_invoice_review_status,
)
from core.refunds import (
    REFUND_STATUSES,
    REFUND_TYPE_REVENUE_LINE,
    REFUND_TYPES,
    add_refund,
    delete_refund,
    get_refunds_df,
    set_refund_status,
)

st.set_page_config(page_title="NeXa", page_icon="🧭", layout="wide")

# These are all pure functions of the `boxes` table (same input -> same output, no side
# effects), but they were getting recomputed from scratch on every single interaction —
# including filter changes elsewhere on the page that don't touch `boxes` at all — and
# enrich_boxes_for_display in particular loops per Multi-box group in plain Python, which
# gets slow with thousands of boxes. Caching keys on the actual data, so a real upload or
# edit still recomputes correctly, while everything else (filters, tab switches, checkbox
# clicks) reuses the cached result instantly.
# ttl=3600: enrich_boxes_for_display's "waiting period expired" cutoff depends on
# today's date, which isn't part of the cache key — without a TTL, a long-running
# app instance would keep serving a stale pending/completed split across midnight.
cached_enrich_boxes = st.cache_data(show_spinner=False, ttl=3600)(enrich_boxes_for_display)
cached_compute_benchmarks = st.cache_data(show_spinner=False)(compute_benchmarks)
cached_compute_above_average_boxes = st.cache_data(show_spinner=False)(compute_above_average_boxes)
cached_compute_data_issues = st.cache_data(show_spinner=False)(compute_data_issues)
cached_compute_duty_above_average_flag = st.cache_data(show_spinner=False)(compute_duty_above_average_flag)
cached_compute_shipping_above_average_flag = st.cache_data(show_spinner=False)(
    compute_shipping_above_average_flag
)

st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .nexa-header {
        display: flex;
        align-items: baseline;
        gap: 0.6rem;
        margin-bottom: 1.25rem;
    }
    .nexa-header .nexa-logo {
        font-size: 1.7rem;
        font-weight: 700;
        color: #1F4E79;
        letter-spacing: 0.02em;
    }
    .nexa-header .nexa-subtitle {
        font-size: 0.9rem;
        color: #6B7280;
    }
    .nexa-sidebar-logo {
        padding: 0.5rem 0.2rem 1.1rem 0.2rem;
        border-bottom: 1px solid rgba(255,255,255,0.18);
        margin-bottom: 0.75rem;
    }
    .nexa-sidebar-logo .nexa-logo {
        display: block;
        font-size: 1.5rem;
        font-weight: 700;
        color: #FFFFFF;
        letter-spacing: 0.02em;
    }
    .nexa-sidebar-logo .nexa-subtitle {
        display: block;
        font-size: 0.75rem;
        color: #B7C6D9;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        margin-top: 0.15rem;
    }
    div[data-testid="stMetric"] {
        background-color: #F9FAFB;
        border: 1px solid #E3E6EA;
        border-radius: 8px;
        padding: 0.75rem 1rem;
    }
    button[data-testid="stBaseButton-secondary"], button[kind="secondary"] {
        border-radius: 6px;
    }
    section[data-testid="stSidebar"] {
        background-color: #1F4E79;
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] {
        background-color: #F9FAFB;
        border-radius: 8px;
    }
    section[data-testid="stSidebar"] div[role="radiogroup"] {
        flex-direction: column;
        flex-wrap: nowrap;
        gap: 0.15rem;
    }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"] {
        width: 100%;
        margin: 0;
        padding: 0.5rem 0.75rem;
        border-radius: 8px;
    }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"] p {
        color: #FFFFFF;
    }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"]:hover {
        background-color: rgba(255,255,255,0.10);
    }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] {
        background-color: rgba(255,255,255,0.16);
    }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] p {
        font-weight: 700;
    }
    /* The label text sits in a sibling div at the exact same nesting depth as the
       radio dot's ring div, so a plain "label > div > div > div" selector matches
       BOTH — painting the text's own background white too. ":not([data-testid])"
       excludes the text container (stMarkdownContainer carries that attribute,
       the ring div doesn't) so only the actual dot is affected. */
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"] [data-testid="stMarkdownContainer"] {
        background-color: transparent !important;
    }
    /* Radio dot: unselected shows as a thin faint ring (its inner fill matches the
       sidebar background, masking the middle), selected shows as one solid bright
       white circle — reads as "bigger/bolder" without actually resizing the box,
       since forcing width/height here breaks the nav's flex layout (collapses it
       to a sliver) in a way plain background-color changes don't. */
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"] > div > div > div:not([data-testid]) {
        background-color: rgba(255,255,255,0.35) !important;
    }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"] > div > div > div:not([data-testid]) > div {
        background-color: #1F4E79 !important;
    }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] > div > div > div:not([data-testid]) {
        background-color: #FFFFFF !important;
    }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] > div > div > div:not([data-testid]) > div {
        background-color: #FFFFFF !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

GRID_CUSTOM_CSS = {
    ".ag-row-selected": {"background-color": "#1F4E79 !important"},
    ".ag-row-selected .ag-cell": {"color": "#FFFFFF !important"},
    ".ag-cell": {
        "border-right": "1px solid #E3E6EA !important",
        "padding-left": "10px !important",
        "padding-right": "10px !important",
    },
    ".ag-header-cell": {
        "border-right": "1px solid #C7CFD8 !important",
        "background-color": "#F2F4F7 !important",
        "font-weight": "700 !important",
    },
    ".ag-row-odd": {"background-color": "#FAFBFC !important"},
    ".ag-row-flagged": {"background-color": "#FFD7D7 !important"},
    ".ag-row-flagged .ag-cell": {"color": "#7F1D1D !important"},
}


def show_selected_sum(df, selected_rows, amount_col, group_col=None, group_amount_col=None):
    """Displays the sum of an amount column for the selected rows (Excel-style
    'select cells to see the total'). When group_col/group_amount_col are given,
    a shared amount that repeats across a group's rows is only counted once."""
    if not selected_rows:
        return
    selected_df = df.iloc[selected_rows]
    if group_col and group_amount_col and group_col in selected_df.columns:
        regular = selected_df[selected_df[group_col].isna()]
        total = pd.to_numeric(regular[amount_col], errors="coerce").sum()
        grouped = selected_df.dropna(subset=[group_col]).drop_duplicates(group_col)
        total += pd.to_numeric(grouped[group_amount_col], errors="coerce").sum()
    else:
        total = pd.to_numeric(selected_df[amount_col], errors="coerce").sum()
    st.caption(f"Selected {len(selected_rows)} row(s) — sum: ${total:,.2f}")


def date_only(df, *cols):
    """Normalizes a date column to plain YYYY-MM-DD. Different tables store dates
    in different raw formats — boxes/customer_invoices come out of SQLite as full
    timestamps ('2026-01-02 00:00:00'), while shipment_charges keeps the PDF's own
    'Aug 27, 2026' text with no time component at all — so a naive character slice
    truncates the latter instead of stripping a time suffix. Parsing with
    pd.to_datetime handles both consistently; a value that fails to parse is left
    exactly as-is rather than blanked out."""
    df = df.copy()
    for col in cols:
        if col in df.columns:
            # format="mixed" parses each value independently — without it pandas infers
            # a single format from the first value and applies it to the whole column,
            # so an ISO timestamp sitting next to a "Mon DD, YYYY" PDF-parsed date would
            # silently fail to parse instead of just being a different valid format.
            parsed = pd.to_datetime(df[col], errors="coerce", format="mixed")
            formatted = parsed.dt.strftime("%Y-%m-%d")
            df[col] = formatted.where(parsed.notna(), df[col])
    return df


CURRENCY_COLUMNS = {
    "customer_shipping_fee",
    "customer_packaging_fee",
    "customer_total_invoice",
    "fedex_duty_amount",
    "fedex_shipping_amount",
    "fedex_total_cost",
    "profit_loss",
    "invoice_amount",
    "amount",
    "group_amount",
    "item_amount",
    "item_rate",
    "total_amount",
    "total",
    "avg_total_per_box",
    "avg_shipping_per_box",
    "avg_duty_per_box",
    "customer_invoice",
    "fedex_invoice",
    "value_for_duty",
    "revenue",
    "fedex_cost",
    "profit",
    "actual_fedex_cost",
    "actual_profit",
    "fedex_cost_excluded_no_invoice",
}

PERCENT_COLUMNS = {"margin_percent"}

INTEGER_COMMA_COLUMNS = {"box_count", "record_count", "pending_count", "completed_count"}

COPYABLE_ID_COLUMNS = {
    "tracking_id",
    "invoice_no",
    "invoice_number",
    "fedex_duty_invoice_no",
    "fedex_shipping_invoice_no",
    "multi_no",
}

CLICK_TO_COPY_HANDLER = JsCode(
    """
    function(params) {
        var copyableColumns = ['tracking_id', 'invoice_no', 'invoice_number',
            'fedex_duty_invoice_no', 'fedex_shipping_invoice_no', 'multi_no'];
        if (copyableColumns.indexOf(params.column.getColId()) === -1) { return; }
        if (params.value === null || params.value === undefined || params.value === '') { return; }
        var text = String(params.value);

        function fallbackCopy() {
            var textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.focus();
            textarea.select();
            try { document.execCommand('copy'); } catch (e) {}
            document.body.removeChild(textarea);
        }

        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).catch(fallbackCopy);
        } else {
            fallbackCopy();
        }

        var cellEl = params.event && params.event.target ? params.event.target.closest('.ag-cell') : null;
        if (cellEl) {
            var original = cellEl.style.backgroundColor;
            cellEl.style.backgroundColor = '#D1FAE5';
            setTimeout(function() { cellEl.style.backgroundColor = original; }, 400);
        }
    }
    """
)


def get_grid_key(key, show_clear_button=True):
    """A grid's key includes a per-grid reset counter so 'Clear filters' can force
    a full remount — the only reliable way to guarantee a stuck floating-filter
    input actually clears, since it's client-side state Python can't reach into."""
    reset_key = f"{key}_reset_count"
    if reset_key not in st.session_state:
        st.session_state[reset_key] = 0
    if show_clear_button and st.button("Clear filters", key=f"{key}_clear_btn"):
        st.session_state[reset_key] += 1
    return f"{key}_{st.session_state[reset_key]}"


def build_totals_row(df):
    """A pinned bottom 'TOTAL' row: sums every currency and count column, blank
    elsewhere. The 'TOTAL' label goes in the first remaining column that isn't
    an id column, so it doesn't land in a numeric id column (AG-Grid would then
    show 'Invalid Number' there instead of the label)."""
    totals_row = {}
    label_assigned = False
    for col in df.columns:
        if col in CURRENCY_COLUMNS:
            total = pd.to_numeric(df[col], errors="coerce").sum()
            totals_row[col] = None if pd.isna(total) else float(total)
        elif col in INTEGER_COMMA_COLUMNS:
            total = pd.to_numeric(df[col], errors="coerce").sum()
            totals_row[col] = None if pd.isna(total) else int(total)
        elif not label_assigned and col.lower() != "id":
            totals_row[col] = "TOTAL"
            label_assigned = True
        else:
            totals_row[col] = None
    return totals_row


def build_selection_aware_totals_handler(totals_row):
    """JS onSelectionChanged handler for the pinned bottom row: shows the
    full-dataset totals (the given totals_row) when nothing is checked, or
    re-sums just the checked rows across the same numeric columns when one or
    more checkboxes are selected — so the TOTAL row always answers 'total of
    what's showing' or 'total of what I've selected', whichever applies."""
    totals_json = json.dumps(totals_row)
    return JsCode(
        f"""
        function(params) {{
            var originalTotals = {totals_json};
            var selectedRows = params.api.getSelectedRows();
            if (!selectedRows || selectedRows.length === 0) {{
                params.api.setGridOption('pinnedBottomRowData', [originalTotals]);
                return;
            }}
            var newTotal = {{}};
            Object.keys(originalTotals).forEach(function(field) {{
                var orig = originalTotals[field];
                if (typeof orig === 'number') {{
                    var sum = 0;
                    selectedRows.forEach(function(row) {{
                        var v = Number(row[field]);
                        if (!isNaN(v)) {{ sum += v; }}
                    }});
                    newTotal[field] = sum;
                }} else if (orig === 'TOTAL') {{
                    newTotal[field] = 'TOTAL (' + selectedRows.length + ' selected)';
                }} else {{
                    newTotal[field] = null;
                }}
            }});
            params.api.setGridOption('pinnedBottomRowData', [newTotal]);
        }}
        """
    )


WAITING_STATUS_CELL_STYLE = JsCode(
    """
    function(params) {
        if (params.value === 'Waiting') {
            return {color: '#DC2626', fontWeight: '600'};
        }
        return null;
    }
    """
)

WAITING_SUFFIX_FORMATTER = JsCode(
    """
    function(params) {
        if (params.data && params.data._waiting && params.value !== null && params.value !== undefined) {
            return params.value + ' (Waiting)';
        }
        return params.value;
    }
    """
)

WAITING_ROW_CELL_STYLE = JsCode(
    """
    function(params) {
        if (params.data && params.data._waiting) {
            return {color: '#DC2626', fontWeight: '600'};
        }
        return null;
    }
    """
)

ALERT_INVOICE_CELL_RENDERER = JsCode(
    """
    (function() {
        function AlertInvoiceRenderer() {}
        AlertInvoiceRenderer.prototype.init = function(params) {
            this.eGui = document.createElement('span');
            this.refresh(params);
        };
        AlertInvoiceRenderer.prototype.getGui = function() { return this.eGui; };
        AlertInvoiceRenderer.prototype.refresh = function(params) {
            var value = params.value;
            if (value === null || value === undefined || value === '') {
                this.eGui.innerHTML = '';
                return true;
            }
            var text = String(value);
            var cellParams = (params.colDef && params.colDef.cellRendererParams) || {};
            var alertField = cellParams.alertField || '_duty_above_average';
            var waitingField = cellParams.waitingField;
            var isAlert = params.data && params.data[alertField];
            var isWaiting = waitingField && params.data && params.data[waitingField];

            if (isAlert && !document.getElementById('nexa-blink-style')) {
                var style = document.createElement('style');
                style.id = 'nexa-blink-style';
                style.innerHTML = '@keyframes nexa-blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.15; } } ' +
                    '.nexa-blink-icon { display: inline-block; animation: nexa-blink 1s infinite; }';
                document.head.appendChild(style);
            }

            if (!isWaiting && !isAlert) {
                this.eGui.textContent = text;
                return true;
            }
            var displayText = isWaiting ? text + ' (Waiting)' : text;
            var textSpan = isWaiting
                ? '<span style="color:#DC2626;font-weight:600;">' + displayText + '</span>'
                : displayText;
            var iconSpan = isAlert
                ? ' <span class="nexa-blink-icon" title="Far above average">\\u26A0\\uFE0F</span>'
                : '';
            this.eGui.innerHTML = textSpan + iconSpan;
            return true;
        };
        return AlertInvoiceRenderer;
    })()
    """
)


def render_excel_grid(
    df,
    key,
    height=420,
    amount_col=None,
    show_totals_row=True,
    checkbox_columns=None,
    enable_filters=True,
    enable_selection=True,
    selection_mode="multiple",
    waiting_flag_column=None,
    waiting_target_column=None,
    double_click_to_select=False,
    highlight_row_column=None,
    duty_alert_column=None,
    shipping_alert_column=None,
    shipping_waiting_column=None,
    column_width=None,
):
    """Renders a dataframe as an interactive grid with an Excel-style filter row
    and sortable column headers, currency columns formatted as $0.00 and pinned
    left, a pinned TOTAL row at the bottom, and shows the sum of amount_col for
    any rows the user selects (checkbox column). Pass checkbox_columns to make
    specific boolean columns editable checkboxes (e.g. an in-grid review flag).
    Pass enable_filters=False / enable_selection=False for a plain read-only
    summary grid that doesn't need per-column filters or a selection checkbox.
    A 'Case Status' column showing 'Waiting' is auto-highlighted in red. Pass
    waiting_flag_column (a hidden boolean column) with waiting_target_column to
    instead append ' (Waiting)' directly onto that column's own value, both in red,
    with no separate status column shown. Pass double_click_to_select=True so a
    single click anywhere in a row doesn't open its detail section below — only
    double-clicking the row (or clicking its selection checkbox directly) does.
    Pass highlight_row_column (a hidden boolean column) to paint the whole row
    light red — e.g. a shipping charge that broke a rate agreement or came in
    above average. Pass duty_alert_column / shipping_alert_column (a hidden
    boolean column) to add a blinking warning triangle next to the
    fedex_duty_invoice_no / fedex_shipping_invoice_no value on flagged rows.
    Pass shipping_waiting_column (e.g. 'Case') to also append ' (Waiting)' in red
    onto fedex_shipping_invoice_no for rows where that column is true. Pass
    column_width for a compact summary table (few columns, short values) so
    columns sit at a fixed readable width instead of stretching to fill the
    container — leave it None for the normal fit-to-content sizing."""
    grid_key = get_grid_key(key, show_clear_button=enable_filters)

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(
        filter=enable_filters,
        sortable=True,
        resizable=True,
        floatingFilter=enable_filters,
        suppressMenu=not enable_filters,
        minWidth=120,
        width=column_width,
        wrapHeaderText=True,
        autoHeaderHeight=True,
    )
    if enable_selection:
        gb.configure_selection(selection_mode=selection_mode, use_checkbox=True)
        if double_click_to_select:
            gb.configure_grid_options(
                suppressRowClickSelection=True,
                onRowDoubleClicked=JsCode(
                    "function(params) { params.node.setSelected(true, true); }"
                ),
            )
    gb.configure_grid_options(
        enableCellTextSelection=True, ensureDomOrder=True, onCellClicked=CLICK_TO_COPY_HANDLER
    )
    if "id" in df.columns:
        # Without this, ag-grid tracks rows by position — so when the same-keyed
        # grid is re-rendered against a differently-sized/ordered dataframe (e.g.
        # picking then clearing an invoice filter changes the row set), old
        # checkbox/selection state can land on the wrong rows and get read back
        # as if the user had just toggled them (spurious Case open/close, etc.).
        # Row identity by the real database id fixes that.
        gb.configure_grid_options(getRowId=JsCode("function(params) { return String(params.data.id); }"))
    for col in df.columns:
        if col in CURRENCY_COLUMNS:
            gb.configure_column(
                col, valueFormatter=CURRENCY_FORMATTER, cellStyle={"textAlign": "left"}
            )
        elif col in INTEGER_COMMA_COLUMNS:
            gb.configure_column(
                col, valueFormatter=COUNT_FORMATTER, cellStyle={"textAlign": "left"}
            )
        elif col in PERCENT_COLUMNS:
            gb.configure_column(
                col, valueFormatter=PERCENT_FORMATTER, cellStyle={"textAlign": "left"}
            )
        elif col == "Case Status":
            gb.configure_column(col, cellStyle=WAITING_STATUS_CELL_STYLE)
        elif col in COPYABLE_ID_COLUMNS:
            gb.configure_column(col, cellStyle={"cursor": "pointer"})
    if waiting_flag_column and waiting_target_column:
        gb.configure_column(waiting_flag_column, hide=True)
        gb.configure_column(
            waiting_target_column,
            valueFormatter=WAITING_SUFFIX_FORMATTER,
            cellStyle=WAITING_ROW_CELL_STYLE,
        )
    if highlight_row_column and highlight_row_column in df.columns:
        gb.configure_column(highlight_row_column, hide=True)
        gb.configure_grid_options(
            rowClassRules={"ag-row-flagged": f"data.{highlight_row_column} === true"}
        )
    if duty_alert_column and duty_alert_column in df.columns and "fedex_duty_invoice_no" in df.columns:
        gb.configure_column(duty_alert_column, hide=True)
        gb.configure_column(
            "fedex_duty_invoice_no",
            cellRenderer=ALERT_INVOICE_CELL_RENDERER,
            cellRendererParams={"alertField": duty_alert_column},
        )
    has_shipping_alert = shipping_alert_column and shipping_alert_column in df.columns
    has_shipping_waiting = shipping_waiting_column and shipping_waiting_column in df.columns
    if (has_shipping_alert or has_shipping_waiting) and "fedex_shipping_invoice_no" in df.columns:
        shipping_renderer_params = {}
        if has_shipping_alert:
            gb.configure_column(shipping_alert_column, hide=True)
            shipping_renderer_params["alertField"] = shipping_alert_column
        if has_shipping_waiting:
            shipping_renderer_params["waitingField"] = shipping_waiting_column
        gb.configure_column(
            "fedex_shipping_invoice_no",
            cellRenderer=ALERT_INVOICE_CELL_RENDERER,
            cellRendererParams=shipping_renderer_params,
        )
    for col in checkbox_columns or []:
        if col in df.columns:
            gb.configure_column(
                col,
                editable=True,
                cellRenderer="agCheckboxCellRenderer",
                cellEditor="agCheckboxCellEditor",
                singleClickEdit=True,
            )
    grid_options = gb.build()
    if show_totals_row and not df.empty:
        totals_row = build_totals_row(df)
        grid_options["pinnedBottomRowData"] = [totals_row]
        if enable_selection:
            grid_options["onSelectionChanged"] = build_selection_aware_totals_handler(totals_row)

    update_mode = GridUpdateMode.SELECTION_CHANGED
    if checkbox_columns:
        update_mode = update_mode | GridUpdateMode.VALUE_CHANGED

    response = AgGrid(
        df,
        gridOptions=grid_options,
        height=height,
        update_mode=update_mode,
        columns_auto_size_mode=(
            ColumnsAutoSizeMode.NO_AUTOSIZE if column_width else ColumnsAutoSizeMode.FIT_CONTENTS
        ),
        allow_unsafe_jscode=True,
        custom_css=GRID_CUSTOM_CSS,
        key=grid_key,
    )

    if amount_col:
        selected = pd.DataFrame(response["selected_rows"])
        if not selected.empty:
            total = pd.to_numeric(selected[amount_col], errors="coerce").sum()
            st.caption(f"Selected {len(selected)} row(s) — sum: ${total:,.2f}")

    return response


CHARGE_TYPE_LABELS = {
    "Duty": "Duty Tax",
    "Shipping": "Fedex Transportation",
    "Pickup": "Pick up",
}

INVOICE_TYPE_CELL_STYLE = JsCode(
    """
    function(params) {
        if (params.value === 'Duty Tax') {
            return {backgroundColor: '#FDECC8', color: '#92400E', fontWeight: '600'};
        }
        if (params.value === 'Fedex Transportation') {
            return {backgroundColor: '#D1FADF', color: '#065F46', fontWeight: '600'};
        }
        if (params.value === 'Pick up') {
            return {backgroundColor: '#E9D8FD', color: '#553C9A', fontWeight: '600'};
        }
        return null;
    }
    """
)

INVOICE_NO_LINK_CELL_STYLE = JsCode(
    """
    function(params) {
        if (params.data && params.data._waiting) {
            return {color: '#DC2626', fontWeight: '600', cursor: 'pointer'};
        }
        return {color: '#1F4E79', fontWeight: '600', cursor: 'pointer'};
    }
    """
)


def render_invoice_type_grid(
    df, key, height=280, waiting_flag_column=None, waiting_target_column=None
):
    """Single-select grid for the FedEx invoice lookup list: invoice_type shown
    as a colored badge (Duty/Shipping), invoice_no styled like a link, and
    Approved/Case (if present) as editable checkbox columns. Pass
    waiting_flag_column (a hidden boolean column) with waiting_target_column to
    paint the whole row light red and append ' (Waiting)' in red onto that
    column's value — e.g. a Shipping invoice with an open Case."""
    grid_key = get_grid_key(key)

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(
        filter=True,
        sortable=True,
        resizable=True,
        floatingFilter=True,
        minWidth=120,
        wrapHeaderText=True,
        autoHeaderHeight=True,
    )
    gb.configure_selection(selection_mode="single", use_checkbox=True)
    gb.configure_grid_options(
        enableCellTextSelection=True, ensureDomOrder=True, onCellClicked=CLICK_TO_COPY_HANDLER
    )
    if "invoice_no" in df.columns:
        # Row identity by invoice_no (not position) — checking then unchecking a
        # row here changes the Boxes grid's own row set below, and without a
        # stable id ag-grid can misread leftover position-based selection state
        # as a fresh toggle on whatever row now occupies that slot.
        gb.configure_grid_options(
            getRowId=JsCode("function(params) { return String(params.data.invoice_no); }")
        )
    gb.configure_column("invoice_type", cellStyle=INVOICE_TYPE_CELL_STYLE)
    if waiting_target_column == "invoice_no":
        gb.configure_column(
            "invoice_no", cellStyle=INVOICE_NO_LINK_CELL_STYLE, valueFormatter=WAITING_SUFFIX_FORMATTER
        )
    else:
        gb.configure_column(
            "invoice_no", cellStyle={"color": "#1F4E79", "fontWeight": "600", "cursor": "pointer"}
        )
    for col in df.columns:
        if col in CURRENCY_COLUMNS:
            gb.configure_column(
                col, valueFormatter=CURRENCY_FORMATTER, cellStyle={"textAlign": "left"}
            )
        elif col in INTEGER_COMMA_COLUMNS:
            gb.configure_column(
                col, valueFormatter=COUNT_FORMATTER, cellStyle={"textAlign": "left"}
            )
        elif col != "invoice_no" and col in COPYABLE_ID_COLUMNS:
            gb.configure_column(col, cellStyle={"cursor": "pointer"})
    for col in ("Approved", "Case"):
        if col in df.columns:
            gb.configure_column(
                col,
                editable=True,
                cellRenderer="agCheckboxCellRenderer",
                cellEditor="agCheckboxCellEditor",
                singleClickEdit=True,
            )
    if waiting_flag_column and waiting_flag_column in df.columns:
        gb.configure_column(waiting_flag_column, hide=True)
        gb.configure_grid_options(
            rowClassRules={"ag-row-flagged": f"data.{waiting_flag_column} === true"}
        )
    grid_options = gb.build()

    return AgGrid(
        df,
        gridOptions=grid_options,
        height=height,
        update_mode=GridUpdateMode.SELECTION_CHANGED | GridUpdateMode.VALUE_CHANGED,
        columns_auto_size_mode=ColumnsAutoSizeMode.FIT_CONTENTS,
        allow_unsafe_jscode=True,
        custom_css=GRID_CUSTOM_CSS,
        key=grid_key,
    )

NAV_PAGES = [
    ("dashboard", "Dashboard"),
    ("reconciliation", "Reconciliation"),
    ("browse", "Invoice Matching"),
    ("boxes", "Boxes"),
    ("benchmarks", "Benchmarks"),
    ("above_average", "Above-Average Invoices"),
    ("data_quality", "Data Quality"),
    ("customers", "Customer Invoices"),
    ("all_charges", "All Shipment Charges"),
    ("disputes", "Disputes"),
    ("refunds", "Refunds"),
    ("reports", "Reports"),
    ("settings", "Settings"),
]
NAV_LABEL_TO_KEY = {label: key for key, label in NAV_PAGES}

# While the rest are still being built out, only these pages are shown by default —
# the "Show all pages" toggle at the bottom of the sidebar reveals the rest as they're
# finished, without deleting any of their code.
CORE_NAV_KEYS = {
    "dashboard", "reconciliation", "boxes", "customers", "all_charges", "disputes", "refunds",
}

if "show_all_pages" not in st.session_state:
    st.session_state["show_all_pages"] = False

with st.sidebar:
    st.markdown(
        '<div class="nexa-sidebar-logo">'
        '<span class="nexa-logo">NeXa</span>'
        '<span class="nexa-subtitle">Finance &amp; Customs Analyzer</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    visible_nav_pages = (
        NAV_PAGES
        if st.session_state["show_all_pages"]
        else [(key, label) for key, label in NAV_PAGES if key in CORE_NAV_KEYS]
    )
    visible_nav_labels = [label for _, label in visible_nav_pages]
    if st.session_state.get("nav_selection") not in visible_nav_labels:
        st.session_state["nav_selection"] = visible_nav_labels[0]
    selected_nav_label = st.radio(
        "Navigation", visible_nav_labels, label_visibility="collapsed", key="nav_selection"
    )
    current_page = NAV_LABEL_TO_KEY[selected_nav_label]

    with st.expander("Upload Data", expanded=False):
        st.caption("Upload FedEx invoice PDFs — data is extracted and saved automatically.")
        if "uploader_reset_count" not in st.session_state:
            st.session_state["uploader_reset_count"] = 0
        uploaded_files = st.file_uploader(
            "FedEx invoice PDF(s)",
            type=["pdf"],
            accept_multiple_files=True,
            key=f"invoice_uploader_{st.session_state['uploader_reset_count']}",
            label_visibility="collapsed",
        )
        if uploaded_files:
            for uploaded_file in uploaded_files:
                results = ingest_pdf_bundle(uploaded_file, uploaded_file.name)
                if len(results) == 1:
                    header, charge_type = results[0]
                    st.success(f"{header['invoice_number']} ({charge_type}) saved.")
                else:
                    st.success(f"{uploaded_file.name}: {len(results)} invoices found and saved.")
                    for header, charge_type in results:
                        st.caption(f"— {header['invoice_number']} ({charge_type})")
            st.session_state["uploader_reset_count"] += 1
            st.rerun()

    st.toggle("Show all pages", key="show_all_pages")

st.markdown(
    f'<div class="nexa-header"><span class="nexa-logo">{selected_nav_label}</span></div>',
    unsafe_allow_html=True,
)

connection = get_connection()
init_db(connection)
try:
    invoices = pd.read_sql("SELECT * FROM invoices", connection)
except pd.errors.DatabaseError:
    invoices = pd.DataFrame()
try:
    shipment_charges = pd.read_sql("SELECT * FROM shipment_charges", connection)
except pd.errors.DatabaseError:
    shipment_charges = pd.DataFrame()
try:
    products = pd.read_sql("SELECT * FROM products", connection)
except pd.errors.DatabaseError:
    products = pd.DataFrame()
try:
    boxes = pd.read_sql("SELECT * FROM boxes", connection)
except pd.errors.DatabaseError:
    boxes = pd.DataFrame()
try:
    customer_invoices = pd.read_sql("SELECT * FROM customer_invoices", connection)
except pd.errors.DatabaseError:
    customer_invoices = pd.DataFrame()
connection.close()

disputed_items_df = get_disputed_items_df()
# Only "Active" disputes count as an open Case anywhere outside the Disputes page
# itself (checkbox state, waiting flags, etc.) — a cancelled one shouldn't still
# hold an invoice in "waiting" limbo.
active_disputed_items_df = (
    disputed_items_df[disputed_items_df["status"] == "Active"]
    if not disputed_items_df.empty
    else disputed_items_df
)
refunds_df = get_refunds_df()

DATE_RANGE_PRESETS = ["All Time", "Current Month", "Previous Month", "Last 3 Months", "YTD", "Custom Range"]


def resolve_date_range(preset, today=None):
    """Returns (start, end) as pandas Timestamps (inclusive) for a preset label,
    or (None, None) for 'All Time' / an unrecognized preset. 'Custom Range' is
    handled by the caller (it needs its own date-picker widget)."""
    today = (today or pd.Timestamp.now()).normalize()
    if preset == "Current Month":
        return today.replace(day=1), today
    if preset == "Previous Month":
        end = today.replace(day=1) - pd.Timedelta(days=1)
        return end.replace(day=1), end
    if preset == "Last 3 Months":
        return today.replace(day=1) - pd.DateOffset(months=2), today
    if preset == "YTD":
        return today.replace(month=1, day=1), today
    return None, None


if current_page == "dashboard":
    if boxes.empty:
        st.info("No historical box data imported yet.")
    else:
        dashboard_boxes = cached_enrich_boxes(boxes)
        dashboard_boxes["ship_date_parsed"] = pd.to_datetime(
            dashboard_boxes["ship_date"], errors="coerce"
        )

        date_filter_col, company_filter_col, customer_filter_col = st.columns([1, 1, 2])
        dashboard_date_preset = date_filter_col.selectbox(
            "Date Range", DATE_RANGE_PRESETS, key="dashboard_date_range_preset"
        )
        if dashboard_date_preset == "Custom Range":
            min_ship_date = dashboard_boxes["ship_date_parsed"].min()
            max_ship_date = dashboard_boxes["ship_date_parsed"].max()
            custom_range = date_filter_col.date_input(
                "Custom dates",
                value=(
                    min_ship_date.date() if pd.notna(min_ship_date) else datetime.date.today(),
                    max_ship_date.date() if pd.notna(max_ship_date) else datetime.date.today(),
                ),
                key="dashboard_custom_date_range",
            )
            if isinstance(custom_range, tuple) and len(custom_range) == 2:
                range_start = pd.Timestamp(custom_range[0])
                range_end = pd.Timestamp(custom_range[1])
            else:
                range_start, range_end = None, None
        else:
            range_start, range_end = resolve_date_range(dashboard_date_preset)

        if range_start is not None and range_end is not None:
            dashboard_boxes = dashboard_boxes[
                (dashboard_boxes["ship_date_parsed"] >= range_start)
                & (dashboard_boxes["ship_date_parsed"] <= range_end)
            ]

        dashboard_company_filter = company_filter_col.multiselect(
            "Company",
            sorted(dashboard_boxes["company"].dropna().unique()),
            key="dashboard_company_filter",
        )
        if dashboard_company_filter:
            dashboard_boxes = dashboard_boxes[
                dashboard_boxes["company"].isin(dashboard_company_filter)
            ]

        dashboard_customer_filter = customer_filter_col.multiselect(
            "Customer",
            sorted(dashboard_boxes["customer_code"].dropna().unique()),
            key="dashboard_customer_filter",
        )
        if dashboard_customer_filter:
            dashboard_boxes = dashboard_boxes[
                dashboard_boxes["customer_code"].isin(dashboard_customer_filter)
            ]

        # Actual-only financial logic (fixed with the user 2026-09-19): a box with
        # no customer invoice is entirely excluded from revenue/cost/profit (but
        # stays visible as Not Invoiced); a box WITH a customer invoice is included
        # at Revenue - Actual FedEx Cost even before FedEx has billed (FedEx Cost
        # = 0 until then) — 14 days only relabels FedEx Status, it never zeroes or
        # estimates a cost. See core.analytics.compute_profit_calculation.
        dashboard_profit = compute_profit_calculation(dashboard_boxes)
        dashboard_included = dashboard_profit[
            dashboard_profit["profit_calculation_status"] == PROFIT_INCLUDED
        ]

        dashboard_total_shipments = len(dashboard_profit)
        dashboard_missing_invoice_count = int(
            (dashboard_profit["profit_calculation_status"] == PROFIT_EXCLUDED_NO_INVOICE).sum()
        )
        dashboard_total_revenue = dashboard_profit["revenue"].sum()
        dashboard_fedex_cost_included = dashboard_profit["actual_fedex_cost"].sum()
        dashboard_fedex_cost_excluded = dashboard_profit["fedex_cost_excluded_no_invoice"].sum()
        dashboard_actual_profit = dashboard_profit["actual_profit"].sum()
        dashboard_margin = (
            dashboard_actual_profit / dashboard_total_revenue if dashboard_total_revenue else 0
        )
        dashboard_fedex_recon = compute_fedex_reconciliation(dashboard_profit, shipment_charges)
        dashboard_customer_recon = compute_customer_invoice_reconciliation(dashboard_profit)

        st.subheader("Financial Summary")
        st.caption(
            "Actual-only: a box with no customer invoice never contributes revenue, "
            "cost, or profit here — see Customer Invoice Missing below instead. A box "
            "with a customer invoice but no FedEx bill yet is still counted, at FedEx "
            "Cost = $0 until the real invoice arrives."
        )
        pl1, pl2, pl3 = st.columns(3)
        pl1.metric("Total Shipments", f"{dashboard_total_shipments:,}")
        pl2.metric("Total Customer Revenue (USD)", f"${dashboard_total_revenue:,.2f}")
        pl3.metric("FedEx Cost Included (USD)", f"${dashboard_fedex_cost_included:,.2f}")
        pl4, pl5, pl6 = st.columns(3)
        pl4.metric("Actual Gross Profit (USD)", f"${dashboard_actual_profit:,.2f}")
        pl5.metric("Profit Margin", f"{dashboard_margin:.2%}")
        pl6.metric("Customer Invoice Missing", f"{dashboard_missing_invoice_count:,}")

        with st.expander("FedEx Reconciliation", expanded=False):
            st.caption(
                "Every dollar FedEx ever billed lands in exactly one bucket below — "
                "included, excluded (no customer invoice), or unallocated (no matching "
                "box at all). The three always add up to Total FedEx Invoice."
            )
            fr1, fr2, fr3 = st.columns(3)
            fr1.metric("Total FedEx Invoice", f"${dashboard_fedex_recon['total_fedex_invoice']:,.2f}")
            fr2.metric("FedEx Cost Included", f"${dashboard_fedex_recon['included']:,.2f}")
            fr3.metric(
                "Excluded – No Customer Invoice", f"${dashboard_fedex_recon['excluded_no_customer_invoice']:,.2f}"
            )
            fr4, fr5, fr6 = st.columns(3)
            fr4.metric("Unallocated FedEx Cost", f"${dashboard_fedex_recon['unallocated']:,.2f}")
            fr5.metric("Pending FedEx Invoice (count)", f"{dashboard_fedex_recon['pending_count']:,}")
            fr6.metric("Invoice Overdue (count)", f"{dashboard_fedex_recon['overdue_count']:,}")
            if not dashboard_fedex_recon["unallocated_detail"].empty:
                st.caption("Unallocated FedEx invoice lines (no matching box/tracking):")
                render_excel_grid(
                    dashboard_fedex_recon["unallocated_detail"][
                        ["invoice_number", "tracking_id", "charge_type", "ship_date", "amount"]
                    ].reset_index(drop=True),
                    key="dashboard_unallocated_fedex_grid",
                    height=220,
                    amount_col="amount",
                    enable_selection=False,
                )

        with st.expander("Customer Invoice Reconciliation", expanded=False):
            cr1, cr2, cr3 = st.columns(3)
            cr1.metric("Total Boxes", f"{dashboard_customer_recon['total_boxes']:,}")
            cr2.metric("Customer Invoiced Boxes", f"{dashboard_customer_recon['invoiced_boxes']:,}")
            cr3.metric("Customer Invoice Missing", f"{dashboard_customer_recon['missing_boxes']:,}")
            cr4, cr5 = st.columns(2)
            cr4.metric("Revenue Included", f"${dashboard_customer_recon['revenue_included']:,.2f}")
            cr5.metric("Revenue Excluded", f"${dashboard_customer_recon['revenue_excluded']:,.2f}")
            missing_invoice_boxes = dashboard_profit[
                dashboard_profit["profit_calculation_status"] == PROFIT_EXCLUDED_NO_INVOICE
            ]
            if not missing_invoice_boxes.empty:
                st.caption("Boxes with no customer invoice on file (excluded from profit, kept visible):")
                missing_invoice_display = date_only(
                    missing_invoice_boxes[
                        [
                            "box_no", "customer_code", "tracking_id", "ship_date", "country",
                            "revenue_status", "fedex_status", "actual_fedex_cost",
                        ]
                    ].reset_index(drop=True),
                    "ship_date",
                )
                render_excel_grid(
                    missing_invoice_display,
                    key="dashboard_missing_invoice_grid",
                    height=260,
                    amount_col="actual_fedex_cost",
                    enable_selection=False,
                )

        dashboard_profit["type_category"] = dashboard_profit["shipment_type"].apply(
            lambda t: "Pallets" if normalize_shipment_type(t) == "Pallet" else "Boxes (Single/Multi)"
        )

        st.subheader("Monthly report")
        monthly_type_filter = st.radio(
            "Shipment type",
            ["All", "Boxes (Single/Multi)", "Pallets"],
            horizontal=True,
            key="dashboard_monthly_type_filter",
        )
        monthly_source_boxes = (
            dashboard_profit
            if monthly_type_filter == "All"
            else dashboard_profit[dashboard_profit["type_category"] == monthly_type_filter]
        )
        st.caption(
            "Revenue / FedEx cost / profit below are Actual-only (Included boxes — a "
            "customer invoice on file, real FedEx cost once billed, $0 until then) — "
            "missing_invoice_count and pending_fedex_count show what's excluded/still open."
        )
        monthly_rows = []
        monthly_source_with_period = monthly_source_boxes[
            monthly_source_boxes["ship_date_parsed"].notna()
        ].copy()
        monthly_source_with_period["year_month"] = monthly_source_with_period[
            "ship_date_parsed"
        ].dt.to_period("M")
        for period, month_boxes in monthly_source_with_period.groupby("year_month"):
            month_included = month_boxes[month_boxes["profit_calculation_status"] == PROFIT_INCLUDED]
            month_revenue = month_included["revenue"].sum()
            month_fedex_cost = month_included["actual_fedex_cost"].sum()
            monthly_rows.append(
                {
                    "month": period.strftime("%b %Y"),
                    "box_count": len(month_boxes),
                    "missing_invoice_count": int(
                        (month_boxes["profit_calculation_status"] == PROFIT_EXCLUDED_NO_INVOICE).sum()
                    ),
                    "pending_fedex_count": int(
                        (month_included["fedex_status"] != "Actual").sum()
                    ),
                    "revenue": month_revenue,
                    "fedex_cost": month_fedex_cost,
                    "profit": month_revenue - month_fedex_cost,
                }
            )
        monthly_report = pd.DataFrame(monthly_rows)
        render_excel_grid(
            monthly_report,
            key="dashboard_monthly_grid",
            height=340,
            show_totals_row=True,
            enable_filters=False,
            enable_selection=False,
        )

        st.subheader("Summary by country")
        st.caption("Actual-only (Included boxes — a customer invoice on file).")
        country_rows = []
        for country, group in dashboard_included.groupby("country"):
            group_revenue = group["revenue"].sum()
            group_fedex_cost = group["actual_fedex_cost"].sum()
            country_rows.append(
                {
                    "country": country,
                    "box_count": len(group),
                    "revenue": group_revenue,
                    "fedex_cost": group_fedex_cost,
                    "profit": group_revenue - group_fedex_cost,
                }
            )
        country_summary = pd.DataFrame(country_rows).sort_values(
            "profit", ascending=True
        ).reset_index(drop=True)
        if not country_summary.empty:
            render_excel_grid(
                country_summary,
                key="dashboard_country_summary_grid",
                height=250,
                show_totals_row=True,
                enable_filters=False,
                enable_selection=False,
            )

        st.subheader("Loss-making customers")
        st.caption(
            "Customers whose total Actual profit across their Included boxes is negative — "
            "FedEx cost exceeded what was invoiced to them. Boxes with no customer invoice "
            "never contribute here."
        )
        by_customer = (
            dashboard_included.groupby("customer_code")
            .agg(
                box_count=("id", "size"),
                revenue=("revenue", "sum"),
                fedex_cost=("actual_fedex_cost", "sum"),
                profit=("actual_profit", "sum"),
            )
            .reset_index()
        )
        losing_customers = by_customer[by_customer["profit"] < 0].sort_values("profit")
        if losing_customers.empty:
            st.success("No customer is currently running a net loss.")
        else:
            for _, row in losing_customers.iterrows():
                st.markdown(
                    f"- **{row['customer_code']}** — net loss of "
                    f"\\${abs(row['profit']):,.2f} across {int(row['box_count'])} box(es) "
                    f"(revenue \\${row['revenue']:,.2f}, "
                    f"FedEx charged \\${row['fedex_cost']:,.2f})"
                )

        st.subheader("Loss-making countries")
        st.caption("Same net profit breakdown, grouped by destination country.")
        by_country = (
            dashboard_included.groupby("country")
            .agg(
                box_count=("id", "size"),
                revenue=("revenue", "sum"),
                fedex_cost=("actual_fedex_cost", "sum"),
                profit=("actual_profit", "sum"),
            )
            .reset_index()
        )
        losing_countries = by_country[by_country["profit"] < 0].sort_values("profit")
        if losing_countries.empty:
            st.success("No country is currently running a net loss.")
        else:
            for _, row in losing_countries.iterrows():
                st.markdown(
                    f"- **{row['country']}** — net loss of "
                    f"\\${abs(row['profit']):,.2f} across {int(row['box_count'])} box(es) "
                    f"(revenue \\${row['revenue']:,.2f}, "
                    f"FedEx charged \\${row['fedex_cost']:,.2f})"
                )

        st.subheader("Customer Profitability")
        st.caption(
            "Actual-only, same rule as above — a customer's boxes with no invoice on "
            "file never contribute here."
        )
        dashboard_customer_table = dashboard_included.copy()
        dashboard_customer_table["customer_code"] = dashboard_customer_table["customer_code"].where(
            dashboard_customer_table["customer_code"].notna() & (dashboard_customer_table["customer_code"] != ""),
            "(Unknown Customer)",
        )
        dashboard_customer_table = (
            dashboard_customer_table.groupby("customer_code")
            .agg(
                boxes=("id", "size"),
                revenue=("revenue", "sum"),
                fedex_cost=("actual_fedex_cost", "sum"),
            )
            .reset_index()
            .rename(columns={"customer_code": "customer"})
        )
        dashboard_customer_table["profit"] = (
            dashboard_customer_table["revenue"] - dashboard_customer_table["fedex_cost"]
        )
        dashboard_customer_table["margin_percent"] = np.where(
            dashboard_customer_table["revenue"] != 0,
            dashboard_customer_table["profit"] / dashboard_customer_table["revenue"] * 100,
            None,
        )
        dashboard_customer_table = dashboard_customer_table.sort_values(
            "profit", ascending=False
        ).reset_index(drop=True)
        render_excel_grid(
            dashboard_customer_table,
            key="dashboard_customer_profitability_grid",
            height=420,
            amount_col="revenue",
            show_totals_row=True,
            enable_selection=False,
            column_width=130,
        )

elif current_page == "reconciliation":
    st.caption(
        "Every dollar FedEx billed and every dollar a customer was invoiced lands in "
        "exactly one bucket here — nothing is dropped just because it didn't match."
    )
    if boxes.empty:
        st.info("No historical box data imported yet.")
    else:
        recon_profit = compute_profit_calculation(cached_enrich_boxes(boxes))
        fedex_recon = compute_fedex_reconciliation(recon_profit, shipment_charges)
        customer_recon = compute_customer_invoice_reconciliation(recon_profit)

        st.subheader("FedEx Reconciliation")
        f1, f2, f3 = st.columns(3)
        f1.metric("Total FedEx Invoice", f"${fedex_recon['total_fedex_invoice']:,.2f}")
        f2.metric("Included", f"${fedex_recon['included']:,.2f}")
        f3.metric("Excluded – No Customer Invoice", f"${fedex_recon['excluded_no_customer_invoice']:,.2f}")
        f4, f5, f6 = st.columns(3)
        f4.metric("Unallocated", f"${fedex_recon['unallocated']:,.2f}")
        f5.metric("Pending (count)", f"{fedex_recon['pending_count']:,}")
        f6.metric("Overdue (count)", f"{fedex_recon['overdue_count']:,}")

        fedex_status_filter = st.radio(
            "Show",
            ["Matched (Actual)", "Excluded – No Customer Invoice", "Unallocated", "Pending", "Overdue"],
            horizontal=True,
            key="recon_fedex_status_filter",
        )
        box_display_cols = [
            "box_no", "customer_code", "tracking_id", "multi_no", "ship_date", "country",
            "revenue_status", "fedex_status", "profit_calculation_status",
            "actual_fedex_cost", "fedex_cost_excluded_no_invoice",
        ]
        if fedex_status_filter == "Matched (Actual)":
            fedex_detail = recon_profit[
                (recon_profit["profit_calculation_status"] == PROFIT_INCLUDED)
                & (recon_profit["fedex_status"] == "Actual")
            ][box_display_cols]
            amount_col = "actual_fedex_cost"
        elif fedex_status_filter == "Excluded – No Customer Invoice":
            fedex_detail = recon_profit[
                (recon_profit["profit_calculation_status"] == PROFIT_EXCLUDED_NO_INVOICE)
                & (recon_profit["fedex_cost_excluded_no_invoice"] > 0)
            ][box_display_cols]
            amount_col = "fedex_cost_excluded_no_invoice"
        elif fedex_status_filter == "Unallocated":
            fedex_detail = fedex_recon["unallocated_detail"][
                ["invoice_number", "tracking_id", "charge_type", "ship_date", "amount"]
            ]
            amount_col = "amount"
        elif fedex_status_filter == "Pending":
            fedex_detail = recon_profit[
                (recon_profit["profit_calculation_status"] == PROFIT_INCLUDED)
                & (recon_profit["fedex_status"] != "Actual")
            ][box_display_cols]
            amount_col = "actual_fedex_cost"
        else:
            fedex_detail = recon_profit[
                (recon_profit["profit_calculation_status"] == PROFIT_INCLUDED)
                & (recon_profit["fedex_status"] == "Invoice Overdue")
            ][box_display_cols]
            amount_col = "actual_fedex_cost"

        fedex_detail = date_only(fedex_detail.reset_index(drop=True), "ship_date")
        st.caption(f"{len(fedex_detail):,} row(s).")
        if fedex_detail.empty:
            st.success("Nothing in this bucket.")
        else:
            render_excel_grid(
                fedex_detail, key="recon_fedex_detail_grid", height=320,
                amount_col=amount_col, enable_selection=False,
            )

        st.subheader("Customer Invoice Reconciliation")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Boxes", f"{customer_recon['total_boxes']:,}")
        c2.metric("Invoiced Boxes", f"{customer_recon['invoiced_boxes']:,}")
        c3.metric("Invoice Missing", f"{customer_recon['missing_boxes']:,}")
        c4, c5 = st.columns(2)
        c4.metric("Revenue Included", f"${customer_recon['revenue_included']:,.2f}")
        c5.metric("Revenue Excluded", f"${customer_recon['revenue_excluded']:,.2f}")

        customer_status_filter = st.radio(
            "Show",
            ["Matched (Invoiced)", "Invoice Missing"],
            horizontal=True,
            key="recon_customer_status_filter",
        )
        customer_display_cols = [
            "box_no", "customer_code", "tracking_id", "ship_date", "country",
            "revenue_status", "fedex_status", "revenue", "actual_fedex_cost", "actual_profit",
        ]
        if customer_status_filter == "Matched (Invoiced)":
            customer_detail = recon_profit[
                recon_profit["profit_calculation_status"] == PROFIT_INCLUDED
            ][customer_display_cols]
        else:
            customer_detail = recon_profit[
                recon_profit["profit_calculation_status"] == PROFIT_EXCLUDED_NO_INVOICE
            ][customer_display_cols]
        customer_detail = date_only(customer_detail.reset_index(drop=True), "ship_date")
        st.caption(f"{len(customer_detail):,} row(s).")
        render_excel_grid(
            customer_detail, key="recon_customer_detail_grid", height=320,
            amount_col="revenue", enable_selection=False,
        )

elif current_page == "boxes":
    with st.expander("Add customer boxes"):
        st.caption(
            "Fields: Tarih, Hesap, Müşteri, Ülke, Kutu No, Sevkiyat Tipi, "
            "Kutu Tipi / Ebat, Multi No, Takip No. FedEx cost fields are filled in later once invoices arrive."
        )
        upload_tab, manual_tab = st.tabs(["Upload file", "Add one box"])

        with upload_tab:
            box_file = st.file_uploader(
                "Excel or CSV in the Kutular format", type=["xlsx", "csv"], key="box_import_file"
            )
            if box_file is not None:
                preview = read_box_import_file(box_file)
                st.write(f"{len(preview)} rows recognized.")
                st.dataframe(preview, use_container_width=True)
                if st.button("Import these boxes"):
                    result = import_boxes(preview)
                    st.success(
                        f"Added {result['added']} new boxes. "
                        f"Skipped {result['skipped_duplicate']} already-existing tracking numbers."
                    )

        with manual_tab:
            with st.form("add_single_box_form"):
                f1, f2, f3 = st.columns(3)
                ship_date = f1.text_input("Tarih (ship date)")
                company = f2.selectbox("Hesap (company)", ["ENRETAG", "LOGIWIX"])
                customer_code = f3.text_input("Müşteri (customer)")
                f4, f5, f6 = st.columns(3)
                country = f4.text_input("Ülke (country)")
                box_no = f5.text_input("Kutu No (box no)")
                shipment_type = f6.selectbox("Sevkiyat Tipi (shipment type)", ["Single", "Multi", "Pallet"])
                f7, f8, f9 = st.columns(3)
                box_type_size = f7.text_input("Kutu Tipi / Ebat (box type/size)")
                multi_no = f8.text_input("Multi No")
                tracking_id = f9.text_input("Takip No (tracking id)")

                if st.form_submit_button("Add box"):
                    if not tracking_id:
                        st.error("Takip No (tracking id) is required.")
                    else:
                        result = add_single_box(
                            ship_date or None,
                            company,
                            customer_code or None,
                            country or None,
                            box_no or None,
                            shipment_type,
                            box_type_size or None,
                            multi_no or None,
                            tracking_id.strip(),
                        )
                        if result["added"]:
                            st.success(f"Box {tracking_id} added.")
                        else:
                            st.warning(f"Tracking id {tracking_id} already exists — not added again.")

    if boxes.empty:
        st.info("No historical box data imported yet.")
    else:
        # Metrics render here (top of the page) even though they depend on the
        # filters below — a placeholder container reserves this visual position,
        # filled in further down once the filter values are known.
        metrics_area = st.container()

        enriched_boxes = cached_enrich_boxes(boxes)
        duty_benchmarks = cached_compute_benchmarks(enriched_boxes)
        enriched_boxes["_duty_above_average"] = cached_compute_duty_above_average_flag(
            enriched_boxes, duty_benchmarks
        )
        enriched_boxes["_shipping_above_average"] = cached_compute_shipping_above_average_flag(
            enriched_boxes, duty_benchmarks
        )

        disputed_pairs = set(
            zip(active_disputed_items_df["invoice_no"], active_disputed_items_df["tracking_id"])
        ) if not active_disputed_items_df.empty else set()
        disputed_invoice_nos = (
            set(active_disputed_items_df["invoice_no"]) if not active_disputed_items_df.empty else set()
        )

        # Auto-open a Case for boxes newly flagged as above-average on Shipping (the
        # red-highlighted rows below) so they don't have to be checked by hand one by
        # one. Checked against EVERY disputed row regardless of status, not just the
        # active ones, so a box that was already reviewed and cancelled from the
        # Disputes page stays cancelled instead of being silently reopened just
        # because it's still red.
        all_disputed_pairs = set(
            zip(disputed_items_df["invoice_no"], disputed_items_df["tracking_id"])
        ) if not disputed_items_df.empty else set()
        auto_case_candidates = enriched_boxes[enriched_boxes["_shipping_above_average"].fillna(False)]
        auto_cased = False
        for _, auto_row in auto_case_candidates.iterrows():
            auto_invoice_no = auto_row.get("fedex_shipping_invoice_no") or auto_row.get("fedex_duty_invoice_no")
            if not auto_invoice_no or pd.isna(auto_invoice_no):
                continue
            if (auto_invoice_no, auto_row["tracking_id"]) in all_disputed_pairs:
                continue
            add_disputed_items(
                auto_invoice_no,
                [(auto_row["tracking_id"], pd.to_numeric(auto_row.get("fedex_total_cost"), errors="coerce"))],
            )
            auto_cased = True
        if auto_cased:
            st.rerun()

        company_filter = st.multiselect(
            "Company", sorted(boxes["company"].dropna().unique()), key="boxes_company_filter"
        )
        col_b, col_c = st.columns(2)
        country_filter = col_b.multiselect("Country", sorted(boxes["country"].dropna().unique()))
        shipment_type_filter = col_c.multiselect(
            "Shipment type", sorted(boxes["shipment_type"].dropna().unique())
        )

        filtered_boxes = enriched_boxes
        if company_filter:
            filtered_boxes = filtered_boxes[filtered_boxes["company"].isin(company_filter)]
        if country_filter:
            filtered_boxes = filtered_boxes[filtered_boxes["country"].isin(country_filter)]
        if shipment_type_filter:
            filtered_boxes = filtered_boxes[
                filtered_boxes["shipment_type"].isin(shipment_type_filter)
            ]

        total_cost = pd.to_numeric(filtered_boxes["fedex_total_cost"], errors="coerce").sum()
        waiting_count = (filtered_boxes["fedex_total_cost"] == "Bekliyor").sum()

        with metrics_area:
            m1, m2, m3 = st.columns(3)
            m1.metric("Boxes", len(filtered_boxes))
            m2.metric("Total FedEx Cost (USD)", f"${total_cost:,.2f}")
            m3.metric("Waiting for invoice", int(waiting_count))

        st.subheader("Look up boxes by FedEx invoice number")

        # Built from enriched_boxes (not raw boxes) so box_count and invoice_amount
        # here always match what the main grid below shows for the same invoice —
        # raw boxes can under-count a Multi-box group where only one sibling
        # carries the invoice number before allocation fills in the rest.
        duty_invoices = enriched_boxes[
            ["fedex_duty_invoice_no", "company", "fedex_duty_amount", "customer_total_invoice"]
        ].dropna(
            subset=["fedex_duty_invoice_no"]
        ).rename(columns={"fedex_duty_invoice_no": "invoice_no", "fedex_duty_amount": "box_amount"})
        duty_invoices["invoice_type"] = "Duty"
        shipping_invoices = enriched_boxes[
            ["fedex_shipping_invoice_no", "company", "fedex_shipping_amount", "customer_total_invoice"]
        ].dropna(subset=["fedex_shipping_invoice_no"]).rename(
            columns={"fedex_shipping_invoice_no": "invoice_no", "fedex_shipping_amount": "box_amount"}
        )
        shipping_invoices["invoice_type"] = "Shipping"

        fedex_invoice_list = (
            pd.concat([duty_invoices, shipping_invoices])
            .groupby(["invoice_no", "invoice_type"])
            .agg(
                box_count=("company", "size"),
                invoice_amount=("box_amount", lambda s: pd.to_numeric(s, errors="coerce").sum()),
                customer_invoice=(
                    "customer_total_invoice", lambda s: pd.to_numeric(s, errors="coerce").sum()
                ),
                company=(
                    "company",
                    lambda s: s.dropna().mode().iloc[0] if not s.dropna().empty else None,
                ),
            )
            .reset_index()
        )
        # Per the user's own convention for this list: FedEx invoice total minus what
        # was billed to the customer for the same boxes — positive means the
        # customer invoice didn't cover the FedEx charge on this invoice.
        fedex_invoice_list["profit_loss"] = (
            fedex_invoice_list["invoice_amount"] - fedex_invoice_list["customer_invoice"]
        )

        if not invoices.empty:
            invoice_meta = invoices[
                ["invoice_number", "invoice_date", "due_date", "company"]
            ].rename(columns={"invoice_number": "invoice_no", "company": "pdf_company"})
            fedex_invoice_list = fedex_invoice_list.merge(invoice_meta, on="invoice_no", how="left")
            fedex_invoice_list["company"] = fedex_invoice_list["pdf_company"].fillna(
                fedex_invoice_list["company"]
            )
            fedex_invoice_list = fedex_invoice_list.drop(columns=["pdf_company"])
        else:
            fedex_invoice_list["invoice_date"] = None
            fedex_invoice_list["due_date"] = None

        if company_filter:
            fedex_invoice_list = fedex_invoice_list[
                fedex_invoice_list["company"].isin(company_filter)
            ]

        review_map = get_invoice_review_map()
        fedex_invoice_list["Approved"] = fedex_invoice_list["invoice_no"].map(
            lambda no: review_map.get(no) == "Approved"
        )

        # A Shipping invoice with at least one box under an open Case shows up here
        # in red with '(Waiting)' — Duty invoices are reviewed per box instead (the
        # blinking warning triangle in the grid below), so they're left alone here.
        fedex_invoice_list["_waiting"] = (fedex_invoice_list["invoice_type"] == "Shipping") & (
            fedex_invoice_list["invoice_no"].isin(disputed_invoice_nos)
        )

        fedex_invoice_list["invoice_type"] = fedex_invoice_list["invoice_type"].map(
            lambda t: CHARGE_TYPE_LABELS.get(t, t)
        )

        fedex_invoice_list["_invoice_date_sort"] = pd.to_datetime(
            fedex_invoice_list["invoice_date"], errors="coerce"
        )
        fedex_invoice_list = fedex_invoice_list.sort_values(
            "_invoice_date_sort", ascending=False, na_position="last"
        )

        fedex_invoice_list = fedex_invoice_list[
            [
                "invoice_no", "invoice_type", "company", "invoice_date", "due_date",
                "box_count", "invoice_amount", "customer_invoice", "profit_loss",
                "Approved", "_waiting",
            ]
        ].reset_index(drop=True)

        invoice_lookup_response = render_invoice_type_grid(
            fedex_invoice_list,
            key="fedex_invoice_lookup_grid",
            waiting_flag_column="_waiting",
            waiting_target_column="invoice_no",
        )
        selected_lookup = pd.DataFrame(invoice_lookup_response["selected_rows"])

        edited_invoice_list = pd.DataFrame(invoice_lookup_response["data"])
        if not edited_invoice_list.empty:
            for _, row in edited_invoice_list.iterrows():
                invoice_no = row["invoice_no"]
                previous_status = review_map.get(invoice_no)
                if row.get("Approved") and previous_status != "Approved":
                    set_invoice_review_status(invoice_no, review.APPROVED)

        selected_invoice_no = None
        if not selected_lookup.empty:
            selected_invoice_no = selected_lookup.iloc[0]["invoice_no"]

        grid_boxes = filtered_boxes
        if selected_invoice_no:
            grid_boxes = grid_boxes[
                (grid_boxes["fedex_duty_invoice_no"] == selected_invoice_no)
                | (grid_boxes["fedex_shipping_invoice_no"] == selected_invoice_no)
            ]
        grid_boxes = date_only(grid_boxes, "ship_date")

        def box_case_open(row):
            return (
                (row["fedex_duty_invoice_no"], row["tracking_id"]) in disputed_pairs
                or (row["fedex_shipping_invoice_no"], row["tracking_id"]) in disputed_pairs
            )

        grid_boxes = grid_boxes.copy()
        grid_boxes["Case"] = grid_boxes.apply(box_case_open, axis=1)
        grid_boxes["Case Status"] = grid_boxes["Case"].map(lambda opened: "Waiting" if opened else "")

        boxes_heading_col, boxes_download_col = st.columns([4, 1])
        boxes_heading_col.subheader("Boxes")
        boxes_download_col.download_button(
            "Download CSV",
            data=grid_boxes.to_csv(index=False).encode("utf-8-sig"),
            file_name="boxes_profit_loss.csv",
            mime="text/csv",
            key="boxes_grid_csv_download",
        )

        boxes_grid_response = render_excel_grid(
            grid_boxes,
            key="boxes_grid",
            height=985,
            amount_col="fedex_total_cost",
            checkbox_columns=["Case"],
            duty_alert_column="_duty_above_average",
            shipping_alert_column="_shipping_above_average",
            highlight_row_column="_shipping_above_average",
        )

        edited_grid_boxes = pd.DataFrame(boxes_grid_response["data"])
        if not edited_grid_boxes.empty:
            # AG-Grid's JS round-trip infers a numeric type for purely-digit tracking
            # ids, turning e.g. "876383137387" into an int — normalize back to str so
            # it still matches the TEXT tracking_id stored/compared elsewhere.
            edited_grid_boxes["tracking_id"] = edited_grid_boxes["tracking_id"].astype(str)
            # Same AG-Grid round-trip type-coercion risk as tracking_id above — force
            # both sides to plain int so a checkbox toggle is never missed (or
            # double-read) just because one side came back as e.g. a numpy int64
            # and the other as a Python/JS int. The pinned TOTAL row comes back with
            # no id at all, so drop that before casting rather than erroring on it.
            edited_grid_boxes["id"] = pd.to_numeric(edited_grid_boxes["id"], errors="coerce")
            edited_grid_boxes = edited_grid_boxes[edited_grid_boxes["id"].notna()]
            edited_grid_boxes["id"] = edited_grid_boxes["id"].astype(int)
            previously_open_ids = set(grid_boxes["id"].astype(int).loc[grid_boxes["Case"]])
            newly_opened = edited_grid_boxes[
                edited_grid_boxes["Case"] & ~edited_grid_boxes["id"].isin(previously_open_ids)
            ]
            newly_closed = edited_grid_boxes[
                ~edited_grid_boxes["Case"] & edited_grid_boxes["id"].isin(previously_open_ids)
            ]
            changed = False
            for _, row in newly_opened.iterrows():
                # Case is mainly used to dispute the Shipping charge (a box's Duty
                # side is reviewed separately via the warning triangle instead), so
                # prefer the Shipping invoice number when a box has both.
                invoice_no = row.get("fedex_shipping_invoice_no") or row.get("fedex_duty_invoice_no")
                if invoice_no and pd.notna(invoice_no):
                    add_disputed_items(
                        invoice_no,
                        [(row["tracking_id"], pd.to_numeric(row.get("fedex_total_cost"), errors="coerce"))],
                    )
                    changed = True
            for _, row in newly_closed.iterrows():
                for invoice_no in (row.get("fedex_duty_invoice_no"), row.get("fedex_shipping_invoice_no")):
                    if invoice_no and pd.notna(invoice_no) and (invoice_no, row["tracking_id"]) in disputed_pairs:
                        remove_disputed_item(invoice_no, row["tracking_id"])
                        changed = True
            if changed:
                st.rerun()

        st.subheader("Boxes missing shipment details")
        st.caption(
            "These exist only because a FedEx invoice mentioned the tracking number — "
            "their box info (company, customer, country, etc.) was never entered. "
            "Selecting an invoice above filters this list too."
        )
        missing_base_info = enriched_boxes[
            enriched_boxes["box_no"].isna() | (enriched_boxes["box_no"] == "")
        ]
        if company_filter:
            missing_base_info = missing_base_info[missing_base_info["company"].isin(company_filter)]
        if selected_invoice_no:
            missing_base_info = missing_base_info[
                (missing_base_info["fedex_duty_invoice_no"] == selected_invoice_no)
                | (missing_base_info["fedex_shipping_invoice_no"] == selected_invoice_no)
            ]
        missing_base_info_display = date_only(
            missing_base_info[
                [
                    "tracking_id", "ship_date", "fedex_duty_invoice_no",
                    "fedex_shipping_invoice_no", "fedex_total_cost",
                ]
            ].reset_index(drop=True),
            "ship_date",
        )
        if missing_base_info_display.empty:
            st.success("No boxes are missing shipment details.")
        else:
            st.download_button(
                "Download CSV",
                data=missing_base_info_display.to_csv(index=False).encode("utf-8-sig"),
                file_name="boxes_missing_shipment_details.csv",
                mime="text/csv",
                key="missing_base_info_csv_download",
            )
            render_excel_grid(
                missing_base_info_display, key="missing_base_info_grid", amount_col="fedex_total_cost"
            )

        st.subheader("Boxes missing customer invoice info")
        st.caption(
            "Box info is on file, but no customer shipping/packaging fee has been entered yet. "
            "Selecting an invoice above filters this list too."
        )
        missing_customer_fee = enriched_boxes[
            (enriched_boxes["box_no"].notna() & (enriched_boxes["box_no"] != ""))
            & enriched_boxes["customer_shipping_fee"].isna()
            & enriched_boxes["customer_packaging_fee"].isna()
        ]
        if company_filter:
            missing_customer_fee = missing_customer_fee[
                missing_customer_fee["company"].isin(company_filter)
            ]
        if selected_invoice_no:
            missing_customer_fee = missing_customer_fee[
                (missing_customer_fee["fedex_duty_invoice_no"] == selected_invoice_no)
                | (missing_customer_fee["fedex_shipping_invoice_no"] == selected_invoice_no)
            ]
        missing_customer_fee_display = date_only(
            missing_customer_fee[
                ["tracking_id", "ship_date", "company", "customer_code", "country", "fedex_total_cost"]
            ].reset_index(drop=True),
            "ship_date",
        )
        if missing_customer_fee_display.empty:
            st.success("No boxes are missing customer invoice info.")
        else:
            render_excel_grid(
                missing_customer_fee_display, key="missing_customer_fee_grid", amount_col="fedex_total_cost"
            )

        st.subheader("Tracking numbers not yet in Boxes")
        st.caption(
            "FedEx invoiced these, but they were never added to Boxes at all — add them manually "
            "via 'Add customer boxes' above. Selecting an invoice above filters this list too."
        )
        all_existing_trackings = set(enriched_boxes["tracking_id"].dropna())
        missing_trackings_source = shipment_charges
        if selected_invoice_no:
            missing_trackings_source = missing_trackings_source[
                missing_trackings_source["invoice_number"] == selected_invoice_no
            ]
        missing_rows = (
            missing_trackings_source[
                ~missing_trackings_source["tracking_id"].isin(all_existing_trackings)
            ]
            .drop_duplicates("tracking_id")[
                [
                    "invoice_number", "tracking_id", "shipment_no", "ship_date",
                    "packages", "amount", "group_amount",
                ]
            ]
            .reset_index(drop=True)
        )
        missing_rows = date_only(missing_rows, "ship_date")
        if missing_rows.empty:
            st.success("All tracking numbers from FedEx invoices are already in Boxes.")
        else:
            render_excel_grid(missing_rows, key="missing_trackings_grid", amount_col="amount")

elif current_page == "benchmarks":
    if boxes.empty:
        st.info("No historical box data imported yet.")
    else:
        st.caption(
            "Average Shipping/Duty/Total cost per box, grouped by Country + Shipment Type. "
            "A combination below the minimum sample size shows 'Not Enough Data' — "
            "this is a statistical observation, not a guarantee."
        )
        benchmarks = cached_compute_benchmarks(boxes).sort_values(["country", "shipment_type"]).reset_index(drop=True)
        render_excel_grid(benchmarks, key="benchmarks_grid", show_totals_row=False)

elif current_page == "above_average":
    if boxes.empty:
        st.info("No historical box data imported yet.")
    else:
        st.caption(
            "Boxes whose total FedEx cost is above the matching Country + Shipment Type "
            "average by more than the configured threshold. Historical pattern, not proof of error."
        )
        above_average = cached_compute_above_average_boxes(boxes)[
            [
                "id",
                "ship_date",
                "company",
                "country",
                "tracking_id",
                "shipment_type_normalized",
                "total",
                "avg_total_per_box",
                "percent_over",
                "fedex_duty_invoice_no",
                "fedex_shipping_invoice_no",
            ]
        ].reset_index(drop=True)
        above_average = date_only(above_average, "ship_date")
        st.metric("Flagged boxes", len(above_average))

        above_average_disputed_pairs = set(
            zip(active_disputed_items_df["invoice_no"], active_disputed_items_df["tracking_id"])
        ) if not active_disputed_items_df.empty else set()

        def _above_average_case_open(row):
            return (
                (row["fedex_duty_invoice_no"], row["tracking_id"]) in above_average_disputed_pairs
                or (row["fedex_shipping_invoice_no"], row["tracking_id"]) in above_average_disputed_pairs
            )

        above_average["Case"] = above_average.apply(_above_average_case_open, axis=1)
        above_average_display_cols = [
            "id", "ship_date", "company", "country", "tracking_id",
            "shipment_type_normalized", "total", "avg_total_per_box", "percent_over", "Case",
        ]
        above_average_grid_response = render_excel_grid(
            above_average[above_average_display_cols],
            key="above_average_table",
            amount_col="total",
            checkbox_columns=["Case"],
        )

        above_average_edited = pd.DataFrame(above_average_grid_response["data"])
        if not above_average_edited.empty:
            above_average_previously_open_ids = set(above_average.loc[above_average["Case"], "id"])
            above_average_newly_opened = above_average_edited[
                above_average_edited["Case"]
                & ~above_average_edited["id"].isin(above_average_previously_open_ids)
            ]
            above_average_newly_closed = above_average_edited[
                ~above_average_edited["Case"]
                & above_average_edited["id"].isin(above_average_previously_open_ids)
            ]
            above_average_changed = False
            for _, row in above_average_newly_opened.iterrows():
                source_row = above_average[above_average["id"] == row["id"]].iloc[0]
                invoice_no = source_row["fedex_shipping_invoice_no"] or source_row["fedex_duty_invoice_no"]
                if invoice_no and pd.notna(invoice_no):
                    add_disputed_items(
                        invoice_no,
                        [(source_row["tracking_id"], pd.to_numeric(source_row["total"], errors="coerce"))],
                    )
                    above_average_changed = True
            for _, row in above_average_newly_closed.iterrows():
                source_row = above_average[above_average["id"] == row["id"]].iloc[0]
                for invoice_no in (source_row["fedex_duty_invoice_no"], source_row["fedex_shipping_invoice_no"]):
                    if (
                        invoice_no
                        and pd.notna(invoice_no)
                        and (invoice_no, source_row["tracking_id"]) in above_average_disputed_pairs
                    ):
                        remove_disputed_item(invoice_no, source_row["tracking_id"])
                        above_average_changed = True
            if above_average_changed:
                st.rerun()

elif current_page == "data_quality":
    if boxes.empty:
        st.info("No historical box data imported yet.")
    else:
        st.caption("Records that need manual review — missing data, rule violations, or unusually high costs.")
        issues = cached_compute_data_issues(boxes)
        st.metric("Flagged records", len(issues))
        if not issues.empty:
            issue_type_filter = st.multiselect("Filter by issue type", sorted(issues["issue"].unique()))
            filtered_issues = issues
            if issue_type_filter:
                filtered_issues = issues[issues["issue"].isin(issue_type_filter)]

            st.caption("Select a row below to fill in its missing values.")
            display_columns = [
                "ship_date", "company", "country", "tracking_id",
                "multi_no", "fedex_total_cost", "issue",
            ]
            issue_display = date_only(filtered_issues[display_columns].reset_index(drop=True), "ship_date")
            issue_selection = st.dataframe(
                issue_display,
                use_container_width=True,
                on_select="rerun",
                selection_mode="multi-row",
                key="data_quality_table",
            )
            show_selected_sum(issue_display, issue_selection.selection.rows, "fedex_total_cost")

            selected_issue_rows = issue_selection.selection.rows
            if selected_issue_rows:
                selected_issue = filtered_issues.iloc[selected_issue_rows[0]]
                box_id = selected_issue["id"]

                st.subheader(f"Edit box {selected_issue['tracking_id']}")
                st.caption("Changes save automatically as soon as you pick or enter a value.")

                def blank_if_na(value):
                    return "" if pd.isna(value) else str(value)

                current_values = {
                    "ship_date": blank_if_na(selected_issue["ship_date"]),
                    "company": blank_if_na(selected_issue["company"]),
                    "country": blank_if_na(selected_issue["country"]),
                    "multi_no": blank_if_na(selected_issue["multi_no"]),
                }

                f1, f2, f3 = st.columns(3)
                ship_date_value = f1.text_input(
                    "Ship date", value=current_values["ship_date"], key=f"edit_ship_date_{box_id}"
                )
                company_options = ["", "ENRETAG", "LOGIWIX"]
                company_index = (
                    company_options.index(current_values["company"])
                    if current_values["company"] in company_options
                    else 0
                )
                company_value = f2.selectbox(
                    "Company", company_options, index=company_index, key=f"edit_company_{box_id}"
                )
                country_value = f3.text_input(
                    "Country", value=current_values["country"], key=f"edit_country_{box_id}"
                )
                multi_no_value = st.text_input(
                    "Multi No", value=current_values["multi_no"], key=f"edit_multi_no_{box_id}"
                )

                new_values = {
                    "ship_date": ship_date_value,
                    "company": company_value,
                    "country": country_value,
                    "multi_no": multi_no_value,
                }
                changed_fields = {
                    field: (value or None)
                    for field, value in new_values.items()
                    if value != current_values[field]
                }
                if changed_fields:
                    update_box_fields(box_id, changed_fields)
                    st.success("Saved.")
                    st.rerun()

elif current_page == "customers":
    with st.expander("Import customer invoices (CSV)"):
        st.caption(
            "Upload the customer-facing invoice export (e.g. 'invoices_manual_*.csv'). "
            "Already-imported lines are skipped automatically, so re-uploading the same "
            "file is safe."
        )
        customer_invoice_file = st.file_uploader(
            "Customer invoices CSV", type=["csv"], key="customer_invoice_csv_uploader"
        )
        if customer_invoice_file is not None:
            preview_df = read_customer_invoice_file(customer_invoice_file)
            st.write(f"{len(preview_df)} line(s) recognized.")
            if st.button("Import these invoice lines"):
                result = import_customer_invoices(preview_df)
                st.success(
                    f"Added {result['added']} new line(s). "
                    f"Skipped {result['skipped_duplicate']} already-imported line(s). "
                    f"Filled in customer fees for {result['fees_synced']} box(es)."
                )
                st.rerun()

    with st.expander("Import MOSAIC handling invoices (CSV)"):
        st.caption(
            "Upload MOSAIC's own handling/storage/shipping-fee export (Order Tracking, "
            "Handling Cost, Handling Total, etc.) — a different layout from the general "
            "customer invoice template above. Already-imported lines are skipped "
            "automatically, so re-uploading the same file is safe."
        )
        mosaic_invoice_file = st.file_uploader(
            "MOSAIC handling invoices CSV", type=["csv"], key="mosaic_handling_csv_uploader"
        )
        if mosaic_invoice_file is not None:
            mosaic_preview_df = read_mosaic_handling_file(mosaic_invoice_file)
            st.write(f"{len(mosaic_preview_df)} line(s) recognized.")
            if st.button("Import these MOSAIC invoice lines"):
                mosaic_result = import_mosaic_handling_invoices(mosaic_preview_df)
                st.success(
                    f"Added {mosaic_result['added']} new line(s). "
                    f"Skipped {mosaic_result['skipped_duplicate']} already-imported line(s). "
                    f"Filled in customer fees for {mosaic_result['fees_synced']} box(es)."
                )
                st.rerun()

    with st.expander("Export customer invoices (CSV)"):
        st.caption(
            "Exports stored customer invoice lines back out in the original "
            "'invoices_manual' template shape — ready to re-import elsewhere."
        )
        if customer_invoices.empty:
            st.info("No customer invoice data to export yet.")
        else:
            export_customer_filter = st.multiselect(
                "Customer",
                sorted(customer_invoices["customer"].dropna().unique()),
                key="customer_invoice_export_customer_filter",
            )
            export_invoice_no_filter = st.text_input(
                "Invoice number contains", key="customer_invoice_export_invoice_no_filter"
            )
            export_source = customer_invoices
            if export_customer_filter:
                export_source = export_source[export_source["customer"].isin(export_customer_filter)]
            if export_invoice_no_filter:
                export_source = export_source[
                    export_source["invoice_no"].str.contains(
                        export_invoice_no_filter, case=False, na=False
                    )
                ]
            st.write(f"{len(export_source)} line(s) match this filter.")
            export_csv = build_customer_invoice_export(export_source).to_csv(index=False)
            st.download_button(
                "Download CSV",
                data=export_csv.encode("utf-8-sig"),
                file_name="invoices_manual_export.csv",
                mime="text/csv",
                key="customer_invoice_export_download",
                disabled=export_source.empty,
            )

    if customer_invoices.empty:
        st.info("No customer invoice data imported yet.")
    else:
        customer_filter = st.multiselect(
            "Customer", sorted(customer_invoices["customer"].dropna().unique())
        )
        filtered_customers = customer_invoices
        if customer_filter:
            filtered_customers = filtered_customers[filtered_customers["customer"].isin(customer_filter)]
        st.metric("Line items", len(filtered_customers))

        st.subheader("Invoices")
        customer_invoice_list = (
            filtered_customers.groupby(["invoice_no", "customer"])
            .agg(
                invoice_date=("invoice_date", "first"),
                line_items=("item_amount", "count"),
                total_amount=("item_amount", "sum"),
            )
            .reset_index()
        )
        customer_invoice_list["_invoice_date_sort"] = pd.to_datetime(
            customer_invoice_list["invoice_date"], errors="coerce", format="mixed"
        )
        customer_invoice_list = customer_invoice_list.sort_values(
            "_invoice_date_sort", ascending=False, na_position="last"
        ).drop(columns="_invoice_date_sort").reset_index(drop=True)
        customer_invoice_list = date_only(customer_invoice_list, "invoice_date")
        customer_invoice_grid_response = render_excel_grid(
            customer_invoice_list,
            key="customer_invoice_table",
            amount_col="total_amount",
            selection_mode="single",
            double_click_to_select=True,
        )

        selected_customer_invoices_df = pd.DataFrame(
            customer_invoice_grid_response["selected_rows"]
        )
        if not selected_customer_invoices_df.empty:
            invoice_no = selected_customer_invoices_df.iloc[0]["invoice_no"]

            st.subheader(f"Tracking numbers in invoice {invoice_no}")
            invoice_line_items = customer_invoices[
                customer_invoices["invoice_no"] == invoice_no
            ][["tracking_id", "item", "item_rate", "item_amount", "shipping_date"]].reset_index(
                drop=True
            )
            invoice_line_items = date_only(invoice_line_items, "shipping_date")
            render_excel_grid(
                invoice_line_items,
                key="customer_invoice_line_items_grid",
                height=280,
                amount_col="item_amount",
            )
        else:
            filtered_customers_display = date_only(
                filtered_customers.reset_index(drop=True), "shipping_date", "invoice_date", "due_date"
            )
            all_customer_lines_selection = st.dataframe(
                filtered_customers_display, use_container_width=True,
                on_select="rerun", selection_mode="multi-row", key="all_customer_lines_table",
            )
            show_selected_sum(
                filtered_customers_display,
                all_customer_lines_selection.selection.rows,
                "item_amount",
            )

elif current_page == "browse":
    if invoices.empty:
        st.info("No PDF invoices yet. Upload a FedEx invoice PDF from the sidebar to get started.")
    else:
        st.subheader("Invoices")
        browse_company_filter = st.multiselect(
            "Customer", sorted(invoices["company"].dropna().unique()), key="browse_invoices_company_filter"
        )
        invoice_display_columns = [
            "company",
            "invoice_number",
            "invoice_date",
            "due_date",
            "invoice_amount",
            "charge_type",
            "account_number",
        ]
        invoices_sorted = invoices.copy()
        if browse_company_filter:
            invoices_sorted = invoices_sorted[invoices_sorted["company"].isin(browse_company_filter)]
        invoices_sorted["_invoice_date_sort"] = pd.to_datetime(
            invoices_sorted["invoice_date"], errors="coerce"
        )
        invoices_sorted = invoices_sorted.sort_values(
            "_invoice_date_sort", ascending=False, na_position="last"
        )
        invoices_display = invoices_sorted[
            [c for c in invoice_display_columns if c in invoices_sorted.columns]
        ].reset_index(drop=True)
        if "charge_type" in invoices_display.columns:
            invoices_display["charge_type"] = invoices_display["charge_type"].map(
                lambda t: CHARGE_TYPE_LABELS.get(t, t)
            )

        browse_review_map = get_invoice_review_map()
        disputed_invoice_nos = (
            set(active_disputed_items_df["invoice_no"]) if not active_disputed_items_df.empty else set()
        )
        invoices_display["Approved"] = invoices_display["invoice_number"].map(
            lambda no: browse_review_map.get(no) == review.APPROVED
        )
        invoices_display["_waiting"] = invoices_display["invoice_number"].isin(disputed_invoice_nos)

        invoices_grid_response = render_excel_grid(
            invoices_display,
            key="invoices_table_grid",
            amount_col="invoice_amount",
            checkbox_columns=["Approved"],
            selection_mode="single",
            waiting_flag_column="_waiting",
            waiting_target_column="invoice_number",
        )

        edited_invoices_display = pd.DataFrame(invoices_grid_response["data"])
        if not edited_invoices_display.empty:
            for _, row in edited_invoices_display.iterrows():
                invoice_no = row["invoice_number"]
                previous_status = browse_review_map.get(invoice_no)
                if row.get("Approved") and previous_status != review.APPROVED:
                    set_invoice_review_status(invoice_no, review.APPROVED)

        selected_invoices_df = pd.DataFrame(invoices_grid_response["selected_rows"])

        if not selected_invoices_df.empty:
            invoice_number = selected_invoices_df.iloc[0]["invoice_number"]

            disputed_tracking_ids_here = set(
                disputed_items_df.loc[disputed_items_df["invoice_no"] == invoice_number, "tracking_id"]
            ) if not disputed_items_df.empty else set()
            st.subheader(f"Shipments in invoice {invoice_number}")

            invoice_shipments = shipment_charges[
                shipment_charges["invoice_number"] == invoice_number
            ].reset_index(drop=True)

            browse_enriched_boxes = cached_enrich_boxes(boxes) if not boxes.empty else pd.DataFrame()
            box_lookup = browse_enriched_boxes[
                ["tracking_id", "country", "fedex_service_type", "shipment_type"]
            ].drop_duplicates("tracking_id").rename(
                columns={"shipment_type": "_real_shipment_type"}
            ) if not browse_enriched_boxes.empty else pd.DataFrame(
                columns=["tracking_id", "country", "fedex_service_type", "_real_shipment_type"]
            )
            shipment_display = invoice_shipments.merge(box_lookup, on="tracking_id", how="left")
            shipment_display["route"] = "USA -> " + shipment_display["country"].fillna("-")
            shipment_display = shipment_display.rename(
                columns={"packages": "box_count", "fedex_service_type": "shipment_type"}
            )
            shipment_display["rated_weight"] = shipment_display["rated_weight_lbs"].map(
                lambda w: f"{w:g} lbs" if pd.notna(w) else ""
            )
            shipment_display["customs_value"] = shipment_display.apply(
                lambda row: (
                    f"{row['customs_value_currency']} {row['customs_value_amount']:,.2f}"
                    if pd.notna(row.get("customs_value_amount"))
                    else ""
                ),
                axis=1,
            )
            shipment_display["Case"] = shipment_display["tracking_id"].isin(disputed_tracking_ids_here)

            # Row-level shipping alert: over the fixed Canada rate agreement (by
            # box-group size) or, elsewhere, above that country + shipment-type's
            # average per-box shipping cost. Only meaningful on a Shipping invoice.
            selected_invoice_charge_type = invoices.loc[
                invoices["invoice_number"] == invoice_number, "charge_type"
            ]
            selected_invoice_charge_type = (
                selected_invoice_charge_type.iloc[0] if not selected_invoice_charge_type.empty else None
            )
            if selected_invoice_charge_type == "Shipping" and not browse_enriched_boxes.empty:
                shipping_benchmarks = cached_compute_benchmarks(browse_enriched_boxes)
                shipment_display["_shipping_alert"] = flag_shipping_rate_alerts(
                    shipment_display, shipping_benchmarks, shipment_type_column="_real_shipment_type"
                )
            else:
                shipment_display["_shipping_alert"] = False

            shipment_display = date_only(
                shipment_display[
                    [
                        "tracking_id", "ship_date", "route", "shipment_type",
                        "box_count", "rated_weight", "customs_value", "amount", "group_amount", "Case",
                        "_shipping_alert",
                    ]
                ],
                "ship_date",
            )

            shipment_grid_response = render_excel_grid(
                shipment_display,
                key="shipments_grid",
                amount_col="amount",
                checkbox_columns=["Case"],
                highlight_row_column="_shipping_alert",
            )

            edited_shipments = pd.DataFrame(shipment_grid_response["data"])
            if not edited_shipments.empty:
                # See the same normalization in the Boxes grid above — AG-Grid's round-trip
                # can turn a purely-numeric tracking_id string into an int.
                edited_shipments["tracking_id"] = edited_shipments["tracking_id"].astype(str)
                newly_opened_shipments = edited_shipments[
                    edited_shipments["Case"]
                    & ~edited_shipments["tracking_id"].isin(disputed_tracking_ids_here)
                ]
                newly_closed_shipments = edited_shipments[
                    ~edited_shipments["Case"]
                    & edited_shipments["tracking_id"].isin(disputed_tracking_ids_here)
                ]
                shipments_changed = False
                for _, row in newly_opened_shipments.iterrows():
                    matching_source_rows = invoice_shipments[
                        invoice_shipments["tracking_id"] == row["tracking_id"]
                    ]
                    if matching_source_rows.empty:
                        st.warning(
                            f"Couldn't find box {row['tracking_id']} in this invoice's shipment "
                            "data — skipped. Try refreshing the page and checking it again."
                        )
                        continue
                    source_row = matching_source_rows.iloc[0]
                    amount_value = (
                        source_row["amount"]
                        if pd.notna(source_row["amount"])
                        else source_row["group_amount"]
                    )
                    add_disputed_items(invoice_number, [(row["tracking_id"], amount_value)])
                    shipments_changed = True
                for _, row in newly_closed_shipments.iterrows():
                    remove_disputed_item(invoice_number, row["tracking_id"])
                    shipments_changed = True
                if shipments_changed:
                    st.rerun()

            selected_rows_df = pd.DataFrame(shipment_grid_response["selected_rows"])
            if not selected_rows_df.empty:
                selected_tracking_ids = set(selected_rows_df["tracking_id"].astype(str))
                selected_shipment_rows = invoice_shipments[
                    invoice_shipments["tracking_id"].isin(selected_tracking_ids)
                ].index.tolist()
            else:
                selected_shipment_rows = []
            if selected_shipment_rows:
                selected_shipment = invoice_shipments.iloc[selected_shipment_rows[0]]
                tracking_id = selected_shipment["tracking_id"]

                st.subheader(f"Products in box {tracking_id}")
                box_products = products[products["tracking_id"] == tracking_id]
                if box_products.empty:
                    st.write("No product detail found for this box.")
                else:
                    if box_products["value_for_duty"].isna().all():
                        st.caption(
                            "Value for Duty isn't available for this invoice — it's only captured for "
                            "invoices ingested after this feature was added. Re-upload the original PDF "
                            "to backfill it."
                        )
                    render_excel_grid(
                        box_products[
                            ["hs_code", "description", "quantity", "country_of_origin", "value_for_duty"]
                        ].reset_index(drop=True),
                        key="box_products_grid",
                        amount_col="value_for_duty",
                    )

            invoice_products = products[products["invoice_number"] == invoice_number]
            if not invoice_products.empty:
                st.subheader(f"Products in invoice {invoice_number}")
                if invoice_products["value_for_duty"].isna().all():
                    st.caption(
                        "Value for Duty isn't available for this invoice — it's only captured for "
                        "invoices ingested after this feature was added. Re-upload the original PDF "
                        "to backfill it."
                    )
                render_excel_grid(
                    invoice_products[
                        ["tracking_id", "hs_code", "description", "quantity", "country_of_origin", "value_for_duty"]
                    ].reset_index(drop=True),
                    key="invoice_products_grid",
                    amount_col="value_for_duty",
                )

                invoice_product_totals = invoice_products.copy()
                invoice_product_totals["quantity"] = pd.to_numeric(
                    invoice_product_totals["quantity"], errors="coerce"
                )
                invoice_product_totals["value_for_duty"] = pd.to_numeric(
                    invoice_product_totals["value_for_duty"], errors="coerce"
                )
                summary_by_product = (
                    invoice_product_totals.groupby("description")
                    .agg(
                        total_quantity=("quantity", "sum"),
                        value_for_duty=("value_for_duty", "sum"),
                        box_count=("tracking_id", "nunique"),
                    )
                    .reset_index()
                    .sort_values("total_quantity", ascending=False)
                )
                st.caption("Summary by product across this invoice")
                render_excel_grid(
                    summary_by_product,
                    key="invoice_products_summary_grid",
                    amount_col="value_for_duty",
                    show_totals_row=False,
                )

elif current_page == "all_charges":
    if shipment_charges.empty:
        st.info("No PDF invoices yet.")
    else:
        charge_type_filter = st.multiselect(
            "Filter by charge type",
            options=sorted(shipment_charges["charge_type"].dropna().unique()),
            default=None,
        )
        filtered = shipment_charges
        if charge_type_filter:
            filtered = filtered[filtered["charge_type"].isin(charge_type_filter)]

        all_charges_enriched_boxes = cached_enrich_boxes(boxes) if not boxes.empty else pd.DataFrame()
        all_charges_box_lookup = all_charges_enriched_boxes[
            ["tracking_id", "country", "shipment_type"]
        ].drop_duplicates("tracking_id") if not all_charges_enriched_boxes.empty else pd.DataFrame(
            columns=["tracking_id", "country", "shipment_type"]
        )
        filtered_with_lookup = filtered.merge(all_charges_box_lookup, on="tracking_id", how="left")

        # Row-level shipping alert: over the fixed Canada rate agreement (by
        # box-group size) or, elsewhere, above that country + shipment-type's
        # average per-box shipping cost. Duty/Pickup rows are never flagged here.
        is_shipping_row = filtered_with_lookup["charge_type"] == "Shipping"
        if is_shipping_row.any() and not all_charges_enriched_boxes.empty:
            shipping_alert_input = filtered_with_lookup.rename(columns={"packages": "box_count"})
            all_charges_benchmarks = cached_compute_benchmarks(all_charges_enriched_boxes)
            shipping_alerts = flag_shipping_rate_alerts(shipping_alert_input, all_charges_benchmarks)
            filtered_with_lookup["_shipping_alert"] = shipping_alerts & is_shipping_row.values
        else:
            filtered_with_lookup["_shipping_alert"] = False

        filtered_charges_display = filtered_with_lookup[
            [
                "invoice_number",
                "charge_type",
                "tracking_id",
                "shipment_no",
                "ship_date",
                "packages",
                "amount",
                "group_amount",
                "group_id",
                "_shipping_alert",
            ]
        ].reset_index(drop=True)
        filtered_charges_display = date_only(filtered_charges_display, "ship_date")

        def _highlight_shipping_alert(row):
            style = "background-color: #FFD7D7; color: #7F1D1D" if row["_shipping_alert"] else ""
            return [style] * len(row)

        display_columns = [c for c in filtered_charges_display.columns if c != "_shipping_alert"]
        styled_charges_display = filtered_charges_display.style.apply(
            _highlight_shipping_alert, axis=1
        ).hide(axis="columns", subset=["_shipping_alert"])

        all_charges_selection = st.dataframe(
            styled_charges_display,
            use_container_width=True,
            on_select="rerun",
            selection_mode="multi-row",
            key="all_charges_table",
        )
        show_selected_sum(
            filtered_charges_display,
            all_charges_selection.selection.rows,
            "amount",
            "group_id",
            "group_amount",
        )

elif current_page == "disputes":
    st.caption(
        "Only the specific boxes you checked 'Case' (in Boxes Historical or Browse Invoices) "
        "show up here — not every box on their invoice."
    )

    disputes_page_boxes = cached_enrich_boxes(boxes)
    case_duty_invoices = disputes_page_boxes[
        ["fedex_duty_invoice_no", "company", "fedex_duty_amount", "customer_total_invoice"]
    ].dropna(subset=["fedex_duty_invoice_no"]).rename(
        columns={"fedex_duty_invoice_no": "invoice_no", "fedex_duty_amount": "box_amount"}
    )
    case_duty_invoices["invoice_type"] = "Duty"
    case_shipping_invoices = disputes_page_boxes[
        ["fedex_shipping_invoice_no", "company", "fedex_shipping_amount", "customer_total_invoice"]
    ].dropna(subset=["fedex_shipping_invoice_no"]).rename(
        columns={"fedex_shipping_invoice_no": "invoice_no", "fedex_shipping_amount": "box_amount"}
    )
    case_shipping_invoices["invoice_type"] = "Shipping"

    case_invoice_list = (
        pd.concat([case_duty_invoices, case_shipping_invoices])
        .groupby(["invoice_no", "invoice_type"])
        .agg(
            box_count=("company", "size"),
            invoice_amount=("box_amount", lambda s: pd.to_numeric(s, errors="coerce").sum()),
            customer_invoice=(
                "customer_total_invoice", lambda s: pd.to_numeric(s, errors="coerce").sum()
            ),
            company=(
                "company",
                lambda s: s.dropna().mode().iloc[0] if not s.dropna().empty else None,
            ),
        )
        .reset_index()
    )
    case_invoice_list["profit_loss"] = (
        case_invoice_list["invoice_amount"] - case_invoice_list["customer_invoice"]
    )

    # Only invoices that currently have at least one box under an active Case —
    # this is the "Cases" list, not every FedEx invoice ever seen.
    active_case_invoice_nos = (
        set(active_disputed_items_df["invoice_no"]) if not active_disputed_items_df.empty else set()
    )
    case_invoice_list = case_invoice_list[case_invoice_list["invoice_no"].isin(active_case_invoice_nos)]

    if not invoices.empty:
        case_invoice_meta = invoices[["invoice_number", "invoice_date", "due_date", "company"]].rename(
            columns={"invoice_number": "invoice_no", "company": "pdf_company"}
        )
        case_invoice_list = case_invoice_list.merge(case_invoice_meta, on="invoice_no", how="left")
        case_invoice_list["company"] = case_invoice_list["pdf_company"].fillna(case_invoice_list["company"])
        case_invoice_list = case_invoice_list.drop(columns=["pdf_company"])
    else:
        case_invoice_list["invoice_date"] = None
        case_invoice_list["due_date"] = None

    case_review_map = get_invoice_review_map()
    case_invoice_list["Approved"] = case_invoice_list["invoice_no"].map(
        lambda no: case_review_map.get(no) == "Approved"
    )
    case_invoice_list["invoice_type"] = case_invoice_list["invoice_type"].map(
        lambda t: CHARGE_TYPE_LABELS.get(t, t)
    )
    case_invoice_list["_invoice_date_sort"] = pd.to_datetime(
        case_invoice_list["invoice_date"], errors="coerce"
    )
    case_invoice_list = case_invoice_list.sort_values(
        "_invoice_date_sort", ascending=False, na_position="last"
    )
    case_invoice_list = case_invoice_list[
        [
            "invoice_no", "invoice_type", "company", "invoice_date", "due_date",
            "box_count", "invoice_amount", "customer_invoice", "profit_loss", "Approved",
        ]
    ].reset_index(drop=True)

    st.subheader("Cases — FedEx Invoices Under Dispute")
    st.caption(
        "Every FedEx invoice with at least one box under an open Case — filter by company, "
        "date, or amount here. Check 'Approved' once you've reviewed and approved pursuing "
        "it; it then moves down to 'Approved Cases'."
    )
    pending_case_invoices = case_invoice_list[~case_invoice_list["Approved"]].reset_index(drop=True)
    approved_case_invoices = case_invoice_list[case_invoice_list["Approved"]].reset_index(drop=True)

    if pending_case_invoices.empty:
        st.success("No pending cases to review.")
    else:
        case_review_response = render_excel_grid(
            pending_case_invoices,
            key="disputes_case_review_grid",
            amount_col="invoice_amount",
            checkbox_columns=["Approved"],
            enable_selection=False,
        )
        edited_case_review = pd.DataFrame(case_review_response["data"])
        changed_case_review = False
        for _, row in edited_case_review.iterrows():
            if row.get("Approved") and case_review_map.get(row["invoice_no"]) != "Approved":
                set_invoice_review_status(row["invoice_no"], review.APPROVED)
                changed_case_review = True
        if changed_case_review:
            st.rerun()

    disputed_items = disputed_items_df
    if disputed_items.empty:
        st.info("No disputed boxes yet. Check the 'Case' box next to a box to add it here.")
    else:
        box_detail_lookup = boxes[
            [
                "tracking_id", "company", "customer_code", "country", "shipment_type",
                "multi_no", "box_type_size", "fedex_service_type", "ship_date",
            ]
        ].drop_duplicates("tracking_id")
        disputed_display = disputed_items.merge(box_detail_lookup, on="tracking_id", how="left")
        weight_value_lookup = shipment_charges[
            ["tracking_id", "rated_weight_lbs", "customs_value_currency", "customs_value_amount"]
        ].drop_duplicates("tracking_id")
        disputed_display = disputed_display.merge(weight_value_lookup, on="tracking_id", how="left")
        disputed_display["rated_weight"] = disputed_display["rated_weight_lbs"].map(
            lambda w: f"{w:g} lbs" if pd.notna(w) else ""
        )
        disputed_display["customs_value"] = disputed_display.apply(
            lambda row: (
                f"{row['customs_value_currency']} {row['customs_value_amount']:,.2f}"
                if pd.notna(row.get("customs_value_amount"))
                else ""
            ),
            axis=1,
        )
        disputed_display = date_only(disputed_display, "ship_date")
        disputed_display = disputed_display.rename(columns={"multi_no": "master_tracking"})
        st.caption(
            "FedEx only reports 'Rated Weight' (the billed weight) per box, not actual scale weight — "
            "shown below where FedEx's invoice included it. Same for declared customs value. "
            "'Master Tracking' is the Multi shipment's lead tracking number, if this box belongs to one."
        )

        active_disputed_display = disputed_display[disputed_display["status"] == "Active"]
        cancelled_disputed_display = disputed_display[disputed_display["status"] == "Cancelled"]

        st.subheader("Open Disputes")
        if active_disputed_display.empty:
            st.info("No open disputes.")
        else:
            total_disputed = pd.to_numeric(active_disputed_display["amount"], errors="coerce").sum()
            d1, d2 = st.columns(2)
            d1.metric("Disputed invoices", active_disputed_display["invoice_no"].nunique())
            d2.metric("Total disputed amount (USD)", f"${total_disputed:,.2f}")

            disputes_export_columns = active_disputed_display[
                [
                    "invoice_no", "tracking_id", "master_tracking", "company", "customer_code",
                    "country", "shipment_type", "box_type_size", "fedex_service_type", "ship_date",
                    "rated_weight", "customs_value", "amount", "added_at",
                ]
            ]
            st.download_button(
                "Download CSV",
                data=disputes_export_columns.to_csv(index=False).encode("utf-8-sig"),
                file_name="disputes_open.csv",
                mime="text/csv",
                key="disputes_open_csv_download",
            )

            disputes_grid_response = render_excel_grid(
                disputes_export_columns,
                key="disputed_items_grid",
                amount_col="amount",
            )

            st.caption("Check the box next to one or more rows above, then cancel their Case.")
            selected_disputed_rows = pd.DataFrame(disputes_grid_response["selected_rows"])
            if not selected_disputed_rows.empty:
                selected_disputed_rows["tracking_id"] = selected_disputed_rows["tracking_id"].astype(str)

            add_cancel_note = st.checkbox("Add a cancellation note (optional)", key="disputes_add_cancel_note")
            cancel_note = (
                st.text_input("Cancellation note", key="disputes_cancel_note") if add_cancel_note else ""
            )

            if not selected_disputed_rows.empty and st.button("Cancel selected Case(s)"):
                pairs = list(zip(selected_disputed_rows["invoice_no"], selected_disputed_rows["tracking_id"]))
                cancel_disputed_items(pairs, reason=(cancel_note.strip() or None) if add_cancel_note else None)
                st.success(f"Cancelled {len(pairs)} case(s).")
                st.rerun()

        st.subheader("Cancelled Disputes")
        if cancelled_disputed_display.empty:
            st.caption("No cancelled disputes yet.")
        else:
            cancelled_export_columns = cancelled_disputed_display[
                [
                    "invoice_no", "tracking_id", "master_tracking", "company", "customer_code",
                    "country", "shipment_type", "box_type_size", "fedex_service_type", "ship_date",
                    "amount", "added_at", "cancel_reason", "cancelled_at",
                ]
            ]
            st.download_button(
                "Download CSV",
                data=cancelled_export_columns.to_csv(index=False).encode("utf-8-sig"),
                file_name="disputes_cancelled.csv",
                mime="text/csv",
                key="disputes_cancelled_csv_download",
            )
            render_excel_grid(
                cancelled_export_columns,
                key="cancelled_disputed_items_grid",
                amount_col="amount",
                enable_selection=False,
            )

    st.subheader("Approved Cases")
    st.caption("Invoices you've reviewed and approved to formally dispute with FedEx.")
    if approved_case_invoices.empty:
        st.caption("No approved cases yet.")
    else:
        render_excel_grid(
            approved_case_invoices,
            key="disputes_approved_cases_grid",
            amount_col="invoice_amount",
            enable_selection=False,
        )

elif current_page == "refunds":
    st.caption(
        "Track refunds issued to customers — shipping, label, packaging, and overcharge "
        "refunds — separate from the FedEx dispute (Case) workflow, which tracks money "
        "clawed back from FedEx rather than money given back to a customer."
    )

    with st.expander("Add Refund", expanded=refunds_df.empty):
        rf_tracking_id = st.text_input(
            "Tracking Number (optional)",
            key="refund_tracking_lookup",
            help="Enter a tracking number to auto-fill the customer and box number below.",
        )
        rf_lookup_box = None
        if rf_tracking_id.strip():
            rf_lookup_match = boxes[boxes["tracking_id"] == rf_tracking_id.strip()]
            if not rf_lookup_match.empty:
                rf_lookup_box = rf_lookup_match.iloc[0]
                st.caption(
                    f"Found: {rf_lookup_box.get('customer_code') or '—'} · "
                    f"{rf_lookup_box.get('company') or '—'} · "
                    f"Box {rf_lookup_box.get('box_no') or '—'}"
                )
            else:
                st.caption("No matching box found for this tracking number — fill in the fields manually.")

        with st.form("add_refund_form", clear_on_submit=True):
            rf2, rf3 = st.columns(2)
            rf_box_no = rf2.text_input(
                "Order ID / Box Number",
                value=(
                    rf_lookup_box["box_no"]
                    if rf_lookup_box is not None and pd.notna(rf_lookup_box["box_no"])
                    else ""
                ),
            )
            rf_customer_code = rf3.text_input(
                "Customer",
                value=(
                    rf_lookup_box["customer_code"]
                    if rf_lookup_box is not None and pd.notna(rf_lookup_box["customer_code"])
                    else ""
                ),
            )

            rf4, rf5, rf6 = st.columns(3)
            rf_refund_type = rf4.selectbox("Refund Type", REFUND_TYPES)
            rf_refund_amount = rf5.number_input(
                "Refund Amount (USD)", min_value=0.0, step=0.01, format="%.2f"
            )
            rf_refund_date = rf6.date_input("Refund Date", value=datetime.date.today())

            rf7, rf8, rf9 = st.columns(3)
            rf_related_invoice = rf7.text_input("Related Invoice No.")
            rf_approved_by = rf8.text_input("Approved By")
            rf_status = rf9.selectbox("Status", REFUND_STATUSES)

            rf_reason = st.text_area("Reason")
            rf_notes = st.text_area("Notes")

            if st.form_submit_button("Add Refund"):
                if rf_refund_amount <= 0:
                    st.error("Refund amount must be greater than 0.")
                else:
                    add_refund(
                        {
                            "tracking_id": rf_tracking_id.strip() or None,
                            "box_no": rf_box_no.strip() or None,
                            "customer_code": rf_customer_code.strip() or None,
                            "refund_type": rf_refund_type,
                            "refund_amount": rf_refund_amount,
                            "reason": rf_reason.strip() or None,
                            "related_invoice_no": rf_related_invoice.strip() or None,
                            "refund_date": rf_refund_date.isoformat(),
                            "approved_by": rf_approved_by.strip() or None,
                            "status": rf_status,
                            "notes": rf_notes.strip() or None,
                        }
                    )
                    st.session_state["refund_tracking_lookup"] = ""
                    st.success("Refund added.")
                    st.rerun()

    if refunds_df.empty:
        st.info("No refunds recorded yet.")
    else:
        total_refunds = len(refunds_df)
        total_refund_amount = pd.to_numeric(refunds_df["refund_amount"], errors="coerce").sum()
        pending_amount = pd.to_numeric(
            refunds_df.loc[refunds_df["status"] == "Pending", "refund_amount"], errors="coerce"
        ).sum()
        completed_count = int((refunds_df["status"] == "Completed").sum())

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Refunds", total_refunds)
        m2.metric("Total Refund Amount", f"${total_refund_amount:,.2f}")
        m3.metric("Pending Amount", f"${pending_amount:,.2f}")
        m4.metric("Completed", completed_count)

        st.markdown("**Refund amount by revenue line item**")
        by_line = (
            refunds_df.assign(
                revenue_line=refunds_df["refund_type"]
                .map(REFUND_TYPE_REVENUE_LINE)
                .fillna("customer_total_invoice")
            )
            .groupby("revenue_line")["refund_amount"]
            .sum()
            .reset_index()
            .rename(columns={"revenue_line": "Revenue line", "refund_amount": "Refund total"})
        )
        st.dataframe(by_line, hide_index=True, use_container_width=True)

        rfilter1, rfilter2, rfilter3 = st.columns(3)
        status_filter = rfilter1.multiselect("Status", REFUND_STATUSES, key="refunds_status_filter")
        type_filter = rfilter2.multiselect("Refund Type", REFUND_TYPES, key="refunds_type_filter")
        customer_options = sorted(refunds_df["customer_code"].dropna().unique().tolist())
        customer_filter = rfilter3.multiselect("Customer", customer_options, key="refunds_customer_filter")

        filtered_refunds = refunds_df.copy()
        if status_filter:
            filtered_refunds = filtered_refunds[filtered_refunds["status"].isin(status_filter)]
        if type_filter:
            filtered_refunds = filtered_refunds[filtered_refunds["refund_type"].isin(type_filter)]
        if customer_filter:
            filtered_refunds = filtered_refunds[filtered_refunds["customer_code"].isin(customer_filter)]

        filtered_refunds = date_only(filtered_refunds, "refund_date")

        refunds_display = filtered_refunds[
            [
                "id", "refund_date", "customer_code", "tracking_id", "box_no",
                "refund_type", "refund_amount", "status", "related_invoice_no",
                "approved_by", "reason", "notes",
            ]
        ]

        st.download_button(
            "Download CSV",
            data=refunds_display.to_csv(index=False).encode("utf-8-sig"),
            file_name="refunds.csv",
            mime="text/csv",
            key="refunds_csv_download",
        )

        refunds_grid_response = render_excel_grid(
            refunds_display,
            key="refunds_grid",
            amount_col="refund_amount",
        )

        st.caption("Check the box next to one or more rows above to update their status or delete them.")
        selected_refund_rows = pd.DataFrame(refunds_grid_response["selected_rows"])
        if not selected_refund_rows.empty:
            action_col1, action_col2, action_col3 = st.columns([2, 1, 1])
            new_status = action_col1.selectbox("Set status to", REFUND_STATUSES, key="refund_status_action")
            if action_col2.button("Apply Status"):
                for _, row in selected_refund_rows.iterrows():
                    set_refund_status(int(row["id"]), new_status)
                st.success(f"Updated {len(selected_refund_rows)} refund(s) to {new_status}.")
                st.rerun()
            if action_col3.button("Delete Selected"):
                for _, row in selected_refund_rows.iterrows():
                    delete_refund(int(row["id"]))
                st.success(f"Deleted {len(selected_refund_rows)} refund(s).")
                st.rerun()

elif current_page == "reports":
    st.caption("Ready-made report exports for managers and accounting.")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Monthly Report", "Coming soon")
    r2.metric("Company Report", "Coming soon")
    r3.metric("Country Report", "Coming soon")
    r4.metric("Excel / PDF Export", "Coming soon")
    st.info(
        "One-click PDF/Excel/CSV report generation and archiving isn't built yet — "
        "for now, use the Dashboard, Boxes, and Browse Invoices tabs, whose grids can "
        "already be exported by selecting rows and copying, or via each grid's own "
        "download icon."
    )

elif current_page == "settings":
    st.caption("Application settings.")
    st.info("Coming soon — configurable invoice waiting period, thresholds, and company list.")
