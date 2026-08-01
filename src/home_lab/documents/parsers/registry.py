"""Dispatch PDF text to the registered financial-document parsers."""

from __future__ import annotations

from typing import Any

from home_lab.documents.parsers import (
    arca_factura_e,
    assa,
    epe,
    litoral_gas,
    naranja_x,
    tgi,
    zetace,
)


PARSER_NAME = "financial_document_router"
PARSER_VERSION = "1.6.0"


PARSERS = (
    arca_factura_e,
    zetace,
    epe,
    assa,
    litoral_gas,
    tgi,
    naranja_x,
)


def parse(text: str) -> dict[str, Any] | None:
    for parser in PARSERS:
        if parser.supports(text):
            data = parser.parse(text)
            data["source_parser"] = parser.PARSER_NAME
            data["source_parser_version"] = parser.PARSER_VERSION
            return data
    return None
