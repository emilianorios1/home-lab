from datetime import datetime, timezone

import pytest

from home_lab.documents.storage import (
    resolve_document_path,
    store_message_metadata,
    store_pdf,
)


def test_stores_content_addressed_pdf_and_metadata(tmp_path) -> None:
    received_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    metadata = store_message_metadata(
        tmp_path,
        received_at=received_at,
        message_id="abc-123",
        message={"id": "abc-123"},
    )
    first = store_pdf(
        tmp_path,
        received_at=received_at,
        message_id="abc-123",
        content=b"%PDF-1.4 test",
    )
    second = store_pdf(
        tmp_path,
        received_at=received_at,
        message_id="abc-123",
        content=b"%PDF-1.4 test",
    )
    assert metadata == "2026/07/abc-123/message.json"
    assert first == second
    assert resolve_document_path(tmp_path, first.relative_path).exists()


def test_rejects_invalid_pdf_and_path_traversal(tmp_path) -> None:
    received_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="PDF signature"):
        store_pdf(
            tmp_path,
            received_at=received_at,
            message_id="abc",
            content=b"not a pdf",
        )
    with pytest.raises(ValueError, match="escapes"):
        resolve_document_path(tmp_path, "../secret")
