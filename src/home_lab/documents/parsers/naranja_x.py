"""Parser for Naranja X credit-card statements."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any


PARSER_NAME = "naranja_x_credit_card_statement"
PARSER_VERSION = "1.0.0"


class NaranjaXParseError(ValueError):
    """Raised when a Naranja X statement lacks a required field."""


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
        raise NaranjaXParseError(f"Missing required field: {field}")
    return match


def _date(value: str) -> date:
    return datetime.strptime(value.strip(), "%d/%m/%y").date()


def _decimal(value: str) -> Decimal:
    compact = re.sub(r"[^\d,.-]", "", value)
    if not compact:
        raise NaranjaXParseError(f"Invalid monetary amount: {value!r}")
    return Decimal(compact.replace(".", "").replace(",", "."))


def _kind(description: str) -> str:
    normalized = _ascii_upper(description)
    if "INTERES" in normalized:
        return "interest"
    if "PLAN TURBO" in normalized:
        return "fee"
    if (
        "PERCEPCION" in normalized
        or normalized.startswith("IVA ")
        or "IMPUESTO DE SELLOS" in normalized
    ):
        return "tax"
    return "purchase"


def _dated_transactions(text: str) -> list[dict[str, str | None]]:
    detail = _search(
        r"FECHA\s+TARJETA\s+CUPON\s+DETALLE\s+CUOTA/PLAN\s+\$\s+U\$S"
        r"(?P<body>[\s\S]*?)"
        r"^\s*Otros\s*$",
        text,
        field="transaction_detail",
    ).group("body")
    transactions: list[dict[str, str | None]] = []
    for raw_line in detail.splitlines():
        line_match = re.match(r"^(\d{2}/\d{2}/\d{2})\s+(.*)$", raw_line)
        if line_match is None:
            continue
        amount_match = re.search(r"([\d.]+,\d{2})\s*$", raw_line)
        if amount_match is None:
            raise NaranjaXParseError(
                f"Invalid credit-card transaction line: {raw_line!r}"
            )

        prefix = raw_line[len(line_match.group(1)) : amount_match.start()].strip()
        card_match = re.match(r"^(Naranja X|NX Visa|NX Mastercard)\s+", prefix)
        card = card_match.group(1) if card_match else None
        if card_match:
            prefix = prefix[card_match.end() :]

        coupon_match = re.match(r"^(\d{4,6})\s+", prefix)
        coupon = coupon_match.group(1) if coupon_match else None
        if coupon_match:
            prefix = prefix[coupon_match.end() :]

        installment_match = re.search(r"\s+(Deb\.Aut\.|\d{2})\s*$", prefix)
        installment = installment_match.group(1) if installment_match else None
        if installment_match:
            prefix = prefix[: installment_match.start()]
        description = prefix.strip()
        currency = "USD" if amount_match.start(1) >= 110 else "ARS"
        transactions.append(
            {
                "purchase_date": _date(line_match.group(1)).isoformat(),
                "card": card,
                "coupon": coupon,
                "description": description,
                "installment": installment,
                "currency": currency,
                "amount": str(_decimal(amount_match.group(1))),
                "kind": _kind(description),
            }
        )
    if not transactions:
        raise NaranjaXParseError("Missing required field: transactions")
    return transactions


def _other_charges(text: str, closing_date: date) -> list[dict[str, str | None]]:
    charges: list[dict[str, str | None]] = []
    patterns = (
        (
            "IVA Operaciones Identificadas",
            r"IVA\s+Operaciones\s+Identificadas\s+con\s+\*"
            r"\s*\n\s*\(Base\s+Imponible\s+\$[\d.,]+\)\s+([\d.,]+)",
        ),
        ("Impuesto de Sellos", r"Impuesto\s+de\s+Sellos\s+([\d.,]+)"),
    )
    for description, pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match is None:
            continue
        charges.append(
            {
                "purchase_date": closing_date.isoformat(),
                "card": None,
                "coupon": None,
                "description": description,
                "installment": None,
                "currency": "ARS",
                "amount": str(_decimal(match.group(1))),
                "kind": "tax",
            }
        )
    return charges


def supports(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", _ascii_upper(text))
    return (
        "CONSUMOS TARJETA DE CREDITO" in normalized
        and "TARJETA NARANJA S.A.U." in normalized
        and "TU TOTAL A PAGAR ES" in normalized
    )


def parse(text: str) -> dict[str, Any]:
    if not supports(text):
        raise NaranjaXParseError(
            "Document is not a supported Naranja X credit-card statement"
        )

    totals = _search(
        r"Tu\s+total\s+a\s+pagar\s+es\s*"
        r"\$\s*([\d.,]+)\s*\+\s*u\$s\s*([\d.,]+)"
        r"\s*y\s+vence\s+el\s+(\d{2}/\d{2}/\d{2})",
        text,
        field="total_and_due_date",
    )
    closing = _search(
        r"El\s+resumen\s+actual\s+cerr[oó]\s+el\s+(\d{2}/\d{2})",
        text,
        field="closing_date",
    )
    statement_number = _search(
        r"RESUMEN\s+N[º°]\s*(\d+)\s+EMITIDO\s+EL\s+\d{2}/\d{2}",
        text,
        field="statement_number",
    )
    minimum = re.search(
        r"LA\s+MENOR\s+ENTREGA\s*\n\s*\$\s*([\d.,]+)",
        text,
        flags=re.IGNORECASE,
    )
    financing = re.search(
        r"y\s+(\d+)\s+cuotas\s+de\s+\$\s*([\d.,]+)",
        text,
        flags=re.IGNORECASE,
    )

    due_date = _date(totals.group(3))
    closing_day, closing_month = map(int, closing.group(1).split("/"))
    closing_year = due_date.year - int(closing_month > due_date.month)
    closing_date = date(closing_year, closing_month, closing_day)
    transactions = _dated_transactions(text)
    transactions.extend(_other_charges(text, closing_date))

    concepts = [
        {"code": transaction["kind"], "amount": transaction["amount"]}
        for transaction in transactions
        if transaction["currency"] == "ARS"
    ]
    return {
        "schema_version": 1,
        "document_type": "credit_card_statement",
        "issuer": "Naranja X",
        "unit": None,
        "statement_number": statement_number.group(1),
        "period": closing_date.replace(day=1).isoformat(),
        "issue_date": closing_date.isoformat(),
        "closing_date": closing_date.isoformat(),
        "first_due_date": due_date.isoformat(),
        "first_due_amount": str(_decimal(totals.group(1))),
        "second_due_date": None,
        "second_due_amount": None,
        "due_date_kind": "single",
        "total_amount": str(_decimal(totals.group(1))),
        "foreign_total_amount": str(_decimal(totals.group(2))),
        "foreign_currency": "USD",
        "minimum_payment": (
            str(_decimal(minimum.group(1))) if minimum is not None else None
        ),
        "financing_installments": (
            int(financing.group(1)) if financing is not None else None
        ),
        "financing_installment_amount": (
            str(_decimal(financing.group(2))) if financing is not None else None
        ),
        "previous_balance": None,
        "collections": None,
        "concepts": concepts,
        "transactions": transactions,
    }
