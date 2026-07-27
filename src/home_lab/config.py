"""Runtime configuration."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def database_url() -> str:
    load_dotenv()
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL must be set in .env")
    return value


def _path_setting(name: str, default: str) -> Path:
    load_dotenv()
    return Path(os.getenv(name, default)).expanduser().resolve()


def document_store_path() -> Path:
    return _path_setting("DOCUMENT_STORE_PATH", "data/bronze/gmail")


def gmail_client_secret_path() -> Path:
    return _path_setting("GMAIL_CLIENT_SECRET_PATH", "secrets/gmail_client_secret.json")


def gmail_token_path() -> Path:
    return _path_setting("GMAIL_TOKEN_PATH", "secrets/gmail_token.json")


def gmail_query() -> str:
    load_dotenv()
    return os.getenv(
        "GMAIL_QUERY",
        "{from:no_reply@zetace.com.ar from:oficinavirtual@epe.santafe.gov.ar} newer_than:30d",
    )


def document_max_bytes() -> int:
    load_dotenv()
    value = int(os.getenv("DOCUMENT_MAX_BYTES", str(20 * 1024 * 1024)))
    if value <= 0:
        raise ValueError("DOCUMENT_MAX_BYTES must be positive")
    return value
