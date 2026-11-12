
import base64
import secrets
import json

import pytest

from solution.database.db import get_connection, init_db
from solution.services.lead_storage import save_merged_leads
from solution.services.encryption import decrypt_pii


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


def test_save_lead_securely(setup_db):
    lead = {
        "workflow_id": "motor_renewal",
        "batch_id": "batch_001",
        "customer_name": "Rahul Kumar",
        "phone": "+918902799046",
        "policy_number": "POLICY001",
        "policy_expiry": "2026-12-31",
        "premium_amount": "5000.00",
        "preferred_language": "en",
    }

    result = save_merged_leads([lead], setup_db)

    assert result["leads_inserted"] == 1

    stored = setup_db.execute(
        "SELECT * FROM leads"
    ).fetchone()

    assert stored is not None

    assert stored["phone_encrypted"] != lead["phone"]
    assert stored["customer_name_encrypted"] != lead["customer_name"]

    assert decrypt_pii(stored["phone_encrypted"]) == lead["phone"]
    assert decrypt_pii(stored["customer_name_encrypted"]) == lead["customer_name"]

    fields = json.loads(stored["fields_json"])

    assert fields["policy_number"] == "POLICY001"


def test_duplicate_lead_updates_existing_record(setup_db):
    lead = {
        "workflow_id": "motor_renewal",
        "batch_id": "batch_001",
        "customer_name": "Rahul Kumar",
        "phone": "+918902799046",
        "policy_number": "POLICY001",
        "policy_expiry": None,
        "premium_amount": None,
        "preferred_language": "en",
    }

    save_merged_leads([lead], setup_db)

    updated_lead = {
        **lead,
        "batch_id": "batch_002",
        "policy_expiry": "2027-01-31",
    }

    result = save_merged_leads([updated_lead], setup_db)

    assert result["leads_updated"] == 1

    records = setup_db.execute(
        "SELECT * FROM leads"
    ).fetchall()

    assert len(records) == 1

    fields = json.loads(records[0]["fields_json"])

    assert fields["policy_expiry"] == "2027-01-31"
    assert records[0]["batch_id"] == "batch_001"
