from decimal import Decimal

import pytest

from home_lab.documents.parsers.arca_factura_e import (
    ArcaFacturaEParseError,
    parse,
    supports,
)


SAMPLE_TEXT = """
Fecha de Emisión:
ORIGINAL
01/07/2026
Comp. Nro: 00002-00000004
FACTURA DE EXPORTACIÓN COD. 19
Moneda: USD - Dólar Estadounidense
01/07/2026Fecha de Pago:
3500,00Importe Total:
CAE N°:
Fecha de Vto. de CAE:
Comprobante Autorizado
10/07/2026
12345678901234
USD
Tipo de Cambio: 1234.567890
"""


def test_parses_arca_factura_e() -> None:
    assert supports(SAMPLE_TEXT)

    result = parse(SAMPLE_TEXT)

    assert result["document_type"] == "export_service_invoice"
    assert result["issuer"] == "ARCA"
    assert result["period"] == "2026-07-01"
    assert result["issue_date"] == "2026-07-01"
    assert result["payment_date"] == "2026-07-01"
    assert result["point_of_sale"] == "00002"
    assert result["invoice_number"] == "00000004"
    assert result["foreign_currency"] == "USD"
    assert Decimal(result["foreign_total_amount"]) == Decimal("3500.00")
    assert Decimal(result["exchange_rate"]) == Decimal("1234.567890")
    assert result["cae"] == "12345678901234"
    assert result["cae_due_date"] == "2026-07-10"


def test_rejects_unrelated_document() -> None:
    with pytest.raises(ArcaFacturaEParseError, match="not a supported"):
        parse("ordinary invoice")


def test_rejects_an_unimplemented_currency() -> None:
    euro_invoice = SAMPLE_TEXT.replace(
        "USD - Dólar Estadounidense",
        "EUR - Euro",
    )
    with pytest.raises(ArcaFacturaEParseError, match="not a supported"):
        parse(euro_invoice)
