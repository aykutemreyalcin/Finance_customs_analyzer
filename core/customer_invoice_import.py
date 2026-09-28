import re

import numpy as np
import pandas as pd

from core.database import get_connection, init_db
from core.dates import to_customer_invoice_date

# The original template's exact column order — used to export customer_invoices
# rows back out in the same shape they were imported in.
EXPORT_COLUMNS = [
    "*InvoiceNo", "*Customer", "*InvoiceDate", "*DueDate", "Terms", "Location",
    "Memo", "Item(Product/Service)", "ItemDescription", "ItemQuantity", "ItemRate",
    "*ItemAmount", "Currency", "Ship via", "Shipping date", "Tracking no.",
    "Shipping Charge", "Service Date",
]

# Maps the QuickBooks-style "invoices_manual" CSV export headers to our
# customer_invoices schema. Matched by exact header name (after normalizing away
# case, whitespace, and punctuation — e.g. both '*InvoiceNo' and 'Invoice No' and
# 'invoiceno' end up as the same 'invoiceno' key), not position, since the
# template's own column names/order/count vary across exports (a simplified
# 'shipment_finance_*.csv' export drops the '*' markers and adds spaces, and
# doesn't include every column — that's fine, unmapped ones are just skipped).
COLUMN_MAP = {
    "invoiceno": "invoice_no",
    "customer": "customer",
    "invoicedate": "invoice_date",
    "duedate": "due_date",
    "memo": "memo",
    "itemproductservice": "item",
    "itemdescription": "tracking_id",
    "itemrate": "item_rate",
    "itemamount": "item_amount",
    "currency": "currency",
    "shipvia": "ship_via",
    "shippingdate": "shipping_date",
}

REQUIRED_FIELD = "invoice_no"


def _normalize_header(header):
    return re.sub(r"[^a-z0-9]", "", str(header).strip().lower())


def read_customer_invoice_file(file):
    """Reads the customer-facing 'invoices_manual' CSV export. The template's
    ItemDescription column is where the tracking number is actually recorded
    for each line (a free-text field repurposed for that), not its own
    'Tracking no.' column, which in practice holds a billing-period string."""
    raw = pd.read_csv(file, dtype=str)

    rename_map = {}
    for col in raw.columns:
        mapped = COLUMN_MAP.get(_normalize_header(col))
        if mapped:
            rename_map[col] = mapped

    df = raw.rename(columns=rename_map)
    df = df.loc[:, ~df.columns.duplicated()]
    known_fields = list(dict.fromkeys(COLUMN_MAP.values()))
    df = df[[c for c in known_fields if c in df.columns]]
    if "tracking_id" in df.columns:
        df["tracking_id"] = df["tracking_id"].str.strip()
    df = df.dropna(subset=[REQUIRED_FIELD]) if REQUIRED_FIELD in df.columns else df.iloc[0:0]
    return df


def sync_customer_fees_from_invoices(connection, tracking_ids=None):
    """Fills in a box's customer_shipping_fee/customer_packaging_fee from its
    customer_invoices line items — but only while both are still empty, so this
    never overwrites fee data that came from elsewhere (e.g. the legacy Excel
    import). Items ending in 'Shipping Fee' (CA:Shipping Fee, US:Shipping Fee,
    etc.) form the shipping bucket; everything else (Box Fee, Label, Polybag,
    Repack, Handling Fee, Storage Fee, ...) is bucketed as packaging. Pass
    tracking_ids to limit the scan to boxes just touched by an import; omit it
    to backfill every box that has invoice lines on file."""
    query = "SELECT tracking_id, item, item_amount FROM customer_invoices WHERE tracking_id IS NOT NULL"
    params = []
    if tracking_ids is not None:
        tracking_ids = [t for t in dict.fromkeys(tracking_ids) if t]
        if not tracking_ids:
            return 0
        query += f" AND tracking_id IN ({','.join('?' for _ in tracking_ids)})"
        params = tracking_ids

    rows = connection.execute(query, params).fetchall()
    if not rows:
        return 0

    lines = pd.DataFrame(rows, columns=["tracking_id", "item", "item_amount"])
    lines["item_amount"] = pd.to_numeric(lines["item_amount"], errors="coerce").fillna(0)
    lines["is_shipping"] = lines["item"].fillna("").str.strip().str.lower().str.endswith("shipping fee")

    totals = lines.groupby(["tracking_id", "is_shipping"])["item_amount"].sum().unstack(fill_value=0)

    updated = 0
    for tracking_id, totals_row in totals.iterrows():
        existing = connection.execute(
            "SELECT customer_shipping_fee, customer_packaging_fee FROM boxes WHERE tracking_id = ?",
            (tracking_id,),
        ).fetchone()
        if existing is None or existing[0] is not None or existing[1] is not None:
            continue
        connection.execute(
            "UPDATE boxes SET customer_shipping_fee = ?, customer_packaging_fee = ? WHERE tracking_id = ?",
            (float(totals_row.get(True, 0)), float(totals_row.get(False, 0)), tracking_id),
        )
        updated += 1
    return updated


