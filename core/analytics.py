import numpy as np
import pandas as pd

from core.config import (
    ABOVE_AVERAGE_THRESHOLD_FIXED_USD,
    ABOVE_AVERAGE_THRESHOLD_PERCENT,
    CANADA_SHIPPING_RATE_CARD,
    HIGH_INVOICE_WARNING_USD,
    INVOICE_WAITING_PERIOD_DAYS,
    MINIMUM_SAMPLE_SIZE_FOR_AVERAGE,
    NO_DUTY_COUNTRIES,
)
from core.dates import parse_dates

ENOUGH_DATA = "Enough Data"
NOT_ENOUGH_DATA = "Not Enough Data"

KNOWN_SHIPMENT_TYPES = {
    "SINGLE": "Single",
    "MULTI": "Multi",
    "PALET": "Pallet",
    "PALLET": "Pallet",
}


def normalize_shipment_type(value):
    if value is None:
        return None
    return KNOWN_SHIPMENT_TYPES.get(str(value).strip().upper())


def find_unrecognized_shipment_types(boxes_df):
    df = boxes_df.copy()
    df["shipment_type_normalized"] = df["shipment_type"].apply(normalize_shipment_type)
    return df[df["shipment_type_normalized"].isna()]


def compute_benchmarks(boxes_df, min_sample_size=MINIMUM_SAMPLE_SIZE_FOR_AVERAGE):
    df = boxes_df.copy()
    df["shipment_type"] = df["shipment_type"].apply(normalize_shipment_type)
    df = df[df["shipment_type"].notna()]
    df["shipping"] = pd.to_numeric(df["fedex_shipping_amount"], errors="coerce")
    df["duty"] = pd.to_numeric(df["fedex_duty_amount"], errors="coerce")
    df["total"] = pd.to_numeric(df["fedex_total_cost"], errors="coerce")

    grouped = (
        df.groupby(["country", "shipment_type"])
        .agg(
            record_count=("total", "count"),
            avg_shipping_per_box=("shipping", "mean"),
            avg_duty_per_box=("duty", "mean"),
            avg_total_per_box=("total", "mean"),
        )
        .reset_index()
    )
    grouped["status"] = grouped["record_count"].apply(
        lambda n: ENOUGH_DATA if n >= min_sample_size else NOT_ENOUGH_DATA
    )
    return grouped


def compute_above_average_boxes(
    boxes_df,
    min_sample_size=MINIMUM_SAMPLE_SIZE_FOR_AVERAGE,
    threshold_percent=ABOVE_AVERAGE_THRESHOLD_PERCENT,
    threshold_fixed=ABOVE_AVERAGE_THRESHOLD_FIXED_USD,
):
    benchmarks = compute_benchmarks(boxes_df, min_sample_size)

    df = boxes_df.copy()
    df["shipment_type_normalized"] = df["shipment_type"].apply(normalize_shipment_type)
    df["total"] = pd.to_numeric(df["fedex_total_cost"], errors="coerce")

    merged = df.merge(
        benchmarks[["country", "shipment_type", "avg_total_per_box", "status"]],
        left_on=["country", "shipment_type_normalized"],
        right_on=["country", "shipment_type"],
        how="left",
    )
    merged["difference"] = merged["total"] - merged["avg_total_per_box"]
    merged["percent_over"] = merged["difference"] / merged["avg_total_per_box"]

    is_above = (merged["status"] == ENOUGH_DATA) & (
        (merged["percent_over"] >= threshold_percent)
        | ((threshold_fixed > 0) & (merged["difference"] >= threshold_fixed))
    )
    return merged[is_above].sort_values("percent_over", ascending=False)


