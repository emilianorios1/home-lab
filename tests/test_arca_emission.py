from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text

from home_lab.arca.client import AfipSdkError
from home_lab.arca.emission import (
    ExportInvoiceDraft,
    RecurringExportInvoiceProfile,
    emit_export_invoice,
    recurring_invoice_profile,
    save_recurring_invoice_profile,
)
from home_lab.database import create_schema, get_engine


class FakeAfipSdkClient:
    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject
        self.payloads: list[dict[str, Any]] = []

    def get_last_request_id(self) -> int:
        return 50

    def get_last_voucher(self, point_of_sale: int) -> int:
        assert point_of_sale == 2
        return 7

    def authorize(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        if self.reject:
            return {
                "FEXAuthorizeResult": {
                    "FEXErr": {"ErrCode": 100, "ErrMsg": "Synthetic rejection"}
                }
            }
        return {
            "FEXAuthorizeResult": {
                "FEXResultAuth": {
                    "Resultado": "A",
                    "Cae": "12345678901234",
                    "Fch_venc_Cae": "20260720",
                },
                "FEXErr": {"ErrCode": 0, "ErrMsg": ""},
            }
        }


def draft() -> ExportInvoiceDraft:
    return ExportInvoiceDraft(
        point_of_sale=2,
        issue_date=date(2026, 7, 15),
        payment_date=date(2026, 7, 20),
        client_name="Example LLC",
        client_address="Synthetic address",
        foreign_tax_id="TEST-123",
        destination_country_code=212,
        destination_country_tax_id=50000000017,
        description="Synthetic software service",
        unit_code=7,
        amount_usd=Decimal("100.00"),
        exchange_rate=Decimal("1200.000000"),
    )


def test_emission_is_one_shot_and_uses_wsfex_fields() -> None:
    client = FakeAfipSdkClient()

    cae, due_date, voucher_number = emit_export_invoice(
        draft(),
        client,  # type: ignore[arg-type]
        today=date(2026, 7, 15),
        now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc),
    )

    assert (cae, due_date, voucher_number) == (
        "12345678901234",
        date(2026, 7, 20),
        8,
    )
    payload = client.payloads[0]
    assert payload["Cbte_Tipo"] == 19
    assert payload["Tipo_expo"] == 2
    assert payload["Moneda_Id"] == "DOL"
    assert payload["Fecha_pago"] == "20260720"
    assert payload["Items"]["Item"][0]["Pro_total_item"] == 100.0


def test_rejected_emission_is_not_retried() -> None:
    with pytest.raises(AfipSdkError, match="Synthetic rejection"):
        emit_export_invoice(
            draft(),
            FakeAfipSdkClient(reject=True),  # type: ignore[arg-type]
            today=date(2026, 7, 15),
        )


@pytest.fixture
def engine() -> Any:
    value = get_engine()
    create_schema(value)
    with value.connect() as connection:
        existing = connection.execute(
            text("SELECT * FROM bronze.recurring_export_invoice_profile WHERE id = 1")
        ).mappings().one_or_none()
    yield value
    with value.begin() as connection:
        connection.execute(
            text("DELETE FROM bronze.recurring_export_invoice_profile WHERE id = 1")
        )
        if existing:
            columns = ", ".join(existing.keys())
            values = ", ".join(f":{column}" for column in existing.keys())
            connection.execute(
                text(
                    "INSERT INTO bronze.recurring_export_invoice_profile "
                    f"({columns}) VALUES ({values})"
                ),
                dict(existing),
            )


def test_recurring_profile_keeps_fixed_fields(engine: Any) -> None:
    profile = RecurringExportInvoiceProfile(
        point_of_sale=2,
        client_name="Example LLC",
        client_address="Synthetic address",
        foreign_tax_id="TEST-123",
        destination_country_code=212,
        destination_country_tax_id=50000000017,
        description="Synthetic software service",
        unit_code=7,
        amount_usd=Decimal("100.00"),
    )

    save_recurring_invoice_profile(engine, profile)

    assert recurring_invoice_profile(engine) == profile
