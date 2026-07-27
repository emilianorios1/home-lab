"""Financial overview page."""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from core.database import get_engine
from dashboard.queries import daily_balance, daily_flow, expenses_by_category, overview


def ars(value: object) -> str:
    return f"$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


engine = get_engine()
start_date = st.session_state["start_date"]
end_date = st.session_state["end_date"]
summary = overview(engine, start_date, end_date)

st.title("Flujo y gastos")
st.caption(f"{start_date:%d/%m/%Y} — {end_date:%d/%m/%Y}")

income, expenses, net_flow, balance = st.columns(4)
income.metric("Ingresos", ars(summary["income"]))
expenses.metric("Egresos", ars(summary["expenses"]))
net_flow.metric("Flujo neto", ars(summary["net_flow"]))
balance.metric("Saldo final", ars(summary["closing_balance"]))

balance_data = daily_balance(engine, start_date, end_date)
flow_data = daily_flow(engine, start_date, end_date)
expense_data = expenses_by_category(engine, start_date, end_date)

left, right = st.columns(2)
with left:
    st.subheader("Saldo diario")
    st.plotly_chart(
        px.line(balance_data, x="release_date", y="partial_balance", markers=True),
        width="stretch",
    )
with right:
    st.subheader("Ingresos y egresos diarios")
    st.plotly_chart(
        px.bar(flow_data, x="release_date", y=["income", "expenses"], barmode="relative"),
        width="stretch",
    )

st.subheader("Egresos por categoría")
st.plotly_chart(
    px.bar(expense_data.sort_values("amount"), x="amount", y="category", orientation="h"),
    width="stretch",
)
