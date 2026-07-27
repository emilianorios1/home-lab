from decimal import Decimal

import pytest

from home_lab.documents.parsers.zetace import ZetaceParseError, parse, supports


SAMPLE_TEXT = """
Consorcio: CONCORDE
Fecha de Emisión: 01/07/2026
U. 04-02 - 4 B
Período: JUNIO / 2026
1er.Vencim.: 14 - 07 - 2026 $ 116839.47
2do.Vencim.: 21-07-2026 $ 119176.26
EXPENSAS GENERALES 53389.47
EXPENSAS EXTRAORDINARIAS 63450.00
SALDO ANTERIOR 142931.74
COBRANZAS -142931.74
"""

PYPDF_ORDERED_TEXT = """
04-02
U.
Fecha de Emisión: 01/07/2026
CONCORDEConsorcio:
14 - 07 - 2026 $ 116839.471er.Vencim.:
Período: JUNIO / 2026
2do.Vencim.: 21-07-2026 $ 119176.260002204025120280597CODIGO DE PAGOS LINK:
53389.47EXPENSAS GENERALES
63450.00EXPENSAS EXTRAORDINARIAS
"""


def test_parses_zeta_expense_statement() -> None:
    assert supports(SAMPLE_TEXT)
    result = parse(SAMPLE_TEXT)
    assert result["period"] == "2026-06-01"
    assert result["unit"] == "04-02"
    assert Decimal(result["first_due_amount"]) == Decimal("116839.47")
    assert Decimal(result["second_due_amount"]) == Decimal("119176.26")
    assert result["concepts"] == [
        {"code": "general_expenses", "amount": "53389.47"},
        {"code": "extraordinary_expenses", "amount": "63450.00"},
    ]


def test_rejects_unrelated_document() -> None:
    with pytest.raises(ZetaceParseError, match="not a supported"):
        parse("ordinary invoice")


def test_parses_reordered_text_emitted_by_pypdf() -> None:
    result = parse(PYPDF_ORDERED_TEXT)
    assert result["issuer"] == "CONCORDE"
    assert result["unit"] == "04-02"
    assert result["first_due_amount"] == "116839.47"
    assert result["second_due_amount"] == "119176.26"
