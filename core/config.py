INVOICE_WAITING_PERIOD_DAYS = 14
ABOVE_AVERAGE_THRESHOLD_PERCENT = 0.2
ABOVE_AVERAGE_THRESHOLD_FIXED_USD = 0
HIGH_INVOICE_WARNING_USD = 750
MINIMUM_SAMPLE_SIZE_FOR_AVERAGE = 3

NO_DUTY_COUNTRIES = {"US", "AU"}

# Agreed FedEx shipping rate per box for Canada, by how many boxes share the
# multi shipment (a Single shipment counts as a group of 1). Groups of 4 and 5
# share the same negotiated rate; any group larger than 5 is billed at that
# same rate too, since no higher tier has been negotiated.
CANADA_SHIPPING_RATE_CARD = {
    1: 38.24,
    3: 32.89,
    4: 28.26,
    5: 28.26,
}
MASTER_DUTY_ALLOCATION_COUNTRIES_NOTE = (
    "Canada and all other countries (UK, DE, MX, FR, etc.) use the same rule: "
    "Duty is invoiced against the Master Tracking Number and split across boxes."
)
