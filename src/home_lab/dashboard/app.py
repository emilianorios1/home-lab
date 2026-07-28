"""Dashboard entrypoint and shared date filter."""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from home_lab.dashboard.queries import available_date_range
from home_lab.database import get_engine


st.set_page_config(page_title="home-lab", page_icon="💸", layout="wide")
engine = get_engine()
date_range = available_date_range(engine)

if date_range is None:
    today = date.today()
    date_range = (today - timedelta(days=30), today)

with st.sidebar:
    st.header("Filtros")
    selected_dates = st.date_input(
        "Período",
        value=date_range,
        min_value=date_range[0],
        max_value=date_range[1],
    )
    if len(selected_dates) != 2:
        st.warning("Elegí una fecha de inicio y una de fin.")
        st.stop()
    st.session_state["start_date"], st.session_state["end_date"] = selected_dates

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
        st.Page("pages/credit_cards.py", title="Tarjeta Naranja", icon="💳"),
        st.Page("pages/documents.py", title="Documentos", icon="📄"),
    ]
)
navigation.run()
