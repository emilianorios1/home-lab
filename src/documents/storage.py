"""Content-addressed storage for immutable Gmail artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StoredAttachment:
    relative_path: str
    sha256: str
    byte_size: int


def _message_directory(root: Path, received_at: datetime, message_id: str) -> Path:
    safe_message_id = "".join(character for character in message_id if character.isalnum() or character in "-_")
    if not safe_message_id:
        raise ValueError("Gmail message id cannot be empty")
    return root / f"{received_at:%Y}" / f"{received_at:%m}" / safe_message_id


def store_message_metadata(
    root: Path,
    *,
    received_at: datetime,
    message_id: str,
    message: dict[str, Any],
) -> str:
    directory = _message_directory(root, received_at, message_id)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "message.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(message, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination.relative_to(root).as_posix()


def store_pdf(
    root: Path,
    *,
    received_at: datetime,
    message_id: str,
    content: bytes,
) -> StoredAttachment:
    if not content.startswith(b"%PDF-"):
        raise ValueError("Attachment does not have a valid PDF signature")

    digest = sha256(content).hexdigest()
    directory = _message_directory(root, received_at, message_id)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{digest}.pdf"
    if not destination.exists():
        temporary = destination.with_suffix(".pdf.tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)
    return StoredAttachment(
        relative_path=destination.relative_to(root).as_posix(),
        sha256=digest,
        byte_size=len(content),
    )


def resolve_document_path(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    resolved_root = root.resolve()
    if not candidate.is_relative_to(resolved_root):
        raise ValueError("Document path escapes the configured storage root")
    return candidate
