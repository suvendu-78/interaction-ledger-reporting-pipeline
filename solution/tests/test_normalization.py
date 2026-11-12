
import pytest

from solution.services.normalization import (
    normalize_header,
    normalize_phone,
    normalize_date,
    normalize_decimal,
    normalize_enum,
)


def test_normalize_header():
    assert normalize_header(" Customer_Name ") == "customer name"


def test_normalize_phone():
    assert normalize_phone("9876543210") == "+919876543210"
    assert normalize_phone("+91 98765-43210") == "+919876543210"
    assert normalize_phone("09876543210") == "+919876543210"


def test_invalid_phone():
    with pytest.raises(ValueError):
        normalize_phone("1234567890")


def test_normalize_date():
    assert normalize_date("01-Dec-2026") == "2026-12-01"
    assert normalize_date("01/12/2026") == "2026-12-01"
    assert normalize_date("2026-12-01") == "2026-12-01"


def test_invalid_date():
    with pytest.raises(ValueError):
        normalize_date("31/02/2026")


def test_normalize_decimal():
    assert normalize_decimal("₹1,250.50") == "1250.50"
    assert normalize_decimal("Rs. 500") == "500.00"


def test_normalize_enum():
    assert normalize_enum("EN", ["en", "hi", "ta"]) == "en"


def test_invalid_enum():
    with pytest.raises(ValueError):
        normalize_enum("fr", ["en", "hi", "ta"])
