"""Rewrites mixed-format date strings to one canonical shape per column.

  boxes.ship_date                               -> 'YYYY-MM-DD 00:00:00'
  customer_invoices.invoice_date/due_date/
                    shipping_date               -> 'M/D/YYYY' (QuickBooks style)

Only the text shape changes — every value must parse to the SAME calendar date
before and after, and a value that can't be parsed is left untouched. Money
columns are never touched.

Default is a dry run (prints the blast radius, writes nothing). With --apply it
first copies the DB to data/backups/, then updates inside one transaction and
verifies (row counts, money sums, same dates) before committing.

    python scripts/data_migration/normalize_dates.py            # dry run
    python scripts/data_migration/normalize_dates.py --apply    # after approval
"""
import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.database import DB_PATH  # noqa: E402
from core.dates import parse_dates, to_box_ship_date, to_customer_invoice_date  # noqa: E402

TARGETS = [
    ("boxes", "ship_date", to_box_ship_date),
    ("customer_invoices", "invoice_date", to_customer_invoice_date),
    ("customer_invoices", "due_date", to_customer_invoice_date),
    ("customer_invoices", "shipping_date", to_customer_invoice_date),
]
MONEY_CHECKS = [
    ("boxes", "customer_shipping_fee"), ("boxes", "customer_packaging_fee"),
    ("boxes", "fedex_duty_amount"), ("boxes", "fedex_shipping_amount"),
    ("customer_invoices", "item_amount"),
]


def plan_changes(connection):
    plan = []
    for table, column, convert in TARGETS:
        df = pd.read_sql(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL", connection)
        df["new"] = df[column].map(convert)
        before = parse_dates(df[column])
        after = parse_dates(df["new"])
        changed = df[df["new"] != df[column]]
        unparseable = int(before.isna().sum())
        mismatched = int(((before != after) & before.notna()).sum())
        plan.append({
            "table": table, "column": column, "rows": len(df), "changed": changed,
            "unparseable": unparseable, "date_mismatch": mismatched,
        })
    return plan


def money_sums(connection):
    return {
        (t, c): connection.execute(f"SELECT ROUND(COALESCE(SUM({c}),0),2), COUNT(*) FROM {t}").fetchone()
        for t, c in MONEY_CHECKS
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()
    db = Path(args.db)

    connection = sqlite3.connect(db)
    plan = plan_changes(connection)
    print(f"Database: {db}")
    for item in plan:
        examples = item["changed"].head(3)
        sample = ", ".join(f"{a!r} -> {b!r}" for a, b in zip(examples[item["column"]], examples["new"]))
        print(f"  {item['table']}.{item['column']}: {len(item['changed'])} of {item['rows']} rows change"
              f" | unparseable (left as-is): {item['unparseable']} | date mismatch: {item['date_mismatch']}")
        if sample:
            print(f"      e.g. {sample}")
    if any(item["date_mismatch"] for item in plan):
        print("ABORT: some value would change to a different calendar date.")
        return 1
    if not args.apply:
        print("Dry run only — nothing written.")
        return 0

    backup_dir = db.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / f"finance_customs_backup_{datetime.now():%Y%m%d_%H%M%S}_before_date_normalize.db"
    connection.close()
    shutil.copy2(db, backup)
    print(f"Backup written: {backup}")

    connection = sqlite3.connect(db)
    before_money = money_sums(connection)
    counts_before = {t: connection.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("boxes", "customer_invoices")}
    try:
        connection.execute("BEGIN")
        for item in plan:
            rows = [(new, row_id) for row_id, new in zip(item["changed"]["id"], item["changed"]["new"])]
            connection.executemany(f"UPDATE {item['table']} SET {item['column']} = ? WHERE id = ?", rows)
        assert money_sums(connection) == before_money, "money totals changed"
        assert {t: connection.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in counts_before} == counts_before
        for table, column, _ in TARGETS:
            values = pd.read_sql(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL", connection)[column]
            assert parse_dates(values).notna().all(), f"{table}.{column} still has unparseable values"
        connection.commit()
    except Exception:
        connection.rollback()
        print("FAILED — rolled back, database unchanged.")
        raise
    finally:
        connection.close()
    print("Applied and verified: row counts and money totals identical, every date parses.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
