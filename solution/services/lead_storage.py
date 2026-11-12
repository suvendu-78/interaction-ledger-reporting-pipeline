
import json

from solution.database.db import get_connection
from solution.services.encryption import encrypt_pii, phone_fingerprint


def save_merged_leads(leads, connection=None):
    """
    Save merged leads securely.

    Phone and customer name are encrypted.
    Phone HMAC is used for identity matching.
    Other normalized fields are stored in fields_json.
    """

    own_connection = connection is None

    if own_connection:
        connection = get_connection()

    saved_count = 0
    updated_count = 0

    try:
        for lead in leads:
            workflow_id = lead["workflow_id"]
            phone = lead["phone"]
            customer_name = lead["customer_name"]

            fingerprint = phone_fingerprint(phone)

            fields = {
                key: value
                for key, value in lead.items()
                if key not in (
                    "workflow_id",
                    "phone",
                    "customer_name",
                    "batch_id",
                )
            }

            existing = connection.execute(
                """
                SELECT id, fields_json
                FROM leads
                WHERE workflow_id = ? AND phone_hmac = ?
                """,
                (workflow_id, fingerprint),
            ).fetchone()

            if existing:
                previous_fields = json.loads(
                    existing["fields_json"] or "{}"
                )

                # Preserve existing values when incoming values are null.
                for key, value in fields.items():
                    if value is not None:
                        previous_fields[key] = value

                connection.execute(
                    """
                    UPDATE leads
                    SET customer_name_encrypted = ?,
                        fields_json = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        encrypt_pii(customer_name),
                        json.dumps(previous_fields),
                        existing["id"],
                    ),
                )

                updated_count += 1

            else:
                connection.execute(
                    """
                    INSERT INTO leads (
                        workflow_id,
                        phone_hmac,
                        phone_encrypted,
                        customer_name_encrypted,
                        external_ref,
                        batch_id,
                        fields_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workflow_id,
                        fingerprint,
                        encrypt_pii(phone),
                        encrypt_pii(customer_name),
                        str(fields.get("policy_number") or fields.get("order_id") or ""),
                        lead["batch_id"],
                        json.dumps(fields),
                    ),
                )

                saved_count += 1

        connection.commit()

        return {
            "leads_inserted": saved_count,
            "leads_updated": updated_count,
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        if own_connection:
            connection.close()
