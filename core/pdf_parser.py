import re

import pdfplumber

DUTY_MARKER = "Total Duties, Tax, Customs, Other Fees"
SHIPPING_MARKER = "Transportation Charge"
OTHER_MARKER = "FedEx Other Charges"

TOTAL_INVOICE_PATTERN = re.compile(r"TOTAL THIS INVOICE\s+USD\s+\$([\d,]+\.\d{2})")

INVOICE_NUMBER_PATTERN = re.compile(r"\b\d-\d{3}-\d{5}\b")
ACCOUNT_NUMBER_PATTERN = re.compile(r"\b\d{4}-\d{4}-\d\b")
INVOICE_DATE_PATTERN = re.compile(r"\b[A-Z][a-z]{2} \d{2}, \d{4}\b")
DUE_DATE_PATTERN = re.compile(
    r"(?:Payments not received by|payment is due by)\s+([A-Z][a-z]{2} \d{2}, \d{4})"
)
KNOWN_COMPANIES = ["LOGIWIX", "ENRETAG"]


def read_pdf_text(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def split_pdf_into_invoice_texts(pdf_path):
    """FedEx lets you bundle several invoices into one PDF download. Detects
    where each new invoice starts (its Invoice Number changing on a page) and
    returns one joined-text blob per invoice, so each can be ingested separately."""
    with pdfplumber.open(pdf_path) as pdf:
        page_texts = [page.extract_text() or "" for page in pdf.pages]

    boundaries = []
    current_invoice = None
    for i, text in enumerate(page_texts):
        match = INVOICE_NUMBER_PATTERN.search(text)
        invoice_number = match.group(0) if match else None
        if invoice_number and invoice_number != current_invoice:
            boundaries.append(i)
            current_invoice = invoice_number

    if not boundaries:
        return ["\n".join(page_texts)]

    if boundaries[0] != 0:
        boundaries[0] = 0

    invoice_texts = []
    for idx, start in enumerate(boundaries):
        end = boundaries[idx + 1] if idx + 1 < len(boundaries) else len(page_texts)
        invoice_texts.append("\n".join(page_texts[start:end]))
    return invoice_texts


def extract_invoice_header(text):
    return {
        "invoice_number": _first_match(INVOICE_NUMBER_PATTERN, text),
        "invoice_date": _first_match(INVOICE_DATE_PATTERN, text),
        "account_number": _first_match(ACCOUNT_NUMBER_PATTERN, text),
        "due_date": _first_match(DUE_DATE_PATTERN, text, group=1),
        "company": _detect_company(text),
    }


def _detect_company(text):
    best_company = None
    best_index = None
    for company in KNOWN_COMPANIES:
        index = text.find(f"{company} LLC")
        if index != -1 and (best_index is None or index < best_index):
            best_index = index
            best_company = company
    return best_company


def classify_charge_type(text):
    if DUTY_MARKER in text:
        return "Duty"
    if SHIPPING_MARKER in text:
        return "Shipping"
    if OTHER_MARKER in text:
        return "Pickup"
    return "Unknown"


def extract_total_invoice_amount(text):
    match = TOTAL_INVOICE_PATTERN.search(text)
    return float(match.group(1).replace(",", "")) if match else None


def _first_match(pattern, text, group=0):
    match = pattern.search(text)
    return match.group(group) if match else None


SHIP_DATE_PATTERN = re.compile(r"Ship Date:\s*([A-Za-z]{3} \d{2}, \d{4})")
TRACKING_ID_PATTERN = re.compile(r"Tracking ID\s+(\d+)")
SHIPMENT_NO_PATTERN = re.compile(r"Shipment No\.\s+(\d+)")
PACKAGES_PATTERN = re.compile(r"\bPackages\s+(\d+)\b")
TOTAL_DUTY_PATTERN = re.compile(
    r"Total Duties, Tax, Customs, Other Fees\s+USD\s+\$([\d,]+\.\d{2})"
)
TOTAL_CHARGE_PATTERN = re.compile(r"Total Charge\s+USD\s+\$([\d,]+\.\d{2})")
RATED_WEIGHT_PATTERN = re.compile(r"Rated Weight\s+([\d,]+\.?\d*)\s*lbs")
CUSTOMS_VALUE_PATTERN = re.compile(r"Customs Value\s+([A-Z]{3})\s+([\d,]+\.\d{2})")

MULTIWEIGHT_GROUP_START = re.compile(r"(?=Ship Date:[^\n]*Destination Zip:)")
MULTIWEIGHT_PACKAGES_PATTERN = re.compile(r"#\s*Packages:\s*(\d+)")
MULTIWEIGHT_TOTAL_PATTERN = re.compile(r"Shipment Total\s+[\d.,]+\s+\$([\d,]+\.\d{2})")
MULTIWEIGHT_TRACKING_ID_PATTERN = re.compile(r"(?m)^(\d{9,12})\b")


def extract_duty_shipments(text):
    return _extract_shipments(text, TOTAL_DUTY_PATTERN, "total_duty_amount")


def extract_shipping_shipments(text):
    return _extract_shipments(text, TOTAL_CHARGE_PATTERN, "total_charge_amount")


def extract_multiweight_groups(text):
    blocks = MULTIWEIGHT_GROUP_START.split(text)
    groups = []
    for block in blocks:
        total_match = MULTIWEIGHT_TOTAL_PATTERN.search(block)
        packages_match = MULTIWEIGHT_PACKAGES_PATTERN.search(block)
        if not total_match or not packages_match:
            continue

        ship_date_match = SHIP_DATE_PATTERN.search(block)
        tracking_ids = MULTIWEIGHT_TRACKING_ID_PATTERN.findall(block)

        groups.append(
            {
                "ship_date": ship_date_match.group(1) if ship_date_match else None,
                "packages": int(packages_match.group(1)),
                "total_charge_amount": float(total_match.group(1).replace(",", "")),
                "tracking_ids": tracking_ids,
            }
        )
    return groups


CARGO_CONTROL_PATTERN = re.compile(r"Cargo Control No\s*\n\s*\d{3}-(\d+)")
HS_CODE_LINE_PATTERN = re.compile(r"^\d+\s+(\d{4}\.\d{2}\.\d{2}\.\d{2})\s+(.+?)\s*$")
UNIT_OF_MEASURE_CODES = {"KGM", "PCS", "EA", "LBS", "MTR", "KG", "NO", "DOZ", "LTR", "L", "M"}


def extract_products(text):
    blocks = re.split(r"(?=Cargo Control No)", text)
    products = []
    for block in blocks:
        cargo_match = CARGO_CONTROL_PATTERN.search(block)
        if not cargo_match:
            continue
        tracking_id = cargo_match.group(1)

        lines = block.splitlines()
        for i, line in enumerate(lines):
            hs_match = HS_CODE_LINE_PATTERN.match(line.strip())
            if not hs_match:
                continue

            quantity = None
            country_of_origin = None
            if i + 2 < len(lines):
                value_tokens = lines[i + 2].split()
                if value_tokens:
                    quantity = value_tokens[0]
                    for token in value_tokens[1:]:
                        if token.isalpha() and token.upper() not in UNIT_OF_MEASURE_CODES:
                            country_of_origin = token
                            break

            # The "Value for Duty" row ("Value for Currency Conversion / Currency /
            # Exchange Rate / Value for Duty / ...") always sits 6 lines below the HS
            # code line, and Value for Duty is always its 4th token — the leading three
            # fields are never blank even when trailing ones (Customs Duties, Excise
            # Tax) are omitted for a $0 line, so this position is stable.
            value_for_duty = None
            if i + 6 < len(lines):
                value_line_tokens = lines[i + 6].split()
                if len(value_line_tokens) > 3:
                    try:
                        value_for_duty = float(value_line_tokens[3].replace(",", ""))
                    except ValueError:
                        value_for_duty = None

            products.append(
                {
                    "tracking_id": tracking_id,
                    "hs_code": hs_match.group(1),
                    "description": hs_match.group(2),
                    "quantity": quantity,
                    "country_of_origin": country_of_origin,
                    "value_for_duty": value_for_duty,
                }
            )
    return products


def _extract_shipments(text, total_pattern, amount_key):
    blocks = re.split(r"(?=Ship Date:)", text)
    shipments = []
    for block in blocks:
        tracking_match = TRACKING_ID_PATTERN.search(block)
        total_match = total_pattern.search(block)
        if not tracking_match or not total_match:
            continue

        ship_date_match = SHIP_DATE_PATTERN.search(block)
        shipment_no_match = SHIPMENT_NO_PATTERN.search(block)
        packages_match = PACKAGES_PATTERN.search(block)
        rated_weight_match = RATED_WEIGHT_PATTERN.search(block)
        customs_value_match = CUSTOMS_VALUE_PATTERN.search(block)

        shipments.append(
            {
                "ship_date": ship_date_match.group(1) if ship_date_match else None,
                "tracking_id": tracking_match.group(1),
                "shipment_no": shipment_no_match.group(1) if shipment_no_match else None,
                "packages": int(packages_match.group(1)) if packages_match else None,
                "rated_weight_lbs": (
                    float(rated_weight_match.group(1).replace(",", "")) if rated_weight_match else None
                ),
                "customs_value_currency": customs_value_match.group(1) if customs_value_match else None,
                "customs_value_amount": (
                    float(customs_value_match.group(2).replace(",", "")) if customs_value_match else None
                ),
                amount_key: float(total_match.group(1).replace(",", "")),
            }
        )
    return shipments
