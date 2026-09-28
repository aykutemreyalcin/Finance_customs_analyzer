"""One place for turning NeXa's stored date strings into real dates, and back.

Why this exists: dates reached the DB from several sources in different shapes —
legacy Excel ('2026-01-02 00:00:00'), FedEx PDFs ('Sep 08, 2026'), manual entry
('2026-09-08'), QuickBooks CSVs ('8/29/2026'), MOSAIC CSVs ('11-May-26'). A plain
pd.to_datetime(..., errors="coerce") infers ONE format from the first value and
silently turns every other shape into NaT, which dropped those boxes out of every
date filter. Always parse through parse_dates().

Slash dates are month/day/year (US / QuickBooks) — confirmed with the user on
2026-09-22 and consistent with the data (no stored value has a first part > 12).
"""
import pandas as pd

# Canonical stored shapes: the format each table's majority of rows already used,
# so normalizing touches as few rows as possible and exports keep their shape.
BOX_SHIP_DATE_FORMAT = "%Y-%m-%d 00:00:00"  # boxes.ship_date


def parse_dates(values):
    """Series/list of raw date strings -> datetime64 Series (NaT where unparseable)."""
    series = values if isinstance(values, pd.Series) else pd.Series(values)
    return pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=False)


def _parse_one(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    parsed = parse_dates(pd.Series([text])).iloc[0]
    return None if pd.isna(parsed) else parsed


def to_box_ship_date(value):
    """Canonical boxes.ship_date string, or the original value unchanged if it
    can't be parsed (never lose what was entered — Data Quality surfaces it)."""
    parsed = _parse_one(value)
    if parsed is None:
        return value if value not in ("",) else None
    return parsed.strftime(BOX_SHIP_DATE_FORMAT)


def to_customer_invoice_date(value):
    """Canonical customer_invoices date string: QuickBooks-style M/D/YYYY (no zero
    padding, e.g. '8/29/2026'), or the original value unchanged if unparseable."""
    parsed = _parse_one(value)
    if parsed is None:
        return value if value not in ("",) else None
    return f"{parsed.month}/{parsed.day}/{parsed.year}"


def is_valid_date(value):
    return _parse_one(value) is not None
