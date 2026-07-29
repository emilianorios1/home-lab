"""Content-addressed storage for immutable Mercado Pago statements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class StoredStatement:
    relative_path: str
    sha256: str
    byte_size: int


def store_statement(
    root: Path,
    *,
    provider: str,
    period_start: date,
    content: bytes,
    suffix: str,
) -> StoredStatement:
    safe_provider = "".join(
        character
        for character in provider.lower()
        if character.isalnum() or character in "-_"
    )
    if not safe_provider:
        raise ValueError("Statement provider cannot be empty")
    if not suffix.startswith(".") or not suffix[1:].isalnum():
        raise ValueError("Statement suffix must be a simple file extension")

    digest = sha256(content).hexdigest()
    directory = root / safe_provider / f"{period_start:%Y}" / f"{period_start:%m}"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{digest}{suffix.lower()}"
    if not destination.exists():
        temporary = destination.with_suffix(f"{suffix.lower()}.tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)

    return StoredStatement(
        relative_path=destination.relative_to(root).as_posix(),
        sha256=digest,
        byte_size=len(content),
    )
