
import os
import sqlite3

from pathlib import Path


DEFAULT_DB_PATH = Path("data") / "agentic_universe.db"


def get_connection():
    """Create a SQLite database connection."""

    db_path = Path(
        os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH))
    )

    db_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(db_path)

    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")

    return connection


def init_db():
    """Create all database tables and constraints."""

    connection = get_connection()

    try:
        connection.executescript("""

        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id TEXT NOT NULL,
            phone_hmac TEXT NOT NULL,
            phone_encrypted TEXT NOT NULL,
            customer_name_encrypted TEXT NOT NULL,
            external_ref TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            fields_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(workflow_id, phone_hmac)
        );


        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            workflow_id TEXT NOT NULL,
            call_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            phone_hmac TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );


        CREATE TABLE IF NOT EXISTS event_links (
            event_id TEXT PRIMARY KEY,
            lead_id INTEGER NOT NULL,
            linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(event_id)
                REFERENCES events(event_id),

            FOREIGN KEY(lead_id)
                REFERENCES leads(id)
        );


        CREATE TABLE IF NOT EXISTS rejections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            row_number INTEGER NOT NULL,
            reason TEXT NOT NULL
        );


        CREATE TABLE IF NOT EXISTS ingestion_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drop_id TEXT NOT NULL UNIQUE,
            processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );


        -- Persistent data-quality counters for each processed drop.
        CREATE TABLE IF NOT EXISTS ingestion_metrics (
            drop_id TEXT PRIMARY KEY,

            lead_rows_total INTEGER NOT NULL DEFAULT 0,
            lead_rows_rejected INTEGER NOT NULL DEFAULT 0,
            duplicate_lead_rows_merged INTEGER NOT NULL DEFAULT 0,
            field_warnings INTEGER NOT NULL DEFAULT 0,

            events_total INTEGER NOT NULL DEFAULT 0,
            malformed_events INTEGER NOT NULL DEFAULT 0,
            duplicate_events_dropped INTEGER NOT NULL DEFAULT 0,
            unknown_disposition_events INTEGER NOT NULL DEFAULT 0,

            FOREIGN KEY(drop_id)
                REFERENCES ingestion_runs(drop_id)
        );


        CREATE INDEX IF NOT EXISTS idx_leads_workflow
            ON leads(workflow_id);

        CREATE INDEX IF NOT EXISTS idx_leads_phone_hmac
            ON leads(phone_hmac);

        CREATE INDEX IF NOT EXISTS idx_events_call_id
            ON events(call_id);

        CREATE INDEX IF NOT EXISTS idx_events_phone
            ON events(workflow_id, phone_hmac);

        CREATE INDEX IF NOT EXISTS idx_events_occurred
            ON events(occurred_at);

        CREATE INDEX IF NOT EXISTS idx_event_links_lead
            ON event_links(lead_id);

        CREATE INDEX IF NOT EXISTS idx_rejections_batch
            ON rejections(workflow_id, batch_id);


        -- Event ledger must remain append-only.
        CREATE TRIGGER IF NOT EXISTS prevent_event_update
        BEFORE UPDATE ON events
        BEGIN
            SELECT RAISE(
                ABORT,
                'Events are append-only'
            );
        END;


        CREATE TRIGGER IF NOT EXISTS prevent_event_delete
        BEFORE DELETE ON events
        BEGIN
            SELECT RAISE(
                ABORT,
                'Events are append-only'
            );
        END;

        """)

        connection.commit()

        print("Database initialized successfully.")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()
