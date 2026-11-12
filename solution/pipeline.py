
from pathlib import Path

from solution.database.db import get_connection
from solution.ingestion.leads import load_schema, ingest_lead_file
from solution.ingestion.events import (
    ingest_event_file,
    relink_orphan_events,
)
from solution.services.lead_merge import merge_leads
from solution.services.lead_storage import save_merged_leads


def process_drop(drop_path, connection=None, project_root=None):
    """
    Process one data drop.

    Steps:
    1. Check whether this drop was already processed.
    2. Ingest and validate lead CSV files.
    3. Merge duplicate leads.
    4. Save leads securely.
    5. Save rejected rows.
    6. Ingest event JSONL files.
    7. Relink orphan events.
    8. Save ingestion metrics.

    Returns a processing summary.
    """

    drop_path = Path(drop_path).resolve()

    if not drop_path.exists() or not drop_path.is_dir():
        raise FileNotFoundError(
            f"Drop folder does not exist: {drop_path}"
        )

    if project_root is None:
        project_root = Path(__file__).resolve().parents[1]
    else:
        project_root = Path(project_root).resolve()

    schemas_dir = project_root / "assignment-a-data" / "schemas"

    dispositions_path = schemas_dir / "dispositions.csv"

    if not dispositions_path.exists():
        raise FileNotFoundError(
            f"Dispositions file not found: {dispositions_path}"
        )

    if connection is None:
        connection = get_connection()

    drop_id = drop_path.name

    # --------------------------------------------------
    # 1. IDEMPOTENCY CHECK
    # --------------------------------------------------

    already_processed = connection.execute(
        """
        SELECT drop_id
        FROM ingestion_runs
        WHERE drop_id = ?
        """,
        (drop_id,),
    ).fetchone()

    if already_processed:
        print(f"{drop_id} was already processed. Skipping.")

        return {
            "drop_id": drop_id,
            "status": "already_processed",
        }

    print(f"\nProcessing {drop_id}...")

    # --------------------------------------------------
    # 2. INITIALIZE METRICS
    # --------------------------------------------------

    metrics = {
        "lead_rows_total": 0,
        "lead_rows_rejected": 0,
        "duplicate_lead_rows_merged": 0,
        "field_warnings": 0,
        "events_total": 0,
        "malformed_events": 0,
        "duplicate_events_dropped": 0,
        "unknown_disposition_events": 0,
    }

    all_lead_batches = []
    schemas = {}
    all_rejections = []

    # --------------------------------------------------
    # 3. INGEST LEAD CSV FILES
    # --------------------------------------------------

    leads_root = drop_path / "leads"

    if leads_root.exists():

        workflow_dirs = sorted(
            folder
            for folder in leads_root.iterdir()
            if folder.is_dir()
        )

        for workflow_dir in workflow_dirs:

            workflow_id = workflow_dir.name

            schema_path = (
                schemas_dir / f"{workflow_id}.json"
            )

            if not schema_path.exists():
                raise FileNotFoundError(
                    f"Schema not found for workflow: {workflow_id}"
                )

            schema = load_schema(schema_path)

            schemas[workflow_id] = schema

            csv_files = sorted(
                workflow_dir.glob("*.csv")
            )

            for csv_file in csv_files:

                print(f"  Reading: {csv_file.name}")

                result = ingest_lead_file(
                    csv_file,
                    schema_path,
                )

                valid_leads = result["valid_leads"]

                all_lead_batches.append(valid_leads)

                metrics["lead_rows_total"] += (
                    result["lead_rows_total"]
                )

                metrics["lead_rows_rejected"] += (
                    result["lead_rows_rejected"]
                )

                metrics["field_warnings"] += (
                    result["field_warnings"]
                )

                all_rejections.extend(
                    result["rejected_rows"]
                )

    # --------------------------------------------------
    # 4. MERGE DUPLICATE LEADS
    # --------------------------------------------------

    merged_result = merge_leads(
        all_lead_batches,
        schemas,
    )

    merged_leads = merged_result["leads"]

    metrics["duplicate_lead_rows_merged"] += (
        merged_result["duplicate_lead_rows_merged"]
    )

    # --------------------------------------------------
    # 5. SAVE LEADS SECURELY
    # --------------------------------------------------

    storage_result = save_merged_leads(
        merged_leads,
        connection,
    )

    # Existing database leads updated by this drop
    # are also duplicate lead rows.
    metrics["duplicate_lead_rows_merged"] += (
        storage_result["leads_updated"]
    )

    print(
        f"  New leads: {storage_result['leads_inserted']}"
    )

    print(
        f"  Existing leads updated: {storage_result['leads_updated']}"
    )

    # --------------------------------------------------
    # 6. SAVE REJECTED ROWS
    # --------------------------------------------------

    for rejected in all_rejections:

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
                rejected["workflow_id"],
                rejected["batch_id"],
                rejected["row_number"],
                rejected["reason"],
            ),
        )

    connection.commit()

    print(
        f"  Rejected lead rows: {metrics['lead_rows_rejected']}"
    )

    # --------------------------------------------------
    # 7. INGEST EVENT FILES
    # --------------------------------------------------

    events_dir = drop_path / "events"

    if events_dir.exists():

        event_files = sorted(
            events_dir.glob("*.jsonl")
        )

        for event_file in event_files:

            print(f"  Reading events: {event_file.name}")

            event_result = ingest_event_file(
                event_file,
                dispositions_path,
                connection,
            )

            metrics["events_total"] += (
                event_result["events_total"]
            )

            metrics["malformed_events"] += (
                event_result["malformed_events"]
            )

            metrics["duplicate_events_dropped"] += (
                event_result["duplicate_events_dropped"]
            )

            metrics["unknown_disposition_events"] += (
                event_result["unknown_disposition_events"]
            )

    # --------------------------------------------------
    # 8. RELINK ORPHAN EVENTS
    # --------------------------------------------------

    relinked_count = relink_orphan_events(connection)

    print(
        f"  Previously orphaned events relinked: {relinked_count}"
    )

    # --------------------------------------------------
    # 9. SAVE DROP PROCESSING RECORD
    # --------------------------------------------------

    connection.execute(
        """
        INSERT INTO ingestion_runs (drop_id)
        VALUES (?)
        """,
        (drop_id,),
    )

    # --------------------------------------------------
    # 10. SAVE INGESTION METRICS
    # --------------------------------------------------

    connection.execute(
        """
        INSERT INTO ingestion_metrics (
            drop_id,
            lead_rows_total,
            lead_rows_rejected,
            duplicate_lead_rows_merged,
            field_warnings,
            events_total,
            malformed_events,
            duplicate_events_dropped,
            unknown_disposition_events
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            drop_id,
            metrics["lead_rows_total"],
            metrics["lead_rows_rejected"],
            metrics["duplicate_lead_rows_merged"],
            metrics["field_warnings"],
            metrics["events_total"],
            metrics["malformed_events"],
            metrics["duplicate_events_dropped"],
            metrics["unknown_disposition_events"],
        ),
    )

    connection.commit()

    print(f"\n{drop_id} processed successfully.")

    return {
        "drop_id": drop_id,
        "status": "processed",
        "metrics": metrics,
        "new_leads": storage_result["leads_inserted"],
        "updated_leads": storage_result["leads_updated"],
        "events_relinked": relinked_count,
    }
