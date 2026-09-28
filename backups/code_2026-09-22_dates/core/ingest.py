from core.database import get_connection, init_db
from core.pdf_parser import (
    classify_charge_type,
    extract_duty_shipments,
    extract_invoice_header,
    extract_multiweight_groups,
    extract_products,
    extract_shipping_shipments,
    extract_total_invoice_amount,
    read_pdf_text,
    split_pdf_into_invoice_texts,
)


def ingest_pdf(pdf_source, source_name=None):
    """Ingests a PDF containing a single FedEx invoice."""
    text = read_pdf_text(pdf_source)
    connection = get_connection()
    try:
        init_db(connection)
        header, charge_type = _ingest_invoice_text(connection, text, source_name or str(pdf_source))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return header, charge_type


def ingest_pdf_bundle(pdf_source, source_name=None):
    """Ingests a PDF that may bundle several FedEx invoices together (FedEx's
    billing portal lets you download many invoices as one combined file).
    Splits it by where each invoice's own Invoice Number starts and ingests
    each one separately. Returns a list of (header, charge_type) per invoice
    found."""
    invoice_texts = split_pdf_into_invoice_texts(pdf_source)

    connection = get_connection()
    try:
        init_db(connection)
        results = []
        for text in invoice_texts:
            header, charge_type = _ingest_invoice_text(connection, text, source_name or str(pdf_source))
            results.append((header, charge_type))
        connection.commit()
    except Exception:
        # All-or-nothing per uploaded file: a failure on one bundled invoice must
        # not leave the earlier ones half-written.
        connection.rollback()
        raise
    finally:
        connection.close()
    return results


def _ingest_invoice_text(connection, text, source_name):
    header = extract_invoice_header(text)
    charge_type = classify_charge_type(text)
    invoice_number = header["invoice_number"]
    if not invoice_number:
        # Without an invoice number every row below would be stored under NULL,
        # which the re-upload DELETEs can never match — so each re-upload of the
        # same file would silently duplicate its charges. Refuse instead.
        raise ValueError("No FedEx invoice number (format 9-999-99999) found in the PDF text.")

    connection.execute("DELETE FROM shipment_charges WHERE invoice_number = ?", (invoice_number,))
    connection.execute("DELETE FROM products WHERE invoice_number = ?", (invoice_number,))

    invoice_amount = 0.0

    if charge_type == "Duty":
        for shipment in extract_duty_shipments(text):
            _insert_shipment(connection, invoice_number, charge_type, shipment, "total_duty_amount")
            _sync_box(
                connection,
                shipment["tracking_id"],
                shipment["ship_date"],
                duty_invoice_no=invoice_number,
                duty_amount=shipment["total_duty_amount"],
            )
            invoice_amount += shipment["total_duty_amount"]
    elif charge_type == "Shipping":
        for shipment in extract_shipping_shipments(text):
            _insert_shipment(connection, invoice_number, charge_type, shipment, "total_charge_amount")
            _sync_box(
                connection,
                shipment["tracking_id"],
                shipment["ship_date"],
                shipping_invoice_no=invoice_number,
                shipping_amount=shipment["total_charge_amount"],
            )
            invoice_amount += shipment["total_charge_amount"]

        for index, group in enumerate(extract_multiweight_groups(text)):
            group_id = f"{invoice_number}:mw:{index}"
            invoice_amount += group["total_charge_amount"]
            # FedEx bills a multi-weight group as a single combined charge, not
            # per box, so there is no real per-box amount to read from the PDF.
            # Split the group total evenly across its boxes so each one still
            # gets a usable fedex_shipping_amount instead of being left blank.
            per_box_amount = group["total_charge_amount"] / len(group["tracking_ids"])
            for tracking_id in group["tracking_ids"]:
                connection.execute(
                    "INSERT INTO shipment_charges "
                    "(invoice_number, charge_type, tracking_id, ship_date, packages, group_id, group_amount) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        invoice_number,
                        charge_type,
                        tracking_id,
                        group["ship_date"],
                        group["packages"],
                        group_id,
                        group["total_charge_amount"],
                    ),
                )
                _sync_box(
                    connection,
                    tracking_id,
                    group["ship_date"],
                    shipping_invoice_no=invoice_number,
                    shipping_amount=per_box_amount,
                )
    else:
        # "Pickup" (FedEx Other Charges, e.g. a fuel surcharge on a pickup
        # request) and "Unknown" invoices don't have the same per-shipment
        # breakdown as Duty/Shipping invoices, but we can still read their
        # stated grand total so the invoice isn't recorded as $0.
        total = extract_total_invoice_amount(text)
        if total is not None:
            invoice_amount = total

    connection.execute(
        "INSERT OR REPLACE INTO invoices "
        "(invoice_number, invoice_date, account_number, charge_type, source_file, company, due_date, invoice_amount) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            invoice_number,
            header["invoice_date"],
            header["account_number"],
            charge_type,
            source_name,
            header["company"],
            header["due_date"],
            round(invoice_amount, 2),
        ),
    )

    for product in extract_products(text):
        connection.execute(
            "INSERT INTO products "
            "(invoice_number, tracking_id, hs_code, description, quantity, country_of_origin, value_for_duty) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                invoice_number,
                product["tracking_id"],
                product["hs_code"],
                product["description"],
                product["quantity"],
                product["country_of_origin"],
                product["value_for_duty"],
            ),
        )

    return header, charge_type


