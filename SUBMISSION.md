# Interaction Ledger & Reporting Pipeline

## 1. Project Overview

This project implements an interaction ledger and reporting pipeline for processing lead data and interaction events.

The solution uses Python and SQLite to ingest lead CSV files, validate and normalize data, merge duplicate leads, securely store personally identifiable information (PII), process interaction events, link events to leads, and generate reporting outputs.

## 2. Technology Stack

- Python 3.11
- SQLite
- pytest
- cryptography (AES-GCM encryption)
- HMAC-SHA256
- python-dotenv

## 3. Project Structure

```text
project-root/
│
├── assignment-a-data/
│   ├── schemas/
│   └── tools/
│
├── data/
│   ├── drop_1/
│   └── drop_2/
│
├── solution/
│   ├── database/
│   │   └── db.py
│   │
│   ├── ingestion/
│   │   ├── leads.py
│   │   └── events.py
│   │
│   ├── reporting/
│   │   └── reports.py
│   │
│   ├── services/
│   │   ├── encryption.py
│   │   ├── lead_merge.py
│   │   ├── lead_storage.py
│   │   └── normalization.py
│   │
│   ├── tests/
│   ├── pipeline.py
│   └── cli.py
│
├── reports/
├── .env
├── .gitignore
├── SUBMISSION.md
└── AI_USAGE.md
```

## 4. Main Features

### Lead Ingestion

- Reads workflow-specific CSV files.
- Normalizes column headers and supports schema aliases.
- Validates required and optional fields.
- Normalizes phone numbers, dates, decimals, and enum values.
- Records rejected rows with rejection reasons.
- Tracks optional field warnings.

### Duplicate Lead Handling

- Identifies leads using workflow ID and normalized phone number.
- Merges duplicate lead records.
- Preserves the original batch ID.
- Applies defaults after merging.
- Prevents null values from overwriting existing values.

### PII Protection

- Encrypts phone numbers and customer names using AES-GCM.
- Uses HMAC-SHA256 fingerprints for phone matching.
- Avoids storing plaintext phone numbers in the leads table.
- Uses masked phone numbers in reports.

### Interaction Event Processing

- Reads JSONL event files.
- Handles malformed and duplicate events.
- Links events to leads using phone fingerprints.
- Supports orphan event relinking.
- Supports disposition events and disposition overrides.
- Maintains an append-only event ledger.

### Reporting

The pipeline generates five reports:

1. `batch_summary.csv`
2. `daily_overview.csv`
3. `lead_report.csv`
4. `rejections.csv`
5. `data_quality.json`

### Idempotency

- Tracks processed drops in SQLite.
- Skips drops that have already been processed.
- Prevents duplicate ingestion when the same drop is run again.

## 5. Setup Instructions

### Requirements

- Python 3.11 or later
- pip

### Create a virtual environment

```powershell
python -m venv .venv
```

### Activate the environment

```powershell
.venv\Scripts\Activate.ps1
```

### Install dependencies

Install the packages listed in `requirements.txt`:

```powershell
pip install -r requirements.txt
```

### Configure environment variables

Create a `.env` file in the project root containing:

```env
PII_ENCRYPTION_KEY=your_base64_encryption_key
PII_HMAC_KEY=your_base64_hmac_key
```

Generate fresh keys for your environment. Never commit actual secret values.

## 6. Run the Pipeline

From the project root:

```powershell
python -m solution.cli run
```

This processes all available drops in order and generates the five reports.

### Process one drop

```powershell
python -m solution.cli ingest data/drop_1
```

### Generate reports

```powershell
python -m solution.cli report
```

## 7. Run Tests

Execute:

```powershell
python -m pytest solution/tests/ -v
```

Current test result:

- Total tests: 42
- Passed: 42
- Failed: 0

## 8. Generated Reports

All generated reports are saved in the `reports/` directory.

- `batch_summary.csv` contains lead counts grouped by workflow and batch.
- `daily_overview.csv` contains daily call and connectivity statistics.
- `lead_report.csv` contains individual lead status and call information.
- `rejections.csv` contains rejected lead rows and their reasons.
- `data_quality.json` contains ingestion and data quality metrics.

## 9. Database

SQLite is used as the persistent storage layer.

Main tables:

- `leads`
- `events`
- `event_links`
- `rejections`
- `ingestion_runs`
- `ingestion_metrics`

The event ledger uses database triggers to prevent event updates and deletions.

## 10. Implementation Status

The core ingestion, normalization, merging, event processing, PII protection, reporting, and idempotency components have been implemented.

The automated test suite currently reports 42 passing tests.
