"""Naranja X statement and purchase explorer."""

from __future__ import annotations

from decimal import Decimal

import streamlit as st

from home_lab.dashboard.queries import (
    credit_card_expenses,
    credit_card_expenses_by_category,
    credit_card_statements,
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

st.title("Tarjeta Naranja")
st.caption(
    "Consumos por fecha de compra. Se muestran aparte del flujo de caja para no "
    "duplicarlos cuando se paga el resumen."
)

search = st.text_input(
    "Buscar consumo",
    placeholder="Ej.: seguro, combustible, software",
)
expenses = credit_card_expenses(engine, start_date, end_date, search)
categories = credit_card_expenses_by_category(engine, start_date, end_date)
statements = credit_card_statements(engine, start_date, end_date)

ars_total = (
    Decimal(expenses.loc[expenses["currency"] == "ARS", "amount"].sum())
    if not expenses.empty
    else Decimal("0")
)
usd_total = (
    Decimal(expenses.loc[expenses["currency"] == "USD", "amount"].sum())
    if not expenses.empty
    else Decimal("0")
)

ars, usd, count = st.columns(3)
ars.metric("Consumos en pesos", money(ars_total))
usd.metric("Consumos en dólares", money(usd_total, "USD"))
count.metric("Cargos", len(expenses))

if expenses.empty:
    st.info("No hay consumos de tarjeta para el período seleccionado.")
else:
    if not categories.empty:
        st.subheader("Gastos en pesos por categoría")
        st.bar_chart(
            categories.sort_values("amount"),
            x="amount",
            y="category",
            x_label="Importe",
            y_label="Categoría",
            horizontal=True,
        )

    st.subheader("Detalle de consumos")
    st.dataframe(
        expenses,
        width="stretch",
        hide_index=True,
        column_config={
            "purchase_date": st.column_config.DateColumn(
                "Fecha",
                format="DD/MM/YYYY",
            ),
            "category": "Categoría",
            "description": "Detalle",
            "card": "Tarjeta",
            "installment": "Cuota/plan",
            "currency": "Moneda",
            "amount": st.column_config.NumberColumn("Importe", format="%.2f"),
            "statement_period": st.column_config.DateColumn(
                "Resumen",
                format="MM/YYYY",
            ),
            "statement_due_date": st.column_config.DateColumn(
                "Vencimiento",
                format="DD/MM/YYYY",
            ),
        },
    )

with st.expander("Resúmenes y vencimientos"):
    if statements.empty:
        st.info("No hay resúmenes emitidos dentro del período seleccionado.")
    else:
        st.dataframe(
            statements,
            width="stretch",
            hide_index=True,
            column_config={
                "statement_id": None,
                "period": st.column_config.DateColumn("Período", format="MM/YYYY"),
                "issue_date": st.column_config.DateColumn(
                    "Cierre",
                    format="DD/MM/YYYY",
                ),
                "due_date": st.column_config.DateColumn(
                    "Vencimiento",
                    format="DD/MM/YYYY",
                ),
                "total_amount": st.column_config.NumberColumn(
                    "Total ARS",
                    format="$ %.2f",
                ),
                "foreign_total_amount": st.column_config.NumberColumn(
                    "Total USD",
                    format="USD %.2f",
                ),
                "foreign_currency": None,
                "minimum_payment": st.column_config.NumberColumn(
                    "Entrega mínima",
                    format="$ %.2f",
                ),
                "status": "Estado",
            },
        )
