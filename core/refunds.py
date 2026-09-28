from datetime import datetime, timezone

import pandas as pd

from core.database import get_connection, init_db

REFUND_TYPES = [
    "Shipping Refund",
    "Label Refund",
    "Packaging Refund",
    "Polybag Refund",
    "Overcharge Refund",
    "Duplicate Charge Refund",
    "Other",
]

REFUND_STATUSES = ["Pending", "Approved", "Rejected", "Completed"]

# Which customer revenue line item a refund of this type reduces, for reporting
# how refunds net against customer_shipping_fee / customer_packaging_fee.
REFUND_TYPE_REVENUE_LINE = {
    "Shipping Refund": "customer_shipping_fee",
    "Overcharge Refund": "customer_shipping_fee",
    "Label Refund": "customer_packaging_fee",
    "Packaging Refund": "customer_packaging_fee",
    "Polybag Refund": "customer_packaging_fee",
    "Duplicate Charge Refund": "customer_total_invoice",
    "Other": "customer_total_invoice",
}


def add_refund(fields):
    connection = get_connection()
    init_db(connection)
    fields = dict(fields)
    fields["created_at"] = datetime.now(timezone.utc).isoformat()
    columns = ", ".join(fields)
    placeholders = ", ".join("?" for _ in fields)
    connection.execute(
        f"INSERT INTO refunds ({columns}) VALUES ({placeholders})",
        tuple(fields.values()),
    )
    connection.commit()
    connection.close()


def set_refund_status(refund_id, status):
    connection = get_connection()
    init_db(connection)
    connection.execute("UPDATE refunds SET status = ? WHERE id = ?", (status, refund_id))
    connection.commit()
    connection.close()


def delete_refund(refund_id):
    connection = get_connection()
    init_db(connection)
    connection.execute("DELETE FROM refunds WHERE id = ?", (refund_id,))
    connection.commit()
    connection.close()


def get_refunds_df():
    connection = get_connection()
    init_db(connection)
    df = pd.read_sql("SELECT * FROM refunds ORDER BY created_at DESC", connection)
    connection.close()
    return df
