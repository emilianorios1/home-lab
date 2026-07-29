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

OVERDUE_NOTICE_TEXT = """
Titular : PERSONA DE PRUEBA
Dir. Inmueble : CALLE FALSA 123
05/07/2026
13/07/2026
05/07/2026
13/07/2026
05/07/2026
13/07/2026
30/06/2026
0200-12345678 S08 2026/03 11/05/2026 1.000,00 100,00 21,00 0,00 1.121,00
COMPROBANTE C.S. PERIODO VTO.ORIG. SALDO RECARGO E
INTERESES
IVA INT.
IVA RET/RS/PER
IMP. TOTAL
RECLAMO DE FACTURAS VENCIDAS
0000123456
0000000001
000000000002
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


def test_parses_assa_overdue_notice() -> None:
    assert supports(OVERDUE_NOTICE_TEXT)
    result = parse(OVERDUE_NOTICE_TEXT)
    assert result["document_type"] == "water_bill"
    assert result["customer_number"] == "123456"
    assert result["period"] == "2026-03-01"
    assert result["issue_date"] == "2026-07-05"
    assert result["first_due_date"] == "2026-07-13"
    assert Decimal(result["first_due_amount"]) == Decimal("1121.00")
    assert result["second_due_date"] is None
    assert result["due_date_kind"] == "single"
    assert Decimal(result["total_amount"]) == Decimal("1121.00")
    assert result["consumption_m3"] is None


def test_rejects_unrelated_document() -> None:
    with pytest.raises(AssaParseError, match="not a supported"):
        parse("ordinary invoice")
