from decimal import Decimal

import pytest

from home_lab.documents.parsers.assa import AssaParseError, parse, supports


SAMPLE_TEXT = """
Dir.Inmueble: MONTEVIDEO 1213 PISO 004 DEPTO 0002
2026/04
SERVICIO PRESTADO : AGUA , CLOACA Y PLUVIAL
VOL.FACTURADO
25,76m3
16/06/2026
CONCEPTO CANTIDAD TARIFA TOTAL
CARGO FIJO $16.824,92
$***69.630,84
ULTIMOS 6 PERIODOS
Punto Suministro: 00380921
13/07/2026
$***34.815,42
PAGO HASTA EL
28/07/2026
13/08/2026
$***34.815,42
PAGO HASTA EL
28/08/2026
"""


def test_parses_assa_water_bill() -> None:
    assert supports(SAMPLE_TEXT)
    result = parse(SAMPLE_TEXT)
    assert result["document_type"] == "water_bill"
    assert result["customer_number"] == "380921"
    assert result["period"] == "2026-04-01"
    assert result["issue_date"] == "2026-06-16"
    assert result["due_date_kind"] == "installment"
    assert Decimal(result["first_due_amount"]) == Decimal("34815.42")
    assert Decimal(result["second_due_amount"]) == Decimal("34815.42")
    assert Decimal(result["total_amount"]) == Decimal("69630.84")
    assert Decimal(result["consumption_m3"]) == Decimal("25.76")


def test_rejects_unrelated_document() -> None:
    with pytest.raises(AssaParseError, match="not a supported"):
        parse("ordinary invoice")