def _insert_shipment(connection, invoice_number, charge_type, shipment, amount_key):
    connection.execute(
        "INSERT INTO shipment_charges "
        "(invoice_number, charge_type, tracking_id, shipment_no, ship_date, packages, amount, "
        "rated_weight_lbs, customs_value_currency, customs_value_amount) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            invoice_number,
            charge_type,
            shipment["tracking_id"],
            shipment["shipment_no"],
            shipment["ship_date"],
            shipment["packages"],
            shipment[amount_key],
            shipment.get("rated_weight_lbs"),
            shipment.get("customs_value_currency"),
            shipment.get("customs_value_amount"),
        ),
    )


def _sync_box(
    connection,
    tracking_id,
    ship_date,
    duty_invoice_no=None,
    duty_amount=None,
    shipping_invoice_no=None,
    shipping_amount=None,
):
    """Matches a newly-parsed invoice line to the Boxes master table by tracking
    id. If the box doesn't exist yet, adds a minimal row for it. If it already
    exists but is still waiting on this side of the charge (its Duty or
    Shipping invoice field is empty), fills that field in from this invoice —
    this is what makes an uploaded invoice show up next to its box on the
    Boxes tab. A box that already has a *different* invoice number recorded
    for that side is left untouched rather than overwritten (a possible
    duplicate-invoice case better surfaced in Data Quality than silently
    clobbered)."""
    existing = connection.execute(
        "SELECT id, fedex_duty_invoice_no, fedex_shipping_invoice_no FROM boxes WHERE tracking_id = ?",
        (tracking_id,),
    ).fetchone()

    if not existing:
        connection.execute(
            """
            INSERT INTO boxes (
                ship_date, tracking_id, fedex_duty_invoice_no, fedex_duty_amount,
                fedex_shipping_invoice_no, fedex_shipping_amount
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ship_date, tracking_id, duty_invoice_no, duty_amount, shipping_invoice_no, shipping_amount),
        )
        return

    box_id, existing_duty_invoice_no, existing_shipping_invoice_no = existing
    updates = {}
    if duty_invoice_no and not existing_duty_invoice_no:
        updates["fedex_duty_invoice_no"] = duty_invoice_no
        updates["fedex_duty_amount"] = duty_amount
    if shipping_invoice_no and not existing_shipping_invoice_no:
        updates["fedex_shipping_invoice_no"] = shipping_invoice_no
        updates["fedex_shipping_amount"] = shipping_amount

    if updates:
        columns = ", ".join(f"{name} = ?" for name in updates)
        connection.execute(
            f"UPDATE boxes SET {columns} WHERE id = ?", (*updates.values(), box_id)
        )
