
import csv
from pathlib import Path

from solution.ingestion.leads import ingest_lead_file


ROOT = Path(__file__).resolve().parents[2]

SCHEMA = (
    ROOT
    / "assignment-a-data"
    / "schemas"
    / "motor_renewal.json"
)


def create_csv(tmp_path, headers, rows):
    file_path = tmp_path / "batch_001.csv"

    with open(file_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(rows)

    return file_path


def test_valid_lead(tmp_path):
    file_path = create_csv(
        tmp_path,
        ["Name", "Mobile", "Policy No", "Expiry Date", "Premium"],
        [[
            "Rahul Kumar",
            "9876543210",
            "POL123",
            "01/12/2026",
            "₹1,250.50"
        ]]
    )

    result = ingest_lead_file(file_path, SCHEMA)

    assert len(result["valid_leads"]) == 1
    assert len(result["rejected_rows"]) == 0

    lead = result["valid_leads"][0]

    assert lead["phone"] == "+919876543210"
    assert lead["policy_number"] == "POL123"
    assert lead["premium_amount"] == "1250.50"


def test_invalid_phone_rejected(tmp_path):
    file_path = create_csv(
        tmp_path,
        ["Name", "Mobile", "Policy No"],
        [["Rahul", "1234567890", "POL123"]]
    )

    result = ingest_lead_file(file_path, SCHEMA)

    assert len(result["valid_leads"]) == 0
    assert result["rejected_rows"][0]["reason"] == "invalid_phone"


def test_missing_required_field(tmp_path):
    file_path = create_csv(
        tmp_path,
        ["Name", "Mobile", "Policy No"],
        [["Rahul", "9876543210", ""]]
    )

    result = ingest_lead_file(file_path, SCHEMA)

    assert result["rejected_rows"][0]["reason"] == (
        "missing_required:policy_number"
    )


def test_optional_invalid_field_warning(tmp_path):
    file_path = create_csv(
        tmp_path,
        ["Name", "Mobile", "Policy No", "Expiry Date"],
        [["Rahul", "9876543210", "POL123", "invalid-date"]]
    )

    result = ingest_lead_file(file_path, SCHEMA)

    assert len(result["valid_leads"]) == 1
    assert result["field_warnings"] == 1
    assert result["valid_leads"][0]["policy_expiry"] is None


def test_blank_rows_are_skipped(tmp_path):
    file_path = create_csv(
        tmp_path,
        ["Name", "Mobile", "Policy No"],
        [
            ["", "", ""],
            ["Rahul", "9876543210", "POL123"],
            ["   ", "   ", "   "]
        ]
    )

    result = ingest_lead_file(file_path, SCHEMA)

    assert result["lead_rows_total"] == 1
    assert len(result["valid_leads"]) == 1
