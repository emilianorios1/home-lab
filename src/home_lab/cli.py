"""Command-line interface for local data imports."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from home_lab.database import create_schema, get_engine
from home_lab.gmail.pipeline import (
    authorize_gmail,
    import_local_pdf,
    ingest_gmail,
    parse_pending_documents,
)
from home_lab.logging import configure_logging
from home_lab.mercadopago.importer import process


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
    subparsers.add_parser("init-db", help="Create Bronze/Silver/Gold PostgreSQL schemas")
    subparsers.add_parser("transform", help="Build and test the dbt analytics models")
    subparsers.add_parser(
        "gmail-auth",
        help="Authorize read-only access to Gmail in a browser",
    )
    gmail_parser = subparsers.add_parser(
        "ingest-gmail",
        help="Download new Gmail PDF attachments into Bronze",
    )
    gmail_parser.add_argument(
        "--query",
        help="Override the configured Gmail search query",
    )
    subparsers.add_parser(
        "parse-documents",
        help="Parse pending Bronze PDF documents",
    )
    subparsers.add_parser(
        "sync-gmail",
        help="Ingest Gmail, parse documents and build Silver/Gold",
    )
    local_parser = subparsers.add_parser(
        "import-document",
        help="Import a local PDF using the document pipeline",
    )
    local_parser.add_argument("pdf_path", type=Path)

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

    if args.command == "gmail-auth":
        authorize_gmail()
        logging.info("Gmail read-only authorization saved")
        return 0

    if args.command == "ingest-gmail":
        result = ingest_gmail(args.query)
        logging.info(
            "Gmail run %s discovered %s messages and loaded %s attachments",
            result.run_id,
            result.messages_discovered,
            result.attachments_loaded,
        )
        return 0

    if args.command == "parse-documents":
        result = parse_pending_documents()
        logging.info(
            "Documents parsed=%s unsupported=%s failed=%s",
            result.parsed,
            result.unsupported,
            result.failed,
        )
        return int(result.failed > 0)

    if args.command == "import-document":
        result = import_local_pdf(args.pdf_path)
        parsed = parse_pending_documents()
        logging.info(
            "Local document %s loaded=%s; parsed=%s unsupported=%s failed=%s",
            result.message_id,
            result.attachment_loaded,
            parsed.parsed,
            parsed.unsupported,
            parsed.failed,
        )
        return int(parsed.failed > 0)

    if args.command == "sync-gmail":
        ingestion = ingest_gmail()
        parsed = parse_pending_documents()
        if not run_transform():
            logging.error("dbt transformation failed")
            return 1
        logging.info(
            "Gmail sync complete: messages=%s attachments=%s parsed=%s unsupported=%s failed=%s",
            ingestion.messages_discovered,
            ingestion.attachments_loaded,
            parsed.parsed,
            parsed.unsupported,
            parsed.failed,
        )
        return int(parsed.failed > 0)

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
