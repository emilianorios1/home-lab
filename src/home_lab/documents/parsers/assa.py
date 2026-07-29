"""Parser for Aguas Santafesinas (ASSA) water bills."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any


PARSER_NAME = "assa_water_bill"
PARSER_VERSION = "1.2.0"


class AssaParseError(ValueError):
    """Raised when an ASSA bill lacks a required field."""


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
        raise AssaParseError(f"Missing required field: {field}")
    return match


def _date(value: str) -> date:
    return datetime.strptime(value, "%d/%m/%Y").date()


def _decimal(value: str) -> Decimal:
    compact = re.sub(r"[^\d,.-]", "", value)
    if not compact:
        raise AssaParseError(f"Invalid monetary amount: {value!r}")
    return Decimal(compact.replace(".", "").replace(",", "."))


def supports(text: str) -> bool:
    normalized = _ascii_upper(text)
    return (
        "PUNTO SUMINISTRO:" in normalized
        and "SERVICIO PRESTADO" in normalized
        and "AGUA" in normalized
        and "CLOACA" in normalized
    )


def parse(text: str) -> dict[str, Any]:
    if not supports(text):
        raise AssaParseError("Document is not a supported ASSA water bill")

    customer = _search(
        r"Punto\s+Suministro:\s*0*(\d+)",
        text,
        field="customer_number",
    )
    period = _search(r"\b(20\d{2})/(\d{2})\b", text, field="period")
    issue = _search(
        r"^\s*(\d{2}/\d{2}/\d{4})\s*$\s*^CONCEPTO\b",
        text,
        field="issue_date",
    )
    total = _search(
        r"^\s*\$\*+([\d.,]+)\s*$\s*^ULTIMOS\s+6\s+PERIODOS",
        text,
        field="total_amount",
    )
    due_matches = list(
        re.finditer(
            r"^\s*(\d{2}/\d{2}/\d{4})\s*$\s*"
            r"^\s*\$\*+([\d.,]+)\s*$\s*"
            r"^PAGO\s+HASTA\s+EL\s*$",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    )
    if len(due_matches) < 2:
        raise AssaParseError("Missing required field: installment_due_dates")

    address = re.search(
        r"^Dir\.Inmueble:\s*([^\r\n]+)",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    volume = re.search(
        r"VOL\.FACTURADO\s*\n\s*([\d.,]+)\s*m3",
        text,
        flags=re.IGNORECASE,
    )
    first_due, second_due = due_matches[:2]
    return {
        "schema_version": 1,
        "document_type": "water_bill",
        "issuer": "Aguas Santafesinas S.A.",
        "unit": customer.group(1),
        "customer_number": customer.group(1),
        "supply_address": address.group(1).strip() if address else None,
        "period": date(int(period.group(1)), int(period.group(2)), 1).isoformat(),
        "issue_date": _date(issue.group(1)).isoformat(),
        "first_due_date": _date(first_due.group(1)).isoformat(),
        "first_due_amount": str(_decimal(first_due.group(2))),
        "second_due_date": _date(second_due.group(1)).isoformat(),
        "second_due_amount": str(_decimal(second_due.group(2))),
        "due_date_kind": "installment",
        "total_amount": str(_decimal(total.group(1))),
        "consumption_m3": str(_decimal(volume.group(1))) if volume else None,
        "previous_balance": None,
        "collections": None,
        "concepts": [],
    }