def compute_data_issues(boxes_df, high_invoice_threshold=HIGH_INVOICE_WARNING_USD):
    df = boxes_df.copy()
    df["duty_numeric"] = pd.to_numeric(df["fedex_duty_amount"], errors="coerce")
    df["total_numeric"] = pd.to_numeric(df["fedex_total_cost"], errors="coerce")
    df["shipment_type_normalized"] = df["shipment_type"].apply(normalize_shipment_type)

    issues = []

    missing_fields = df[df["country"].isna() | df["company"].isna() | df["ship_date"].isna()]
    for _, row in missing_fields.iterrows():
        issues.append({**row.to_dict(), "issue": "Missing country, company, or ship date"})

    unexpected_duty = df[df["country"].isin(NO_DUTY_COUNTRIES) & (df["duty_numeric"] > 0)]
    for _, row in unexpected_duty.iterrows():
        issues.append({**row.to_dict(), "issue": f"Unexpected Duty charge for {row['country']}"})

    high_invoices = df[df["total_numeric"] > high_invoice_threshold]
    for _, row in high_invoices.iterrows():
        issues.append({**row.to_dict(), "issue": "Unusually high invoice total"})

    missing_master = df[
        (df["shipment_type_normalized"] == "Multi") & (df["multi_no"].isna() | (df["multi_no"] == ""))
    ]
    for _, row in missing_master.iterrows():
        issues.append({**row.to_dict(), "issue": "Multi-box shipment missing Master Tracking / Multi No"})

    unrecognized = find_unrecognized_shipment_types(df)
    for _, row in unrecognized.iterrows():
        issues.append({**row.to_dict(), "issue": f"Unrecognized shipment type: {row['shipment_type']}"})

    return pd.DataFrame(issues)


def enrich_boxes_for_display(boxes_df):
    """Computes display-only convenience fields on top of the raw Boxes data —
    never written back to the database, so the raw historical record stays intact.

    - customer_total_invoice = customer_shipping_fee + customer_packaging_fee.
    - Master Duty/Shipping allocation: when several boxes share the same Multi No
      (a multi-box shipment) and only one of them carries the FedEx invoice
      number/amount (because FedEx bills the master tracking number, not every
      box), that invoice number and service type are copied onto its sibling
      boxes and the amount is split evenly across the whole group — matching the
      Canada Duty / Express multi-box billing rule.
    """
    df = boxes_df.copy()

    shipping_fee = pd.to_numeric(df["customer_shipping_fee"], errors="coerce")
    packaging_fee = pd.to_numeric(df["customer_packaging_fee"], errors="coerce")
    # A plain shipping_fee + packaging_fee would go NaN the moment either side is
    # missing — most boxes only ever have customer_shipping_fee set (packaging_fee
    # is only populated for the pallets that carry a separate duty/tax charge), so
    # that silently zeroed out the known shipping fee for the vast majority of
    # boxes. Only treat the total as unknown when BOTH sides are missing.
    both_fees_missing = shipping_fee.isna() & packaging_fee.isna()
    df["customer_total_invoice"] = (shipping_fee.fillna(0) + packaging_fee.fillna(0)).where(
        ~both_fees_missing
    )

    df["fedex_duty_amount"] = pd.to_numeric(df["fedex_duty_amount"], errors="coerce")
    df["fedex_shipping_amount"] = pd.to_numeric(df["fedex_shipping_amount"], errors="coerce")

    groupable = df[df["multi_no"].notna() & (df["multi_no"] != "")]
    for multi_no, group in groupable.groupby("multi_no"):
        if len(group) <= 1:
            continue
        box_count = len(group)

        duty_source = group[group["fedex_duty_invoice_no"].notna()]
        if len(duty_source) >= 1:
            source = duty_source.iloc[0]
            # A Multi group can legitimately carry more than one duty invoice (a
            # partial/separate customs entry against a second box in the same
            # group) — sum every duty-carrying box's amount, not just the first,
            # or the second invoice's money silently vanishes from the group's
            # total (found 2026-09-22: 4 groups, $167.98 lost this way). The
            # displayed invoice number still shows only the first one; the
            # dollar amount is now always correct.
            duty_amounts = pd.to_numeric(duty_source["fedex_duty_amount"], errors="coerce")
            per_box_duty = duty_amounts.sum() / box_count if duty_amounts.notna().any() else None
            for idx in group.index:
                df.at[idx, "fedex_duty_invoice_no"] = source["fedex_duty_invoice_no"]
                df.at[idx, "fedex_duty_amount"] = per_box_duty
                if pd.isna(df.at[idx, "fedex_service_type"]) and pd.notna(source["fedex_service_type"]):
                    df.at[idx, "fedex_service_type"] = source["fedex_service_type"]

        shipping_source = group[group["fedex_shipping_invoice_no"].notna()]
        if len(shipping_source) == 1:
            source = shipping_source.iloc[0]
            per_box_shipping = (
                source["fedex_shipping_amount"] / box_count
                if pd.notna(source["fedex_shipping_amount"])
                else None
            )
            for idx in group.index:
                df.at[idx, "fedex_shipping_invoice_no"] = source["fedex_shipping_invoice_no"]
                df.at[idx, "fedex_shipping_amount"] = per_box_shipping
                if pd.isna(df.at[idx, "fedex_service_type"]) and pd.notna(source["fedex_service_type"]):
                    df.at[idx, "fedex_service_type"] = source["fedex_service_type"]

    both_missing = df["fedex_duty_amount"].isna() & df["fedex_shipping_amount"].isna()
    total_cost = df["fedex_duty_amount"].fillna(0) + df["fedex_shipping_amount"].fillna(0)

    # A box with no FedEx invoice match after INVOICE_WAITING_PERIOD_DAYS is treated
    # as permanently resolved at $0 cost rather than staying "Bekliyor" forever — the
    # business rule established for this app from the start, just never wired up
    # until now. Only boxes still inside that window keep showing "Bekliyor".
    ship_date_parsed = parse_dates(df["ship_date"])
    waiting_period_cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=INVOICE_WAITING_PERIOD_DAYS)
    still_within_waiting_period = both_missing & (ship_date_parsed >= waiting_period_cutoff)

    df["fedex_total_cost"] = total_cost.where(~still_within_waiting_period, "Bekliyor")

    # True for a box that's only showing a $0 cost because it aged past the waiting
    # period with no invoice ever matched — as opposed to a genuine $0 or a real
    # invoiced amount. Lets a report tell "actually resolved" apart from "forced
    # resolved by the clock" without changing what fedex_total_cost itself displays.
    df["_forced_zero_cost"] = both_missing & ~still_within_waiting_period

    numeric_total = pd.to_numeric(df["fedex_total_cost"], errors="coerce")
    df["profit_loss"] = (df["customer_total_invoice"] - numeric_total).where(
        numeric_total.notna(), "Bekliyor"
    )

    return df


