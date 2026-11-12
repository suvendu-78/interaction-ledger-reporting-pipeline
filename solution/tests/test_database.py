
import base64
import secrets
import sqlite3

import pytest

from solution.services.encryption import (
    encrypt_pii,
    decrypt_pii,
    phone_fingerprint,
)

from solution.database.db import init_db, get_connection


@pytest.fixture
def configure_keys(monkeypatch):
    encryption_key = base64.b64encode(
        secrets.token_bytes(32)
    ).decode()

    hmac_key = base64.b64encode(
        secrets.token_bytes(32)
    ).decode()

    monkeypatch.setenv("PII_ENCRYPTION_KEY", encryption_key)
    monkeypatch.setenv("PII_HMAC_KEY", hmac_key)


def test_encryption_and_decryption(configure_keys):

    original = "Rahul Kumar"

    encrypted = encrypt_pii(original)

    assert encrypted != original
    assert decrypt_pii(encrypted) == original


def test_encryption_uses_random_nonce(configure_keys):

    original = "Rahul Kumar"

    encrypted1 = encrypt_pii(original)
    encrypted2 = encrypt_pii(original)

    assert encrypted1 != encrypted2


def test_phone_fingerprint_is_deterministic(configure_keys):

    phone = "+919876543210"

    fingerprint1 = phone_fingerprint(phone)
    fingerprint2 = phone_fingerprint(phone)

    assert fingerprint1 == fingerprint2


def test_different_phones_have_different_fingerprints(configure_keys):

    fingerprint1 = phone_fingerprint("+919876543210")
    fingerprint2 = phone_fingerprint("+918765432109")

    assert fingerprint1 != fingerprint2


def test_database_initialization(tmp_path, monkeypatch):

    db_path = tmp_path / "test.db"

    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    init_db()

    connection = get_connection()

    tables = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        """
    ).fetchall()

    table_names = [row["name"] for row in tables]

    assert "leads" in table_names
    assert "events" in table_names
    assert "event_links" in table_names
    assert "rejections" in table_names
    assert "ingestion_runs" in table_names

    connection.close()


def test_event_ledger_is_append_only(tmp_path, monkeypatch):

    db_path = tmp_path / "test.db"

    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    init_db()

    connection = get_connection()

    connection.execute(
        """
        INSERT INTO events (
            event_id,
            event_type,
            workflow_id,
            call_id,
            occurred_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "evt_001",
            "call.initiated",
            "motor_renewal",
            "call_001",
            "2026-11-12T10:00:00+05:30",
        )
    )

    connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE events SET event_type = ? WHERE event_id = ?",
            ("call.connected", "evt_001")
        )

    connection.close()
