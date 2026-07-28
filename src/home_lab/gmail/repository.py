"""PostgreSQL persistence for Gmail ingestion and document parsing."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text


class GmailRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def start_run(self, run_id: UUID, query: str, *, source: str = "gmail") -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO bronze.ingestion_runs (id, source, query, status)
                    VALUES (:id, :source, :query, 'running')
                    """
                ),
                {"id": run_id, "source": source, "query": query},
            )

    def finish_run(
        self,
        run_id: UUID,
        *,
        discovered: int,
        loaded: int,
        error: Exception | None = None,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE bronze.ingestion_runs
                    SET status = :status,
                        completed_at = now(),
                        records_discovered = :discovered,
                        records_loaded = :loaded,
                        error_message = :error_message
                    WHERE id = :run_id
                    """
                ),
                {
                    "run_id": run_id,
                    "status": "failed" if error else "succeeded",
                    "discovered": discovered,
                    "loaded": loaded,
                    "error_message": str(error)[:2000] if error else None,
                },
            )

    def save_message(self, values: Mapping[str, Any]) -> None:
        with self.engine.begin() as connection:
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
                dict(values),
            )

    def attachment_exists(self, message_id: str, attachment_id: str) -> bool:
        with self.engine.connect() as connection:
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

    def save_attachment(self, values: Mapping[str, Any]) -> bool:
        with self.engine.begin() as connection:
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
                dict(values),
            ).scalar_one_or_none()
        return inserted is not None

    def pending_attachments(
        self,
        *,
        parser_name: str,
        parser_version: str,
    ) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
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
                    "parser_name": parser_name,
                    "parser_version": parser_version,
                },
            ).mappings()
            return [dict(row) for row in rows]

    def save_parse_result(
        self,
        *,
        attachment_id: int,
        parser_name: str,
        parser_version: str,
        status: str,
        page_count: int | None,
        extracted_text: str | None,
        extracted_data: dict[str, Any] | None,
        error_message: str | None,
    ) -> None:
        with self.engine.begin() as connection:
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
                    "attachment_id": attachment_id,
                    "parser_name": parser_name,
                    "parser_version": parser_version,
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
