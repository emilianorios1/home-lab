"""Command-line interface for local data imports."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from core.database import create_schema, get_engine
from core.logging import configure_logging
from pipelines.mercadopago_account_statement import process


DBT_PROJECT_DIR = Path(__file__).resolve().parents[2] / "dbt"


def run_transform() -> bool:
    from dbt.cli.main import dbtRunner

    result = dbtRunner().invoke(
        [
            "build",
            "--project-dir",
            str(DBT_PROJECT_DIR),
            "--profiles-dir",
            str(DBT_PROJECT_DIR),
        ]
    )
    return result.success


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="home-lab data tools")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="Create the raw PostgreSQL schema")
    subparsers.add_parser("transform", help="Build and test the dbt analytics models")

    import_parser = subparsers.add_parser(
        "import-account-statement", help="Import one Mercado Pago account statement CSV"
    )
    import_parser.add_argument("csv_path", type=Path, help="Path to the CSV file")
    return parser


def main() -> int:
    configure_logging()
    args = build_parser().parse_args()

    if args.command == "init-db":
        create_schema(get_engine())
        logging.info("Raw schema is ready")
        return 0

    if args.command == "import-account-statement":
        result = process(args.csv_path)
        logging.info(
            "Imported %s rows from %s into batch %s",
            result.row_count,
            result.source_filename,
            result.batch_id,
        )
        return 0

    if args.command == "transform":
        if not run_transform():
            logging.error("dbt transformation failed")
            return 1
        logging.info("Analytics models are ready")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
