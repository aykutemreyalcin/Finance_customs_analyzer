import pandas as pd

from core.database import get_connection, init_db

COLUMN_MAP = {
    "tarih": "ship_date",
    "hesap": "company",
    "müşteri": "customer_code",
    "musteri": "customer_code",
    "ülke": "country",
    "ulke": "country",
    "kutu no": "box_no",
    "sevkiyat tipi": "shipment_type",
    "kutu tipi / ebat": "box_type_size",
    "kutu tipi/ebat": "box_type_size",
    "multi no": "multi_no",
    "takip no": "tracking_id",
}

REQUIRED_FIELD = "tracking_id"


def _normalize_header(header):
    return str(header).strip().lower()


def read_box_import_file(file):
    if str(getattr(file, "name", file)).lower().endswith(".csv"):
        raw = pd.read_csv(file, dtype=str)
    else:
        raw = pd.read_excel(file, dtype=str)

    rename_map = {}
    for col in raw.columns:
        mapped = COLUMN_MAP.get(_normalize_header(col))
        if mapped:
            rename_map[col] = mapped

    df = raw.rename(columns=rename_map)
    df = df.loc[:, ~df.columns.duplicated()]
    known_fields = list(dict.fromkeys(COLUMN_MAP.values()))
    df = df[[c for c in known_fields if c in df.columns]]
    df = df.dropna(subset=[REQUIRED_FIELD]) if REQUIRED_FIELD in df.columns else df.iloc[0:0]
    return df


def import_boxes(df):
    connection = get_connection()
    init_db(connection)

    existing = {
        row[0]
        for row in connection.execute("SELECT tracking_id FROM boxes WHERE tracking_id IS NOT NULL")
    }

    added = 0
    skipped_duplicate = 0

    for _, row in df.iterrows():
        tracking_id = str(row.get("tracking_id")).strip()
        if tracking_id in existing:
            skipped_duplicate += 1
            continue

        connection.execute(
            """
            INSERT INTO boxes (
                ship_date, company, customer_code, country, box_no,
                shipment_type, box_type_size, multi_no, tracking_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("ship_date"),
                row.get("company"),
                row.get("customer_code"),
                row.get("country"),
                row.get("box_no"),
                row.get("shipment_type"),
                row.get("box_type_size"),
                row.get("multi_no"),
                tracking_id,
            ),
        )
        existing.add(tracking_id)
        added += 1

    connection.commit()
    connection.close()
    return {"added": added, "skipped_duplicate": skipped_duplicate}


def add_single_box(
    ship_date, company, customer_code, country, box_no, shipment_type, box_type_size, multi_no, tracking_id
):
    connection = get_connection()
    init_db(connection)

    existing = connection.execute(
        "SELECT id FROM boxes WHERE tracking_id = ?", (tracking_id,)
    ).fetchone()
    if existing:
        connection.close()
        return {"added": False, "reason": "duplicate_tracking_id"}

    connection.execute(
        """
        INSERT INTO boxes (
            ship_date, company, customer_code, country, box_no,
            shipment_type, box_type_size, multi_no, tracking_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (ship_date, company, customer_code, country, box_no, shipment_type, box_type_size, multi_no, tracking_id),
    )
    connection.commit()
    connection.close()
    return {"added": True}
