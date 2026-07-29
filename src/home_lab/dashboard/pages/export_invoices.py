"""ARCA Factura E monthly and rolling-12-month tracker."""

from __future__ import annotations

from decimal import Decimal

import streamlit as st

from home_lab.config import monotributo_annual_limit_ars
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
