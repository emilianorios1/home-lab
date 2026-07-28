from decimal import Decimal

import pytest

from home_lab.documents.parsers.litoral_gas import (
    LitoralGasParseError,
    parse,
    supports,
)


SAMPLE_TEXT = """
0081-60522736
10/07/2026
MONTEVIDEO 1213 P 04 D02 - (2000) ROSARIO 12 12 113 0015 04/2026
Liquidación 1 de 2 Bimestre 04/2026 m3 asignados a la presente 134.14
20/07/2026
TOTAL A PAGAR hasta el 20/07/2026
LIQUIDACION DE SERVICIOS PUBLICOS "B" - Codigo 18
48.033,45
0081-60522736 20/07/2026 48.033,45
N° CLIENTE 0013753702
Litoral Gas S.A.
"""


def test_parses_litoral_gas_bill() -> None:
    assert supports(SAMPLE_TEXT)
    result = parse(SAMPLE_TEXT)
    assert result["document_type"] == "gas_bill"
    assert result["customer_number"] == "13753702"
    assert result["invoice_number"] == "0081-60522736"
    assert result["period"] == "2026-04-01"
    assert result["issue_date"] == "2026-07-10"
    assert result["first_due_date"] == "2026-07-20"
    assert result["second_due_date"] is None
    assert result["due_date_kind"] == "single"
    assert Decimal(result["first_due_amount"]) == Decimal("48033.45")
    assert Decimal(result["total_amount"]) == Decimal("48033.45")
    assert Decimal(result["consumption_m3"]) == Decimal("134.14")


def test_rejects_unrelated_document() -> None:
    with pytest.raises(LitoralGasParseError, match="not a supported"):
        parse("ordinary invoice")
