"""Regression tests for the Actual-only financial model in core/analytics.py.

The model itself is documented in CLAUDE.md ("Financial model"). Tests marked
xfail(strict=True) pin down KNOWN, not-yet-fixed bugs found in the 2026-09-22
audit (docs/NEXA_HEALTH_REPORT.md); when one of them is fixed the test starts
passing, strict=True turns that into a failure, and the marker must be removed.
"""
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from core.analytics import (
    FEDEX_STATUS_ACTUAL,
    FEDEX_STATUS_EXPECTED,
    FEDEX_STATUS_OVERDUE,
    PROFIT_EXCLUDED_NO_INVOICE,
    PROFIT_INCLUDED,
    compute_customer_profitability,
    compute_fedex_reconciliation,
    compute_profit_calculation,
    enrich_boxes_for_display,
    get_canada_agreed_shipping_rate,
)

BOX_COLUMNS = [
    "id", "ship_date", "company", "customer_code", "country", "box_no", "shipment_type",
    "box_type_size", "multi_no", "tracking_id", "customer_shipping_fee",
    "customer_packaging_fee", "customer_total_invoice", "fedex_service_type",
    "fedex_duty_invoice_no", "fedex_duty_amount", "fedex_shipping_invoice_no",
    "fedex_shipping_amount", "fedex_total_cost", "profit_loss",
]


def make_boxes(rows):
    df = pd.DataFrame(rows)
    for col in BOX_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df["id"] = range(1, len(df) + 1)
    return df[BOX_COLUMNS]


def days_ago(n):
    return (pd.Timestamp.now().normalize() - pd.Timedelta(days=n)).strftime("%Y-%m-%d 00:00:00")


def profit_of(rows):
    return compute_profit_calculation(enrich_boxes_for_display(make_boxes(rows)))


# --- Rule 1: no customer invoice -> excluded, all zero, never dropped -------------

def test_box_without_customer_invoice_is_excluded_but_kept():
    p = profit_of([{"tracking_id": "1", "ship_date": days_ago(30),
                    "fedex_shipping_invoice_no": "9-1", "fedex_shipping_amount": 40.0}])
    row = p.iloc[0]
    assert len(p) == 1
    assert row["profit_calculation_status"] == PROFIT_EXCLUDED_NO_INVOICE
    assert row["revenue"] == 0 and row["actual_fedex_cost"] == 0 and row["actual_profit"] == 0
    # Rule 4: the real FedEx money is tracked separately, never lost.
    assert row["fedex_cost_excluded_no_invoice"] == pytest.approx(40.0)


def test_literal_zero_fees_count_as_not_invoiced():
    p = profit_of([{"tracking_id": "1", "ship_date": days_ago(30),
                    "customer_shipping_fee": 0.0, "customer_packaging_fee": 0.0,
                    "fedex_shipping_invoice_no": "9-1", "fedex_shipping_amount": 25.0}])
    assert p.iloc[0]["profit_calculation_status"] == PROFIT_EXCLUDED_NO_INVOICE
    assert p.iloc[0]["actual_profit"] == 0


def test_packaging_fee_only_still_counts_as_invoiced():
    p = profit_of([{"tracking_id": "1", "ship_date": days_ago(30),
                    "customer_packaging_fee": 12.5}])
    assert p.iloc[0]["revenue"] == pytest.approx(12.5)


# --- Rule 2: customer invoice, FedEx not yet billed -> included at cost 0 ---------

@pytest.mark.parametrize("age_days, expected_status", [(3, FEDEX_STATUS_EXPECTED), (40, FEDEX_STATUS_OVERDUE)])
def test_waiting_period_only_relabels_status_never_cost(age_days, expected_status):
    p = profit_of([{"tracking_id": "1", "ship_date": days_ago(age_days), "customer_shipping_fee": 50.0}])
    row = p.iloc[0]
    assert row["profit_calculation_status"] == PROFIT_INCLUDED
    assert row["fedex_status"] == expected_status
    assert row["actual_fedex_cost"] == 0
    assert row["actual_profit"] == pytest.approx(50.0)


# --- Rule 3: both present -> real numbers ----------------------------------------

def test_profit_is_revenue_minus_actual_fedex_cost():
    p = profit_of([{"tracking_id": "1", "ship_date": days_ago(30), "customer_shipping_fee": 50.0,
                    "fedex_shipping_invoice_no": "9-1", "fedex_shipping_amount": 30.0,
                    "fedex_duty_invoice_no": "9-2", "fedex_duty_amount": 5.0}])
    row = p.iloc[0]
    assert row["fedex_status"] == FEDEX_STATUS_ACTUAL
    assert row["actual_profit"] == pytest.approx(15.0)


# --- Multi-box allocation ---------------------------------------------------------

def test_master_duty_is_split_evenly_across_multi_group():
    rows = [{"tracking_id": str(i), "multi_no": "M1", "ship_date": days_ago(30),
             "customer_shipping_fee": 10.0} for i in range(3)]
    rows[0].update(fedex_duty_invoice_no="9-D", fedex_duty_amount=30.0)
    e = enrich_boxes_for_display(make_boxes(rows))
    assert list(e["fedex_duty_amount"]) == [10.0, 10.0, 10.0]
    assert e["fedex_duty_amount"].sum() == pytest.approx(30.0)


# Regression for H-2 (fixed 2026-09-22): a Multi group with 2+ duty-carrying
# boxes used to keep only the first one's amount, silently dropping the rest.
def test_multi_group_with_two_duty_sources_keeps_every_dollar():
    rows = [{"tracking_id": str(i), "multi_no": "M1", "ship_date": days_ago(30),
             "customer_shipping_fee": 10.0} for i in range(3)]
    rows[0].update(fedex_duty_invoice_no="9-D1", fedex_duty_amount=30.0)
    rows[1].update(fedex_duty_invoice_no="9-D2", fedex_duty_amount=15.0)
    e = enrich_boxes_for_display(make_boxes(rows))
    assert e["fedex_duty_amount"].sum() == pytest.approx(45.0)


