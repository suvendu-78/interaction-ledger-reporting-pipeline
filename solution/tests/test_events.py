
import json
import base64
import secrets

import pytest

from solution.database.db import get_connection, init_db
from solution.services.encryption import phone_fingerprint
from solution.ingestion.events import (
    normalize_timestamp,
    load_dispositions,
    ingest_event_file,
    relink_orphan_events,
)


DISPOSITIONS_PATH = "assignment-a-data/schemas/dispositions.csv"


# --------------------------------------------------
# DATABASE FIXTURE
# --------------------------------------------------

@pytest.fixture
def setup_db(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "DATABASE_PATH",
        str(tmp_path / "test.db"),
    )

    monkeypatch.setenv(
        "PII_ENCRYPTION_KEY",
        base64.b64encode(secrets.token_bytes(32)).decode(),
    )

    monkeypatch.setenv(
        "PII_HMAC_KEY",
        base64.b64encode(secrets.token_bytes(32)).decode(),
    )

    init_db()

    connection = get_connection()

    yield connection

    connection.close()


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def write_event_file(tmp_path, event):
    """Create a temporary JSONL event file."""

    event_file = tmp_path / "events.jsonl"

    event_file.write_text(
        json.dumps(event) + "\n",
        encoding="utf-8",
    )

    return event_file


def insert_test_lead(connection, phone="8902799046"):
    """Insert a test lead into the database."""

    fingerprint = phone_fingerprint("+91" + phone)

    cursor = connection.execute(
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
            "motor_renewal",
            fingerprint,
            "encrypted_phone",
            "encrypted_name",
            "POLICY001",
            "batch_001",
            "{}",
        ),
    )

    connection.commit()

    return cursor.lastrowid


# --------------------------------------------------
# TIMESTAMP TESTS
# --------------------------------------------------

def test_normalize_utc_timestamp():
    result = normalize_timestamp("2026-10-01T05:26:10Z")

    assert result.startswith("2026-10-01T05:26:10")


def test_normalize_ist_timestamp():
    result = normalize_timestamp("2026-10-01 09:15:55")

    assert result.startswith("2026-10-01T03:45:55")


# --------------------------------------------------
# DISPOSITION TESTS
# --------------------------------------------------

def test_load_dispositions():
    data = load_dispositions(DISPOSITIONS_PATH)

    assert data["motor_renewal"]["renewed"]["is_terminal"] is True
    assert data["motor_renewal"]["renewed"]["is_success"] is True


# --------------------------------------------------
# BASIC EVENT INGESTION TESTS
# --------------------------------------------------

def test_event_ingestion(setup_db, tmp_path):
    event = {
        "event_id": "evt_test_001",
        "event_type": "call.initiated",
        "workflow_id": "motor_renewal",
        "call_id": "call_test_001",
        "occurred_at": "2026-10-01T05:26:10Z",
        "phone": "8902799046",
        "payload": {},
    }

    event_file = write_event_file(tmp_path, event)

    result = ingest_event_file(
        event_file,
        DISPOSITIONS_PATH,
        setup_db,
    )

    assert result["events_inserted"] == 1

    stored = setup_db.execute(
        "SELECT * FROM events WHERE event_id = ?",
        ("evt_test_001",),
    ).fetchone()

    assert stored is not None
    assert stored["phone_hmac"] is not None


def test_duplicate_event_is_ignored(setup_db, tmp_path):
    event = {
        "event_id": "evt_duplicate",
        "event_type": "call.initiated",
        "workflow_id": "motor_renewal",
        "call_id": "call_duplicate",
        "occurred_at": "2026-10-01T05:26:10Z",
        "phone": "8902799046",
        "payload": {},
    }

    event_file = tmp_path / "events.jsonl"

    event_file.write_text(
        json.dumps(event) + "\n" + json.dumps(event) + "\n",
        encoding="utf-8",
    )

    result = ingest_event_file(
        event_file,
        DISPOSITIONS_PATH,
        setup_db,
    )

    assert result["events_inserted"] == 1
    assert result["duplicate_events_dropped"] == 1


def test_malformed_event_is_counted(setup_db, tmp_path):
    event_file = tmp_path / "events.jsonl"

    event_file.write_text(
        '{"event_id": "valid", "event_type": }\n',
        encoding="utf-8",
    )

    result = ingest_event_file(
        event_file,
        DISPOSITIONS_PATH,
        setup_db,
    )

    assert result["malformed_events"] == 1


