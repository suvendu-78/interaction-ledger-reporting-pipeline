
import base64
import secrets
import json

import pytest

from solution.database.db import get_connection, init_db
from solution.services.encryption import (
    encrypt_pii,
    phone_fingerprint,
)

from solution.reporting.reports import (
    build_batch_summary,
    build_daily_overview,
    build_lead_report,
    build_rejections_report,
    build_data_quality_report,
    generate_reports,
)


DISPOSITIONS_PATH = "assignment-a-data/schemas/dispositions.csv"


# --------------------------------------------------
# DATABASE FIXTURE
# --------------------------------------------------

@pytest.fixture
def setup_db(tmp_path, monkeypatch):

    monkeypatch.setenv(
        "DATABASE_PATH",
        str(tmp_path / "reports_test.db"),
    )

    monkeypatch.setenv(
        "PII_ENCRYPTION_KEY",
        base64.b64encode(
            secrets.token_bytes(32)
        ).decode(),
    )

    monkeypatch.setenv(
        "PII_HMAC_KEY",
        base64.b64encode(
            secrets.token_bytes(32)
        ).decode(),
    )

    init_db()

    connection = get_connection()

    yield connection

    connection.close()


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def insert_test_lead(
    connection,
    phone,
    external_ref,
    batch_id="batch_001",
):

    normalized_phone = "+91" + phone

    fingerprint = phone_fingerprint(
        normalized_phone
    )

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
            encrypt_pii(normalized_phone),
            encrypt_pii("Test Customer"),
            external_ref,
            batch_id,
            json.dumps({
                "policy_number": external_ref,
            }),
        ),
    )

    connection.commit()

    return cursor.lastrowid


def insert_test_event(
    connection,
    lead_id,
    event_id,
    event_type,
    call_id,
    occurred_at,
    payload=None,
):

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
            "motor_renewal",
            call_id,
            occurred_at,
            None,
            json.dumps(payload or {}),
        ),
    )

    connection.execute(
        """
        INSERT INTO event_links (
            event_id,
            lead_id
        )
        VALUES (?, ?)
        """,
        (
            event_id,
            lead_id,
        ),
    )

    connection.commit()


def create_successful_call(connection, lead_id):

    call_id = "call_success"

    insert_test_event(
        connection,
        lead_id,
        "evt_success_initiated",
        "call.initiated",
        call_id,
        "2026-10-01T05:30:00+00:00",
    )

    insert_test_event(
        connection,
        lead_id,
        "evt_success_connected",
        "call.connected",
        call_id,
        "2026-10-01T05:31:00+00:00",
    )

    insert_test_event(
        connection,
        lead_id,
        "evt_success_disposition",
        "disposition.set",
        call_id,
        "2026-10-01T05:35:00+00:00",
        {
            "disposition_code": "renewed",
        },
    )


# --------------------------------------------------
# BATCH SUMMARY TESTS
# --------------------------------------------------

def test_batch_summary(setup_db):

    connection = setup_db

    lead_id = insert_test_lead(
        connection,
        "8902799046",
        "POLICY001",
    )

    insert_test_lead(
        connection,
        "9876543210",
        "POLICY002",
    )

    create_successful_call(
        connection,
        lead_id,
    )

    result = build_batch_summary(
        connection,
        __import__(
            "solution.ingestion.events",
            fromlist=["load_dispositions"]
        ).load_dispositions(DISPOSITIONS_PATH),
    )

    assert len(result) == 1

    summary = result[0]

    assert summary["workflow_id"] == "motor_renewal"
    assert summary["batch_id"] == "batch_001"
    assert summary["total_leads"] == 2
    assert summary["completed"] == 1
    assert summary["yet_to_reach_out"] == 1


# --------------------------------------------------
# DAILY OVERVIEW TESTS
# --------------------------------------------------

