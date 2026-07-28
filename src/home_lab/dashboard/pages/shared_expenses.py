"""Monthly household expenses shared with Vitoria."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st

from home_lab.dashboard.queries import (
    monthly_shared_expenses,
    shared_expense_months,
)
from home_lab.database import get_engine


MONTH_NAMES = (
    "",
    "Enero",
    "Febrero",
    "Marzo",
    "Abril",
    "Mayo",
    "Junio",
    "Julio",
    "Agosto",
    "Septiembre",
    "Octubre",
    "Noviembre",
    "Diciembre",
)


def ars(value: object) -> str:
    return f"$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def month_label(value: date) -> str:
    return f"{MONTH_NAMES[value.month]} {value.year}"


def date_label(value: object) -> str:
    if value is None or pd.isna(value):
        return "Sin fecha"
    return value.strftime("%d/%m/%Y")


SERVICE_ICONS = {
    "Expensas": "🏢",
    "Luz": "⚡",
    "Agua": "💧",
    "Gas": "🔥",
    "TGI": "🏛️",
}

STATUS_ICONS = {
    "Pagado": "✅",
    "Parcial": "🟡",
    "Pendiente": "⏳",
    "Sin factura": "⚪",
}

SERVICE_ORDER = {
    "Expensas": 0,
    "Luz": 1,
    "Agua": 2,
    "Gas": 3,
    "TGI": 4,
}


engine = get_engine()
months = shared_expense_months(engine)

st.title("Gastos compartidos")
st.caption("Resumen del hogar y monto mensual a dividir con Vitoria.")

if not months:
    st.info("Todavía no hay facturas ni pagos de alquiler para resumir.")
    st.stop()

current_month = date.today().replace(day=1)
default_month = max((month for month in months if month <= current_month), default=months[-1])
selected_month = st.selectbox(
    "Mes",
    months,
    index=months.index(default_month),
    format_func=month_label,
)
summary = monthly_shared_expenses(engine, selected_month)
services = summary["services"].copy()
rent = summary["rent"]

st.subheader(f"Resumen de {month_label(selected_month).lower()}")
share, total = st.columns([1.5, 1])
share.metric("Parte de cada uno", ars(summary["per_person"]))
total.metric("Total del hogar", ars(summary["shared_total"]))

progress = float(summary["payment_progress"])
st.progress(progress, text=f"{progress:.0%} pagado")
paid, pending = st.columns(2)
paid.metric("Pagado", ars(summary["paid_total"]))
pending.metric("Pendiente", ars(summary["pending_total"]))

pending_services = services[
    services["status"].isin(["Pendiente", "Parcial"])
    & (services["pending_amount"] > Decimal("0"))
]
missing_services = services[services["status"] == "Sin factura"]

if not pending_services.empty:
    st.warning(
        f"Faltan pagar o conciliar {len(pending_services)} gastos por "
        f"{ars(pending_services['pending_amount'].sum())}."
    )
elif summary["pending_total"] == Decimal("0"):
    st.success("Todos los gastos registrados del mes están pagados.")

if not missing_services.empty:
    missing_names = ", ".join(missing_services["concept"])
    st.info(f"Todavía no apareció la factura de: {missing_names}.")

st.divider()
st.subheader("Alquiler")
gross, discount, net = st.columns(3)
gross.metric("Alquiler bruto", ars(rent["gross"]))
discount.metric("Extraordinarias descontadas", f"− {ars(rent['extraordinary'])}")
net.metric("Alquiler efectivo", ars(rent["net"]))
st.caption(
    "El alquiler efectivo es el alquiler bruto menos las expensas extraordinarias."
)

st.divider()
st.subheader("Servicios")

status_order = {"Pendiente": 0, "Parcial": 1, "Sin factura": 2, "Pagado": 3}
services["_order"] = services["status"].map(status_order)
services["_service_order"] = services["category"].map(SERVICE_ORDER)
services = services.sort_values(["_order", "_service_order"])

for service in services.itertuples(index=False):
    with st.container(border=True):
        concept, amount, status = st.columns([2, 1.25, 1])
        concept.markdown(
            f"#### {SERVICE_ICONS.get(service.category, '🧾')} {service.concept}"
        )
        issuer = service.issuer or "Factura todavía no disponible"
        due_text = (
            f" · Vence {date_label(service.due_date)}"
            if service.due_date is not None and not pd.isna(service.due_date)
            else ""
        )
        concept.caption(f"{issuer}{due_text}")
        amount.metric("Importe", ars(service.amount))
        status.markdown(
            f"**{STATUS_ICONS.get(service.status, '•')} {service.status}**"
        )
        if service.status == "Parcial":
            status.caption(f"Faltan {ars(service.pending_amount)}")
        elif service.status == "Pagado":
            payment_text = (
                f" el {date_label(service.payment_date)}"
                if service.payment_date is not None
                and not pd.isna(service.payment_date)
                else ""
            )
            status.caption(f"Pago conciliado{payment_text}")

share_text = "\n".join(
    [
        f"Gastos de {month_label(selected_month).lower()}",
        f"Total del hogar: {ars(summary['shared_total'])}",
        f"Parte de cada uno: {ars(summary['per_person'])}",
        f"Pagado hasta ahora: {ars(summary['paid_total'])}",
        f"Pendiente: {ars(summary['pending_total'])}",
    ]
)
with st.expander("📋 Copiar resumen para Vitoria"):
    st.code(share_text, language=None)
    st.caption("Usá el botón de copiar del recuadro y pegalo en WhatsApp.")

with st.expander("Ver facturas y conciliaciones"):
    detail = services.drop(columns=["_order", "_service_order"]).rename(
        columns={
            "concept": "Concepto",
            "issuer": "Emisor",
            "due_date": "Vencimiento",
            "amount": "Importe",
            "paid_amount": "Pago encontrado",
            "pending_amount": "Pendiente",
            "payment_date": "Fecha de pago",
            "status": "Estado",
        }
    )
    detail = detail[
        [
            "Concepto",
            "Emisor",
            "Vencimiento",
            "Importe",
            "Pago encontrado",
            "Pendiente",
            "Fecha de pago",
            "Estado",
        ]
    ]
    st.dataframe(
        detail,
        width="stretch",
        hide_index=True,
        column_config={
            "Importe": st.column_config.NumberColumn(format="$ %.2f"),
            "Pago encontrado": st.column_config.NumberColumn(format="$ %.2f"),
            "Pendiente": st.column_config.NumberColumn(format="$ %.2f"),
            "Vencimiento": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Fecha de pago": st.column_config.DateColumn(format="DD/MM/YYYY"),
        },
    )
    st.caption(
        "Las conciliaciones se completan automáticamente cuando aparece un pago "
        "compatible en Mercado Pago."
    )
