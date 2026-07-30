from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text

from home_lab.arca.client import AfipSdkError
from home_lab.arca.emission import (
    ExportInvoiceDraft,
    RecurringExportInvoiceProfile,
    create_emission,
    emission_attempt,
    emit_export_invoice,
    recurring_invoice_profile,
    save_recurring_invoice_profile,
)
from home_lab.database import create_schema, get_engine


class FakeAfipSdkClient:
    def __init__(
        self,
        *,
        fail_authorize: bool = False,
        reject_authorize: bool = False,
    ) -> None:
        self.fail_authorize = fail_authorize
        self.reject_authorize = reject_authorize
        self.payloads: list[dict[str, Any]] = []

    def get_last_request_id(self) -> int:
        return 50

    def get_last_voucher(self, point_of_sale: int) -> int:
        assert point_of_sale == 2
        return 7

    def authorize(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        if self.fail_authorize:
            raise AfipSdkError("No se pudo conectar con Afip SDK.")
        if self.reject_authorize:
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
                    "Motivos_Obs": "",
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


@pytest.fixture
def engine() -> Any:
    value = get_engine()
    create_schema(value)
    with value.connect() as connection:
        existing_profile = connection.execute(
            text("SELECT * FROM bronze.recurring_export_invoice_profile WHERE id = 1")
        ).mappings().one_or_none()
    yield value
    with value.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM bronze.export_invoice_emissions
                WHERE foreign_tax_id = 'TEST-123'
                """
            )
        )
        connection.execute(
            text("DELETE FROM bronze.recurring_export_invoice_profile WHERE id = 1")
        )
        if existing_profile:
            connection.execute(
                text(
                    """
                    INSERT INTO bronze.recurring_export_invoice_profile (
                        id, point_of_sale, client_name, client_address,
                        foreign_tax_id, destination_country_code,
                        destination_country_tax_id, description, unit_code,
                        amount_usd, created_at, updated_at
                    )
                    VALUES (
                        :id, :point_of_sale, :client_name, :client_address,
                        :foreign_tax_id, :destination_country_code,
                        :destination_country_tax_id, :description, :unit_code,
                        :amount_usd, :created_at, :updated_at
                    )
                    """
                ),
                dict(existing_profile),
            )


def create_test_emission(
    engine: Any,
    client: FakeAfipSdkClient,
    *,
    second: int = 0,
) -> int:
    return create_emission(
        engine,
        draft(),
        client,  # type: ignore[arg-type]
        today=date(2026, 7, 15),
        now=datetime(2026, 7, 15, 12, 0, second, tzinfo=timezone.utc),
    )


def test_authorization_is_persisted_and_uses_wsfex_service_fields(
    engine: Any,
) -> None:
    client = FakeAfipSdkClient()
    request_id = create_test_emission(engine, client)

    result = emit_export_invoice(
        engine,
        request_id,
        client,  # type: ignore[arg-type]
    )

    assert result.status == "authorized"
    assert result.voucher_number == 8
    assert result.cae == "12345678901234"
    payload = client.payloads[0]
    assert payload["Id"] == request_id
    assert payload["Cbte_Tipo"] == 19
    assert payload["Tipo_expo"] == 2
    assert payload["Moneda_Id"] == "DOL"
    assert payload["Fecha_pago"] == "20260720"
    assert payload["Items"]["Item"][0]["Pro_total_item"] == 100.0
    with engine.connect() as connection:
        tracked_as_real = connection.execute(
            text(
                """
                SELECT count(*)
                FROM gold.export_invoices
                WHERE cae = '12345678901234'
                """
            )
        ).scalar_one()
    assert tracked_as_real == 0


def test_indeterminate_call_retries_the_exact_persisted_payload(
    engine: Any,
) -> None:
    first_client = FakeAfipSdkClient(fail_authorize=True)
    request_id = create_test_emission(engine, first_client)

    with pytest.raises(AfipSdkError, match="No se pudo conectar"):
        emit_export_invoice(
            engine,
            request_id,
            first_client,  # type: ignore[arg-type]
        )

    assert emission_attempt(engine, request_id).status == "unknown"
    retry_client = FakeAfipSdkClient()
    result = emit_export_invoice(
        engine,
        request_id,
        retry_client,  # type: ignore[arg-type]
    )

    assert result.status == "authorized"
    assert retry_client.payloads == first_client.payloads


def test_rejected_voucher_number_is_available_for_a_corrected_draft(
    engine: Any,
) -> None:
    rejected_request = create_test_emission(
        engine,
        FakeAfipSdkClient(reject_authorize=True),
    )
    rejected = emit_export_invoice(
        engine,
        rejected_request,
        FakeAfipSdkClient(reject_authorize=True),  # type: ignore[arg-type]
    )
    assert rejected.status == "rejected"

    accepted_client = FakeAfipSdkClient()
    accepted_request = create_test_emission(
        engine,
        accepted_client,
        second=1,
    )
    accepted = emit_export_invoice(
        engine,
        accepted_request,
        accepted_client,  # type: ignore[arg-type]
    )

    assert accepted.status == "authorized"
    assert accepted.voucher_number == rejected.voucher_number


def test_recurring_profile_keeps_the_fixed_invoice_fields(
    engine: Any,
) -> None:
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
    saved = recurring_invoice_profile(engine)

    assert saved == profile