def test_daily_overview(setup_db):

    connection = setup_db

    lead_id = insert_test_lead(
        connection,
        "8902799046",
        "POLICY001",
    )

    create_successful_call(
        connection,
        lead_id,
    )

    from solution.ingestion.events import load_dispositions

    result = build_daily_overview(
        connection,
        load_dispositions(DISPOSITIONS_PATH),
    )

    assert len(result) == 1

    daily = result[0]

    assert daily["workflow_id"] == "motor_renewal"

    # 05:30 UTC is 11:00 IST.
    assert daily["date"] == "2026-10-01"

    assert daily["total_calls"] == 1
    assert daily["connected_calls"] == 1
    assert daily["connectivity_rate"] == "1.0000"
    assert daily["success_leads"] == 1


# --------------------------------------------------
# LEAD REPORT TESTS
# --------------------------------------------------

def test_lead_report_masks_phone(setup_db):

    connection = setup_db

    lead_id = insert_test_lead(
        connection,
        "8902799046",
        "POLICY001",
    )

    create_successful_call(
        connection,
        lead_id,
    )

    from solution.ingestion.events import load_dispositions

    result = build_lead_report(
        connection,
        load_dispositions(DISPOSITIONS_PATH),
    )

    assert len(result) == 1

    lead = result[0]

    assert lead["external_ref"] == "POLICY001"
    assert lead["phone_masked"] == "+91******9046"

    assert lead["bucket"] == "completed"
    assert lead["total_calls"] == 1
    assert lead["connected_calls"] == 1

    assert lead["current_disposition"] == "renewed"
    assert lead["ever_success"] == "true"

    # Full phone number must not appear in the report.
    assert "8902799046" not in lead["phone_masked"]


def test_lead_without_calls(setup_db):

    connection = setup_db

    insert_test_lead(
        connection,
        "8902799046",
        "POLICY001",
    )

    from solution.ingestion.events import load_dispositions

    result = build_lead_report(
        connection,
        load_dispositions(DISPOSITIONS_PATH),
    )

    assert result[0]["bucket"] == "yet_to_reach_out"
    assert result[0]["total_calls"] == 0
    assert result[0]["last_call_at"] == ""
    assert result[0]["current_disposition"] == ""
    assert result[0]["ever_success"] == "false"


# --------------------------------------------------
# REJECTIONS REPORT TESTS
# --------------------------------------------------

def test_rejections_report(setup_db):

    connection = setup_db

    connection.execute(
        """
        INSERT INTO rejections (
            workflow_id,
            batch_id,
            row_number,
            reason
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            "motor_renewal",
            "batch_001",
            2,
            "invalid_phone",
        ),
    )

    connection.commit()

    result = build_rejections_report(connection)

    assert len(result) == 1

    assert result[0]["workflow_id"] == "motor_renewal"
    assert result[0]["batch_id"] == "batch_001"
    assert result[0]["row_number"] == 2
    assert result[0]["reason"] == "invalid_phone"


# --------------------------------------------------
# DATA QUALITY TESTS
# --------------------------------------------------

def test_data_quality_report(setup_db):

    connection = setup_db

    connection.execute(
        """
        INSERT INTO rejections (
            workflow_id,
            batch_id,
            row_number,
            reason
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            "motor_renewal",
            "batch_001",
            2,
            "invalid_phone",
        ),
    )

    connection.commit()

    result = build_data_quality_report(connection)

    assert result["lead_rows_rejected"] == 1

    assert result["rejections_by_reason"] == {
        "invalid_phone": 1,
    }

    assert result["events_total"] == 0
    assert result["orphan_events"] == 0


# --------------------------------------------------
# GENERATE ALL REPORTS TEST
# --------------------------------------------------

def test_generate_reports_creates_all_files(
    setup_db,
    tmp_path,
):

    connection = setup_db

    output_dir = tmp_path / "reports"

    insert_test_lead(
        connection,
        "8902799046",
        "POLICY001",
    )

    result = generate_reports(
        connection,
        output_dir,
        DISPOSITIONS_PATH,
    )

    expected_files = [
        "batch_summary.csv",
        "daily_overview.csv",
        "lead_report.csv",
        "rejections.csv",
        "data_quality.json",
    ]

    for filename in expected_files:
        assert (output_dir / filename).exists()

    assert len(result["batch_summary"]) == 1
    assert len(result["lead_report"]) == 1
