from decimal import Decimal

import pytest

from home_lab.documents.parsers.naranja_x import (
    NaranjaXParseError,
    parse,
    supports,
)


SAMPLE_TEXT = """
Tu total a pagar es
$123.456,78 + u$s9,99
y vence el 15/08/26.
LA MENOR ENTREGA
$40.000,00
y 8 cuotas de $15.000,00
Consumos tarjeta de crédito de Persona
FECHA         TARJETA                  CUPON   DETALLE                                                                                                            CUOTA/PLAN                             $                       U$S
22/07/26 Naranja X    710488 SEGURO COMPRA                                          Deb.Aut.          1.234,56
27/07/26                     *INTERES POR MORA CONSUMOS EN PESOS                                        123,45
24/06/26 NX Visa        5973 ESTACION DE SERVICIO                                        01         12.345,67
21/06/26 NX Visa      186682 SERVICIO DIGITAL                                       Deb.Aut.                         9,99
27/07/26                     *PLAN TURBO (REEMPLAZA COSTO DE MANTENIMIENTO)                             999,99
Otros
cargos:
IVA Operaciones Identificadas con *
(Base Imponible $1.000,00)                                                 210,00
Impuesto de Sellos                                                          50,00
El resumen actual cerró el 31/07.
RESUMEN Nº 12345678 EMITIDO EL 31/07.
TARJETA NARANJA S.A.U.
"""


def test_parses_naranja_x_statement_and_transactions() -> None:
    assert supports(SAMPLE_TEXT)

    result = parse(SAMPLE_TEXT)

    assert result["document_type"] == "credit_card_statement"
    assert result["period"] == "2026-07-01"
    assert result["issue_date"] == "2026-07-31"
    assert result["first_due_date"] == "2026-08-15"
    assert Decimal(result["first_due_amount"]) == Decimal("123456.78")
    assert Decimal(result["foreign_total_amount"]) == Decimal("9.99")
    assert Decimal(result["minimum_payment"]) == Decimal("40000.00")
    assert result["financing_installments"] == 8
    assert len(result["transactions"]) == 7
    assert result["transactions"][0] == {
        "purchase_date": "2026-07-22",
        "card": "Naranja X",
        "coupon": "710488",
        "description": "SEGURO COMPRA",
        "installment": "Deb.Aut.",
        "currency": "ARS",
        "amount": "1234.56",
        "kind": "purchase",
    }
    assert result["transactions"][3]["currency"] == "USD"
    assert result["transactions"][3]["amount"] == "9.99"
    assert result["transactions"][-1]["description"] == "Impuesto de Sellos"


def test_rejects_unrelated_document() -> None:
    with pytest.raises(NaranjaXParseError, match="not a supported"):
        parse("ordinary invoice")