def import_customer_invoices(df):
    """Appends new customer invoice lines — never wipes existing data. A line is
    treated as a duplicate (and skipped) if the same invoice_no + item + tracking_id
    + item_amount was already recorded, so re-uploading the same export is safe.
    Also fills in customer_shipping_fee/customer_packaging_fee on any newly-touched
    box that didn't have them yet."""
    connection = get_connection()
    init_db(connection)

    existing = {
        (row[0], row[1], row[2], row[3])
        for row in connection.execute(
            "SELECT invoice_no, item, tracking_id, item_amount FROM customer_invoices"
        )
    }

    added = 0
    skipped_duplicate = 0
    touched_tracking_ids = set()

    for _, row in df.iterrows():
        item_amount = pd.to_numeric(row.get("item_amount"), errors="coerce")
        item_amount = None if pd.isna(item_amount) else float(item_amount)
        item_rate = pd.to_numeric(row.get("item_rate"), errors="coerce")
        item_rate = None if pd.isna(item_rate) else float(item_rate)

        key = (row.get("invoice_no"), row.get("item"), row.get("tracking_id"), item_amount)
        if key in existing:
            skipped_duplicate += 1
            continue

        connection.execute(
            """
            INSERT INTO customer_invoices (
                invoice_no, customer, invoice_date, due_date, memo, item,
                tracking_id, item_rate, item_amount, currency, ship_via, shipping_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("invoice_no"),
                row.get("customer"),
                to_customer_invoice_date(row.get("invoice_date")),
                to_customer_invoice_date(row.get("due_date")),
                row.get("memo"),
                row.get("item"),
                row.get("tracking_id"),
                item_rate,
                item_amount,
                row.get("currency"),
                row.get("ship_via"),
                to_customer_invoice_date(row.get("shipping_date")),
            ),
        )
        existing.add(key)
        touched_tracking_ids.add(row.get("tracking_id"))
        added += 1

    fees_synced = sync_customer_fees_from_invoices(connection, touched_tracking_ids)

    connection.commit()
    connection.close()
    return {"added": added, "skipped_duplicate": skipped_duplicate, "fees_synced": fees_synced}


def read_mosaic_handling_file(file):
    """Reads MOSAIC's own handling/storage/shipping-fee export — a different shape
    entirely from the QuickBooks 'invoices_manual' template (no *Customer column,
    since the whole file is always MOSAIC; the item/service code is an unlabeled
    trailing column). Order Tracking maps to our tracking_id; many lines (pallet/box/
    container receiving, storage fees) have no tracking number at all and are still
    kept, since they're real billable charges."""
    raw = pd.read_csv(file, dtype=str)

    df = pd.DataFrame(index=raw.index)
    df["invoice_no"] = raw["*InvoiceNo"]
    df["customer"] = "MOSAIC"
    df["invoice_date"] = raw["Order Date"]
    df["due_date"] = raw["Order Date"]
    memo_parts = raw[["Order No", "Store Address", "PRODUCT TITTLE"]].fillna("")
    df["memo"] = (
        memo_parts["Order No"] + " " + memo_parts["Store Address"] + " — " + memo_parts["PRODUCT TITTLE"]
    ).str.strip(" —")
    df["item"] = raw.iloc[:, -1]
    df["tracking_id"] = raw["Order Tracking"].where(raw["Order Tracking"].notna(), None)
    df["item_rate"] = raw["HANDLING COST"]
    df["item_amount"] = raw["HANDLING TOTAL"].astype(str).str.replace(",", "", regex=False)
    df["currency"] = "USD"
    df["ship_via"] = None
    df["shipping_date"] = raw["Order Date"]
    df = df.dropna(subset=[REQUIRED_FIELD])
    return df


def import_mosaic_handling_invoices(df):
    """Same append-only behavior as import_customer_invoices, but dedups by
    occurrence count within the (invoice_no, item, tracking_id, item_amount) group
    instead of plain set-membership. MOSAIC's export legitimately repeats that exact
    combination on separate order lines (e.g. three identical $5 'DIY Home Kit'
    charges with no tracking number) — a plain set would wrongly collapse those
    into one, while still needing to skip real re-uploads of the same file."""
    connection = get_connection()
    init_db(connection)

    existing_counts = {}
    for row in connection.execute(
        "SELECT invoice_no, item, tracking_id, item_amount FROM customer_invoices WHERE customer = 'MOSAIC'"
    ):
        existing_counts[row] = existing_counts.get(row, 0) + 1

    seen_counts = {}
    added = 0
    skipped_duplicate = 0
    touched_tracking_ids = set()

    for _, row in df.iterrows():
        item_amount = pd.to_numeric(row.get("item_amount"), errors="coerce")
        item_amount = None if pd.isna(item_amount) else float(item_amount)
        item_rate = pd.to_numeric(row.get("item_rate"), errors="coerce")
        item_rate = None if pd.isna(item_rate) else float(item_rate)

        key = (row.get("invoice_no"), row.get("item"), row.get("tracking_id"), item_amount)
        seen_counts[key] = seen_counts.get(key, 0) + 1

        if seen_counts[key] <= existing_counts.get(key, 0):
            skipped_duplicate += 1
            continue

        connection.execute(
            """
            INSERT INTO customer_invoices (
                invoice_no, customer, invoice_date, due_date, memo, item,
                tracking_id, item_rate, item_amount, currency, ship_via, shipping_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("invoice_no"),
                row.get("customer"),
                to_customer_invoice_date(row.get("invoice_date")),
                to_customer_invoice_date(row.get("due_date")),
                row.get("memo"),
                row.get("item"),
                row.get("tracking_id"),
                item_rate,
                item_amount,
                row.get("currency"),
                row.get("ship_via"),
                to_customer_invoice_date(row.get("shipping_date")),
            ),
        )
        touched_tracking_ids.add(row.get("tracking_id"))
        added += 1

    fees_synced = sync_customer_fees_from_invoices(connection, touched_tracking_ids)

    connection.commit()
    connection.close()
    return {"added": added, "skipped_duplicate": skipped_duplicate, "fees_synced": fees_synced}


def build_customer_invoice_export(df):
    """Rebuilds the original 'invoices_manual' CSV shape from stored customer_invoices
    rows, so previously-imported lines can be exported back out in the same template.
    ItemQuantity isn't stored (the template doesn't require it — only *ItemAmount is
    marked required) so it's recovered as item_amount / item_rate where the rate is
    nonzero, falling back to 1 for flat-fee lines (e.g. a $0 Box Fee)."""
    rate = pd.to_numeric(df["item_rate"], errors="coerce")
    amount = pd.to_numeric(df["item_amount"], errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        recovered_quantity = np.where(rate.fillna(0) != 0, (amount / rate).round(2), 1)

    export = pd.DataFrame(index=df.index)
    export["*InvoiceNo"] = df["invoice_no"]
    export["*Customer"] = df["customer"]
    export["*InvoiceDate"] = df["invoice_date"]
    export["*DueDate"] = df["due_date"]
    export["Terms"] = ""
    export["Location"] = ""
    export["Memo"] = df["memo"]
    export["Item(Product/Service)"] = df["item"]
    export["ItemDescription"] = df["tracking_id"]
    export["ItemQuantity"] = recovered_quantity
    export["ItemRate"] = df["item_rate"]
    export["*ItemAmount"] = df["item_amount"]
    export["Currency"] = df["currency"]
    export["Ship via"] = df["ship_via"]
    export["Shipping date"] = df["shipping_date"]
    export["Tracking no."] = ""
    export["Shipping Charge"] = ""
    export["Service Date"] = df["shipping_date"]
    return export[EXPORT_COLUMNS]
