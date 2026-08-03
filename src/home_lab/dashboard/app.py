"""Dashboard entrypoint and shared monthly filter."""

from __future__ import annotations

from datetime import date

import streamlit as st

from home_lab.dashboard.periods import month_bounds, month_label, months_between
from home_lab.dashboard.queries import available_date_range, shared_expense_months
from home_lab.database import get_engine


st.set_page_config(page_title="House Ledger", page_icon="💸", layout="wide")
engine = get_engine()
date_range = available_date_range(engine)
current_month = date.today().replace(day=1)
available_dates = [current_month, *shared_expense_months(engine)]
if date_range is not None:
    available_dates.extend(date_range)
months = months_between(min(available_dates), max(available_dates))

with st.sidebar:
    st.header("Filtros")
    selected_month = st.selectbox(
        "Mes",
        months,
        index=months.index(current_month),
        format_func=month_label,
        key="selected_month",
    )
    st.session_state["start_date"], st.session_state["end_date"] = month_bounds(
        selected_month
    )

navigation = st.navigation(
    [
        st.Page(
            "pages/shared_expenses.py",
            title="Gastos compartidos",
            icon="🏠",
            default=True,
        ),
        st.Page("pages/overview.py", title="Flujo general", icon="📊"),
        st.Page("pages/movements.py", title="Movimientos", icon="🧾"),
        st.Page("pages/export_invoices.py", title="Facturación E", icon="🌎"),
        st.Page("pages/credit_cards.py", title="Tarjeta Naranja", icon="💳"),
        st.Page("pages/documents.py", title="Documentos", icon="📄"),
        st.Page("pages/operations.py", title="Operaciones", icon="🔄"),
    ]
)
navigation.run()
