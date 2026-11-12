
def merge_leads(lead_batches: list, schemas: dict) -> dict:
    """
    Merge leads using (workflow_id, canonical phone).

    First batch_id is preserved.
    Later non-null values overwrite earlier values.
    Defaults are applied after all merging.
    """

    merged = {}
    duplicate_count = 0

    # Process leads in the order received.
    for batch_leads in lead_batches:

        for lead in batch_leads:

            workflow_id = lead["workflow_id"]
            phone = lead["phone"]

            identity = (workflow_id, phone)

            if identity not in merged:

                # First valid row creates the lead.
                merged[identity] = lead.copy()
                continue

            # Existing identity means one duplicate row.
            duplicate_count += 1

            existing_lead = merged[identity]

            # Last non-null value wins.
            for field_name, value in lead.items():

                if field_name in ("workflow_id", "batch_id"):
                    continue

                if value is not None:
                    existing_lead[field_name] = value

    # Apply schema defaults only after all merging.
    for identity, lead in merged.items():

        workflow_id = lead["workflow_id"]
        schema = schemas[workflow_id]

        for field in schema["fields"]:

            field_name = field["name"]
            default_value = field.get("default")

            if (
                lead.get(field_name) is None
                and default_value is not None
            ):
                lead[field_name] = default_value

    return {
        "leads": list(merged.values()),
        "duplicate_lead_rows_merged": duplicate_count,
    }
