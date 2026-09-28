import re

from core.database import get_connection

MULTI_NO_PATTERN = re.compile(r"^\d+-\d+$")

CANONICAL_SHIPMENT_TYPES = {
    "MULTI": "Multi",
    "SINGLE": "Single",
    "PALET": "Pallet",
    "PALLET": "Pallet",
}


def fix_shipment_type_data():
    """Fixes a source-data bug: for some rows, the box-type/size code (e.g. "1323-1")
    was written into the shipment_type column while box_type_size was left empty.
    Confirmed pattern: a box-type/size code is populated almost exclusively for
    Multi-box shipments in otherwise-clean rows, so a row matching this pattern is
    corrected to shipment_type="Multi" with the code moved into box_type_size."""
    connection = get_connection()
    rows = connection.execute("SELECT id, shipment_type, box_type_size FROM boxes").fetchall()

    normalized_count = 0
    moved_to_box_type_size_count = 0

    for row_id, shipment_type, box_type_size in rows:
        if shipment_type is None:
            continue
        raw = str(shipment_type).strip()
        canonical = CANONICAL_SHIPMENT_TYPES.get(raw.upper())

        if canonical:
            if raw != canonical:
                connection.execute(
                    "UPDATE boxes SET shipment_type = ? WHERE id = ?", (canonical, row_id)
                )
                normalized_count += 1
        elif MULTI_NO_PATTERN.match(raw) and not box_type_size:
            connection.execute(
                "UPDATE boxes SET shipment_type = 'Multi', box_type_size = ? WHERE id = ?",
                (raw, row_id),
            )
            moved_to_box_type_size_count += 1

    connection.commit()
    connection.close()
    return {
        "normalized_casing": normalized_count,
        "moved_to_box_type_size": moved_to_box_type_size_count,
    }


VALID_COMPANIES = {"ENRETAG", "LOGIWIX"}


def fix_company_data():
    """Clears the invalid 'EXPRESS' company value rather than guessing which of the
    two real companies (ENRETAG/LOGIWIX) it should be — its customer_code appears
    under both, so there's no reliable way to infer the right one. Cleared rows
    surface in the Data Quality tab's "missing company" check instead."""
    connection = get_connection()
    cursor = connection.execute(
        "UPDATE boxes SET company = NULL WHERE company IS NOT NULL AND UPPER(company) NOT IN (?, ?, '-')",
        tuple(VALID_COMPANIES),
    )
    cleared_count = cursor.rowcount
    connection.commit()
    connection.close()
    return {"cleared_invalid_company": cleared_count}


def fix_country_data():
    """Normalizes country code casing (e.g. 'Au' -> 'AU')."""
    connection = get_connection()
    rows = connection.execute("SELECT id, country FROM boxes").fetchall()

    normalized_count = 0
    for row_id, country in rows:
        if country is None or country == "-":
            continue
        upper = country.strip().upper()
        if country != upper:
            connection.execute("UPDATE boxes SET country = ? WHERE id = ?", (upper, row_id))
            normalized_count += 1

    connection.commit()
    connection.close()
    return {"normalized_country_casing": normalized_count}
