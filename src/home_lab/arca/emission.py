"""Persistent, retry-safe Factura E sandbox emission."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, text

from home_lab.arca.client import (
    DEVELOPMENT_TAX_ID,
    EXPORT_INVOICE_TYPE,
    AfipSdkClient,
    AfipSdkError,
)


@dataclass(frozen=True)
class ExportInvoiceDraft:
    point_of_sale: int
    issue_date: date
    payment_date: date
    client_name: str
    client_address: str
    foreign_tax_id: str
    destination_country_code: int
    destination_country_tax_id: int
    description: str
    unit_code: int
    amount_usd: Decimal
    exchange_rate: Decimal

    def validate(self, *, today: date | None = None) -> None:
        today = today or date.today()
        required_text = {
            "nombre del cliente": self.client_name,
            "domicilio del cliente": self.client_address,
            "identificación tributaria extranjera": self.foreign_tax_id,
            "descripción": self.description,
        }
        for label, value in required_text.items():
            if not value.strip():
                raise ValueError(f"Falta {label}.")
        if self.point_of_sale <= 0:
            raise ValueError("El punto de venta debe ser positivo.")
        if self.destination_country_code <= 0:
            raise ValueError("El código de país debe ser positivo.")
        if self.destination_country_tax_id <= 0:
            raise ValueError("La CUIT del país debe ser positiva.")
        if self.unit_code <= 0:
            raise ValueError("El código de unidad debe ser positivo.")
        if self.amount_usd <= 0:
            raise ValueError("El importe debe ser positivo.")
        if self.exchange_rate <= 0:
            raise ValueError("El tipo de cambio debe ser positivo.")
        if abs((self.issue_date - today).days) > 5:
            raise ValueError(
                "La fecha de emisión debe estar dentro de los cinco días de hoy."
            )
        if self.payment_date < self.issue_date:
            raise ValueError(
                "La fecha de pago no puede ser anterior a la emisión."
            )


@dataclass(frozen=True)
class RecurringExportInvoiceProfile:
    point_of_sale: int
    client_name: str
    client_address: str
    foreign_tax_id: str
    destination_country_code: int
    destination_country_tax_id: int
    description: str
    unit_code: int
    amount_usd: Decimal

    def validate(self) -> None:
        ExportInvoiceDraft(
            point_of_sale=self.point_of_sale,
            issue_date=date.today(),
            payment_date=date.today(),
            client_name=self.client_name,
            client_address=self.client_address,
            foreign_tax_id=self.foreign_tax_id,
            destination_country_code=self.destination_country_code,
            destination_country_tax_id=self.destination_country_tax_id,
            description=self.description,
            unit_code=self.unit_code,
            amount_usd=self.amount_usd,
            exchange_rate=Decimal("1"),
        ).validate()


@dataclass(frozen=True)
class EmissionAttempt:
    request_id: int
    status: str
    point_of_sale: int
    voucher_number: int | None
    cae: str | None
    cae_due_date: date | None
    error_message: str | None


def _request_id(last_id: int, now: datetime | None = None) -> int:
    moment = now or datetime.now(timezone.utc)
    timestamp_id = int(moment.strftime("%y%m%d%H%M%S%f")[:15])
    return max(last_id + 1, timestamp_id)


def recurring_invoice_profile(
    engine: Engine,
) -> RecurringExportInvoiceProfile | None:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    point_of_sale, client_name, client_address, foreign_tax_id,
                    destination_country_code, destination_country_tax_id,
                    description, unit_code, amount_usd
                FROM bronze.recurring_export_invoice_profile
                WHERE id = 1
                """
            )
        ).mappings().one_or_none()
    return RecurringExportInvoiceProfile(**dict(row)) if row else None


