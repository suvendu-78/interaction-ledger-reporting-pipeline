
import argparse
from pathlib import Path

from solution.database.db import get_connection, init_db
from solution.pipeline import process_drop
from solution.reporting.reports import generate_reports


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_ROOT / "data"

REPORTS_DIR = PROJECT_ROOT / "reports"

DISPOSITIONS_PATH = (
    PROJECT_ROOT
    / "assignment-a-data"
    / "schemas"
    / "dispositions.csv"
)


def run_ingest(drop_path):
    """Ingest one drop."""

    init_db()

    connection = get_connection()

    try:
        result = process_drop(
            drop_path,
            connection=connection,
            project_root=PROJECT_ROOT,
        )

        print("\nIngestion result:")
        print(result)

    finally:
        connection.close()


def run_report():
    """Generate all five reports."""

    init_db()

    connection = get_connection()

    try:
        generate_reports(
            connection,
            REPORTS_DIR,
            DISPOSITIONS_PATH,
        )

        print(f"\nReports saved in: {REPORTS_DIR}")

    finally:
        connection.close()


def run_all():
    """Process all drops in order and generate reports."""

    init_db()

    connection = get_connection()

    try:
        if not DATA_DIR.exists():
            raise FileNotFoundError(
                f"Data directory not found: {DATA_DIR}"
            )

        drop_folders = sorted(
            [
                folder
                for folder in DATA_DIR.iterdir()
                if folder.is_dir()
                and folder.name.startswith("drop_")
            ],
            key=lambda folder: int(
                folder.name.split("_")[1]
            ),
        )

        if not drop_folders:
            print("No drop folders found.")
            return

        for drop_folder in drop_folders:

            process_drop(
                drop_folder,
                connection=connection,
                project_root=PROJECT_ROOT,
            )

        generate_reports(
            connection,
            REPORTS_DIR,
            DISPOSITIONS_PATH,
        )

        print("\nComplete pipeline finished successfully.")

    finally:
        connection.close()


def main():

    parser = argparse.ArgumentParser(
        description="Agentic Universe Interaction Ledger Pipeline"
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    # Ingest one drop
    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Ingest one data drop",
    )

    ingest_parser.add_argument(
        "drop_path",
        help="Path to the drop folder",
    )

    # Generate reports
    subparsers.add_parser(
        "report",
        help="Generate all five reports",
    )

    # Run everything
    subparsers.add_parser(
        "run",
        help="Process all drops and generate reports",
    )

    args = parser.parse_args()

    if args.command == "ingest":
        run_ingest(args.drop_path)

    elif args.command == "report":
        run_report()

    elif args.command == "run":
        run_all()


if __name__ == "__main__":
    main()
