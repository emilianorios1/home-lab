"""Command-line interface for local data imports."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from core.database import create_schema, get_engine
from core.logging import configure_logging
from pipelines.mercadopago_settlements import import_csv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="home-lab data tools")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="Create the raw PostgreSQL schema")

    import_parser = subparsers.add_parser(
        "import-mercadopago", help="Import one Mercado Pago settlement CSV"
    )
    import_parser.add_argument("csv_path", type=Path, help="Path to the CSV file")
    return parser


def main() -> int:
    configure_logging()
    args = build_parser().parse_args()
    engine = get_engine()

    if args.command == "init-db":
        create_schema(engine)
        logging.info("Raw schema is ready")
        return 0

    if args.command == "import-mercadopago":
        result = import_csv(engine, args.csv_path)
        logging.info(
            "Imported %s rows from %s into batch %s",
            result.row_count,
            result.source_filename,
            result.batch_id,
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
