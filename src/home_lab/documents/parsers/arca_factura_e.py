"""Parser for ARCA export-service invoices (Factura E)."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any


PARSER_NAME = "arca_export_service_invoice"
PARSER_VERSION = "1.0.0"


class ArcaFacturaEParseError(ValueError):
    """Raised when an ARCA Factura E lacks a required fiscal field."""


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
        raise ArcaFacturaEParseError(f"Missing required field: {field}")
    return match


def _date(value: str) -> date:
    return datetime.strptime(value.strip(), "%d/%m/%Y").date()


def _decimal(value: str) -> Decimal:
    compact = re.sub(r"[^\d,.-]", "", value)
    if not compact:
        raise ArcaFacturaEParseError("Invalid monetary amount")
    comma = compact.rfind(",")
    dot = compact.rfind(".")
    if comma >= 0 and dot >= 0:
        decimal_separator = "," if comma > dot else "."
        thousands_separator = "." if decimal_separator == "," else ","
        compact = compact.replace(thousands_separator, "").replace(
            decimal_separator,
            ".",
        )
    elif comma >= 0:
        compact = compact.replace(".", "").replace(",", ".")
    return Decimal(compact)


def supports(text: str) -> bool:
    normalized = _ascii_upper(text)
    return (
        "FACTURA DE EXPORTACION" in normalized
        and "COD. 19" in normalized
        and "FECHA DE VTO. DE CAE" in normalized
        and "USD - DOLAR ESTADOUNIDENSE" in normalized
    )


def parse(text: str) -> dict[str, Any]:
    if not supports(text):
        raise ArcaFacturaEParseError(
            "Document is not a supported ARCA Factura E"
        )

    dates = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", text)
    if not dates:
        raise ArcaFacturaEParseError("Missing required field: issue_date")
    issue_date = _date(dates[0])
    invoice = _search(
        r"Nro:\s*(\d{5})-(\d{8})",
        text,
        field="invoice_number",
    )
    payment = _search(
        r"(\d{2}/\d{2}/\d{4})\s*Fecha\s+de\s+Pago:",
        text,
        field="payment_date",
    )
    total = _search(
        r"([\d.,]+)\s*Importe\s+Total:",
        text,
        field="foreign_total_amount",
    )
    exchange_rate = _search(
        r"Tipo\s+de\s+Cambio:\s*([\d.,]+)",
        text,
        field="exchange_rate",
    )
    cae = _search(
        r"CAE[^\n:]*:\s*"
        r"Fecha\s+de\s+Vto\.\s+de\s+CAE:\s*"
        r"[\s\S]{0,500}?(\d{2}/\d{2}/\d{4})\s*(\d{14})",
        text,
        field="cae",
    )

    return {
        "schema_version": 1,
        "document_type": "export_service_invoice",
        "issuer": "ARCA",
        "period": issue_date.replace(day=1).isoformat(),
        "issue_date": issue_date.isoformat(),
        "payment_date": _date(payment.group(1)).isoformat(),
        "point_of_sale": invoice.group(1),
        "invoice_number": invoice.group(2),
        "foreign_currency": "USD",
        "foreign_total_amount": str(_decimal(total.group(1))),
        "exchange_rate": str(_decimal(exchange_rate.group(1))),
        "cae": cae.group(2),
        "cae_due_date": _date(cae.group(1)).isoformat(),
    }
