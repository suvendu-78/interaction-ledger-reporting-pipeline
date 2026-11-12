
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def normalize_header(header: str) -> str:
    """Normalize CSV headers for schema matching."""
    return re.sub(r"[_\s]+", " ", header.strip().lower())


def normalize_phone(value: str) -> str:
    """Normalize and validate Indian mobile numbers."""

    digits = re.sub(r"\D", "", value)

    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]

    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    if len(digits) != 10 or digits[0] not in "6789":
        raise ValueError("invalid_phone")

    return f"+91{digits}"


def normalize_date(value: str) -> str:
    """Convert supported date formats to YYYY-MM-DD."""

    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d-%b-%Y",
    ]

    value = value.strip()

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue

    raise ValueError("invalid_date")


def normalize_decimal(value: str) -> str:
    """Normalize currency values and round to two decimal places."""

    cleaned = value.strip()

    cleaned = re.sub(
        r"^(?:₹|Rs\.?|INR)\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = cleaned.replace(",", "")

    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError("invalid_decimal")

    if not amount.is_finite() or amount < 0:
        raise ValueError("invalid_decimal")

    amount = amount.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )

    return str(amount)


def normalize_enum(value: str, allowed_values: list[str]) -> str:
    """Validate enum values without case sensitivity."""

    normalized = value.strip().lower()

    allowed = [item.lower() for item in allowed_values]

    if normalized not in allowed:
        raise ValueError("invalid_enum")

    return normalized
