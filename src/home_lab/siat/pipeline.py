"""Download new monthly TGI bills into the document pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from home_lab.config import (
    document_max_bytes,
    document_store_path,
    siat_tgi_account,
    siat_tgi_management_code,
)
from home_lab.database import create_schema, get_engine
from home_lab.documents.storage import store_message_metadata, store_pdf
from home_lab.gmail.repository import GmailRepository
from home_lab.siat.client import SiatTgiClient, TgiPeriod


@dataclass(frozen=True)
class TgiSyncResult:
    run_id: UUID
    periods_discovered: int
    bills_loaded: int


def _message_id(account: str, period: TgiPeriod) -> str:
    account_ref = sha256(account.encode("utf-8")).hexdigest()[:16]
    return f"siat-tgi-{account_ref}-{period.year}-{period.month:02d}"


def sync_tgi(client: SiatTgiClient | None = None) -> TgiSyncResult:
    account = siat_tgi_account()
    management_code = siat_tgi_management_code()
    selected_client = client or SiatTgiClient()
    engine = get_engine()
    create_schema(engine)
    repository = GmailRepository(engine)
    root = document_store_path()
    root.mkdir(parents=True, exist_ok=True)
    run_id = uuid4()
    account_hint = account[-4:] if len(account) >= 4 else "configured"
    repository.start_run(
        run_id,
        f"TGI account ending {account_hint}",
        source="siat_tgi",
    )

    discovered = 0
    loaded = 0
    try:
        periods = selected_client.selectable_periods(account, management_code)
        discovered = len(periods)
        for period in periods:
            message_id = _message_id(account, period)
            attachment_id = f"siat-tgi:{period.year}-{period.month:02d}"
            if repository.attachment_exists(message_id, attachment_id):
                continue

            bill = selected_client.download_bill(account, management_code, period)
            if len(bill.content) > document_max_bytes():
                raise ValueError(
                    f"TGI PDF exceeds DOCUMENT_MAX_BYTES: {len(bill.content)} bytes"
                )
            received_at = datetime.now(tz=timezone.utc)
            metadata_path = store_message_metadata(
                root,
                received_at=received_at,
                message_id=message_id,
                message={
                    "source": "siat_tgi",
                    "period": period.period.isoformat(),
                    "downloaded_at": received_at.isoformat(),
                },
            )
            stored = store_pdf(
                root,
                received_at=received_at,
                message_id=message_id,
                content=bill.content,
            )
            repository.save_message(
                {
                    "message_id": message_id,
                    "thread_id": None,
                    "history_id": None,
                    "internal_date": received_at,
                    "sender": "siat.rosario.gob.ar",
                    "subject": f"TGI {period.year}-{period.month:02d}",
                    "received_at": received_at,
                    "snippet": None,
                    "metadata_path": metadata_path,
                    "ingestion_run_id": run_id,
                }
            )
            loaded += repository.save_attachment(
                {
                    "message_id": message_id,
                    "attachment_id": attachment_id,
                    "original_filename": (
                        f"tgi-{period.year}-{period.month:02d}.pdf"
                    ),
                    "mime_type": "application/pdf",
                    "byte_size": stored.byte_size,
                    "sha256": stored.sha256,
                    "storage_path": stored.relative_path,
                }
            )
        repository.finish_run(run_id, discovered=discovered, loaded=loaded)
    except Exception as error:
        repository.finish_run(
            run_id,
            discovered=discovered,
            loaded=loaded,
            error=error,
        )
        raise
    return TgiSyncResult(run_id, discovered, loaded)
