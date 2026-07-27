"""Parser for EPE Santa Fe electricity bills."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any


PARSER_NAME = "epe_electricity_bill"
PARSER_VERSION = "1.0.0"


class EpeParseError(ValueError):
    """Raised when an EPE bill lacks a required field."""


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
        raise EpeParseError(f"Missing required field: {field}")
    return match


def _date(value: str) -> date:
    return datetime.strptime(value.strip(), "%d/%m/%Y").date()


def _decimal(value: str) -> Decimal:
    compact = re.sub(r"[^\d,.-]", "", value)
    if not compact:
        raise EpeParseError(f"Invalid monetary amount: {value!r}")
    if "," in compact:
        compact = compact.replace(".", "").replace(",", ".")
    elif compact.count(".") > 1 or (
        "." in compact and len(compact) - compact.rfind(".") - 1 != 2
    ):
        compact = compact.replace(".", "")
    return Decimal(compact)


def supports(text: str) -> bool:
    normalized = _ascii_upper(text)
    return (
        "EMPRESA PROVINCIAL DE LA ENERGIA DE SANTA FE" in normalized
        and "NUMERO DE CLIENTE:" in normalized
        and "DETALLE DE FACTURACION" in normalized
    )


def parse(text: str) -> dict[str, Any]:
    if not supports(text):
        raise EpeParseError("Document is not a supported EPE electricity bill")

    customer = _search(
        r"N[uú]mero\s+de\s+Cliente:\s*0*(\d+)",
        text,
        field="customer_number",
    )
    issue = _search(
        r"FECHA\s+DE\s+EMISI[OÓ]N:\s*(\d{2}/\d{2}/\d{4})",
        text,
        field="issue_date",
    )
    first_due = _search(
        r"Cuota\s+1\s+(\d{2}/\d{2}/\d{4})\s+\$\**([\d.,]+)",
        text,
        field="first_due",
    )
    second_due = _search(
        r"Cuota\s+2\s+(\d{2}/\d{2}/\d{4})\s+\$\**([\d.,]+)",
        text,
        field="second_due",
    )
    total = _search(
        r"^\s*TOTAL\s+\$\**([\d.,]+)\s*$",
        text,
        field="total_amount",
    )
    address = re.search(
        r"Direcci[oó]n\s+del\s+Suministro\s*\n\s*([^\r\n]+)",
        text,
        flags=re.IGNORECASE,
    )
    consumption = re.search(
        r"Consumo\s+Total:\s*([\d.,]+)\s*kWh",
        text,
        flags=re.IGNORECASE,
    )

    issue_date = _date(issue.group(1))
    return {
        "schema_version": 1,
        "document_type": "electricity_bill",
        "issuer": "Empresa Provincial de la Energía de Santa Fe",
        "unit": customer.group(1),
        "customer_number": customer.group(1),
        "supply_address": address.group(1).strip() if address else None,
        "period": issue_date.replace(day=1).isoformat(),
        "issue_date": issue_date.isoformat(),
        "first_due_date": _date(first_due.group(1)).isoformat(),
        "first_due_amount": str(_decimal(first_due.group(2))),
        "second_due_date": _date(second_due.group(1)).isoformat(),
        "second_due_amount": str(_decimal(second_due.group(2))),
        "due_date_kind": "installment",
        "total_amount": str(_decimal(total.group(1))),
        "consumption_kwh": (
            str(_decimal(consumption.group(1))) if consumption else None
        ),
        "previous_balance": None,
        "collections": None,
        "concepts": [],
    }