REVENUE_INVOICED = "Invoiced"
REVENUE_NOT_INVOICED = "Not Invoiced"

FEDEX_STATUS_ACTUAL = "Actual"
FEDEX_STATUS_EXPECTED = "Invoice Expected"
FEDEX_STATUS_OVERDUE = "Invoice Overdue"

PROFIT_INCLUDED = "Included"
PROFIT_EXCLUDED_NO_INVOICE = "Excluded - Customer Invoice Missing"


def compute_profit_calculation(enriched_boxes_df):
    """Adds the Actual-only profit/loss fields on top of enrich_boxes_for_display's
    output, per the business rule fixed with the user on 2026-09-19:

    - No customer invoice at all -> the box is entirely excluded from revenue,
      cost, and profit (all zero), but stays visible as "Not Invoiced" /
      "Excluded - Customer Invoice Missing" rather than being deleted or hidden.
    - Customer invoice present but no FedEx invoice yet -> the box IS included,
      at Revenue = Customer Invoice, FedEx Cost = 0, Profit = Revenue. This does
      NOT change once 14 days pass; the 14-day mark only flips FedEx Status from
      "Invoice Expected" to "Invoice Overdue" for visibility, never the cost.
    - Customer invoice + FedEx invoice both present -> Revenue - Actual FedEx
      Cost, the real numbers, no estimation involved anywhere in this path.
    - A FedEx cost that lands on a box with no customer invoice is real money
      the company spent, so it must never vanish — it's tracked separately as
      fedex_cost_excluded_no_invoice, visible in reconciliation, but deliberately
      kept out of that box's own profit (which is 0, per the first rule).

    No accrual/estimated cost is computed here — deliberately out of scope for
    the Actual profit numbers. Estimation, if ever wanted, belongs in a
    completely separate forecast view, never blended into these fields.
    """
    df = enriched_boxes_df.copy()

    # A box whose shipping/packaging fee columns are both a literal 0.0 (rather than
    # NULL) is, in practice, the same as never having been invoiced at all — real
    # customer invoices here are never actually $0 — so it must not show up as a
    # "loss" against a real FedEx cost. Only a genuine positive invoice counts.
    customer_invoice = pd.to_numeric(df["customer_total_invoice"], errors="coerce")
    has_customer_invoice = customer_invoice.notna() & (customer_invoice > 0)
    df["revenue_status"] = np.where(has_customer_invoice, REVENUE_INVOICED, REVENUE_NOT_INVOICED)

    duty = pd.to_numeric(df["fedex_duty_amount"], errors="coerce")
    shipping = pd.to_numeric(df["fedex_shipping_amount"], errors="coerce")
    has_fedex_invoice = duty.notna() | shipping.notna()
    fedex_amount = duty.fillna(0) + shipping.fillna(0)

    ship_date_parsed = parse_dates(df["ship_date"])
    waiting_cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=INVOICE_WAITING_PERIOD_DAYS)
    df["fedex_status"] = np.select(
        [has_fedex_invoice, ship_date_parsed >= waiting_cutoff],
        [FEDEX_STATUS_ACTUAL, FEDEX_STATUS_EXPECTED],
        default=FEDEX_STATUS_OVERDUE,
    )

    df["profit_calculation_status"] = np.where(
        has_customer_invoice, PROFIT_INCLUDED, PROFIT_EXCLUDED_NO_INVOICE
    )

    df["revenue"] = customer_invoice.where(has_customer_invoice, 0.0)
    # Only an Included box's FedEx cost counts toward profit — an Excluded box's
    # real FedEx charge (if any) is tracked separately below, never here.
    df["actual_fedex_cost"] = fedex_amount.where(has_customer_invoice, 0.0)
    df["fedex_cost_excluded_no_invoice"] = fedex_amount.where(~has_customer_invoice, 0.0)
    df["actual_profit"] = df["revenue"] - df["actual_fedex_cost"]

    return df


