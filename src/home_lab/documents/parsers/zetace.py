"""Parser for Zeta condominium expense statements."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any


PARSER_NAME = "zetace_expenses"
PARSER_VERSION = "1.0.0"

MONTHS = {
    "ENERO": 1,
    "FEBRERO": 2,
    "MARZO": 3,
    "ABRIL": 4,
    "MAYO": 5,
    "JUNIO": 6,
    "JULIO": 7,
    "AGOSTO": 8,
    "SEPTIEMBRE": 9,
    "SETIEMBRE": 9,
    "OCTUBRE": 10,
    "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}


class ZetaceParseError(ValueError):
    """Raised when a document resembles Zeta output but lacks required fields."""


def _ascii_upper(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(character for character in normalized if not unicodedata.combining(character)).upper()


def _search(pattern: str, text: str, *, field: str) -> re.Match[str]:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if match is None:
        raise ZetaceParseError(f"Missing required field: {field}")
    return match


def _date(value: str) -> date:
    compact = re.sub(r"\s+", "", value).replace("-", "/")
    return datetime.strptime(compact, "%d/%m/%Y").date()


def _decimal(value: str) -> Decimal:
    compact = re.sub(r"[^\d,.-]", "", value)
    if not compact:
        raise ZetaceParseError(f"Invalid monetary amount: {value!r}")

    comma = compact.rfind(",")
    dot = compact.rfind(".")
    if comma >= 0 and dot >= 0:
        decimal_separator = "," if comma > dot else "."
        thousands_separator = "." if decimal_separator == "," else ","
        compact = compact.replace(thousands_separator, "").replace(decimal_separator, ".")
    elif comma >= 0:
        compact = compact.replace(".", "").replace(",", ".")
    elif dot >= 0 and len(compact) - dot - 1 != 2:
        compact = compact.replace(".", "")
    return Decimal(compact)


def _amount_line(text: str, label: str) -> Decimal | None:
    match = re.search(
        rf"^\s*(?:{label}\s+\$?\s*(-?[\d.,]+)|\$?\s*(-?[\d.,]+)\s*{label})\s*$",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    return _decimal(match.group(1) or match.group(2)) if match else None


def _due(text: str, ordinal: str, *, field: str) -> tuple[date, Decimal]:
    date_pattern = r"(\d{1,2}\s*[-/]\s*\d{1,2}\s*[-/]\s*\d{4})"
    label = rf"{ordinal}\.?\s*Vencim\.?:"
    forward = re.search(
        rf"{label}\s*{date_pattern}\s*\$\s*([\d.,]*?[.,]\d{{2}})(?=\s|$|\d*CODIGO)",
        text,
        flags=re.IGNORECASE,
    )
    reverse = re.search(
        rf"{date_pattern}\s*\$\s*([\d.,]+?)\s*{label}",
        text,
        flags=re.IGNORECASE,
    )
    match = forward or reverse
    if match is None:
        raise ZetaceParseError(f"Missing required field: {field}")
    return _date(match.group(1)), _decimal(match.group(2))


def supports(text: str) -> bool:
    normalized = _ascii_upper(text)
    return "1ER.VENCIM" in normalized and "PERIODO:" in normalized and "EXPENSAS GENERALES" in normalized


def parse(text: str) -> dict[str, Any]:
    if not supports(text):
        raise ZetaceParseError("Document is not a supported Zeta expense statement")

    unit_match = re.search(r"\bU\.\s*([0-9]{2}-[0-9]{2})\b", text)
    if unit_match is None:
        unit_match = re.search(r"^\s*([0-9]{2}-[0-9]{2})\s*$", text, flags=re.MULTILINE)
    if unit_match is None:
        raise ZetaceParseError("Missing required field: unit")
    unit = unit_match.group(1)
    issue = _search(
        r"Fecha\s+de\s+Emisi[oó]n:\s*(\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{4})",
        text,
        field="issue_date",
    )
    period = _search(
        r"Per[ií]odo:\s*([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)\s*/\s*(\d{4})",
        text,
        field="period",
    )
    first_due_date, first_due_amount = _due(text, "1er", field="first_due")
    second_due_date, second_due_amount = _due(text, "2do", field="second_due")

    month_name = _ascii_upper(period.group(1))
    if month_name not in MONTHS:
        raise ZetaceParseError(f"Unknown period month: {period.group(1)}")
    period_date = date(int(period.group(2)), MONTHS[month_name], 1)

    issuer_match = re.search(
        r"^\s*(.+?)\s*Consorcio:\s*$",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if issuer_match is None:
        issuer_match = re.search(
            r"Consorcio:[ \t]*([^\r\n]+)",
            text,
            flags=re.IGNORECASE,
        )
    issuer = issuer_match.group(1).strip() if issuer_match else "Zeta"

    concepts: list[dict[str, str]] = []
    for code, label in (
        ("general_expenses", r"EXPENSAS\s+GENERALES"),
        ("extraordinary_expenses", r"EXPENSAS\s+EXTRAORDINARIAS"),
    ):
        amount = _amount_line(text, label)
        if amount is not None:
            concepts.append({"code": code, "amount": str(amount)})

    return {
        "schema_version": 1,
        "document_type": "condominium_expense",
        "issuer": issuer,
        "unit": unit,
        "period": period_date.isoformat(),
        "issue_date": _date(issue.group(1)).isoformat(),
        "first_due_date": first_due_date.isoformat(),
        "first_due_amount": str(first_due_amount),
        "second_due_date": second_due_date.isoformat(),
        "second_due_amount": str(second_due_amount),
        "previous_balance": (
            str(value) if (value := _amount_line(text, r"SALDO\s+ANTERIOR")) is not None else None
        ),
        "collections": (
            str(value) if (value := _amount_line(text, r"COBRANZAS")) is not None else None
        ),
        "concepts": concepts,
    }