def save_recurring_invoice_profile(
    engine: Engine,
    profile: RecurringExportInvoiceProfile,
) -> None:
    profile.validate()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO bronze.recurring_export_invoice_profile (
                    id, point_of_sale, client_name, client_address,
                    foreign_tax_id, destination_country_code,
                    destination_country_tax_id, description, unit_code,
                    amount_usd
                )
                VALUES (
                    1, :point_of_sale, :client_name, :client_address,
                    :foreign_tax_id, :destination_country_code,
                    :destination_country_tax_id, :description, :unit_code,
                    :amount_usd
                )
                ON CONFLICT (id) DO UPDATE
                SET point_of_sale = excluded.point_of_sale,
                    client_name = excluded.client_name,
                    client_address = excluded.client_address,
                    foreign_tax_id = excluded.foreign_tax_id,
                    destination_country_code = excluded.destination_country_code,
                    destination_country_tax_id = excluded.destination_country_tax_id,
                    description = excluded.description,
                    unit_code = excluded.unit_code,
                    amount_usd = excluded.amount_usd,
                    updated_at = now()
                """
            ),
            {
                "point_of_sale": profile.point_of_sale,
                "client_name": profile.client_name.strip(),
                "client_address": profile.client_address.strip(),
                "foreign_tax_id": profile.foreign_tax_id.strip(),
                "destination_country_code": profile.destination_country_code,
                "destination_country_tax_id": profile.destination_country_tax_id,
                "description": profile.description.strip(),
                "unit_code": profile.unit_code,
                "amount_usd": profile.amount_usd,
            },
        )


def create_emission(
    engine: Engine,
    draft: ExportInvoiceDraft,
    client: AfipSdkClient,
    *,
    today: date | None = None,
    now: datetime | None = None,
) -> int:
    """Persist a draft and return its WSFEX request ID."""
    draft.validate(today=today)
    request_id = _request_id(client.get_last_request_id(), now)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO bronze.export_invoice_emissions (
                    request_id, environment, tax_id, status, point_of_sale,
                    voucher_type, issue_date, payment_date, client_name,
                    client_address, foreign_tax_id, destination_country_code,
                    destination_country_tax_id, description, unit_code,
                    foreign_currency, foreign_total_amount, exchange_rate
                )
                VALUES (
                    :request_id, 'dev', :tax_id, 'pending', :point_of_sale,
                    :voucher_type, :issue_date, :payment_date, :client_name,
                    :client_address, :foreign_tax_id, :destination_country_code,
                    :destination_country_tax_id, :description, :unit_code,
                    'USD', :foreign_total_amount, :exchange_rate
                )
                """
            ),
            {
                "request_id": request_id,
                "tax_id": DEVELOPMENT_TAX_ID,
                "point_of_sale": draft.point_of_sale,
                "voucher_type": EXPORT_INVOICE_TYPE,
                "issue_date": draft.issue_date,
                "payment_date": draft.payment_date,
                "client_name": draft.client_name.strip(),
                "client_address": draft.client_address.strip(),
                "foreign_tax_id": draft.foreign_tax_id.strip(),
                "destination_country_code": draft.destination_country_code,
                "destination_country_tax_id": draft.destination_country_tax_id,
                "description": draft.description.strip(),
                "unit_code": draft.unit_code,
                "foreign_total_amount": draft.amount_usd,
                "exchange_rate": draft.exchange_rate,
            },
        )
    return request_id


