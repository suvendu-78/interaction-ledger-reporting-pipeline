
from solution.services.lead_merge import merge_leads


def test_duplicate_leads_are_merged():

    first_batch = [{
        "workflow_id": "motor_renewal",
        "batch_id": "batch_001",
        "customer_name": "Rahul",
        "phone": "+919876543210",
        "policy_number": "POL123",
        "policy_expiry": None,
        "premium_amount": None,
        "preferred_language": None,
    }]

    second_batch = [{
        "workflow_id": "motor_renewal",
        "batch_id": "batch_003",
        "customer_name": "Rahul Kumar",
        "phone": "+919876543210",
        "policy_number": "POL123",
        "policy_expiry": "2026-12-01",
        "premium_amount": "1250.50",
        "preferred_language": "hi",
    }]

    schemas = {
        "motor_renewal": {
            "fields": [
                {"name": "preferred_language", "default": "en"}
            ]
        }
    }

    result = merge_leads(
        [first_batch, second_batch],
        schemas
    )

    assert len(result["leads"]) == 1

    lead = result["leads"][0]

    assert lead["customer_name"] == "Rahul Kumar"
    assert lead["premium_amount"] == "1250.50"
    assert lead["policy_expiry"] == "2026-12-01"

    # Original batch ID must remain unchanged.
    assert lead["batch_id"] == "batch_001"

    assert result["duplicate_lead_rows_merged"] == 1


def test_defaults_applied_after_merging():

    first_batch = [{
        "workflow_id": "motor_renewal",
        "batch_id": "batch_001",
        "customer_name": "Rahul",
        "phone": "+919876543210",
        "preferred_language": None,
    }]

    second_batch = [{
        "workflow_id": "motor_renewal",
        "batch_id": "batch_002",
        "customer_name": "Rahul Kumar",
        "phone": "+919876543210",
        "preferred_language": "hi",
    }]

    schemas = {
        "motor_renewal": {
            "fields": [
                {"name": "preferred_language", "default": "en"}
            ]
        }
    }

    result = merge_leads(
        [first_batch, second_batch],
        schemas
    )

    assert result["leads"][0]["preferred_language"] == "hi"


def test_null_values_do_not_overwrite_existing_values():

    first_batch = [{
        "workflow_id": "motor_renewal",
        "batch_id": "batch_001",
        "customer_name": "Rahul",
        "phone": "+919876543210",
        "premium_amount": "1500.00",
    }]

    second_batch = [{
        "workflow_id": "motor_renewal",
        "batch_id": "batch_002",
        "customer_name": "Rahul Kumar",
        "phone": "+919876543210",
        "premium_amount": None,
    }]

    schemas = {"motor_renewal": {"fields": []}}

    result = merge_leads(
        [first_batch, second_batch],
        schemas
    )

    lead = result["leads"][0]

    assert lead["customer_name"] == "Rahul Kumar"
    assert lead["premium_amount"] == "1500.00"
    assert lead["batch_id"] == "batch_001"


def test_different_workflows_are_not_merged():

    leads = [
        [{
            "workflow_id": "motor_renewal",
            "batch_id": "batch_001",
            "phone": "+919876543210",
        }],
        [{
            "workflow_id": "policy_feedback",
            "batch_id": "batch_002",
            "phone": "+919876543210",
        }],
    ]

    schemas = {
        "motor_renewal": {"fields": []},
        "policy_feedback": {"fields": []},
    }

    result = merge_leads(leads, schemas)

    assert len(result["leads"]) == 2
    assert result["duplicate_lead_rows_merged"] == 0
