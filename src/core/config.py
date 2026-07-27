"""Runtime configuration."""

from __future__ import annotations

import os

from dotenv import load_dotenv


def database_url() -> str:
    load_dotenv()
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL must be set in .env")
    return value
