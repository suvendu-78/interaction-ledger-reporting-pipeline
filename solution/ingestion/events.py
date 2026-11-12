
import csv
import json
from datetime import datetime, timezone, timedelta

from solution.database.db import get_connection
from solution.services.encryption import phone_fingerprint
from solution.services.normalization import normalize_phone


def normalize_timestamp(value):
    """
    Convert an event timestamp to UTC ISO format.

    Supported:
    - 2026-10-01T05:26:10Z
    - 2026-10-01T10:40:19+05:30
    - 2026-10-01 09:15:55 (assumed IST)
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid_timestamp")

    value = value.strip()

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    parsed = datetime.fromisoformat(value)

    # Naive timestamps are assumed to be IST (+05:30).
    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone(timedelta(hours=5, minutes=30))
        )

    return parsed.astimezone(timezone.utc).isoformat()


def load_dispositions(dispositions_path):
    """
    Load valid disposition codes from dispositions.csv.

    Returns:
        {
            "motor_renewal": {
                "renewed": {
                    "is_terminal": True,
                    "is_success": True
                }
            }
        }
    """
    dispositions = {}

    with open(
        dispositions_path,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            workflow_id = row["workflow_id"].strip()
            code = row["code"].strip().lower()

            dispositions.setdefault(workflow_id, {})

            dispositions[workflow_id][code] = {
                "is_terminal": (
                    row["is_terminal"].strip().lower() == "true"
                ),
                "is_success": (
                    row["is_success"].strip().lower() == "true"
                ),
            }

    return dispositions


def find_lead_by_phone(connection, workflow_id, phone_hmac):
    row = connection.execute(
        """
        SELECT id
        FROM leads
        WHERE workflow_id = ? AND phone_hmac = ?
        """,
        (workflow_id, phone_hmac),
    ).fetchone()

    return row["id"] if row else None


def find_lead_by_call_id(connection, workflow_id, call_id):
    """
    Find the lead associated with another already-linked event
    belonging to the same call.
    """
    row = connection.execute(
        """
        SELECT el.lead_id
        FROM events e
        JOIN event_links el ON el.event_id = e.event_id
        WHERE e.workflow_id = ?
          AND e.call_id = ?
        LIMIT 1
        """,
        (workflow_id, call_id),
    ).fetchone()

    return row["lead_id"] if row else None


def link_event(connection, event_id, lead_id):
    connection.execute(
        """
        INSERT OR IGNORE INTO event_links (event_id, lead_id)
        VALUES (?, ?)
        """,
        (event_id, lead_id),
    )


def relink_orphan_events(connection):
    """
    Retry linking all events that do not currently have a lead.

    Phone-based events are linked using HMAC fingerprints.
    disposition.override events are linked using call_id.
    """
    orphan_events = connection.execute(
        """
        SELECT
            e.event_id,
            e.event_type,
            e.workflow_id,
            e.call_id,
            e.phone_hmac
        FROM events e
        LEFT JOIN event_links el ON el.event_id = e.event_id
        WHERE el.event_id IS NULL
        ORDER BY e.received_at, e.event_id
        """
    ).fetchall()

    linked_count = 0

    for event in orphan_events:
        lead_id = None

        if event["phone_hmac"]:
            lead_id = find_lead_by_phone(
                connection,
                event["workflow_id"],
                event["phone_hmac"],
            )

        # Override events usually do not contain a phone.
        if (
            lead_id is None
            and event["event_type"] == "disposition.override"
        ):
            lead_id = find_lead_by_call_id(
                connection,
                event["workflow_id"],
                event["call_id"],
            )

        if lead_id is not None:
            link_event(connection, event["event_id"], lead_id)
            linked_count += 1

    return linked_count


def ingest_event_file(
    jsonl_path,
    dispositions_path,
    connection=None,
):
    """
    Read and ingest a JSONL event file into the SQLite ledger.

    A connection can be supplied by the caller. Otherwise, this
    function creates and closes its own connection.
    """
    own_connection = connection is None

    if own_connection:
        connection = get_connection()

    dispositions = load_dispositions(dispositions_path)

    result = {
        "events_total": 0,
        "malformed_events": 0,
        "duplicate_events_dropped": 0,
        "unknown_disposition_events": 0,
        "orphan_events": 0,
        "events_inserted": 0,
        "events_linked": 0,
    }

    try:
        with open(
            jsonl_path,
            "r",
            encoding="utf-8-sig"
        ) as file:

            for line in file:
                if not line.strip():
                    continue

                result["events_total"] += 1

                try:
                    event = json.loads(line)

                    if not isinstance(event, dict):
                        raise ValueError("event must be a JSON object")

                    event_id = event.get("event_id")

                    if not event_id:
                        raise ValueError("missing event_id")

                    event_id = str(event_id).strip()

                    if not event_id:
                        raise ValueError("missing event_id")

                    # Check duplicate IDs across all previously
                    # ingested drops.
                    existing = connection.execute(
                        """
                        SELECT 1
                        FROM events
                        WHERE event_id = ?
                        """,
                        (event_id,),
                    ).fetchone()

                    if existing:
                        result["duplicate_events_dropped"] += 1
                        continue

                    event_type = event.get("event_type")
                    workflow_id = event.get("workflow_id")
                    call_id = event.get("call_id")
                    occurred_at = event.get("occurred_at")

                    if not all([
                        event_type,
                        workflow_id,
                        call_id,
                        occurred_at,
                    ]):
                        raise ValueError("missing required event field")

                    event_type = str(event_type).strip()
                    workflow_id = str(workflow_id).strip()
                    call_id = str(call_id).strip()

                    if not event_type or not workflow_id or not call_id:
                        raise ValueError("invalid required event field")

                    normalized_timestamp = normalize_timestamp(
                        occurred_at
                    )

                    payload = event.get("payload", {})

                    if not isinstance(payload, dict):
                        raise ValueError("payload must be an object")

                    phone_hmac = None
                    phone = event.get("phone")

                    if phone:
                        normalized_phone = normalize_phone(phone)
                        phone_hmac = phone_fingerprint(normalized_phone)

                    # Validate disposition codes.
                    # The assignment uses payload.disposition_code.
                    if event_type in (
                        "disposition.set",
                        "disposition.override",
                    ):
                        code = payload.get("disposition_code")

                        if not isinstance(code, str) or not code.strip():
                            result["unknown_disposition_events"] += 1
                            continue

                        code = code.strip().lower()

                        allowed_codes = dispositions.get(
                            workflow_id,
                            {}
                        )

                        if code not in allowed_codes:
                            result["unknown_disposition_events"] += 1
                            continue

                        # Store the normalized code.
                        payload["disposition_code"] = code

                    connection.execute(
                        """
                        INSERT INTO events (
                            event_id,
                            event_type,
                            workflow_id,
                            call_id,
                            occurred_at,
                            phone_hmac,
                            payload_json
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event_id,
                            event_type,
                            workflow_id,
                            call_id,
                            normalized_timestamp,
                            phone_hmac,
                            json.dumps(
                                payload,
                                ensure_ascii=False
                            ),
                        ),
                    )

                    result["events_inserted"] += 1

                except (
                    json.JSONDecodeError,
                    ValueError,
                    TypeError,
                    KeyError,
                ):
                    result["malformed_events"] += 1
                    continue

        # Retry linking events that were orphaned previously.
        result["events_linked"] = relink_orphan_events(connection)

        orphan_count = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM events e
            LEFT JOIN event_links el
                ON el.event_id = e.event_id
            WHERE el.event_id IS NULL
            """
        ).fetchone()["total"]

        result["orphan_events"] = orphan_count

        connection.commit()

        return result

    except Exception:
        connection.rollback()
        raise

    finally:
        if own_connection:
            connection.close()
