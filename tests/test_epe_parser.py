from decimal import Decimal

import pytest

from home_lab.documents.parsers.epe import EpeParseError, parse, supports


SAMPLE_TEXT = """
EMPRESA PROVINCIAL DE LA ENERGÍA DE SANTA FE
FECHA DE EMISION: 16/07/2026
Número de Cliente: 002028476
Dirección del Suministro
MONTEVIDO 1213 Piso 04 Dto.02
Consumo Total:    450  kWh
Fecha de Vencimiento Importe Total
Cuota 1 11/08/2026 $*92.566,54
Fecha de Vencimiento Importe Total
Cuota 2 10/09/2026 $*92.566,53
Detalle de Facturación Importe
TOTAL $**185.133,07
"""


def test_parses_epe_electricity_bill() -> None:
    assert supports(SAMPLE_TEXT)
    result = parse(SAMPLE_TEXT)
    assert result["document_type"] == "electricity_bill"
    assert result["customer_number"] == "2028476"
    assert result["unit"] == "2028476"
    assert result["supply_address"] == "MONTEVIDO 1213 Piso 04 Dto.02"
    assert result["period"] == "2026-07-01"
    assert result["due_date_kind"] == "installment"
    assert Decimal(result["first_due_amount"]) == Decimal("92566.54")
    assert Decimal(result["second_due_amount"]) == Decimal("92566.53")
    assert Decimal(result["total_amount"]) == Decimal("185133.07")
    assert Decimal(result["consumption_kwh"]) == Decimal("450")


def test_rejects_unrelated_document() -> None:
    with pytest.raises(EpeParseError, match="not a supported"):
        parse("ordinary invoice")