# --- Dates ------------------------------------------------------------------------

# Regression for C-1 (fixed 2026-09-22): ship_date was stored in 3 formats and a
# plain pd.to_datetime turned all but the first shape into NaT.
def test_mixed_ship_date_formats_all_parse():
    p = profit_of([
        {"tracking_id": "1", "ship_date": "2026-09-01 00:00:00", "customer_shipping_fee": 10.0},
        {"tracking_id": "2", "ship_date": "Sep 02, 2026", "customer_shipping_fee": 10.0},
        {"tracking_id": "3", "ship_date": "2026-09-03", "customer_shipping_fee": 10.0},
    ])
    table, _ = compute_customer_profitability(p, month="Sep 2026")
    assert table["boxes"].sum() == 3


# --- Customer profitability -------------------------------------------------------

def test_customer_profitability_keeps_revenue_of_unknown_customer():
    p = profit_of([
        {"tracking_id": "1", "ship_date": days_ago(30), "customer_code": "ZL", "customer_shipping_fee": 20.0},
        {"tracking_id": "2", "ship_date": days_ago(30), "customer_code": None, "customer_shipping_fee": 5.0},
        {"tracking_id": "3", "ship_date": days_ago(30), "customer_code": "ZL"},
    ])
    table, excluded = compute_customer_profitability(p)
    assert table["revenue"].sum() == pytest.approx(p["revenue"].sum()) == pytest.approx(25.0)
    assert excluded == 1
    assert "(Unknown Customer)" in set(table["customer_code"])


# --- Reconciliation ---------------------------------------------------------------

def test_reconciliation_buckets_add_up_and_unallocated_is_counted():
    p = profit_of([
        {"tracking_id": "1", "ship_date": days_ago(30), "customer_shipping_fee": 50.0,
         "fedex_shipping_invoice_no": "9-1", "fedex_shipping_amount": 30.0},
        {"tracking_id": "2", "ship_date": days_ago(30),
         "fedex_shipping_invoice_no": "9-1", "fedex_shipping_amount": 20.0},
    ])
    charges = pd.DataFrame({"tracking_id": ["1", "2", "999"], "amount": [30.0, 20.0, 7.0]})
    r = compute_fedex_reconciliation(p, charges)
    assert r["included"] == pytest.approx(30.0)
    assert r["excluded_no_customer_invoice"] == pytest.approx(20.0)
    assert r["unallocated"] == pytest.approx(7.0)
    assert r["total_fedex_invoice"] == pytest.approx(57.0)


# Regression for H-1 (fixed 2026-09-22, narrower than first proposed — see the
# docstring on compute_fedex_reconciliation for why total_fedex_invoice is NOT
# computed directly from shipment_charges): a second real charge line for a
# box's tracking_id, billed under a different invoice number than the one
# already recorded on the box, used to disappear from every bucket. It's now
# surfaced as its own "unmatched_second_invoice" bucket instead of being lost.
def test_reconciliation_second_invoice_for_same_box_is_not_lost():
    p = profit_of([{"tracking_id": "1", "ship_date": days_ago(30), "customer_shipping_fee": 50.0,
                    "fedex_duty_invoice_no": "9-A", "fedex_duty_amount": 10.0}])
    charges = pd.DataFrame({
        "tracking_id": ["1", "1"],
        "invoice_number": ["9-A", "9-B"],
        "charge_type": ["Duty", "Duty"],
        "amount": [10.0, 4.0],
    })
    r = compute_fedex_reconciliation(p, charges)
    assert r["included"] == pytest.approx(10.0)
    assert r["unmatched_second_invoice"] == pytest.approx(4.0)
    assert r["total_fedex_invoice"] == pytest.approx(14.0)


# --- Canada rate card -------------------------------------------------------------

@pytest.mark.parametrize("count, rate", [(1, 38.24), (2, None), (3, 32.89), (4, 28.26), (5, 28.26), (9, 28.26)])
def test_canada_rate_card(count, rate):
    assert get_canada_agreed_shipping_rate(count) == rate


# --- Live database invariants (read-only; skipped when the DB isn't present) -----

LIVE_DB = Path(__file__).resolve().parent.parent / "data" / "finance_customs.db"


@pytest.mark.skipif(not LIVE_DB.exists() or LIVE_DB.stat().st_size == 0, reason="no live DB")
def test_live_db_excluded_boxes_contribute_zero_and_views_agree():
    connection = sqlite3.connect(f"file:{LIVE_DB.as_posix()}?mode=ro", uri=True)
    boxes = pd.read_sql("SELECT * FROM boxes", connection)
    charges = pd.read_sql("SELECT * FROM shipment_charges", connection)
    connection.close()
    p = compute_profit_calculation(enrich_boxes_for_display(boxes))
    excluded = p[p["profit_calculation_status"] == PROFIT_EXCLUDED_NO_INVOICE]
    assert excluded[["revenue", "actual_fedex_cost", "actual_profit"]].abs().sum().sum() == 0
    table, _ = compute_customer_profitability(p)
    assert table["revenue"].sum() == pytest.approx(p["revenue"].sum(), abs=0.01)
    r = compute_fedex_reconciliation(p, charges)
    assert r["total_fedex_invoice"] == pytest.approx(
        r["included"] + r["excluded_no_customer_invoice"] + r["unallocated"]
        + r["unmatched_second_invoice"],
        abs=0.01,
    )
