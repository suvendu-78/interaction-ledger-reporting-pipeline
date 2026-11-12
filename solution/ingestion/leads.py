
import csv
import json

from pathlib import Path

from solution.services.normalization import (
    normalize_header,
    normalize_phone,
    normalize_date,
    normalize_decimal,
    normalize_enum,
)


def load_schema(schema_path: str | Path) -> dict:
    """Load a workflow schema from JSON."""

    with open(schema_path, "r", encoding="utf-8") as file:
        return json.load(file)


def build_header_mapping(headers: list, fields: list) -> dict:
    """Map CSV column names to schema field names."""

    aliases = {}

    for field in fields:
        names = [field["name"]] + field.get("aliases", [])

        for name in names:
            aliases[normalize_header(name)] = field["name"]

    mapping = {}

    for header in headers:
        if header is None:
            continue

        normalized = normalize_header(header)

        if normalized in aliases:
            field_name = aliases[normalized]

            # Keep the first matching CSV column.
            if field_name not in mapping.values():
                mapping[header] = field_name

    return mapping


def normalize_field(value: str, field: dict):
    """Normalize a value based on its schema type."""

    value = value.strip()

    if not value:
        return None

    field_type = field["type"]

    if field_type == "string":
        return value

    if field_type == "phone":
        return normalize_phone(value)

    if field_type == "date":
        return normalize_date(value)

    if field_type == "decimal":
        return normalize_decimal(value)

    if field_type == "enum":
        return normalize_enum(value, field["values"])

    raise ValueError("unsupported_field_type")


def process_row(row: dict, header_mapping: dict, schema: dict):
    """Validate and normalize one non-blank CSV row."""

    lead = {}
    warnings = 0

    for field in schema["fields"]:

        field_name = field["name"]

        raw_value = None

        for csv_header, mapped_name in header_mapping.items():
            if mapped_name == field_name:
                raw_value = row.get(csv_header)
                break

        value = (raw_value or "").strip()

        # Required field validation
        if not value:

            if field.get("required", False):
                return None, f"missing_required:{field_name}", warnings

            lead[field_name] = None
            continue

        try:
            lead[field_name] = normalize_field(value, field)

        except ValueError:

            # Invalid phone numbers reject the entire lead.
            if field["type"] == "phone":
                return None, "invalid_phone", warnings

            # Invalid optional values become NULL.
            if not field.get("required", False):
                lead[field_name] = None
                warnings += 1

            else:
                return None, f"invalid_{field['type']}", warnings

    return lead, None, warnings


def ingest_lead_file(
    csv_path: str | Path,
    schema_path: str | Path,
) -> dict:
    """Read, validate and normalize a lead CSV file."""

    csv_path = Path(csv_path)

    schema = load_schema(schema_path)

    valid_leads = []
    rejected_rows = []

    total_rows = 0
    warning_count = 0

    with open(
        csv_path,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise ValueError("CSV file has no header")

        header_mapping = build_header_mapping(
            reader.fieldnames,
            schema["fields"]
        )

        for row in reader:

            # Handle extra CSV columns and blank rows.
            cells = []

            for value in row.values():

                if isinstance(value, list):
                    cells.extend(value)

                else:
                    cells.append(value)

            # Ignore completely blank rows.
            if not any(
                str(value or "").strip()
                for value in cells
            ):
                continue

            total_rows += 1

            lead, reason, warnings = process_row(
                row,
                header_mapping,
                schema
            )

            warning_count += warnings

            # Store rejected records separately.
            if reason:

                rejected_rows.append({
                    "workflow_id": schema["workflow_id"],
                    "batch_id": csv_path.stem,
                    "row_number": total_rows,
                    "reason": reason,
                })

                continue

            # Store normalized lead in memory.
            valid_leads.append({
                "workflow_id": schema["workflow_id"],
                "batch_id": csv_path.stem,
                **lead,
            })

    return {
        "valid_leads": valid_leads,
        "rejected_rows": rejected_rows,
        "lead_rows_total": total_rows,
        "lead_rows_rejected": len(rejected_rows),
        "field_warnings": warning_count,
    }