def compute_unallocated_fedex(boxes_df, shipment_charges_df):
    """FedEx invoice lines whose tracking number has no matching row in Boxes at
    all — a real cost the company already paid, that can't be attributed to any
    box yet. Returned as (total_amount, detail_df) so the Dashboard can show the
    number while a drill-down screen shows exactly which lines make it up."""
    known_tracking_ids = set(boxes_df["tracking_id"].dropna())
    unallocated = shipment_charges_df[
        ~shipment_charges_df["tracking_id"].isin(known_tracking_ids)
    ].copy()
    total = pd.to_numeric(unallocated["amount"], errors="coerce").sum()
    return total, unallocated


def compute_unmatched_second_invoice(boxes_df, shipment_charges_df):
    """A shipment_charges line whose tracking_id DOES match a box, but whose
    invoice_number differs from the invoice number already recorded on that box
    for the same charge type (Duty vs Shipping) — a second/adjustment invoice
    that _sync_box correctly refused to overwrite (so the box keeps its original
    invoice), but whose money then landed in none of Included/Excluded/
    Unallocated — the reconciliation identity never noticed because it was
    computed as the sum of its own three buckets instead of against the real
    charge lines. Found 2026-09-22 (H-1): $10,177.46 across 541 lines.

    Only Duty and Shipping charge types are evaluated here (matching the box
    columns that exist to compare against); needs both an 'invoice_number' and
    a 'charge_type' column on shipment_charges_df — returns an empty result if
    either is absent rather than guessing."""
    if "invoice_number" not in shipment_charges_df.columns or "charge_type" not in shipment_charges_df.columns:
        return 0.0, shipment_charges_df.iloc[0:0]

    box_lookup = boxes_df.drop_duplicates("tracking_id", keep="first").set_index("tracking_id")[
        ["fedex_duty_invoice_no", "fedex_shipping_invoice_no"]
    ]

    charges = shipment_charges_df[shipment_charges_df["tracking_id"].isin(box_lookup.index)].copy()
    joined = charges.join(box_lookup, on="tracking_id")

    is_duty = joined["charge_type"] == "Duty"
    is_shipping = joined["charge_type"] == "Shipping"
    matches_duty = is_duty & (joined["invoice_number"] == joined["fedex_duty_invoice_no"])
    matches_shipping = is_shipping & (joined["invoice_number"] == joined["fedex_shipping_invoice_no"])
    already_reflected = matches_duty | matches_shipping

    unmatched = joined[(is_duty | is_shipping) & ~already_reflected]
    total = pd.to_numeric(unmatched["amount"], errors="coerce").sum()
    return total, unmatched


