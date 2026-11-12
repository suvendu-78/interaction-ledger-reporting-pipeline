
import csv
import json

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from solution.ingestion.events import load_dispositions
from solution.services.encryption import decrypt_pii


IST = timezone(timedelta(hours=5, minutes=30))


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def convert_to_ist(value):
    """Convert a stored UTC timestamp into an IST datetime."""

    if not value:
        return None

    parsed = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(IST)


def get_event_payload(event):
    """Safely decode an event payload."""

    try:
        return json.loads(event["payload_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def get_effective_disposition(events, dispositions):
    """
    Determine the effective disposition for one call.

    Latest override takes precedence over disposition.set.
    If there is no override, use the latest disposition.set.
    """

    overrides = []
    disposition_sets = []

    for event in events:

        event_type = event["event_type"]

        if event_type not in (
            "disposition.set",
            "disposition.override",
        ):
            continue

        payload = get_event_payload(event)

        code = payload.get("disposition_code")

        if not code:
            continue

        item = {
            "code": code.lower(),
            "occurred_at": event["occurred_at"],
        }

        if event_type == "disposition.override":
            overrides.append(item)

        else:
            disposition_sets.append(item)

    if overrides:
        selected = max(
            overrides,
            key=lambda item: item["occurred_at"],
        )

    elif disposition_sets:
        selected = max(
            disposition_sets,
            key=lambda item: item["occurred_at"],
        )

    else:
        return None

    workflow_id = events[0]["workflow_id"]

    catalog = dispositions.get(workflow_id, {})

    disposition_info = catalog.get(selected["code"])

    if not disposition_info:
        return None

    return {
        "code": selected["code"],
        "is_terminal": disposition_info["is_terminal"],
        "is_success": disposition_info["is_success"],
    }


def get_call_information(connection, dispositions):
    """
    Build call-level information from linked events.

    Only calls containing call.initiated events are counted.
    """

    rows = connection.execute(
        """
        SELECT
            e.event_id,
            e.event_type,
            e.workflow_id,
            e.call_id,
            e.occurred_at,
            e.payload_json,
            el.lead_id

        FROM events e

        INNER JOIN event_links el
            ON el.event_id = e.event_id

        ORDER BY e.occurred_at
        """
    ).fetchall()

    grouped_events = defaultdict(list)

    for row in rows:
        key = (
            row["lead_id"],
            row["workflow_id"],
            row["call_id"],
        )

        grouped_events[key].append(row)

    calls = []

    for key, events in grouped_events.items():

        initiated_events = [
            event
            for event in events
            if event["event_type"] == "call.initiated"
        ]

        # Ignore events without a call.initiated event.
        if not initiated_events:
            continue

        initiated = min(
            initiated_events,
            key=lambda event: event["occurred_at"],
        )

        connected = any(
            event["event_type"] == "call.connected"
            for event in events
        )

        telephony_failed = any(
            event["event_type"] == "call.telephony_failed"
            for event in events
        )

        effective_disposition = get_effective_disposition(
            events,
            dispositions,
        )

        calls.append({
            "lead_id": key[0],
            "workflow_id": key[1],
            "call_id": key[2],
            "initiated_at": initiated["occurred_at"],
            "connected": connected,
            "telephony_failed": telephony_failed,
            "disposition": effective_disposition,
        })

    return calls


def calculate_bucket(lead_calls):
    """Calculate the required lead bucket."""

    if not lead_calls:
        return "yet_to_reach_out"

    # Any terminal disposition completes the lead.
    for call in lead_calls:

        disposition = call["disposition"]

        if disposition and disposition["is_terminal"]:
            return "completed"

    # Every call must have a telephony failure.
    if all(
        call["telephony_failed"]
        for call in lead_calls
    ):
        return "in_progress_telephony_failed"

    return "in_progress_dialed"


def mask_phone(encrypted_phone):
    """Decrypt phone temporarily and return only its masked form."""

    phone = decrypt_pii(encrypted_phone)

    digits = "".join(
        character
        for character in phone
        if character.isdigit()
    )

    return "+91******" + digits[-4:]


# --------------------------------------------------
# BATCH SUMMARY
# --------------------------------------------------

def build_batch_summary(connection, dispositions):

    leads = connection.execute(
        """
        SELECT *
        FROM leads
        ORDER BY workflow_id, batch_id
        """
    ).fetchall()

    calls = get_call_information(
        connection,
        dispositions,
    )

    calls_by_lead = defaultdict(list)

    for call in calls:
        calls_by_lead[call["lead_id"]].append(call)

    summary = {}

    for lead in leads:

        workflow_id = lead["workflow_id"]
        batch_id = lead["batch_id"]

        key = (workflow_id, batch_id)

        if key not in summary:
            summary[key] = {
                "workflow_id": workflow_id,
                "batch_id": batch_id,
                "total_leads": 0,
                "yet_to_reach_out": 0,
                "in_progress_telephony_failed": 0,
                "in_progress_dialed": 0,
                "completed": 0,
            }

        lead_calls = calls_by_lead[lead["id"]]

        bucket = calculate_bucket(lead_calls)

        summary[key]["total_leads"] += 1
        summary[key][bucket] += 1

    return sorted(
        summary.values(),
        key=lambda row: (
            row["workflow_id"],
            row["batch_id"],
        ),
    )


# --------------------------------------------------
# DAILY OVERVIEW
# --------------------------------------------------

def build_daily_overview(connection, dispositions):

    calls = get_call_information(
        connection,
        dispositions,
    )

    daily = {}

    successful_leads = defaultdict(set)

    for call in calls:

        ist_datetime = convert_to_ist(
            call["initiated_at"]
        )

        date = ist_datetime.date().isoformat()

        key = (
            call["workflow_id"],
            date,
        )

        if key not in daily:
            daily[key] = {
                "workflow_id": call["workflow_id"],
                "date": date,
                "total_calls": 0,
                "connected_calls": 0,
            }

        daily[key]["total_calls"] += 1

        if call["connected"]:
            daily[key]["connected_calls"] += 1

        disposition = call["disposition"]

        if disposition and disposition["is_success"]:
            successful_leads[key].add(
                call["lead_id"]
            )

    result = []

    for key, row in daily.items():

        total_calls = row["total_calls"]
        connected_calls = row["connected_calls"]

        connectivity_rate = (
            connected_calls / total_calls
            if total_calls
            else 0
        )

        result.append({
            "workflow_id": row["workflow_id"],
            "date": row["date"],
            "total_calls": total_calls,
            "connected_calls": connected_calls,
            "connectivity_rate": f"{connectivity_rate:.4f}",
            "success_leads": len(successful_leads[key]),
        })

    return sorted(
        result,
        key=lambda row: (
            row["workflow_id"],
            row["date"],
        ),
    )


# --------------------------------------------------
# LEAD REPORT
# --------------------------------------------------

def build_lead_report(connection, dispositions):

    leads = connection.execute(
        """
        SELECT *
        FROM leads
        ORDER BY workflow_id, external_ref
        """
    ).fetchall()

    calls = get_call_information(
        connection,
        dispositions,
    )

    calls_by_lead = defaultdict(list)

    for call in calls:
        calls_by_lead[call["lead_id"]].append(call)

    result = []

    for lead in leads:

        lead_calls = sorted(
            calls_by_lead[lead["id"]],
            key=lambda call: call["initiated_at"],
        )

        bucket = calculate_bucket(lead_calls)

        total_calls = len(lead_calls)

        connected_calls = sum(
            1
            for call in lead_calls
            if call["connected"]
        )

        # Latest call initiation timestamp.
        last_call_at = ""

        if lead_calls:
            latest_call = max(
                lead_calls,
                key=lambda call: call["initiated_at"],
            )

            latest_ist = convert_to_ist(
                latest_call["initiated_at"]
            )

            last_call_at = latest_ist.isoformat()

        # Current disposition is from the most recent call
        # that has an effective disposition.
        current_disposition = ""

        for call in reversed(lead_calls):

            disposition = call["disposition"]

            if disposition:
                current_disposition = disposition["code"]
                break

        # Success can come from any call.
        ever_success = any(
            call["disposition"]
            and call["disposition"]["is_success"]
            for call in lead_calls
        )

        result.append({
            "workflow_id": lead["workflow_id"],
            "external_ref": lead["external_ref"],
            "batch_id": lead["batch_id"],
            "phone_masked": mask_phone(
                lead["phone_encrypted"]
            ),
            "bucket": bucket,
            "total_calls": total_calls,
            "connected_calls": connected_calls,
            "last_call_at": last_call_at,
            "current_disposition": current_disposition,
            "ever_success": str(ever_success).lower(),
        })

    return sorted(
        result,
        key=lambda row: (
            row["workflow_id"],
            row["external_ref"],
        ),
    )


# --------------------------------------------------
# REJECTIONS REPORT
# --------------------------------------------------

def build_rejections_report(connection):

    rows = connection.execute(
        """
        SELECT
            workflow_id,
            batch_id,
            row_number,
            reason

        FROM rejections

        ORDER BY
            workflow_id,
            batch_id,
            row_number
        """
    ).fetchall()

    return [
        {
            "workflow_id": row["workflow_id"],
            "batch_id": row["batch_id"],
            "row_number": row["row_number"],
            "reason": row["reason"],
        }
        for row in rows
    ]


# --------------------------------------------------
# DATA QUALITY REPORT
# --------------------------------------------------

def build_data_quality_report(connection):
    """Build data-quality metrics across all processed drops."""

    metric_columns = [
        "lead_rows_total",
        "lead_rows_rejected",
        "duplicate_lead_rows_merged",
        "field_warnings",
        "events_total",
        "malformed_events",
        "duplicate_events_dropped",
        "unknown_disposition_events",
    ]

    totals = {
        column: 0
        for column in metric_columns
    }

    metric_rows = connection.execute(
        """
        SELECT *
        FROM ingestion_metrics
        """
    ).fetchall()

    for row in metric_rows:
        for column in metric_columns:
            totals[column] += row[column]

    # Use the rejections table as the source of truth.
    rejection_rows = connection.execute(
        """
        SELECT reason, COUNT(*) AS total
        FROM rejections
        GROUP BY reason
        ORDER BY reason
        """
    ).fetchall()

    rejections_by_reason = {
        row["reason"]: row["total"]
        for row in rejection_rows
    }

    # Count actual rejected rows from the rejections table.
    totals["lead_rows_rejected"] = sum(
        rejections_by_reason.values()
    )

    orphan_events = connection.execute(
        """
        SELECT COUNT(*) AS total
        FROM events e

        LEFT JOIN event_links el
            ON el.event_id = e.event_id

        WHERE el.event_id IS NULL
        """
    ).fetchone()["total"]

    return {
        "lead_rows_total": totals["lead_rows_total"],
        "lead_rows_rejected": totals["lead_rows_rejected"],
        "rejections_by_reason": rejections_by_reason,
        "duplicate_lead_rows_merged": totals["duplicate_lead_rows_merged"],
        "field_warnings": totals["field_warnings"],
        "events_total": totals["events_total"],
        "malformed_events": totals["malformed_events"],
        "duplicate_events_dropped": totals["duplicate_events_dropped"],
        "orphan_events": orphan_events,
        "unknown_disposition_events": totals["unknown_disposition_events"],
    }


# --------------------------------------------------
# CSV WRITER
# --------------------------------------------------

def write_csv(output_path, fieldnames, rows):

    with open(
        output_path,
        "w",
        encoding="utf-8",
        newline="",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(rows)


# --------------------------------------------------
# GENERATE ALL REPORTS
# --------------------------------------------------

def generate_reports(
    connection,
    output_dir,
    dispositions_path,
):
    """
    Generate all five required reports.
    """

    output_dir = Path(output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    dispositions = load_dispositions(
        dispositions_path
    )

    # 1. Batch summary
    batch_summary = build_batch_summary(
        connection,
        dispositions,
    )

    write_csv(
        output_dir / "batch_summary.csv",
        [
            "workflow_id",
            "batch_id",
            "total_leads",
            "yet_to_reach_out",
            "in_progress_telephony_failed",
            "in_progress_dialed",
            "completed",
        ],
        batch_summary,
    )

    # 2. Daily overview
    daily_overview = build_daily_overview(
        connection,
        dispositions,
    )

    write_csv(
        output_dir / "daily_overview.csv",
        [
            "workflow_id",
            "date",
            "total_calls",
            "connected_calls",
            "connectivity_rate",
            "success_leads",
        ],
        daily_overview,
    )

    # 3. Lead report
    lead_report = build_lead_report(
        connection,
        dispositions,
    )

    write_csv(
        output_dir / "lead_report.csv",
        [
            "workflow_id",
            "external_ref",
            "batch_id",
            "phone_masked",
            "bucket",
            "total_calls",
            "connected_calls",
            "last_call_at",
            "current_disposition",
            "ever_success",
        ],
        lead_report,
    )

    # 4. Rejections
    rejections = build_rejections_report(
        connection
    )

    write_csv(
        output_dir / "rejections.csv",
        [
            "workflow_id",
            "batch_id",
            "row_number",
            "reason",
        ],
        rejections,
    )

    # 5. Data quality
    data_quality = build_data_quality_report(
        connection
    )

    with open(
        output_dir / "data_quality.json",
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            data_quality,
            file,
            indent=4,
        )

    print("All five reports generated successfully.")

    return {
        "batch_summary": batch_summary,
        "daily_overview": daily_overview,
        "lead_report": lead_report,
        "rejections": rejections,
        "data_quality": data_quality,
    }
