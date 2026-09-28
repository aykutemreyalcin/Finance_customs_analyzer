"""Vercel entrypoint for NeXa's JSON API.

The Streamlit application remains available for local data migration only.  This
module is the production interface: it uses DATABASE_URL/POSTGRES_URL, never a
filesystem database, and exposes the same calculation engine as the old UI.
"""

import os
import secrets
import gzip
import sqlite3
import tempfile
from io import BytesIO
from typing import Any

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from core.analytics import (
    compute_above_average_boxes,
    compute_benchmarks,
    compute_customer_invoice_reconciliation,
    compute_customer_profitability,
    compute_data_issues,
    compute_fedex_reconciliation,
    compute_profit_calculation,
    enrich_boxes_for_display,
)
from core.box_import import add_single_box, import_boxes, read_box_import_file
from core.customer_invoice_import import (
    import_customer_invoices,
    import_mosaic_handling_invoices,
    read_customer_invoice_file,
    read_mosaic_handling_file,
)
from core.database import get_connection, init_db, update_box_fields
from core.ingest import ingest_pdf_bundle
from core.refunds import add_refund, delete_refund, set_refund_status
from core.review import add_disputed_items, cancel_disputed_items, set_invoice_review_status

app = FastAPI(title="NeXa API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)
security = HTTPBearer(auto_error=False)
MIGRATION_TABLES = (
    "invoices", "shipment_charges", "boxes", "legacy_fedex_invoice_raw",
    "customer_invoices", "products", "invoice_review", "disputed_items", "refunds",
)


def require_password(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    expected = os.getenv("NEXA_PASSWORD")
    if not expected:
        raise HTTPException(503, "NEXA_PASSWORD is not configured.")
    if not credentials or credentials.scheme.lower() != "bearer" or not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(401, "A valid NeXa password is required.")


def read_frame(query: str, params: tuple = ()) -> pd.DataFrame:
    connection = get_connection()
    try:
        init_db(connection)
        cursor = connection.execute(query, params)
        if not cursor.description:
            return pd.DataFrame()
        columns = [getattr(column, "name", column[0]) for column in cursor.description]
        return pd.DataFrame(cursor.fetchall(), columns=columns)
    finally:
        connection.close()


def json_value(value: Any):
    """Convert pandas/numpy scalar values into JSON-safe Python values."""
    if value is None or value is pd.NA:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    cleaned = frame.replace([np.inf, -np.inf], np.nan).where(pd.notnull(frame), None)
    return [{key: json_value(value) for key, value in row.items()} for row in cleaned.to_dict(orient="records")]


def page_records(frame: pd.DataFrame, page: int, page_size: int) -> dict[str, Any]:
    """Keep the Vercel UI responsive even with the historical 35k-line import."""
    start = (page - 1) * page_size
    return {"items": records(frame.iloc[start:start + page_size]), "total": len(frame),
            "page": page, "page_size": page_size}


def load_financial_frames():
    boxes = read_frame("SELECT * FROM boxes ORDER BY id")
    charges = read_frame("SELECT * FROM shipment_charges ORDER BY id")
    if boxes.empty:
        # The calculation engine expects the schema-shaped columns even before an import.
        boxes = pd.DataFrame(columns=[
            "id", "ship_date", "company", "customer_code", "country", "box_no", "shipment_type",
            "box_type_size", "multi_no", "tracking_id", "customer_shipping_fee",
            "customer_packaging_fee", "fedex_service_type", "fedex_duty_invoice_no",
            "fedex_duty_amount", "fedex_shipping_invoice_no", "fedex_shipping_amount",
        ])
    if charges.empty:
        charges = pd.DataFrame(columns=["id", "invoice_number", "charge_type", "tracking_id", "amount"])
    enriched = enrich_boxes_for_display(boxes)
    return boxes, charges, compute_profit_calculation(enriched)


def restore_sqlite_backup(compressed_backup: bytes) -> dict[str, int]:
    """Copies a gzip-compressed SQLite backup to an *empty* Postgres database.

    This exists for the one-time production migration. It rejects a non-empty
    target rather than risking duplicate financial records on a repeated upload.
    The temporary SQLite file is created under /tmp and removed before return.
    """
    if len(compressed_backup) > 4 * 1024 * 1024:
        raise ValueError("Compressed backup is larger than the 4 MB upload limit.")
    try:
        sqlite_bytes = gzip.decompress(compressed_backup)
    except OSError as error:
        raise ValueError("Upload a gzip-compressed .db.gz backup.") from error
    if len(sqlite_bytes) > 64 * 1024 * 1024:
        raise ValueError("Decompressed backup is larger than the 64 MB safety limit.")

    temporary_file = tempfile.NamedTemporaryFile(suffix=".db", dir="/tmp", delete=False)
    try:
        temporary_file.write(sqlite_bytes)
        temporary_file.close()
        source = sqlite3.connect(f"file:{temporary_file.name}?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        target = get_connection()
        try:
            init_db(target)
            existing = {
                table: target.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in MIGRATION_TABLES
            }
            if any(existing.values()):
                raise ValueError("Target Postgres database is not empty; migration was not run.")

            copied = {}
            for table in MIGRATION_TABLES:
                rows = source.execute(f"SELECT * FROM {table}").fetchall()
                if not rows:
                    copied[table] = 0
                    continue
                columns = list(rows[0].keys())
                placeholders = ", ".join("?" for _ in columns)
                target.executemany(
                    f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                    [tuple(row[column] for column in columns) for row in rows],
                )
                copied[table] = len(rows)
            if getattr(target, "is_postgres", False):
                for table in ("shipment_charges", "boxes", "legacy_fedex_invoice_raw", "customer_invoices", "products", "disputed_items", "refunds"):
                    target.execute(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1), true) FROM {table}"
                    )
            target.commit()
            return copied
        except Exception:
            target.rollback()
            raise
        finally:
            source.close()
            target.close()
    finally:
        temporary_file.close()
        if os.path.exists(temporary_file.name):
            os.unlink(temporary_file.name)


class BoxCreate(BaseModel):
    ship_date: str | None = None
    company: str | None = None
    customer_code: str | None = None
    country: str | None = None
    box_no: str | None = None
    shipment_type: str | None = None
    box_type_size: str | None = None
    multi_no: str | None = None
    tracking_id: str = Field(min_length=1, max_length=100)


class BoxPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ship_date: str | None = None
    company: str | None = None
    customer_code: str | None = None
    country: str | None = None
    box_no: str | None = None
    shipment_type: str | None = None
    box_type_size: str | None = None
    multi_no: str | None = None
    customer_shipping_fee: float | None = None
    customer_packaging_fee: float | None = None


class ReviewChange(BaseModel):
    status: str = Field(pattern="^(Approved|Case)$")


class DisputeChange(BaseModel):
    invoice_no: str
    items: list[tuple[str, float]] = []


class CancelDispute(BaseModel):
    pairs: list[tuple[str, str]]
    reason: str | None = Field(default=None, max_length=1000)


class RefundCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tracking_id: str | None = None
    box_no: str | None = None
    customer_code: str | None = None
    refund_type: str
    refund_amount: float
    reason: str | None = None
    related_invoice_no: str | None = None
    refund_date: str | None = None
    approved_by: str | None = None
    status: str = "Pending"
    notes: str | None = None


@app.get("/api/health")
def health():
    # Deliberately doesn't require the key, so Vercel health monitoring can identify
    # a missing database configuration without exposing business data.
    try:
        connection = get_connection()
        init_db(connection)
        connection.close()
    except Exception as error:
        raise HTTPException(503, "Database unavailable") from error
    return {"status": "ok"}


@app.get("/api/dashboard", dependencies=[Depends(require_password)])
def dashboard():
    boxes, charges, profit = load_financial_frames()
    fedex = compute_fedex_reconciliation(profit, charges)
    customer = compute_customer_invoice_reconciliation(profit)
    return {
        "box_count": len(boxes),
        "revenue": float(pd.to_numeric(profit["revenue"], errors="coerce").sum()),
        "profit": float(pd.to_numeric(profit["actual_profit"], errors="coerce").sum()),
        "fedex": json_value({key: value for key, value in fedex.items() if not key.endswith("_detail")}),
        "customer": json_value(customer),
    }


@app.get("/api/boxes", dependencies=[Depends(require_password)])
def boxes(
    query: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    _, _, profit = load_financial_frames()
    if query:
        query = query.lower()
        searchable = profit.fillna("").astype(str).apply(lambda column: column.str.lower().str.contains(query))
        profit = profit[searchable.any(axis=1)]
    total = len(profit)
    start = (page - 1) * page_size
    return {"items": records(profit.iloc[start:start + page_size]), "total": total, "page": page, "page_size": page_size}


@app.post("/api/boxes", dependencies=[Depends(require_password)])
def create_box(box: BoxCreate):
    result = add_single_box(**box.model_dump())
    if not result["added"]:
        raise HTTPException(409, "A box with this tracking ID already exists.")
    return result


@app.patch("/api/boxes/{box_id}", dependencies=[Depends(require_password)])
def patch_box(box_id: int, patch: BoxPatch):
    fields = {key: value for key, value in patch.model_dump().items() if value is not None}
    if not fields:
        raise HTTPException(400, "No changes supplied.")
    existing = read_frame("SELECT id FROM boxes WHERE id = ?", (box_id,))
    if existing.empty:
        raise HTTPException(404, "Box not found.")
    update_box_fields(box_id, fields)
    return {"updated": True}


@app.get("/api/profitability", dependencies=[Depends(require_password)])
def profitability(month: str | None = Query(None, max_length=20)):
    _, _, profit = load_financial_frames()
    table, excluded_count = compute_customer_profitability(profit, month)
    return {"items": records(table), "excluded_box_count": excluded_count}


@app.get("/api/benchmarks", dependencies=[Depends(require_password)])
def benchmarks():
    boxes, _, _ = load_financial_frames()
    return {"items": records(compute_benchmarks(enrich_boxes_for_display(boxes)))}


@app.get("/api/above-average", dependencies=[Depends(require_password)])
def above_average(page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=200)):
    boxes, _, _ = load_financial_frames()
    return page_records(compute_above_average_boxes(enrich_boxes_for_display(boxes)), page, page_size)


@app.get("/api/data-issues", dependencies=[Depends(require_password)])
def data_issues():
    boxes, _, _ = load_financial_frames()
    return {"items": records(compute_data_issues(enrich_boxes_for_display(boxes)))}


@app.get("/api/reconciliation", dependencies=[Depends(require_password)])
def reconciliation():
    boxes, charges, profit = load_financial_frames()
    fedex = compute_fedex_reconciliation(profit, charges)
    customer = compute_customer_invoice_reconciliation(profit)
    pending = profit[(profit["profit_calculation_status"] == "Included") &
                     (profit["fedex_status"] != "Actual")]
    missing = profit[profit["profit_calculation_status"] != "Included"]
    return {
        "fedex": json_value({key: value for key, value in fedex.items() if not key.endswith("_detail")}),
        "customer": json_value(customer),
        "pending": records(pending), "missing_customer_invoices": records(missing),
        "unallocated": records(fedex["unallocated_detail"]),
        "unmatched_second_invoices": records(fedex["unmatched_second_invoice_detail"]),
    }


@app.get("/api/invoices", dependencies=[Depends(require_password)])
def invoices():
    return {"items": records(read_frame("SELECT * FROM invoices ORDER BY invoice_date DESC, invoice_number"))}


@app.get("/api/customer-invoices", dependencies=[Depends(require_password)])
def customer_invoices(query: str = Query("", max_length=100), page: int = Query(1, ge=1),
                      page_size: int = Query(100, ge=1, le=200)):
    frame = read_frame("SELECT * FROM customer_invoices ORDER BY invoice_date DESC, id DESC")
    if query:
        mask = frame.fillna("").astype(str).apply(lambda column: column.str.contains(query, case=False, regex=False))
        frame = frame[mask.any(axis=1)]
    return page_records(frame, page, page_size)


@app.get("/api/charges", dependencies=[Depends(require_password)])
def charges(query: str = Query("", max_length=100), page: int = Query(1, ge=1),
            page_size: int = Query(100, ge=1, le=200)):
    frame = read_frame("SELECT * FROM shipment_charges ORDER BY id DESC")
    if query:
        mask = frame.fillna("").astype(str).apply(lambda column: column.str.contains(query, case=False, regex=False))
        frame = frame[mask.any(axis=1)]
    return page_records(frame, page, page_size)


@app.get("/api/disputes", dependencies=[Depends(require_password)])
def disputes():
    return {"items": records(read_frame("SELECT * FROM disputed_items ORDER BY added_at DESC")),
            "reviews": records(read_frame("SELECT * FROM invoice_review ORDER BY reviewed_at DESC"))}


@app.get("/api/reports", dependencies=[Depends(require_password)])
def reports():
    _, _, profit = load_financial_frames()
    included = profit[profit["profit_calculation_status"] == "Included"].copy()
    ship_date = pd.to_datetime(included["ship_date"], errors="coerce")
    included["month"] = ship_date.dt.strftime("%b %Y").fillna("Unknown")
    monthly = included.groupby("month", dropna=False).agg(boxes=("id", "size"), revenue=("revenue", "sum"),
        fedex_cost=("actual_fedex_cost", "sum"), profit=("actual_profit", "sum")).reset_index()
    country = included.groupby("country", dropna=False).agg(boxes=("id", "size"), revenue=("revenue", "sum"),
        fedex_cost=("actual_fedex_cost", "sum"), profit=("actual_profit", "sum")).reset_index()
    return {"monthly": records(monthly), "countries": records(country)}


@app.get("/api/refunds", dependencies=[Depends(require_password)])
def refunds():
    return {"items": records(read_frame("SELECT * FROM refunds ORDER BY created_at DESC"))}


@app.post("/api/refunds", dependencies=[Depends(require_password)])
def create_refund(refund: RefundCreate):
    add_refund(refund.model_dump())
    return {"created": True}


@app.delete("/api/refunds/{refund_id}", dependencies=[Depends(require_password)])
def remove_refund(refund_id: int):
    delete_refund(refund_id)
    return {"deleted": True}


@app.put("/api/refunds/{refund_id}/status", dependencies=[Depends(require_password)])
def update_refund_status(refund_id: int, status: str = Query(pattern="^(Pending|Approved|Rejected|Completed)$")):
    set_refund_status(refund_id, status)
    return {"updated": True}


@app.put("/api/reviews/{invoice_no}", dependencies=[Depends(require_password)])
def update_review(invoice_no: str, change: ReviewChange):
    set_invoice_review_status(invoice_no, change.status)
    return {"updated": True}


@app.post("/api/disputes", dependencies=[Depends(require_password)])
def create_dispute(dispute: DisputeChange):
    add_disputed_items(dispute.invoice_no, dispute.items)
    return {"created": True}


@app.put("/api/disputes/cancel", dependencies=[Depends(require_password)])
def cancel_disputes(change: CancelDispute):
    cancel_disputed_items(change.pairs, change.reason)
    return {"updated": True}


@app.post("/api/import/boxes", dependencies=[Depends(require_password)])
async def import_box_file(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(400, "Upload a CSV or Excel box file.")
    uploaded = BytesIO(await file.read())
    uploaded.name = file.filename
    frame = read_box_import_file(uploaded)
    return import_boxes(frame)


@app.post("/api/import/customer-invoices", dependencies=[Depends(require_password)])
async def import_customer_invoice_file(file: UploadFile = File(...), mosaic: bool = Query(False)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Upload a CSV customer invoice file.")
    uploaded = BytesIO(await file.read())
    frame = read_mosaic_handling_file(uploaded) if mosaic else read_customer_invoice_file(uploaded)
    return import_mosaic_handling_invoices(frame) if mosaic else import_customer_invoices(frame)


@app.post("/api/import/fedex", dependencies=[Depends(require_password)])
async def import_fedex_pdf(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Upload a PDF invoice.")
    return {"invoices": ingest_pdf_bundle(BytesIO(await file.read()), file.filename)}


@app.post("/api/admin/migrate-sqlite", dependencies=[Depends(require_password)])
async def migrate_sqlite(file: UploadFile = File(...)):
    """One-time authenticated migration of the local NeXa SQLite backup."""
    if not file.filename or not file.filename.lower().endswith(".db.gz"):
        raise HTTPException(400, "Upload a gzip-compressed SQLite backup ending in .db.gz.")
    try:
        copied = await run_in_threadpool(restore_sqlite_backup, await file.read())
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    return {"migrated": copied}
