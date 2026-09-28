import os
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "finance_customs.db"


class PostgresConnection:
    """Small compatibility layer for the existing repository functions.

    The financial engine deliberately uses DB-API style ``?`` placeholders.  psycopg
    uses ``%s`` instead, so keeping the conversion here lets the same vetted business
    rules run locally on SQLite and in Vercel on Postgres.
    """

    def __init__(self, connection):
        self._connection = connection
        self.is_postgres = True

    def execute(self, query, params=None):
        query = query.replace("?", "%s")
        return self._connection.execute(query, params or ())

    def executemany(self, query, params_seq):
        return self._connection.cursor().executemany(query.replace("?", "%s"), params_seq)

    def cursor(self, *args, **kwargs):
        return self._connection.cursor(*args, **kwargs)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


def _database_url():
    """Use Vercel Postgres when configured; preserve SQLite for local development."""
    return os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")


def get_connection():
    database_url = _database_url()
    if database_url:
        try:
            import psycopg
        except ImportError as error:  # pragma: no cover - deployment configuration error
            raise RuntimeError("Postgres is configured but psycopg is not installed.") from error
        return PostgresConnection(psycopg.connect(database_url))
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
    if getattr(connection, "is_postgres", False):
        _init_postgres_db(connection)
        return
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


def _init_postgres_db(connection):
    """Idempotent production schema. Historical records are never altered here."""
    statements = (
        """CREATE TABLE IF NOT EXISTS invoices (
            invoice_number TEXT PRIMARY KEY, invoice_date TEXT, account_number TEXT,
            charge_type TEXT, source_file TEXT, company TEXT, due_date TEXT, invoice_amount DOUBLE PRECISION)""",
        """CREATE TABLE IF NOT EXISTS shipment_charges (
            id BIGSERIAL PRIMARY KEY, invoice_number TEXT, charge_type TEXT, tracking_id TEXT,
            shipment_no TEXT, ship_date TEXT, packages INTEGER, amount DOUBLE PRECISION,
            group_id TEXT, group_amount DOUBLE PRECISION, rated_weight_lbs DOUBLE PRECISION,
            customs_value_currency TEXT, customs_value_amount DOUBLE PRECISION)""",
        """CREATE TABLE IF NOT EXISTS boxes (
            id BIGSERIAL PRIMARY KEY, ship_date TEXT, company TEXT, customer_code TEXT,
            country TEXT, box_no TEXT, shipment_type TEXT, box_type_size TEXT, multi_no TEXT,
            tracking_id TEXT, customer_shipping_fee DOUBLE PRECISION, customer_packaging_fee DOUBLE PRECISION,
            customer_total_invoice DOUBLE PRECISION, fedex_service_type TEXT,
            fedex_duty_invoice_no TEXT, fedex_duty_amount DOUBLE PRECISION,
            fedex_shipping_invoice_no TEXT, fedex_shipping_amount DOUBLE PRECISION,
            fedex_total_cost TEXT, profit_loss TEXT)""",
        """CREATE TABLE IF NOT EXISTS legacy_fedex_invoice_raw (
            id BIGSERIAL PRIMARY KEY, col1 TEXT, col2 TEXT, col3 TEXT, col4 TEXT, col5 TEXT,
            col6 TEXT, col7 TEXT, col8 TEXT, col9 TEXT, col10 TEXT, col11 TEXT, col12 TEXT,
            col13 TEXT, col14 TEXT, col15 TEXT, col16 TEXT, col17 TEXT, col18 TEXT, col19 TEXT, col20 TEXT)""",
        """CREATE TABLE IF NOT EXISTS customer_invoices (
            id BIGSERIAL PRIMARY KEY, invoice_no TEXT, customer TEXT, invoice_date TEXT, due_date TEXT,
            memo TEXT, item TEXT, tracking_id TEXT, item_rate DOUBLE PRECISION, item_amount DOUBLE PRECISION,
            currency TEXT, ship_via TEXT, shipping_date TEXT)""",
        """CREATE TABLE IF NOT EXISTS products (
            id BIGSERIAL PRIMARY KEY, invoice_number TEXT, tracking_id TEXT, hs_code TEXT,
            description TEXT, quantity TEXT, country_of_origin TEXT, value_for_duty DOUBLE PRECISION)""",
        """CREATE TABLE IF NOT EXISTS invoice_review (
            invoice_no TEXT PRIMARY KEY, status TEXT, reviewed_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS disputed_items (
            id BIGSERIAL PRIMARY KEY, invoice_no TEXT, tracking_id TEXT, amount DOUBLE PRECISION,
            added_at TEXT, status TEXT, cancel_reason TEXT, cancelled_at TEXT,
            UNIQUE(invoice_no, tracking_id))""",
        """CREATE TABLE IF NOT EXISTS refunds (
            id BIGSERIAL PRIMARY KEY, tracking_id TEXT, box_no TEXT, customer_code TEXT, refund_type TEXT,
            refund_amount DOUBLE PRECISION, reason TEXT, related_invoice_no TEXT, refund_date TEXT,
            approved_by TEXT, status TEXT, notes TEXT, created_at TEXT)""",
        "CREATE INDEX IF NOT EXISTS boxes_tracking_id_idx ON boxes (tracking_id)",
        "CREATE INDEX IF NOT EXISTS shipment_charges_invoice_number_idx ON shipment_charges (invoice_number)",
    )
    for statement in statements:
        connection.execute(statement)
    # SQLite historically stores the display sentinel "Bekliyor" in these two
    # fields while the invoice is pending. They must remain text in Postgres too;
    # pandas converts their numeric values back for calculations. Avoid an ALTER
    # on every function request once the schema has been corrected.
    for column in ("fedex_total_cost", "profit_loss"):
        data_type = connection.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'boxes' AND column_name = ?",
            (column,),
        ).fetchone()[0]
        if data_type != "text":
            connection.execute(
                f"ALTER TABLE boxes ALTER COLUMN {column} TYPE TEXT USING {column}::TEXT"
            )
    connection.commit()
