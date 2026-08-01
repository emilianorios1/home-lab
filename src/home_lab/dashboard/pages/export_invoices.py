"""ARCA Factura E monthly and rolling-12-month tracker."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

import streamlit as st

from home_lab.arca.client import AfipSdkClient, AfipSdkError
from home_lab.arca.emission import (
    ExportInvoiceDraft,
    RecurringExportInvoiceProfile,
    emit_export_invoice,
    recurring_invoice_profile,
    save_recurring_invoice_profile,
)
from home_lab.config import afip_sdk_access_token, monotributo_annual_limit_ars
from home_lab.dashboard.queries import (
    export_invoice_monthly,
    export_invoice_summary,
    export_invoices,
)
from home_lab.database import get_engine


def money(value: object, symbol: str = "$") -> str:
    return (
        f"{symbol} {float(value):,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


engine = get_engine()
start_date = st.session_state["start_date"]
end_date = st.session_state["end_date"]
summary = export_invoice_summary(engine, end_date)
monthly = export_invoice_monthly(engine, end_date)
invoices = export_invoices(engine, start_date, end_date)

st.title("Facturación E")
st.caption(
    "Comprobantes emitidos en ARCA. El equivalente en pesos conserva la "
    "cotización de cada factura; emitir una factura no significa haberla cobrado."
)

month_ars, month_usd, rolling, count = st.columns(4)
month_ars.metric("Facturado este mes", money(summary["current_month_ars"]))
month_usd.metric(
    "Facturado este mes en USD",
    money(summary["current_month_usd"], "USD"),
)
rolling.metric("Últimos 12 meses", money(summary["rolling_12_month_ars"]))
count.metric("Facturas en 12 meses", int(summary["invoice_count"]))

limit = monotributo_annual_limit_ars()
if limit is None:
    st.info(
        "Configurá MONOTRIBUTO_ANNUAL_LIMIT_ARS con el límite vigente de tu "
        "categoría para ver el margen disponible."
    )
else:
    rolling_total = Decimal(summary["rolling_12_month_ars"])
    ratio = rolling_total / limit
    st.progress(min(float(ratio), 1.0))
    available = max(limit - rolling_total, Decimal("0"))
    st.caption(
        f"{ratio:.1%} del límite configurado · Disponible: {money(available)}. "
        "Verificá el límite vigente en ARCA o con tu contador."
    )
    if ratio >= Decimal("1"):
        st.error("El acumulado alcanzó o superó el límite configurado.")
    elif ratio >= Decimal("0.9"):
        st.warning("El acumulado superó el 90% del límite configurado.")

if monthly.empty:
    st.info("Todavía no hay Facturas E importadas.")
else:
    st.subheader("Evolución de los últimos 12 meses")
    st.bar_chart(
        monthly.set_index("month")["total_amount_ars"],
        x_label="Mes",
        y_label="Importe en pesos",
    )

st.subheader("Comprobantes del período")
if invoices.empty:
    st.info("No hay Facturas E dentro del período seleccionado.")
else:
    st.dataframe(
        invoices.drop(columns=["invoice_id"]),
        width="stretch",
        hide_index=True,
        column_config={
            "invoice_key": "Comprobante",
            "issue_date": st.column_config.DateColumn(
                "Emisión",
                format="DD/MM/YYYY",
            ),
            "payment_date": st.column_config.DateColumn(
                "Fecha de pago declarada",
                format="DD/MM/YYYY",
            ),
            "foreign_currency": None,
            "foreign_total_amount": st.column_config.NumberColumn(
                "Total USD",
                format="USD %.2f",
            ),
            "exchange_rate": st.column_config.NumberColumn(
                "Tipo de cambio",
                format="$ %.6f",
            ),
            "total_amount_ars": st.column_config.NumberColumn(
                "Equivalente ARS",
                format="$ %.2f",
            ),
            "cae": "CAE",
            "cae_due_date": st.column_config.DateColumn(
                "Vencimiento CAE",
                format="DD/MM/YYYY",
            ),
        },
    )

st.divider()
st.subheader("Laboratorio de emisión")
st.caption(
    "Emite Facturas E de prueba con el CUIT compartido de desarrollo de "
    "Afip SDK. No genera un comprobante fiscal válido y no suma importes al "
    "tracker ni al monotributo."
)

access_token = afip_sdk_access_token()
profile = recurring_invoice_profile(engine)
if access_token is None:
    st.warning(
        "Falta AFIP_SDK_ACCESS_TOKEN. Revocá el token que quedó expuesto, "
        "creá uno nuevo y guardalo únicamente en el .env de este entorno."
    )

with st.expander("Nueva Factura E de prueba"):
    if profile:
        st.caption(
            "Perfil recurrente cargado: verificá fecha, pago y tipo de cambio."
        )
    with st.form("sandbox-export-invoice"):
        point_of_sale = st.number_input(
            "Punto de venta WSFEX",
            min_value=1,
            step=1,
            value=profile.point_of_sale if profile else 1,
        )
        issue_date = st.date_input("Fecha de emisión", value=date.today())
        payment_date = st.date_input(
            "Fecha de pago declarada",
            value=date.today(),
        )
        client_name = st.text_input(
            "Nombre o razón social del cliente",
            value=profile.client_name if profile else "",
        )
        client_address = st.text_input(
            "Domicilio del cliente",
            value=profile.client_address if profile else "",
        )
        foreign_tax_id = st.text_input(
            "Identificación tributaria extranjera",
            value=profile.foreign_tax_id if profile else "",
        )
        destination_country_code = st.text_input(
            "Código WSFEX del país de destino",
            value=str(profile.destination_country_code) if profile else "",
            help="Usá el código que devuelve FEXGetPARAM_DST_pais.",
        )
        destination_country_tax_id = st.text_input(
            "CUIT ARCA del país de destino",
            value=str(profile.destination_country_tax_id) if profile else "",
            help="Usá el valor que devuelve FEXGetPARAM_DST_CUIT.",
        )
        description = st.text_area(
            "Descripción del servicio",
            value=profile.description if profile else "",
        )
        unit_code = st.number_input(
            "Código WSFEX de unidad de medida",
            min_value=1,
            step=1,
            value=profile.unit_code if profile else 7,
            help="7 suele representar unidad; verificá el código en WSFEX.",
        )
        amount_usd = st.number_input(
            "Importe total (USD)",
            min_value=0.01,
            step=10.0,
            format="%.2f",
            value=float(profile.amount_usd) if profile else 0.01,
        )
        exchange_rate = st.number_input(
            "Tipo de cambio histórico (ARS por USD)",
            min_value=0.000001,
            step=1.0,
            format="%.6f",
        )
        confirmed = st.checkbox(
            "Confirmo que esto se enviará al sandbox compartido de Afip SDK."
        )
        save_profile = st.form_submit_button("Guardar perfil recurrente")
        submitted = st.form_submit_button(
            "Solicitar CAE de prueba",
            disabled=access_token is None,
        )

    if save_profile:
        try:
            save_recurring_invoice_profile(
                engine,
                RecurringExportInvoiceProfile(
                    point_of_sale=int(point_of_sale),
                    client_name=client_name,
                    client_address=client_address,
                    foreign_tax_id=foreign_tax_id,
                    destination_country_code=int(destination_country_code),
                    destination_country_tax_id=int(destination_country_tax_id),
                    description=description,
                    unit_code=int(unit_code),
                    amount_usd=Decimal(str(amount_usd)),
                ),
            )
        except (ValueError, InvalidOperation) as error:
            st.error(str(error))
        else:
            st.success("Perfil recurrente guardado.")
            st.rerun()
    elif submitted:
        try:
            country_code = int(destination_country_code)
            country_tax_id = int(destination_country_tax_id)
            draft = ExportInvoiceDraft(
                point_of_sale=int(point_of_sale),
                issue_date=issue_date,
                payment_date=payment_date,
                client_name=client_name,
                client_address=client_address,
                foreign_tax_id=foreign_tax_id,
                destination_country_code=country_code,
                destination_country_tax_id=country_tax_id,
                description=description,
                unit_code=int(unit_code),
                amount_usd=Decimal(str(amount_usd)),
                exchange_rate=Decimal(str(exchange_rate)),
            )
            if not confirmed:
                raise ValueError("Confirmá el envío al sandbox.")
            client = AfipSdkClient(access_token or "")
            cae, cae_due_date, voucher_number = emit_export_invoice(draft, client)
        except (ValueError, InvalidOperation) as error:
            st.error(str(error))
        except AfipSdkError as error:
            st.warning(
                f"{error} Verificá el sandbox antes de intentar otra emisión."
            )
        else:
            due = f" · vence {cae_due_date:%d/%m/%Y}" if cae_due_date else ""
            st.success(
                f"CAE de prueba {cae} generado para "
                f"{int(point_of_sale):05d}-{voucher_number:08d}{due}."
            )
