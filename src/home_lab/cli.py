"""Command-line interface for local data imports."""

from __future__ import annotations

import argparse
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from home_lab.database import create_schema, get_engine
from home_lab.gmail.pipeline import (
    authorize_gmail,
    import_local_pdf,
    ingest_gmail,
    parse_pending_documents,
)
from home_lab.logging import configure_logging
from home_lab.mercadopago.importer import process
from home_lab.mercadopago.pipeline import (
    configure_account_reports,
    sync_account_activity,
)
from home_lab.siat.pipeline import sync_tgi


ARGENTINA_TIMEZONE = ZoneInfo("America/Argentina/Buenos_Aires")


def resolve_dbt_project_dir() -> Path:
    configured = os.getenv("HOME_LAB_DBT_PROJECT_DIR")
    if configured:
        project_dir = Path(configured).expanduser().resolve()
        if (project_dir / "dbt_project.yml").is_file():
            return project_dir
        raise FileNotFoundError(
            "HOME_LAB_DBT_PROJECT_DIR does not contain dbt_project.yml: "
            f"{project_dir}"
        )

    candidates = (
        Path(__file__).resolve().parents[2] / "dbt",
        Path.cwd() / "dbt",
    )
    for candidate in candidates:
        if (candidate / "dbt_project.yml").is_file():
            return candidate.resolve()

    raise FileNotFoundError(
        "Could not locate the dbt project; set HOME_LAB_DBT_PROJECT_DIR"
    )


def iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from error


def run_transform() -> bool:
    from dbt.cli.main import dbtRunner

    project_dir = resolve_dbt_project_dir()
    result = dbtRunner().invoke(
        [
            "build",
            "--project-dir",
            str(project_dir),
            "--profiles-dir",
            str(project_dir),
        ]
    )
    return result.success


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="House Ledger data tools")
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
        help="Import local PDFs, parse them and rebuild analytics",
    )
    local_parser.add_argument("pdf_paths", nargs="+", type=Path)

    import_parser = subparsers.add_parser(
        "import-account-statement", help="Import one Mercado Pago account statement CSV"
    )
    import_parser.add_argument("csv_path", type=Path, help="Path to the CSV file")
    mercadopago_parser = subparsers.add_parser(
        "sync-mercadopago",
        help="Download account activity from Mercado Pago's official API",
    )
    mercadopago_parser.add_argument(
        "--from",
        dest="start_date",
        type=iso_date,
        help="First date to import (YYYY-MM-DD); defaults to yesterday",
    )
    mercadopago_parser.add_argument(
        "--to",
        dest="end_date",
        type=iso_date,
        help="Last date to import, inclusive (YYYY-MM-DD); defaults to --from",
    )
    mercadopago_parser.add_argument(
        "--wait-seconds",
        type=float,
        default=300,
        help="Maximum time to wait for report generation (default: 300)",
    )
    subparsers.add_parser(
        "configure-mercadopago",
        help="Create/update the API report format required by House Ledger",
    )
    subparsers.add_parser(
        "sync-siat-tgi",
        help="Download new Rosario TGI bills, parse them and build Silver/Gold",
    )
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
        results = [import_local_pdf(path) for path in args.pdf_paths]
        parsed = parse_pending_documents(
            tuple(result.message_id for result in results)
        )
        if not run_transform():
            logging.error("Documents imported, but dbt transformation failed")
            return 1
        logging.info(
            "Local documents requested=%s loaded=%s; "
            "parsed=%s unsupported=%s failed=%s",
            len(results),
            sum(result.attachment_loaded for result in results),
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
            "Imported %s rows from %s into statement %s (stored at %s)",
            result.row_count,
            result.source_filename,
            result.statement_id,
            result.storage_path,
        )
        return 0

    if args.command == "sync-mercadopago":
        yesterday = datetime.now(ARGENTINA_TIMEZONE).date() - timedelta(days=1)
        start = args.start_date or yesterday
        end = args.end_date or start
        if end < start:
            logging.error("--to cannot be before --from")
            return 2
        if args.wait_seconds <= 0:
            logging.error("--wait-seconds must be positive")
            return 2
        result = sync_account_activity(
            start,
            end,
            wait_seconds=args.wait_seconds,
        )
        if not run_transform():
            logging.error("Mercado Pago imported, but dbt transformation failed")
            return 1
        logging.info(
            "Mercado Pago sync complete: task=%s report=%s rows=%s batch=%s",
            result.task_id,
            result.api_file_name,
            result.imported.row_count,
            result.imported.batch_id,
        )
        return 0

    if args.command == "configure-mercadopago":
        configuration = configure_account_reports()
        logging.info(
            "Mercado Pago report configuration ready: prefix=%s columns=%s",
            configuration.get("file_name_prefix"),
            len(configuration.get("columns", [])),
        )
        return 0

    if args.command == "sync-siat-tgi":
        ingestion = sync_tgi()
        parsed = parse_pending_documents()
        if not run_transform():
            logging.error("TGI bills imported, but dbt transformation failed")
            return 1
        logging.info(
            "SIAT TGI sync complete: periods=%s bills=%s parsed=%s "
            "unsupported=%s failed=%s",
            ingestion.periods_discovered,
            ingestion.bills_loaded,
            parsed.parsed,
            parsed.unsupported,
            parsed.failed,
        )
        return int(parsed.failed > 0)

    if args.command == "transform":
        if not run_transform():
            logging.error("dbt transformation failed")
            return 1
        logging.info("Analytics models are ready")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
