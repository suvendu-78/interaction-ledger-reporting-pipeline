# AI Usage Disclosure

## 1. Overview

AI tools were used as development assistance while implementing the Interaction Ledger & Reporting Pipeline assignment.

The tools helped with understanding requirements, discussing implementation approaches, debugging errors, reviewing code, and preparing documentation.

## 2. Areas Where AI Assistance Was Used

### Requirement Understanding

- Understanding the assignment requirements.
- Breaking the project into smaller implementation tasks.
- Clarifying lead ingestion, event processing, PII protection, and reporting requirements.

### Implementation Assistance

- Discussing Python and SQLite implementation approaches.
- Assistance with phone number, date, decimal, and enum normalization.
- Discussing duplicate lead merging and event linking.
- Assistance with AES-GCM encryption and HMAC-based phone matching.
- Reviewing reporting logic and idempotent processing.

### Debugging and Testing

- Understanding Python exceptions and SQLite errors.
- Debugging environment variable configuration.
- Reviewing failing pytest tests.
- Improving implementation based on test results.

### Documentation

- Assistance preparing project documentation and setup instructions.

## 3. Developer Responsibilities

I reviewed and integrated the suggested implementation into the project.

I ran the application locally, inspected execution output, fixed configuration issues, and executed the automated test suite.

I remain responsible for understanding, validating, and explaining the submitted implementation.

## 4. Testing

The project was tested locally using pytest.

Command:

```powershell
python -m pytest solution/tests/ -v
```

Latest result:

- 42 tests collected.
- 42 tests passed.
- 0 tests failed.

## 5. Transparency

AI was used as an assistance tool, not as a replacement for understanding, testing, or validating the implementation.
