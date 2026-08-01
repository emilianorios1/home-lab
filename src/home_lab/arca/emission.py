"""One-shot Factura E sandbox emission and recurring profile storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, text

from home_lab.arca.client import EXPORT_INVOICE_TYPE, AfipSdkClient, AfipSdkError


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
        required_text = {
            "nombre del cliente": self.client_name,
            "domicilio del cliente": self.client_address,
            "identificación tributaria extranjera": self.foreign_tax_id,
            "descripción": self.description,
        }
        for label, value in required_text.items():
            if not value.strip():
                raise ValueError(f"Falta {label}.")
        for label, value in {
            "punto de venta": self.point_of_sale,
            "código de país": self.destination_country_code,
            "CUIT del país": self.destination_country_tax_id,
            "código de unidad": self.unit_code,
            "importe": self.amount_usd,
            "tipo de cambio": self.exchange_rate,
        }.items():
            if value <= 0:
                raise ValueError(f"El {label} debe ser positivo.")
        if abs((self.issue_date - (today or date.today())).days) > 5:
            raise ValueError(
                "La fecha de emisión debe estar dentro de los cinco días de hoy."
            )
        if self.payment_date < self.issue_date:
            raise ValueError("La fecha de pago no puede ser anterior a la emisión.")


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


def _request_id(last_id: int, now: datetime | None = None) -> int:
    moment = now or datetime.now(timezone.utc)
    timestamp_id = int(moment.strftime("%y%m%d%H%M%S%f")[:15])
    return max(last_id + 1, timestamp_id)


def _voucher_payload(
    draft: ExportInvoiceDraft,
    request_id: int,
    voucher_number: int,
) -> dict[str, Any]:
    amount = float(draft.amount_usd)
    return {
        "Id": request_id,
        "Fecha_cbte": draft.issue_date.strftime("%Y%m%d"),
        "Cbte_Tipo": EXPORT_INVOICE_TYPE,
        "Punto_vta": draft.point_of_sale,
        "Cbte_nro": voucher_number,
        "Tipo_expo": 2,
        "Permiso_existente": "",
        "Dst_cmp": draft.destination_country_code,
        "Cliente": draft.client_name.strip(),
        "Cuit_pais_cliente": draft.destination_country_tax_id,
        "Domicilio_cliente": draft.client_address.strip(),
        "Id_impositivo": draft.foreign_tax_id.strip(),
        "Moneda_Id": "DOL",
        "Moneda_ctz": float(draft.exchange_rate),
        "Imp_total": amount,
        "Forma_pago": "Transferencia bancaria",
        "Idioma_cbte": 1,
        "Items": {
            "Item": [
                {
                    "Pro_codigo": "SERVICIO",
                    "Pro_ds": draft.description.strip(),
                    "Pro_qty": 1,
                    "Pro_umed": draft.unit_code,
                    "Pro_precio_uni": amount,
                    "Pro_bonificacion": 0,
                    "Pro_total_item": amount,
                }
            ]
        },
        "Fecha_pago": draft.payment_date.strftime("%Y%m%d"),
    }


def _cae_due_date(value: object) -> date | None:
    if not value:
        return None
    for pattern in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), pattern).date()
        except ValueError:
            pass
    return None


def emit_export_invoice(
    draft: ExportInvoiceDraft,
    client: AfipSdkClient,
    *,
    today: date | None = None,
    now: datetime | None = None,
) -> tuple[str, date | None, int]:
    """Send one confirmed sandbox request without retaining fiscal state."""
    # ponytail: sandbox calls are one-shot; persist retries only for real emission.
    draft.validate(today=today)
    request_id = _request_id(client.get_last_request_id(), now)
    voucher_number = client.get_last_voucher(draft.point_of_sale) + 1
    response = client.authorize(_voucher_payload(draft, request_id, voucher_number))
    result = response.get("FEXAuthorizeResult")
    if not isinstance(result, dict):
        raise AfipSdkError("WSFEX devolvió una respuesta que no se pudo interpretar.")
    if error := AfipSdkClient._service_error(result):
        raise error
    authorization = result.get("FEXResultAuth")
    if not isinstance(authorization, dict):
        raise AfipSdkError("WSFEX no informó el resultado de autorización.")
    cae = str(authorization.get("Cae") or "").strip()
    if str(authorization.get("Resultado") or "").upper() != "A" or not cae:
        detail = authorization.get("Motivos_Obs") or "ARCA rechazó la solicitud."
        raise AfipSdkError(str(detail))
    return cae, _cae_due_date(authorization.get("Fch_venc_Cae")), voucher_number
