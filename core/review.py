from datetime import datetime, timezone

import pandas as pd

from core.database import get_connection, init_db

APPROVED = "Approved"
CASE = "Case"


def get_invoice_review_map():
    connection = get_connection()
    init_db(connection)
    rows = connection.execute("SELECT invoice_no, status FROM invoice_review").fetchall()
    connection.close()
    return dict(rows)


def set_invoice_review_status(invoice_no, status):
    if invoice_no is None or (isinstance(invoice_no, float) and pd.isna(invoice_no)):
        # invoice_review's ON CONFLICT is keyed by invoice_no, and SQLite never
        # treats two NULLs as a conflict — so a NULL invoice_no would INSERT a
        # fresh garbage row every single call instead of ever updating one.
        # Real incident (2026-09-19, root cause fixed in app.py's grid row
        # identity): 16,254 such rows accumulated before this guard existed.
        return
    connection = get_connection()
    init_db(connection)
    connection.execute(
        "INSERT INTO invoice_review (invoice_no, status, reviewed_at) VALUES (?, ?, ?) "
        "ON CONFLICT(invoice_no) DO UPDATE SET status = excluded.status, reviewed_at = excluded.reviewed_at",
        (invoice_no, status, datetime.now(timezone.utc).isoformat()),
    )
    connection.commit()
    connection.close()


def add_disputed_items(invoice_no, items):
    """items: iterable of (tracking_id, amount). If a (invoice_no, tracking_id) pair
    was previously cancelled from the Disputes page, re-adding it (e.g. re-checking
    the Case box) reactivates that same row instead of being silently ignored."""
    if not items:
        return
    connection = get_connection()
    init_db(connection)
    now = datetime.now(timezone.utc).isoformat()
    for tracking_id, amount in items:
        connection.execute(
            "INSERT INTO disputed_items (invoice_no, tracking_id, amount, added_at, status) "
            "VALUES (?, ?, ?, ?, 'Active') "
            "ON CONFLICT(invoice_no, tracking_id) DO UPDATE SET "
            "status = 'Active', cancel_reason = NULL, cancelled_at = NULL, "
            "amount = excluded.amount, added_at = excluded.added_at",
            (invoice_no, tracking_id, amount, now),
        )
    connection.commit()
    connection.close()


def remove_disputed_invoice(invoice_no):
    connection = get_connection()
    init_db(connection)
    connection.execute("DELETE FROM disputed_items WHERE invoice_no = ?", (invoice_no,))
    connection.commit()
    connection.close()


def remove_disputed_item(invoice_no, tracking_id):
    """Removes a single disputed box, unlike remove_disputed_invoice which clears
    every box under that invoice — used when a Case checkbox is unchecked for
    just that one box."""
    connection = get_connection()
    init_db(connection)
    connection.execute(
        "DELETE FROM disputed_items WHERE invoice_no = ? AND tracking_id = ?",
        (invoice_no, tracking_id),
    )
    connection.commit()
    connection.close()


def cancel_disputed_items(pairs, reason=None):
    """Soft-cancels disputed boxes (invoice_no, tracking_id pairs): the row stays in
    the table with status='Cancelled' instead of being deleted, so it can still be
    reviewed in the Disputes page's Cancelled list. reason is an optional free-text
    note explaining why the case was cancelled."""
    if not pairs:
        return
    connection = get_connection()
    init_db(connection)
    now = datetime.now(timezone.utc).isoformat()
    for invoice_no, tracking_id in pairs:
        connection.execute(
            "UPDATE disputed_items SET status = 'Cancelled', cancel_reason = ?, cancelled_at = ? "
            "WHERE invoice_no = ? AND tracking_id = ?",
            (reason, now, invoice_no, tracking_id),
        )
    connection.commit()
    connection.close()


def get_disputed_items_df():
    connection = get_connection()
    init_db(connection)
    df = pd.read_sql("SELECT * FROM disputed_items ORDER BY added_at DESC", connection)
    connection.close()
    if not df.empty:
        df["status"] = df["status"].fillna("Active")
    return df
