"""Account activity ingestion from Mercado Pago's official API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from home_lab.config import mercadopago_access_token
from home_lab.mercadopago.client import MercadoPagoClient
from home_lab.mercadopago.importer import ImportResult, process_api_report


@dataclass(frozen=True)
class SyncResult:
    task_id: int
    api_file_name: str
    imported: ImportResult


def configure_account_reports(
    client: MercadoPagoClient | None = None,
) -> dict[str, object]:
    client = client or MercadoPagoClient(mercadopago_access_token())
    return client.configure_report()


def sync_account_activity(
    start: date,
    end: date,
    *,
    wait_seconds: float = 300,
    client: MercadoPagoClient | None = None,
) -> SyncResult:
    client = client or MercadoPagoClient(mercadopago_access_token())
    report = client.generate_report(start, end, wait_seconds=wait_seconds)
    # API filenames contain their generation timestamp. A period-based local name
    # makes retries idempotent by replacing the previous batch for that interval.
    source_filename = f"mercadopago-api-{start.isoformat()}-{end.isoformat()}.csv"
    imported = process_api_report(report.content, source_filename)
    return SyncResult(report.task_id, report.file_name, imported)
