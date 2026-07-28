"""Dispatch PDF text to the registered financial-document parsers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from home_lab.documents.parsers import assa, epe, litoral_gas, tgi, zetace


PARSER_NAME = "financial_document_router"
PARSER_VERSION = "1.2.0"


class ParserModule(Protocol):
    PARSER_NAME: str
    PARSER_VERSION: str

    def supports(self, text: str) -> bool: ...

    def parse(self, text: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ParsedDocument:
    data: dict[str, Any]
    source_parser: str
    source_parser_version: str


PARSERS: tuple[ParserModule, ...] = (zetace, epe, assa, litoral_gas, tgi)


def parse(text: str) -> ParsedDocument | None:
    for parser in PARSERS:
        if parser.supports(text):
            data = parser.parse(text)
            data["source_parser"] = parser.PARSER_NAME
            data["source_parser_version"] = parser.PARSER_VERSION
            return ParsedDocument(data, parser.PARSER_NAME, parser.PARSER_VERSION)
    return None
