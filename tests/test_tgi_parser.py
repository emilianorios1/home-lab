from home_lab.documents.parsers import tgi


TGI_TEXT = """
27/07/2026
TGI - Tasa General de Inmuebles
Reimpresión

Contribuyente: Persona de prueba     Cuenta: 0012345678
Cod. Gestión Personal: 1234567
Ubicación: CALLE DE PRUEBA 123

PERIODO       VENCIMIENTO ORIGINAL       IMPORTE       INTERES       TOTAL
8/2026             10/08/2026            27894,55        0,00       27894,55
"""


def test_parses_tgi_bill() -> None:
    assert tgi.supports(TGI_TEXT)
    parsed = tgi.parse(TGI_TEXT)

    assert parsed["document_type"] == "property_tax_bill"
    assert parsed["issuer"] == "Municipalidad de Rosario"
    assert parsed["unit"] == "12345678"
    assert parsed["period"] == "2026-08-01"
    assert parsed["issue_date"] == "2026-07-27"
    assert parsed["first_due_date"] == "2026-08-10"
    assert parsed["first_due_amount"] == "27894.55"
    assert parsed["total_amount"] == "27894.55"
    assert parsed["due_date_kind"] == "single"
