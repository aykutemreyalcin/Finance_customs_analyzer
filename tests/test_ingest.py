import sqlite3

import pytest

from core import ingest
from core.database import init_db


def test_invoice_without_number_is_rejected_and_writes_nothing():
    connection = sqlite3.connect(":memory:")
    init_db(connection)
    text = "Ship Date: Sep 02, 2026\nTracking ID 123456789012\nTransportation Charge\nTotal Charge USD $10.00"
    with pytest.raises(ValueError):
        ingest._ingest_invoice_text(connection, text, "broken.pdf")
    assert connection.execute("SELECT COUNT(*) FROM shipment_charges").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 0


def test_shipping_invoice_creates_charge_and_fills_box():
    connection = sqlite3.connect(":memory:")
    init_db(connection)
    text = (
        "Invoice Number 9-123-45678\n"
        "Ship Date: Sep 02, 2026\nTracking ID 123456789012\nTransportation Charge\nTotal Charge USD $10.00"
    )
    header, charge_type = ingest._ingest_invoice_text(connection, text, "ok.pdf")
    assert (header["invoice_number"], charge_type) == ("9-123-45678", "Shipping")
    assert connection.execute(
        "SELECT fedex_shipping_invoice_no, fedex_shipping_amount FROM boxes WHERE tracking_id='123456789012'"
    ).fetchone() == ("9-123-45678", 10.0)
    # Re-ingesting the same invoice must not duplicate its charge lines.
    ingest._ingest_invoice_text(connection, text, "ok.pdf")
    assert connection.execute("SELECT COUNT(*) FROM shipment_charges").fetchone()[0] == 1


def test_reuploaded_same_invoice_refreshes_amount():
    connection = sqlite3.connect(":memory:")
    init_db(connection)
    text = (
        "Invoice Number 9-123-45678\n"
        "Ship Date: Sep 02, 2026\nTracking ID 123456789012\nTransportation Charge\nTotal Charge USD $10.00"
    )
    ingest._ingest_invoice_text(connection, text, "ok.pdf")
    corrected_text = text.replace("$10.00", "$25.00")
    ingest._ingest_invoice_text(connection, corrected_text, "ok_corrected.pdf")
    assert connection.execute(
        "SELECT fedex_shipping_invoice_no, fedex_shipping_amount FROM boxes WHERE tracking_id='123456789012'"
    ).fetchone() == ("9-123-45678", 25.0)


def test_different_invoice_number_does_not_overwrite_existing():
    connection = sqlite3.connect(":memory:")
    init_db(connection)
    text = (
        "Invoice Number 9-123-45678\n"
        "Ship Date: Sep 02, 2026\nTracking ID 123456789012\nTransportation Charge\nTotal Charge USD $10.00"
    )
    ingest._ingest_invoice_text(connection, text, "ok.pdf")
    second_text = text.replace("9-123-45678", "9-999-99999").replace("$10.00", "$25.00")
    ingest._ingest_invoice_text(connection, second_text, "second.pdf")
    assert connection.execute(
        "SELECT fedex_shipping_invoice_no, fedex_shipping_amount FROM boxes WHERE tracking_id='123456789012'"
    ).fetchone() == ("9-123-45678", 10.0)


def test_box_created_from_pdf_gets_canonical_ship_date():
    connection = sqlite3.connect(":memory:")
    init_db(connection)
    text = (
        "Invoice Number 9-123-45678\n"
        "Ship Date: Sep 02, 2026\nTracking ID 123456789012\nTransportation Charge\nTotal Charge USD $10.00"
    )
    ingest._ingest_invoice_text(connection, text, "ok.pdf")
    assert connection.execute("SELECT ship_date FROM boxes").fetchone()[0] == "2026-09-02 00:00:00"
