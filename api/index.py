"""Vercel entrypoint for NeXa's JSON API.

The Streamlit application remains available for local data migration only.  This
module is the production interface: it uses DATABASE_URL/POSTGRES_URL, never a
filesystem database, and exposes the same calculation engine as the old UI.
"""

import os
import secrets
from io import BytesIO
from typing import Any

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from core.analytics import (
    compute_benchmarks,
    compute_customer_invoice_reconciliation,
    compute_customer_profitability,
    compute_data_issues,
    compute_fedex_reconciliation,
    compute_profit_calculation,
    enrich_boxes_for_display,
)
from core.box_import import add_single_box, import_boxes, read_box_import_file
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


@app.get("/api/data-issues", dependencies=[Depends(require_password)])
def data_issues():
    boxes, _, _ = load_financial_frames()
    return {"items": records(compute_data_issues(enrich_boxes_for_display(boxes)))}


@app.get("/api/invoices", dependencies=[Depends(require_password)])
def invoices():
    return {"items": records(read_frame("SELECT * FROM invoices ORDER BY invoice_date DESC, invoice_number"))}


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


@app.post("/api/import/fedex", dependencies=[Depends(require_password)])
async def import_fedex_pdf(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Upload a PDF invoice.")
    return {"invoices": ingest_pdf_bundle(BytesIO(await file.read()), file.filename)}
