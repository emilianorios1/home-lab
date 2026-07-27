"""Gmail-to-Bronze ingestion and document parsing pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from core.config import (
    document_max_bytes,
    document_store_path,
    gmail_client_secret_path,
    gmail_query,
    gmail_token_path,
)
from core.database import create_schema, get_engine
from documents.parsers import zetace
from documents.pdf import extract_pdf
from documents.storage import resolve_document_path, store_message_metadata, store_pdf
from integrations.gmail import (
    attachment_bytes,
    authorize,
    build_service,
    get_message,
    list_message_ids,
    pdf_parts,
)


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
    milliseconds = int(message["internalDate"])
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)


def _part_attachment_id(part: dict[str, Any]) -> str:
    body = part.get("body", {})
    return body.get("attachmentId") or f"inline:{part.get('partId', 'root')}"


def _attachment_exists(engine: Engine, message_id: str, attachment_id: str) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM bronze.gmail_attachments
                        WHERE message_id = :message_id
                          AND attachment_id = :attachment_id
                    )
                    """
                ),
                {"message_id": message_id, "attachment_id": attachment_id},
            ).scalar_one()
        )


def ingest_gmail(query: str | None = None) -> GmailIngestionResult:
    selected_query = query or gmail_query()
    engine = get_engine()
    create_schema(engine)
    service = build_service(gmail_client_secret_path(), gmail_token_path())
    root = document_store_path()
    root.mkdir(parents=True, exist_ok=True)
    run_id = uuid4()

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO bronze.ingestion_runs (id, source, query, status)
                VALUES (:id, 'gmail', :query, 'running')
                """
            ),
            {"id": run_id, "query": selected_query},
        )

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

            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO bronze.gmail_messages (
                            message_id, thread_id, history_id, internal_date,
                            sender, subject, received_at, snippet, metadata_path,
                            ingestion_run_id
                        )
                        VALUES (
                            :message_id, :thread_id, :history_id, :internal_date,
                            :sender, :subject, :received_at, :snippet, :metadata_path,
                            :ingestion_run_id
                        )
                        ON CONFLICT (message_id) DO NOTHING
                        """
                    ),
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
                    },
                )

            for part in pdf_parts(message):
                attachment_id = _part_attachment_id(part)
                if _attachment_exists(engine, message_id, attachment_id):
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
                with engine.begin() as connection:
                    inserted = connection.execute(
                        text(
                            """
                            INSERT INTO bronze.gmail_attachments (
                                message_id, attachment_id, original_filename,
                                mime_type, byte_size, sha256, storage_path
                            )
                            VALUES (
                                :message_id, :attachment_id, :original_filename,
                                :mime_type, :byte_size, :sha256, :storage_path
                            )
                            ON CONFLICT (message_id, attachment_id) DO NOTHING
                            RETURNING id
                            """
                        ),
                        {
                            "message_id": message_id,
                            "attachment_id": attachment_id,
                            "original_filename": part.get("filename") or "attachment.pdf",
                            "mime_type": part.get("mimeType") or "application/pdf",
                            "byte_size": stored.byte_size,
                            "sha256": stored.sha256,
                            "storage_path": stored.relative_path,
                        },
                    ).scalar_one_or_none()
                loaded += int(inserted is not None)

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE bronze.ingestion_runs
                    SET status = 'succeeded',
                        completed_at = now(),
                        records_discovered = :discovered,
                        records_loaded = :loaded
                    WHERE id = :run_id
                    """
                ),
                {"run_id": run_id, "discovered": discovered, "loaded": loaded},
            )
    except Exception as error:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE bronze.ingestion_runs
                    SET status = 'failed',
                        completed_at = now(),
                        records_discovered = :discovered,
                        records_loaded = :loaded,
                        error_message = :error
                    WHERE id = :run_id
                    """
                ),
                {
                    "run_id": run_id,
                    "discovered": discovered,
                    "loaded": loaded,
                    "error": str(error)[:2000],
                },
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

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO bronze.gmail_messages (
                    message_id, internal_date, sender, subject, received_at,
                    metadata_path
                )
                VALUES (
                    :message_id, :received_at, 'local-import', :subject,
                    :received_at, :metadata_path
                )
                ON CONFLICT (message_id) DO NOTHING
                """
            ),
            {
                "message_id": message_id,
                "subject": path.name,
                "received_at": received_at,
                "metadata_path": metadata_path,
            },
        )
        inserted = connection.execute(
            text(
                """
                INSERT INTO bronze.gmail_attachments (
                    message_id, attachment_id, original_filename, mime_type,
                    byte_size, sha256, storage_path
                )
                VALUES (
                    :message_id, :attachment_id, :filename, 'application/pdf',
                    :byte_size, :sha256, :storage_path
                )
                ON CONFLICT (message_id, attachment_id) DO NOTHING
                RETURNING id
                """
            ),
            {
                "message_id": message_id,
                "attachment_id": f"local:{digest}",
                "filename": path.name,
                "byte_size": stored.byte_size,
                "sha256": stored.sha256,
                "storage_path": stored.relative_path,
            },
        ).scalar_one_or_none()
    return LocalImportResult(message_id, inserted is not None)


def _pending_attachments(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT a.id, a.storage_path
                FROM bronze.gmail_attachments a
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM bronze.document_parse_results p
                    WHERE p.attachment_id = a.id
                      AND p.parser_name = :parser_name
                      AND p.parser_version = :parser_version
                )
                ORDER BY a.id
                """
            ),
            {
                "parser_name": zetace.PARSER_NAME,
                "parser_version": zetace.PARSER_VERSION,
            },
        ).mappings()
        return [dict(row) for row in rows]


def parse_pending_documents() -> ParseResult:
    engine = get_engine()
    create_schema(engine)
    root = document_store_path()
    counters = {"parsed": 0, "unsupported": 0, "failed": 0}

    for attachment in _pending_attachments(engine):
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
            if not zetace.supports(extracted.text):
                status = "unsupported"
                error_message = "No registered parser supports this document"
            else:
                extracted_data = zetace.parse(extracted.text)
                status = "parsed"
        except Exception as error:
            error_message = str(error)[:2000]

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO bronze.document_parse_results (
                        attachment_id, parser_name, parser_version, status,
                        page_count, extracted_text, extracted_data, error_message
                    )
                    VALUES (
                        :attachment_id, :parser_name, :parser_version, :status,
                        :page_count, :extracted_text,
                        CAST(:extracted_data AS JSONB), :error_message
                    )
                    ON CONFLICT (attachment_id, parser_name, parser_version)
                    DO NOTHING
                    """
                ),
                {
                    "attachment_id": attachment["id"],
                    "parser_name": zetace.PARSER_NAME,
                    "parser_version": zetace.PARSER_VERSION,
                    "status": status,
                    "page_count": page_count,
                    "extracted_text": extracted_text,
                    "extracted_data": (
                        json.dumps(extracted_data, ensure_ascii=False)
                        if extracted_data is not None
                        else None
                    ),
                    "error_message": error_message,
                },
            )
        counters[status] += 1

    return ParseResult(**counters)
