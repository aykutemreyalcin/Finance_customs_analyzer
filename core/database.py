import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "finance_customs.db"


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def update_box_fields(box_id, fields):
    if not fields:
        return
    connection = get_connection()
    columns = ", ".join(f"{name} = ?" for name in fields)
    # box_id often arrives as a numpy.int64 (read out of a pandas DataFrame by
    # the Data Quality page) — sqlite3 doesn't recognize that as an INTEGER
    # bind value, so `WHERE id = ?` silently matches zero rows instead of
    # raising. Cast to a plain Python int so the match actually happens.
    connection.execute(
        f"UPDATE boxes SET {columns} WHERE id = ?", (*fields.values(), int(box_id))
    )
    connection.commit()
    connection.close()


def init_db(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_number TEXT PRIMARY KEY,
            invoice_date TEXT,
            account_number TEXT,
            charge_type TEXT,
            source_file TEXT,
            company TEXT,
            due_date TEXT,
            invoice_amount REAL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS shipment_charges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT,
            charge_type TEXT,
            tracking_id TEXT,
            shipment_no TEXT,
            ship_date TEXT,
            packages INTEGER,
            amount REAL,
            group_id TEXT,
            group_amount REAL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS boxes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ship_date TEXT,
            company TEXT,
            customer_code TEXT,
            country TEXT,
            box_no TEXT,
            shipment_type TEXT,
            box_type_size TEXT,
            multi_no TEXT,
            tracking_id TEXT,
            customer_shipping_fee REAL,
            customer_packaging_fee REAL,
            customer_total_invoice REAL,
            fedex_service_type TEXT,
            fedex_duty_invoice_no TEXT,
            fedex_duty_amount REAL,
            fedex_shipping_invoice_no TEXT,
            fedex_shipping_amount REAL,
            fedex_total_cost REAL,
            profit_loss REAL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS legacy_fedex_invoice_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            col1 TEXT, col2 TEXT, col3 TEXT, col4 TEXT, col5 TEXT,
            col6 TEXT, col7 TEXT, col8 TEXT, col9 TEXT, col10 TEXT,
            col11 TEXT, col12 TEXT, col13 TEXT, col14 TEXT, col15 TEXT,
            col16 TEXT, col17 TEXT, col18 TEXT, col19 TEXT, col20 TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS customer_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_no TEXT,
            customer TEXT,
            invoice_date TEXT,
            due_date TEXT,
            memo TEXT,
            item TEXT,
            tracking_id TEXT,
            item_rate REAL,
            item_amount REAL,
            currency TEXT,
            ship_via TEXT,
            shipping_date TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT,
            tracking_id TEXT,
            hs_code TEXT,
            description TEXT,
            quantity TEXT,
            country_of_origin TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS invoice_review (
            invoice_no TEXT PRIMARY KEY,
            status TEXT,
            reviewed_at TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS disputed_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_no TEXT,
            tracking_id TEXT,
            amount REAL,
            added_at TEXT,
            UNIQUE(invoice_no, tracking_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS refunds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_id TEXT,
            box_no TEXT,
            customer_code TEXT,
            refund_type TEXT,
            refund_amount REAL,
            reason TEXT,
            related_invoice_no TEXT,
            refund_date TEXT,
            approved_by TEXT,
            status TEXT,
            notes TEXT,
            created_at TEXT
        )
        """
    )
    _ensure_columns(
        connection, "invoices", {"company": "TEXT", "due_date": "TEXT", "invoice_amount": "REAL"}
    )
    _ensure_columns(connection, "products", {"value_for_duty": "REAL"})
    _ensure_columns(
        connection,
        "shipment_charges",
        {
            "rated_weight_lbs": "REAL",
            "customs_value_currency": "TEXT",
            "customs_value_amount": "REAL",
        },
    )
    _ensure_columns(
        connection,
        "disputed_items",
        {"status": "TEXT", "cancel_reason": "TEXT", "cancelled_at": "TEXT"},
    )
    connection.commit()


def _ensure_columns(connection, table, columns):
    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    for name, coltype in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}")
