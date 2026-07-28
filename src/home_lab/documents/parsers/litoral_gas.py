"""Parser for Litoral Gas utility bills."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any


PARSER_NAME = "litoral_gas_bill"
PARSER_VERSION = "1.0.0"


class LitoralGasParseError(ValueError):
    """Raised when a Litoral Gas bill lacks a required field."""


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
        raise LitoralGasParseError(f"Missing required field: {field}")
    return match


def _date(value: str) -> date:
    return datetime.strptime(value, "%d/%m/%Y").date()


def _decimal(value: str) -> Decimal:
    compact = re.sub(r"[^\d,.-]", "", value)
    if not compact:
        raise LitoralGasParseError(f"Invalid monetary amount: {value!r}")
    if "," in compact:
        compact = compact.replace(".", "").replace(",", ".")
    return Decimal(compact)


def supports(text: str) -> bool:
    normalized = _ascii_upper(text)
    return (
        "LITORAL GAS S.A." in normalized
        and "LIQUIDACION DE SERVICIOS PUBLICOS" in normalized
        and "N° CLIENTE" in normalized
    )


def parse(text: str) -> dict[str, Any]:
    if not supports(text):
        raise LitoralGasParseError("Document is not a supported Litoral Gas bill")

    invoice = _search(r"\b(\d{4}-\d{8})\b", text, field="invoice_number")
    issue = _search(
        rf"{re.escape(invoice.group(1))}\s*\n\s*(\d{{2}}/\d{{2}}/\d{{4}})",
        text,
        field="issue_date",
    )
    customer = _search(
        r"N[°º]\s*CLIENTE\s+0*(\d+)",
        text,
        field="customer_number",
    )
    period = _search(
        r"Liquidaci[oó]n\s+\d+\s+de\s+\d+\s+Bimestre\s+(\d{2})/(20\d{2})",
        text,
        field="period",
    )
    due = _search(
        rf"{re.escape(invoice.group(1))}\s+"
        r"(\d{2}/\d{2}/\d{4})\s+([\d.,]+)",
        text,
        field="due_date",
    )
    address = re.search(
        r"^(.+?-\s*\(\d{4}\)\s+[A-ZÁÉÍÓÚÑ ]+?)\s+\d+\s+\d+\s+\d+",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    consumption = re.search(
        r"Liquidaci[oó]n\s+\d+\s+de\s+\d+\s+Bimestre\s+\d{2}/20\d{2}"
        r"\s+m3\s+asignados\s+a\s+la\s+presente\s+([\d.,]+)",
        text,
        flags=re.IGNORECASE,
    )
    amount = _decimal(due.group(2))
    return {
        "schema_version": 1,
        "document_type": "gas_bill",
        "issuer": "Litoral Gas S.A.",
        "unit": customer.group(1),
        "customer_number": customer.group(1),
        "invoice_number": invoice.group(1),
        "supply_address": address.group(1).strip() if address else None,
        "period": date(int(period.group(2)), int(period.group(1)), 1).isoformat(),
        "issue_date": _date(issue.group(1)).isoformat(),
        "first_due_date": _date(due.group(1)).isoformat(),
        "first_due_amount": str(amount),
        "second_due_date": None,
        "second_due_amount": None,
        "due_date_kind": "single",
        "total_amount": str(amount),
        "consumption_m3": (
            str(_decimal(consumption.group(1))) if consumption else None
        ),
        "previous_balance": None,
        "collections": None,
        "concepts": [],
    }
