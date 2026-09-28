import pandas as pd
import pytest

from core.dates import is_valid_date, parse_dates, to_box_ship_date, to_customer_invoice_date

SAME_DAY = ["2026-08-29 00:00:00", "Aug 29, 2026", "2026-08-29", "8/29/2026", "08/29/2026", "29-Aug-26"]


def test_every_stored_shape_parses_to_the_same_day():
    parsed = parse_dates(pd.Series(SAME_DAY))
    assert parsed.notna().all()
    assert set(parsed.dt.date) == {pd.Timestamp("2026-08-29").date()}


def test_slash_dates_are_month_first():
    assert parse_dates(pd.Series(["9/1/2026"])).iloc[0] == pd.Timestamp("2026-09-01")


@pytest.mark.parametrize("raw", SAME_DAY)
def test_canonical_shapes(raw):
    assert to_box_ship_date(raw) == "2026-08-29 00:00:00"
    assert to_customer_invoice_date(raw) == "8/29/2026"


def test_unparseable_values_are_kept_not_lost():
    assert to_box_ship_date("ask Ahmet") == "ask Ahmet"
    assert to_box_ship_date(None) is None
    assert to_box_ship_date("") is None
    assert not is_valid_date("ask Ahmet") and is_valid_date("Sep 08, 2026")