def compute_fedex_reconciliation(profit_boxes_df, shipment_charges_df):
    """The FedEx-cost identity that must always hold:
    Total FedEx Invoice = Included + Excluded (no customer invoice) + Unallocated
    + Unmatched Second Invoice. Every dollar FedEx ever billed lands in exactly
    one of these four buckets — never dropped, never double-counted.

    total_fedex_invoice is the SUM of those four buckets (true by construction),
    not an independent sum over shipment_charges — that was tried (2026-09-22,
    investigating H-1) and reverted: shipment_charges only holds costs that came
    through PDF ingestion, while boxes.fedex_duty_amount/fedex_shipping_amount
    also includes real cost entered through other paths (manual/bulk historical
    import, the legacy Excel migration). ~845 boxes ($103k+ raw) carry a real
    FedEx cost with no shipment_charges row at all for their tracking_id —
    treating shipment_charges as ground truth would make the headline total
    wrong by that much, not more correct. unmatched_second_invoice (H-1's
    actual, narrower finding) is still fully captured and shown separately."""
    included = pd.to_numeric(profit_boxes_df["actual_fedex_cost"], errors="coerce").sum()
    excluded = pd.to_numeric(profit_boxes_df["fedex_cost_excluded_no_invoice"], errors="coerce").sum()
    unallocated_total, unallocated_detail = compute_unallocated_fedex(profit_boxes_df, shipment_charges_df)
    unmatched_total, unmatched_detail = compute_unmatched_second_invoice(profit_boxes_df, shipment_charges_df)
    total_invoice = included + excluded + unallocated_total + unmatched_total

    pending_mask = (profit_boxes_df["profit_calculation_status"] == PROFIT_INCLUDED) & (
        profit_boxes_df["fedex_status"] != FEDEX_STATUS_ACTUAL
    )
    return {
        "total_fedex_invoice": total_invoice,
        "included": included,
        "excluded_no_customer_invoice": excluded,
        "unallocated": unallocated_total,
        "unmatched_second_invoice": unmatched_total,
        "pending_count": int(pending_mask.sum()),
        "overdue_count": int(
            (pending_mask & (profit_boxes_df["fedex_status"] == FEDEX_STATUS_OVERDUE)).sum()
        ),
        "unallocated_detail": unallocated_detail,
        "unmatched_second_invoice_detail": unmatched_detail,
    }


def compute_customer_invoice_reconciliation(profit_boxes_df):
    total_boxes = len(profit_boxes_df)
    included = profit_boxes_df[profit_boxes_df["profit_calculation_status"] == PROFIT_INCLUDED]
    excluded = profit_boxes_df[profit_boxes_df["profit_calculation_status"] == PROFIT_EXCLUDED_NO_INVOICE]
    return {
        "total_boxes": total_boxes,
        "invoiced_boxes": len(included),
        "missing_boxes": len(excluded),
        "revenue_included": pd.to_numeric(included["revenue"], errors="coerce").sum(),
        "revenue_excluded": 0.0,
    }


def compute_customer_profitability(profit_boxes_df, month=None):
    """Customer Profitability table (Excel's 'Müşterilere Göre Kar/Zarar', mirrored
    1:1 in NeXa): one row per customer, Included boxes only — a box with no
    customer invoice never contributes revenue or profit here. month, if given,
    is a 'Mon YYYY' string (e.g. 'Sep 2026') filtering to that shipment month;
    None means all-time totals per customer."""
    df = profit_boxes_df[profit_boxes_df["profit_calculation_status"] == PROFIT_INCLUDED].copy()
    # A box can have a real customer invoice with no customer_code entered yet —
    # grouping would otherwise silently drop that revenue from every total below.
    df["customer_code"] = df["customer_code"].where(
        df["customer_code"].notna() & (df["customer_code"] != ""), "(Unknown Customer)"
    )
    ship_date = parse_dates(df["ship_date"])
    df["_month_label"] = ship_date.dt.strftime("%b %Y")
    excluded_count = (profit_boxes_df["profit_calculation_status"] == PROFIT_EXCLUDED_NO_INVOICE).sum()

    if month:
        df = df[df["_month_label"] == month]

    grouped = df.groupby("customer_code").agg(
        boxes=("id", "size"),
        revenue=("revenue", "sum"),
        fedex_cost=("actual_fedex_cost", "sum"),
    ).reset_index()
    grouped["profit"] = grouped["revenue"] - grouped["fedex_cost"]
    grouped["margin_percent"] = np.where(
        grouped["revenue"] != 0, grouped["profit"] / grouped["revenue"], None
    )
    grouped = grouped.sort_values("customer_code").reset_index(drop=True)
    return grouped, int(excluded_count)


def get_canada_agreed_shipping_rate(box_count):
    """The negotiated per-box Canada shipping rate for a group of this size
    (a Single shipment is a group of 1). Groups larger than the highest
    negotiated tier are billed at that tier's rate. Returns None when the
    group size has no agreed rate at all (e.g. a 2-box group)."""
    if pd.isna(box_count):
        return None
    box_count = int(box_count)
    if box_count in CANADA_SHIPPING_RATE_CARD:
        return CANADA_SHIPPING_RATE_CARD[box_count]
    max_tier = max(CANADA_SHIPPING_RATE_CARD)
    if box_count > max_tier:
        return CANADA_SHIPPING_RATE_CARD[max_tier]
    return None


