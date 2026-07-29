"""Orchestrate Gmail ingestion and document parsing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from home_lab.config import (
    document_max_bytes,
    document_store_path,
    gmail_client_secret_path,
    gmail_query,
    gmail_token_path,
)
from home_lab.database import create_schema, get_engine
from home_lab.documents.parsers import registry
from home_lab.documents.pdf import extract_pdf
from home_lab.documents.storage import (
    resolve_document_path,
    store_message_metadata,
    store_pdf,
)
from home_lab.gmail.client import (
    attachment_bytes,
    authorize,
    build_service,
    get_message,
    linked_pdfs,
    list_message_ids,
    download_linked_pdf,
    pdf_parts,
)
from home_lab.gmail.repository import GmailRepository


@dataclass(frozen=True)
class GmailIngestionResult:
    run_id: UUID
    messages_discovered: int
    attachments_loaded: int


@dataclass(frozen=True)
class ParseResult:
    parsed: int
    unsupported: int
    failed: int


@dataclass(frozen=True)
class LocalImportResult:
    message_id: str
    attachment_loaded: bool


def authorize_gmail() -> None:
    authorize(gmail_client_secret_path(), gmail_token_path())


def _headers(message: dict[str, Any]) -> dict[str, str]:
    return {
        header["name"].lower(): header["value"]
        for header in message.get("payload", {}).get("headers", [])
    }


def _received_at(message: dict[str, Any], headers: dict[str, str]) -> datetime:
    header_date = headers.get("date")
    if header_date:
        try:
            value = parsedate_to_datetime(header_date)
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value
        except (TypeError, ValueError):
            pass
    return datetime.fromtimestamp(int(message["internalDate"]) / 1000, tz=timezone.utc)


def _part_attachment_id(part: dict[str, Any]) -> str:
    body = part.get("body", {})
    return body.get("attachmentId") or f"inline:{part.get('partId', 'root')}"


def ingest_gmail(query: str | None = None) -> GmailIngestionResult:
    selected_query = query or gmail_query()
    engine = get_engine()
    create_schema(engine)
    repository = GmailRepository(engine)
    service = build_service(gmail_client_secret_path(), gmail_token_path())
    root = document_store_path()
    root.mkdir(parents=True, exist_ok=True)
    run_id = uuid4()
    repository.start_run(run_id, selected_query)

    discovered = 0
    loaded = 0
    try:
        message_ids = list_message_ids(service, selected_query)
        discovered = len(message_ids)
        for message_id in message_ids:
            message = get_message(service, message_id)
            headers = _headers(message)
            received_at = _received_at(message, headers)
            metadata_path = store_message_metadata(
                root,
                received_at=received_at,
                message_id=message_id,
                message=message,
            )
            repository.save_message(
                {
                    "message_id": message_id,
                    "thread_id": message.get("threadId"),
                    "history_id": message.get("historyId"),
                    "internal_date": datetime.fromtimestamp(
                        int(message["internalDate"]) / 1000,
                        tz=timezone.utc,
                    ),
                    "sender": headers.get("from"),
                    "subject": headers.get("subject"),
                    "received_at": received_at,
                    "snippet": message.get("snippet"),
                    "metadata_path": metadata_path,
                    "ingestion_run_id": run_id,
                }
            )

            for part in pdf_parts(message):
                attachment_id = _part_attachment_id(part)
                if repository.attachment_exists(message_id, attachment_id):
                    continue

                declared_size = int(part.get("body", {}).get("size") or 0)
                if declared_size > document_max_bytes():
                    raise ValueError(
                        f"PDF attachment exceeds DOCUMENT_MAX_BYTES: {declared_size} bytes"
                    )
                content = attachment_bytes(service, message_id, part)
                if len(content) > document_max_bytes():
                    raise ValueError(
                        f"PDF attachment exceeds DOCUMENT_MAX_BYTES: {len(content)} bytes"
                    )
                stored = store_pdf(
                    root,
                    received_at=received_at,
                    message_id=message_id,
                    content=content,
                )
                loaded += repository.save_attachment(
                    {
                        "message_id": message_id,
                        "attachment_id": attachment_id,
                        "original_filename": part.get("filename") or "attachment.pdf",
                        "mime_type": part.get("mimeType") or "application/pdf",
                        "byte_size": stored.byte_size,
                        "sha256": stored.sha256,
                        "storage_path": stored.relative_path,
                    }
                )

            for linked in linked_pdfs(message):
                if repository.attachment_exists(message_id, linked.attachment_id):
                    continue
                content = download_linked_pdf(linked.url, document_max_bytes())
                stored = store_pdf(
                    root,
                    received_at=received_at,
                    message_id=message_id,
                    content=content,
                )
                loaded += repository.save_attachment(
                    {
                        "message_id": message_id,
                        "attachment_id": linked.attachment_id,
                        "original_filename": linked.filename,
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

    return GmailIngestionResult(run_id, discovered, loaded)


def import_local_pdf(path: Path) -> LocalImportResult:
    """Import a local PDF through the same Bronze contracts used by Gmail."""
    content = path.read_bytes()
    if len(content) > document_max_bytes():
        raise ValueError(
            f"PDF document exceeds DOCUMENT_MAX_BYTES: {len(content)} bytes"
        )
    digest = sha256(content).hexdigest()
    message_id = f"local-{digest[:32]}"
    received_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    engine = get_engine()
    create_schema(engine)
    repository = GmailRepository(engine)
    root = document_store_path()
    root.mkdir(parents=True, exist_ok=True)
    metadata_path = store_message_metadata(
        root,
        received_at=received_at,
        message_id=message_id,
        message={
            "source": "local",
            "message_id": message_id,
            "original_filename": path.name,
            "imported_at": datetime.now(tz=timezone.utc).isoformat(),
        },
    )
    stored = store_pdf(
        root,
        received_at=received_at,
        message_id=message_id,
        content=content,
    )
    repository.save_message(
        {
            "message_id": message_id,
            "thread_id": None,
            "history_id": None,
            "internal_date": received_at,
            "sender": "local-import",
            "subject": path.name,
            "received_at": received_at,
            "snippet": None,
            "metadata_path": metadata_path,
            "ingestion_run_id": None,
        }
    )
    loaded = repository.save_attachment(
        {
            "message_id": message_id,
            "attachment_id": f"local:{digest}",
            "original_filename": path.name,
            "mime_type": "application/pdf",
            "byte_size": stored.byte_size,
            "sha256": stored.sha256,
            "storage_path": stored.relative_path,
        }
    )
    return LocalImportResult(message_id, loaded)


def parse_pending_documents(
    message_ids: tuple[str, ...] = (),
) -> ParseResult:
    engine = get_engine()
    create_schema(engine)
    repository = GmailRepository(engine)
    root = document_store_path()
    counters = {"parsed": 0, "unsupported": 0, "failed": 0}
    attachments = repository.pending_attachments(
        parser_name=registry.PARSER_NAME,
        parser_version=registry.PARSER_VERSION,
        message_ids=message_ids,
    )

    for attachment in attachments:
        status = "failed"
        page_count: int | None = None
        extracted_text: str | None = None
        extracted_data: dict[str, Any] | None = None
        error_message: str | None = None
        try:
            path = resolve_document_path(root, attachment["storage_path"])
            extracted = extract_pdf(path)
            page_count = extracted.page_count
            extracted_text = extracted.text
            parsed = registry.parse(extracted.text)
            if parsed is not None:
                extracted_data = parsed.data
                status = "parsed"
            else:
                status = "unsupported"
                error_message = "No registered parser supports this document"
        except Exception as error:
            error_message = str(error)[:2000]
            if error_message == "PDF contains no extractable text; OCR is required":
                status = "unsupported"

        repository.save_parse_result(
            attachment_id=attachment["id"],
            parser_name=registry.PARSER_NAME,
            parser_version=registry.PARSER_VERSION,
            status=status,
            page_count=page_count,
            extracted_text=extracted_text,
            extracted_data=extracted_data,
            error_message=error_message,
        )
        counters[status] += 1

    return ParseResult(**counters)
