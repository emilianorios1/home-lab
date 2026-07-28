"""Monthly household expenses shared with Vitoria."""

from __future__ import annotations

from datetime import date

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


engine = get_engine()
months = shared_expense_months(engine)

st.title("Gastos compartidos")
st.caption("Facturas del hogar, pagos conciliados y monto a dividir con Vitoria.")

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
rows = summary["rows"].copy()

total, per_person, paid = st.columns(3)
total.metric("Total compartido", ars(summary["shared_total"]))
per_person.metric("A dividir por persona", ars(summary["per_person"]))
paid.metric("Pagos conciliados", ars(summary["paid_total"]))

visible = rows.rename(
    columns={
        "concept": "Concepto",
        "amount": "Importe del mes",
        "paid_amount": "Pago encontrado",
        "status": "Estado",
    }
)
visible["Importe del mes"] = visible["Importe del mes"].map(ars)
visible["Pago encontrado"] = visible["Pago encontrado"].map(ars)
st.dataframe(visible, width="stretch", hide_index=True)

pending = visible[visible["Estado"].isin(["Pendiente", "Parcial", "Sin factura"])]
if not pending.empty:
    st.caption(
        "Los renglones pendientes se completan automáticamente cuando aparece "
        "la factura o un pago compatible en Mercado Pago."
    )