def flag_shipping_rate_alerts(shipment_df, benchmarks_df, shipment_type_column="shipment_type"):
    """Flags shipping-charge rows (one per FedEx invoice line) that either broke
    the fixed Canada shipping rate agreement (by box-group size) or, for every
    other country, came in above that country + shipment-type's average per-box
    shipping cost. shipment_df needs: amount, group_amount, box_count, country,
    and a shipment-type column (Single/Multi/Pallet, named by shipment_type_column)."""
    df = shipment_df.reset_index(drop=True)
    per_box = pd.to_numeric(df["amount"], errors="coerce")
    group_amount = pd.to_numeric(df["group_amount"], errors="coerce")
    box_count = pd.to_numeric(df["box_count"], errors="coerce")
    per_box = per_box.where(per_box.notna(), group_amount / box_count)

    is_canada = df["country"] == "CA"
    canada_rate = box_count.apply(get_canada_agreed_shipping_rate)
    canada_alert = is_canada & canada_rate.notna() & (per_box > canada_rate)

    enough_data_benchmarks = benchmarks_df[benchmarks_df["status"] == ENOUGH_DATA][
        ["country", "shipment_type", "avg_shipping_per_box"]
    ]
    merged = df.merge(
        enough_data_benchmarks,
        left_on=["country", shipment_type_column],
        right_on=["country", "shipment_type"],
        how="left",
    )
    other_alert = (
        (~is_canada).values
        & merged["avg_shipping_per_box"].notna().values
        & (per_box.values > merged["avg_shipping_per_box"].values)
    )

    return canada_alert.values | other_alert


def compute_duty_above_average_flag(
    boxes_df,
    benchmarks_df,
    threshold_percent=ABOVE_AVERAGE_THRESHOLD_PERCENT,
    threshold_fixed=ABOVE_AVERAGE_THRESHOLD_FIXED_USD,
):
    """Per-box boolean flag: True when this box's Duty cost is far enough above
    its country + shipment-type average to warrant a visible warning (same
    over-threshold rule used for the Above-Average Invoices page, restricted to
    the Duty portion only)."""
    df = boxes_df.reset_index(drop=True).copy()
    df["shipment_type_normalized"] = df["shipment_type"].apply(normalize_shipment_type)
    duty_numeric = pd.to_numeric(df["fedex_duty_amount"], errors="coerce")

    merged = df.merge(
        benchmarks_df[["country", "shipment_type", "avg_duty_per_box", "status"]],
        left_on=["country", "shipment_type_normalized"],
        right_on=["country", "shipment_type"],
        how="left",
    )
    diff = duty_numeric.values - merged["avg_duty_per_box"].values
    with np.errstate(divide="ignore", invalid="ignore"):
        percent_over = diff / merged["avg_duty_per_box"].values
    is_above = (
        (merged["status"] == ENOUGH_DATA).values
        & duty_numeric.notna().values
        & (
            (percent_over >= threshold_percent)
            | ((threshold_fixed > 0) & (diff >= threshold_fixed))
        )
    )
    return pd.Series(is_above).fillna(False).values


def compute_shipping_above_average_flag(boxes_df, benchmarks_df):
    """Per-box boolean flag: True when this box's Shipping cost broke the fixed
    Canada rate agreement (by multi-group size) or, for every other country, came
    in above its country + shipment-type average per-box shipping cost — the same
    rule used for the Shipping-invoice row highlight on the invoice-drilldown pages,
    applied here at the box level."""
    df = boxes_df.reset_index(drop=True).copy()
    df["shipment_type_normalized"] = df["shipment_type"].apply(normalize_shipment_type)

    group_sizes = df.groupby("multi_no")["multi_no"].transform("size")
    box_count = group_sizes.where(df["multi_no"].notna() & (df["multi_no"] != ""), 1)

    shipping_input = pd.DataFrame(
        {
            "amount": pd.to_numeric(df["fedex_shipping_amount"], errors="coerce"),
            "group_amount": None,
            "box_count": box_count,
            "country": df["country"],
            "shipment_type": df["shipment_type_normalized"],
        }
    )
    return flag_shipping_rate_alerts(shipping_input, benchmarks_df)