def _load_emission(engine: Engine, request_id: int) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT *
                FROM bronze.export_invoice_emissions
                WHERE request_id = :request_id
                """
            ),
            {"request_id": request_id},
        ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"No existe la emisión {request_id}.")
    return dict(row)


def _voucher_payload(row: dict[str, Any]) -> dict[str, Any]:
    amount = float(row["foreign_total_amount"])
    return {
        "Id": row["request_id"],
        "Fecha_cbte": row["issue_date"].strftime("%Y%m%d"),
        "Cbte_Tipo": row["voucher_type"],
        "Punto_vta": row["point_of_sale"],
        "Cbte_nro": row["voucher_number"],
        "Tipo_expo": 2,
        "Permiso_existente": "",
        "Dst_cmp": row["destination_country_code"],
        "Cliente": row["client_name"],
        "Cuit_pais_cliente": row["destination_country_tax_id"],
        "Domicilio_cliente": row["client_address"],
        "Id_impositivo": row["foreign_tax_id"],
        "Moneda_Id": "DOL",
        "Moneda_ctz": float(row["exchange_rate"]),
        "Imp_total": amount,
        "Forma_pago": "Transferencia bancaria",
        "Idioma_cbte": 1,
        "Items": {
            "Item": [
                {
                    "Pro_codigo": "SERVICIO",
                    "Pro_ds": row["description"],
                    "Pro_qty": 1,
                    "Pro_umed": row["unit_code"],
                    "Pro_precio_uni": amount,
                    "Pro_bonificacion": 0,
                    "Pro_total_item": amount,
                }
            ]
        },
        "Fecha_pago": row["payment_date"].strftime("%Y%m%d"),
    }


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    raw = str(value)
    for pattern in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    return None


def _response_detail(value: object) -> str | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _interpret_response(
    response: dict[str, Any],
) -> tuple[str, str | None, date | None, str | None, str | None]:
    result = response.get("FEXAuthorizeResult")
    if not isinstance(result, dict):
        return (
            "unknown",
            None,
            None,
            None,
            "WSFEX devolvió una respuesta que no se pudo interpretar.",
        )

    service_error = result.get("FEXErr")
    if isinstance(service_error, dict):
        try:
            error_code = int(service_error.get("ErrCode") or 0)
        except (TypeError, ValueError):
            error_code = -1
        if error_code:
            return (
                "rejected",
                None,
                None,
                str(error_code),
                str(service_error.get("ErrMsg") or "WSFEX rechazó la solicitud."),
            )

    authorization = result.get("FEXResultAuth")
    if not isinstance(authorization, dict):
        return (
            "unknown",
            None,
            None,
            None,
            "WSFEX no informó el resultado de autorización.",
        )
    outcome = str(authorization.get("Resultado") or "").upper()
    cae = str(authorization.get("Cae") or "").strip() or None
    cae_due_date = _parse_date(authorization.get("Fch_venc_Cae"))
    observations = _response_detail(authorization.get("Motivos_Obs"))
    if outcome == "A" and cae:
        return ("authorized", cae, cae_due_date, None, observations)
    if outcome == "R":
        return ("rejected", None, None, None, observations or "ARCA rechazó la solicitud.")
    return (
        "unknown",
        cae,
        cae_due_date,
        None,
        observations or "WSFEX no informó un resultado concluyente.",
    )


def emit_export_invoice(
    engine: Engine,
    request_id: int,
    client: AfipSdkClient,
) -> EmissionAttempt:
    """Authorize a persisted draft, safely reusing its exact request on retry."""
    row = _load_emission(engine, request_id)
    if row["status"] == "authorized":
        return emission_attempt(engine, request_id)
    if row["status"] == "rejected":
        raise ValueError("Una emisión rechazada no se reintenta sin corregirla.")

    if row["voucher_number"] is None:
        voucher_number = client.get_last_voucher(row["point_of_sale"]) + 1
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE bronze.export_invoice_emissions
                    SET voucher_number = :voucher_number, updated_at = now()
                    WHERE request_id = :request_id
                      AND voucher_number IS NULL
                    """
                ),
                {
                    "request_id": request_id,
                    "voucher_number": voucher_number,
                },
            )
        row = _load_emission(engine, request_id)

    if row["request_payload"] is None:
        payload = _voucher_payload(row)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE bronze.export_invoice_emissions
                    SET request_payload = cast(:payload AS jsonb),
                        updated_at = now()
                    WHERE request_id = :request_id
                      AND request_payload IS NULL
                    """
                ),
                {
                    "request_id": request_id,
                    "payload": json.dumps(payload),
                },
            )
        row = _load_emission(engine, request_id)

    try:
        response = client.authorize(row["request_payload"])
    except AfipSdkError as error:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE bronze.export_invoice_emissions
                    SET status = 'unknown', error_message = :error_message,
                        updated_at = now()
                    WHERE request_id = :request_id
                    """
                ),
                {
                    "request_id": request_id,
                    "error_message": str(error),
                },
            )
        raise

    status, cae, cae_due_date, error_code, error_message = _interpret_response(
        response
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE bronze.export_invoice_emissions
                SET status = :status,
                    response_payload = cast(:response_payload AS jsonb),
                    cae = :cae,
                    cae_due_date = :cae_due_date,
                    error_code = :error_code,
                    error_message = :error_message,
                    updated_at = now()
                WHERE request_id = :request_id
                """
            ),
            {
                "request_id": request_id,
                "status": status,
                "response_payload": json.dumps(response),
                "cae": cae,
                "cae_due_date": cae_due_date,
                "error_code": error_code,
                "error_message": error_message,
            },
        )
    return emission_attempt(engine, request_id)


def emission_attempt(engine: Engine, request_id: int) -> EmissionAttempt:
    row = _load_emission(engine, request_id)
    return EmissionAttempt(
        request_id=row["request_id"],
        status=row["status"],
        point_of_sale=row["point_of_sale"],
        voucher_number=row["voucher_number"],
        cae=row["cae"],
        cae_due_date=row["cae_due_date"],
        error_message=row["error_message"],
    )


def retryable_emissions(engine: Engine) -> list[EmissionAttempt]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT request_id
                FROM bronze.export_invoice_emissions
                WHERE environment = 'dev'
                  AND status IN ('pending', 'unknown')
                ORDER BY created_at DESC
                LIMIT 10
                """
            )
        ).scalars()
        request_ids = list(rows)
    return [emission_attempt(engine, request_id) for request_id in request_ids]


def emission_history(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    request_id,
                    status,
                    point_of_sale,
                    voucher_number,
                    issue_date,
                    foreign_total_amount,
                    exchange_rate,
                    cae,
                    cae_due_date,
                    error_message
                FROM bronze.export_invoice_emissions
                WHERE environment = 'dev'
                ORDER BY created_at DESC
                LIMIT 20
                """
            )
        ).mappings()
        return [dict(row) for row in rows]