def test_unknown_disposition_is_ignored(setup_db, tmp_path):
    event = {
        "event_id": "evt_unknown",
        "event_type": "disposition.set",
        "workflow_id": "motor_renewal",
        "call_id": "call_unknown",
        "occurred_at": "2026-10-01T05:26:10Z",
        "phone": "8902799046",
        "payload": {
            "disposition_code": "not_a_real_disposition",
        },
    }

    event_file = write_event_file(tmp_path, event)

    result = ingest_event_file(
        event_file,
        DISPOSITIONS_PATH,
        setup_db,
    )

    assert result["unknown_disposition_events"] == 1
    assert result["events_inserted"] == 0


# --------------------------------------------------
# EVENT-TO-LEAD LINKING TESTS
# --------------------------------------------------

def test_event_links_to_lead_using_phone(setup_db, tmp_path):
    lead_id = insert_test_lead(setup_db)

    event = {
        "event_id": "evt_phone_link",
        "event_type": "call.initiated",
        "workflow_id": "motor_renewal",
        "call_id": "call_phone_link",
        "occurred_at": "2026-10-01T05:26:10Z",
        "phone": "+91 89027 99046",
        "payload": {},
    }

    event_file = write_event_file(tmp_path, event)

    result = ingest_event_file(
        event_file,
        DISPOSITIONS_PATH,
        setup_db,
    )

    linked = setup_db.execute(
        """
        SELECT lead_id
        FROM event_links
        WHERE event_id = ?
        """,
        ("evt_phone_link",),
    ).fetchone()

    assert linked is not None
    assert linked["lead_id"] == lead_id
    assert result["orphan_events"] == 0


def test_orphan_event_relinks_after_lead_arrives(setup_db, tmp_path):
    event = {
        "event_id": "evt_orphan",
        "event_type": "call.initiated",
        "workflow_id": "motor_renewal",
        "call_id": "call_orphan",
        "occurred_at": "2026-10-01T05:26:10Z",
        "phone": "8902799046",
        "payload": {},
    }

    event_file = write_event_file(tmp_path, event)

    # First ingestion: lead does not exist.
    first_result = ingest_event_file(
        event_file,
        DISPOSITIONS_PATH,
        setup_db,
    )

    assert first_result["orphan_events"] == 1

    # Insert the lead afterwards.
    lead_id = insert_test_lead(setup_db)

    # Retry orphan linking.
    linked_count = relink_orphan_events(setup_db)

    setup_db.commit()

    linked = setup_db.execute(
        """
        SELECT lead_id
        FROM event_links
        WHERE event_id = ?
        """,
        ("evt_orphan",),
    ).fetchone()

    assert linked_count == 1
    assert linked is not None
    assert linked["lead_id"] == lead_id


def test_override_event_links_using_call_id(setup_db, tmp_path):
    lead_id = insert_test_lead(setup_db)

    # First event: call initiated with a phone.
    initiated_event = {
        "event_id": "evt_call_base",
        "event_type": "call.initiated",
        "workflow_id": "motor_renewal",
        "call_id": "call_override_test",
        "occurred_at": "2026-10-01T05:26:10Z",
        "phone": "8902799046",
        "payload": {},
    }

    initiated_file = write_event_file(
        tmp_path,
        initiated_event,
    )

    ingest_event_file(
        initiated_file,
        DISPOSITIONS_PATH,
        setup_db,
    )

    # Second event: override without phone.
    override_event = {
        "event_id": "evt_override",
        "event_type": "disposition.override",
        "workflow_id": "motor_renewal",
        "call_id": "call_override_test",
        "occurred_at": "2026-10-01T06:00:00Z",
        "payload": {
            "disposition_code": "renewed",
        },
    }

    override_file = tmp_path / "override.jsonl"

    override_file.write_text(
        json.dumps(override_event) + "\n",
        encoding="utf-8",
    )

    result = ingest_event_file(
        override_file,
        DISPOSITIONS_PATH,
        setup_db,
    )

    linked = setup_db.execute(
        """
        SELECT lead_id
        FROM event_links
        WHERE event_id = ?
        """,
        ("evt_override",),
    ).fetchone()

    assert linked is not None
    assert linked["lead_id"] == lead_id
    assert result["orphan_events"] == 0
