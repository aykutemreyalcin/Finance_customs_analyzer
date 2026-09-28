"""
NeXa RAW DATA extraction script.

Purpose
-------
Read-only extraction of the current NeXa operational data (SQLite database at
data/finance_customs.db) into a timestamped RAW DATA snapshot folder, for use
as the starting point of a NEW finance software project.

Hard rules enforced by this script:
  - Opens the source database in SQLite read-only URI mode (mode=ro). No
    INSERT / UPDATE / DELETE / ALTER / DROP / TRUNCATE is ever issued.
  - Never writes anything back into data/finance_customs.db.
  - Does NOT clean, normalize, deduplicate, rename, or recalculate anything.
    Every extracted value is stored exactly as read from the source table.
  - Only reads. All output goes to a new data/raw/nexa/<timestamp>/ folder
    and a new logs/data_extraction/ log file.

Usage
-----
  python scripts/data_migration/extract_nexa_raw.py            # full run (sample + full extraction)
  python scripts/data_migration/extract_nexa_raw.py --sample-only  # only run the small sample test
"""

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOURCE_DB_PATH = os.path.join(PROJECT_ROOT, "data", "finance_customs.db")
SOURCE_SYSTEM = "NeXa"
SOURCE_DATABASE = "data/finance_customs.db"
SCHEMA_VERSION = "nexa-sqlite-2026-09-22"  # bump if core/database.py schema changes
BATCH_SIZE = 10000
SAMPLE_SIZE = 20

# Tables in priority order per the extraction request. sqlite_sequence is an
# internal SQLite bookkeeping table, not business data, so it is excluded.
PRIORITY_ORDER = [
    "invoices",             # BILLING
    "shipment_charges",     # BILLING / SHIPPING
    "customer_invoices",    # BILLING
    "boxes",                # OPERATIONAL / SHIPPING
    "products",             # CUSTOMS
    "refunds",               # REFUND
    "disputed_items",        # REFUND / adjustment
    "invoice_review",        # internal workflow state
    "legacy_fedex_invoice_raw",  # legacy raw import
]


def get_ro_connection():
    """Open the source SQLite DB strictly read-only. Raises if the file is missing."""
    if not os.path.exists(SOURCE_DB_PATH):
        raise FileNotFoundError(f"Source database not found: {SOURCE_DB_PATH}")
    uri = f"file:{SOURCE_DB_PATH.replace(os.sep, '/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def list_tables(conn):
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence' ORDER BY name"
    )
    found = [r[0] for r in cur.fetchall()]
    # Order by priority list first, then anything else found but not anticipated.
    ordered = [t for t in PRIORITY_ORDER if t in found]
    ordered += [t for t in found if t not in PRIORITY_ORDER]
    return ordered


def get_columns(conn, table):
    cur = conn.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]


def get_pk_columns(conn, table):
    cur = conn.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall() if row[5] > 0]


def sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_valid_date(value):
    if value in (None, ""):
        return True  # NULL/blank dates are a separate NULL check, not a format error
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%b %d, %Y",       # e.g. "Jun 01, 2026" (invoices.invoice_date/due_date)
        "%B %d, %Y",
    ):
        try:
            datetime.strptime(text, fmt)
            return True
        except ValueError:
            continue
    # ISO 8601 with time and/or timezone, e.g. "2026-09-17T23:15:35.353242+00:00"
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def looks_like_date_column(col_name):
    lowered = col_name.lower()
    return "date" in lowered or lowered.endswith("_at")


def looks_like_numeric_column(col_name, decl_type):
    return decl_type.upper() in ("REAL", "INTEGER") if decl_type else False


