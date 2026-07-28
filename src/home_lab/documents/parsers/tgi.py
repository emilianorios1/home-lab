"""Parser for Rosario TGI monthly bills."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any


PARSER_NAME = "rosario_tgi_bill"
PARSER_VERSION = "1.0.0"


class TgiParseError(ValueError):
    """Raised when a TGI bill lacks a required field."""


def _ascii_upper(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    ).upper()


def _search(pattern: str, text: str, *, field: str) -> re.Match[str]:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if match is None:
        raise TgiParseError(f"Missing required field: {field}")
    return match


def _date(value: str) -> date:
    return datetime.strptime(value.strip(), "%d/%m/%Y").date()


def _decimal(value: str) -> Decimal:
    compact = re.sub(r"[^\d,.-]", "", value)
    if not compact:
        raise TgiParseError(f"Invalid monetary amount: {value!r}")
    if "," in compact:
        compact = compact.replace(".", "").replace(",", ".")
    return Decimal(compact)


def supports(text: str) -> bool:
    normalized = _ascii_upper(text)
    return (
        "TGI - TASA GENERAL DE INMUEBLES" in normalized
        and "COD. GESTION PERSONAL:" in normalized
        and "VENCIMIENTO ORIGINAL" in normalized
    )


def parse(text: str) -> dict[str, Any]:
    if not supports(text):
        raise TgiParseError("Document is not a Rosario TGI bill")

    account = _search(r"Cuenta:\s*0*(\d+)", text, field="account")
    period = _search(
        r"^\s*(\d{1,2})/(\d{4})\s+"
        r"(\d{2}/\d{2}/\d{4})\s+"
        r"([\d.,]+)\s+[\d.,]+\s+([\d.,]+)\s*$",
        text,
        field="period_and_amount",
    )
    issue = re.search(r"^\s*(\d{2}/\d{2}/\d{4})\s*$", text, flags=re.MULTILINE)
    location = re.search(r"Ubicaci[oó]n:\s*([^\r\n]+)", text, flags=re.IGNORECASE)
    month = int(period.group(1))
    year = int(period.group(2))
    amount = _decimal(period.group(5))

    return {
        "schema_version": 1,
        "document_type": "property_tax_bill",
        "issuer": "Municipalidad de Rosario",
        "unit": account.group(1),
        "account_number": account.group(1),
        "supply_address": location.group(1).strip() if location else None,
        "period": date(year, month, 1).isoformat(),
        "issue_date": _date(issue.group(1)).isoformat() if issue else None,
        "first_due_date": _date(period.group(3)).isoformat(),
        "first_due_amount": str(amount),
        "second_due_date": None,
        "second_due_amount": None,
        "due_date_kind": "single",
        "total_amount": str(amount),
        "previous_balance": None,
        "collections": None,
        "concepts": [],
    }
