"""Runtime configuration."""

from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
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


def financial_statement_store_path() -> Path:
    return _path_setting(
        "FINANCIAL_STATEMENT_STORE_PATH",
        "data/bronze/financial-statements",
    )


def gmail_client_secret_path() -> Path:
    return _path_setting("GMAIL_CLIENT_SECRET_PATH", "secrets/gmail_client_secret.json")


def gmail_token_path() -> Path:
    return _path_setting("GMAIL_TOKEN_PATH", "secrets/gmail_token.json")


def gmail_query() -> str:
    load_dotenv()
    return os.getenv(
        "GMAIL_QUERY",
        "{from:no_reply@zetace.com.ar "
        "from:oficinavirtual@epe.santafe.gov.ar "
        "from:facturadigital@aguassantafesinas.com "
        "from:factura@digital.litoralgas.com.ar "
        "from:avisos@info.naranjax.com} newer_than:45d",
    )


def _required_setting(name: str) -> str:
    load_dotenv()
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} must be set in .env")
    return value


def siat_tgi_account() -> str:
    return _required_setting("SIAT_TGI_ACCOUNT")


def siat_tgi_management_code() -> str:
    return _required_setting("SIAT_TGI_MANAGEMENT_CODE")


def mercadopago_access_token() -> str:
    return _required_setting("MERCADOPAGO_ACCESS_TOKEN")


def document_max_bytes() -> int:
    load_dotenv()
    value = int(os.getenv("DOCUMENT_MAX_BYTES", str(20 * 1024 * 1024)))
    if value <= 0:
        raise ValueError("DOCUMENT_MAX_BYTES must be positive")
    return value


def monotributo_annual_limit_ars() -> Decimal | None:
    load_dotenv()
    raw = os.getenv("MONOTRIBUTO_ANNUAL_LIMIT_ARS", "").strip()
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation as error:
        raise ValueError(
            "MONOTRIBUTO_ANNUAL_LIMIT_ARS must be a decimal number"
        ) from error
    if value <= 0:
        raise ValueError("MONOTRIBUTO_ANNUAL_LIMIT_ARS must be positive")
    return value