def run_sample_test(conn, tables, log):
    log("=" * 70)
    log("STEP: SMALL SAMPLE TEST (first %d rows per table)" % SAMPLE_SIZE)
    log("=" * 70)
    sample_report = {}
    for table in tables:
        cols = get_columns(conn, table)
        cur = conn.execute(f"SELECT * FROM {table} LIMIT {SAMPLE_SIZE}")
        rows = cur.fetchall()
        sample_report[table] = {
            "columns": cols,
            "sample_row_count": len(rows),
        }
        log(f"[SAMPLE] {table}: {len(rows)} row(s) fetched, {len(cols)} column(s) -> {cols}")
        if rows:
            first = dict(rows[0])
            log(f"[SAMPLE] {table} first row preview: {json.dumps(first, default=str, ensure_ascii=False)[:300]}")
    return sample_report


def extract_table_full(conn, table, out_dir, log):
    cols = get_columns(conn, table)
    pk_cols = get_pk_columns(conn, table)

    cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
    source_row_count = cur.fetchone()[0]

    csv_path = os.path.join(out_dir, f"{table}.csv")
    started_at = datetime.now(timezone.utc)

    extracted_row_count = 0
    error_count = 0

    # Quality-check accumulators (report only, never mutate source or output)
    pk_seen = set()
    pk_duplicates = 0
    pk_nulls = 0
    invalid_dates = 0
    invalid_numerics = 0

    decl_types = {}
    for row in conn.execute(f"PRAGMA table_info({table})"):
        decl_types[row[1]] = row[2]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(cols)

        offset = 0
        while True:
            cur = conn.execute(
                f"SELECT * FROM {table} ORDER BY rowid LIMIT {BATCH_SIZE} OFFSET {offset}"
            )
            batch = cur.fetchall()
            if not batch:
                break
            for row in batch:
                try:
                    writer.writerow([row[c] for c in cols])
                    extracted_row_count += 1

                    # PK checks
                    if pk_cols:
                        pk_value = tuple(row[c] for c in pk_cols)
                        if any(v is None for v in pk_value):
                            pk_nulls += 1
                        elif pk_value in pk_seen:
                            pk_duplicates += 1
                        else:
                            pk_seen.add(pk_value)

                    # date / numeric sanity checks (report only)
                    for c in cols:
                        val = row[c]
                        if looks_like_date_column(c) and not is_valid_date(val):
                            invalid_dates += 1
                        if looks_like_numeric_column(c, decl_types.get(c)) and val is not None:
                            if not isinstance(val, (int, float)):
                                invalid_numerics += 1
                except Exception as exc:  # noqa: BLE001 - log and continue, never abort silently
                    error_count += 1
                    log(f"[ERROR] {table}: row extraction failed: {exc}")
            offset += BATCH_SIZE
            log(f"[PROGRESS] {table}: {min(offset, source_row_count)}/{source_row_count} rows written")

    finished_at = datetime.now(timezone.utc)
    checksum = sha256_of_file(csv_path)
    file_size = os.path.getsize(csv_path)

    integrity_ok = (extracted_row_count == source_row_count) and (error_count == 0)

    metadata = {
        "source_system": SOURCE_SYSTEM,
        "source_database": SOURCE_DATABASE,
        "source_table": table,
        "extraction_timestamp": started_at.isoformat(),
        "extraction_finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "schema_version": SCHEMA_VERSION,
        "columns": cols,
        "primary_key_columns": pk_cols,
        "source_row_count": source_row_count,
        "extracted_row_count": extracted_row_count,
        "error_count": error_count,
        "row_count_match": extracted_row_count == source_row_count,
        "extraction_status": "SUCCESS" if integrity_ok else ("PARTIAL" if extracted_row_count > 0 else "FAILED"),
        "output_file": os.path.basename(csv_path),
        "output_file_size_bytes": file_size,
        "output_file_sha256": checksum,
        "data_quality_warnings": {
            "primary_key_duplicates": pk_duplicates,
            "primary_key_nulls": pk_nulls,
            "invalid_date_values": invalid_dates,
            "invalid_numeric_values": invalid_numerics,
        },
    }

    meta_path = os.path.join(out_dir, f"{table}.metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    log(
        f"[DONE] {table}: source={source_row_count} extracted={extracted_row_count} "
        f"errors={error_count} status={metadata['extraction_status']} sha256={checksum[:12]}..."
    )
    if pk_duplicates or pk_nulls or invalid_dates or invalid_numerics:
        log(
            f"[QUALITY WARNING] {table}: pk_duplicates={pk_duplicates} pk_nulls={pk_nulls} "
            f"invalid_dates={invalid_dates} invalid_numerics={invalid_numerics}"
        )

    return metadata


