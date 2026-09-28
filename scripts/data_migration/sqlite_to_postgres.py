"""One-way, additive NeXa SQLite -> Postgres migration.

Run only after reviewing the source row counts and setting DATABASE_URL.  It never
modifies the SQLite source and uses one target transaction, so a failed migration
does not leave a half-loaded production database.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

# Direct script execution puts scripts/data_migration on sys.path rather than the
# repository root. Add the root explicitly so the documented command works.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.database import get_connection, init_db

TABLES = (
    "invoices", "shipment_charges", "boxes", "legacy_fedex_invoice_raw",
    "customer_invoices", "products", "invoice_review", "disputed_items", "refunds",
)


def migrate(source: Path):
    if not source.is_file():
        raise FileNotFoundError(f"SQLite source does not exist: {source}")
    source_connection = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    source_connection.row_factory = sqlite3.Row
    target = get_connection()
    if not getattr(target, "is_postgres", False):
        raise RuntimeError("Set DATABASE_URL or POSTGRES_URL to a PostgreSQL database before migrating.")
    try:
        init_db(target)
        for table in TABLES:
            rows = source_connection.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                print(f"{table}: 0 rows")
                continue
            columns = list(rows[0].keys())
            placeholders = ", ".join("?" for _ in columns)
            target.executemany(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
                "ON CONFLICT DO NOTHING",
                [tuple(row[column] for column in columns) for row in rows],
            )
            print(f"{table}: {len(rows)} rows copied")
        for table in ("shipment_charges", "boxes", "legacy_fedex_invoice_raw", "customer_invoices", "products", "disputed_items", "refunds"):
            target.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1), true) FROM {table}"
            )
        target.commit()
    except Exception:
        target.rollback()
        raise
    finally:
        source_connection.close()
        target.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Copy a NeXa SQLite database into Postgres.")
    parser.add_argument("source", type=Path, help="Path to the existing SQLite database")
    migrate(parser.parse_args().source)