def main():
    parser = argparse.ArgumentParser(description="NeXa read-only RAW DATA extraction")
    parser.add_argument("--sample-only", action="store_true", help="Only run the small sample test, skip full extraction")
    args = parser.parse_args()

    run_started = datetime.now(timezone.utc)
    timestamp_str = run_started.strftime("%Y-%m-%d_%H-%M-%S")

    raw_out_dir = os.path.join(PROJECT_ROOT, "data", "raw", "nexa", timestamp_str)
    log_dir = os.path.join(PROJECT_ROOT, "logs", "data_extraction")
    os.makedirs(raw_out_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"extraction_{timestamp_str}.log")

    log_lines = []

    def log(msg):
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line)
        log_lines.append(line)

    log(f"NeXa RAW DATA extraction started. Source: {SOURCE_DB_PATH}")
    log(f"Output folder: {raw_out_dir}")
    log("Mode: READ-ONLY (sqlite3 uri mode=ro). No writes to source will be attempted.")

    overall_status = "SUCCESS"
    table_metadatas = {}

    try:
        conn = get_ro_connection()
    except Exception as exc:
        log(f"[FATAL] Could not open source database read-only: {exc}")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(log_lines))
        print(f"EXTRACTION FAILED: {exc}")
        sys.exit(1)

    try:
        tables = list_tables(conn)
        log(f"Tables discovered ({len(tables)}): {tables}")

        sample_report = run_sample_test(conn, tables, log)

        if args.sample_only:
            log("Sample-only mode requested. Stopping before full extraction, per instruction.")
        else:
            log("=" * 70)
            log("STEP: FULL EXTRACTION (batched, %d rows/batch)" % BATCH_SIZE)
            log("=" * 70)
            for table in tables:
                try:
                    meta = extract_table_full(conn, table, raw_out_dir, log)
                    table_metadatas[table] = meta
                    if meta["extraction_status"] != "SUCCESS":
                        overall_status = "PARTIAL"
                except Exception as exc:  # noqa: BLE001
                    overall_status = "PARTIAL"
                    log(f"[ERROR] Full extraction failed for table {table}: {exc}")
                    table_metadatas[table] = {
                        "source_table": table,
                        "extraction_status": "FAILED",
                        "error": str(exc),
                    }
    finally:
        conn.close()
        log("Source connection closed. No writes were made to the source database at any point.")

    run_finished = datetime.now(timezone.utc)

    manifest = {
        "source_system": SOURCE_SYSTEM,
        "source_database": SOURCE_DATABASE,
        "source_database_absolute_path": SOURCE_DB_PATH,
        "extraction_run_started": run_started.isoformat(),
        "extraction_run_finished": run_finished.isoformat(),
        "schema_version": SCHEMA_VERSION,
        "sample_only": args.sample_only,
        "overall_status": overall_status if not args.sample_only else "SAMPLE_ONLY",
        "tables": table_metadatas,
        "sample_report": sample_report,
        "raw_data_location": raw_out_dir,
        "log_file": log_path,
        "next_step": "NOT imported into any new finance database yet. Awaiting explicit approval before proceeding.",
    }

    manifest_path = os.path.join(raw_out_dir, "_extraction_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    log(f"Manifest written: {manifest_path}")
    log(f"Overall status: {manifest['overall_status']}")

    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))

    print("\n" + "=" * 70)
    print(f"EXTRACTION FINISHED. Overall status: {manifest['overall_status']}")
    print(f"RAW DATA location: {raw_out_dir}")
    print(f"Log file: {log_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
