"""Dashboard entrypoint and shared date filter."""

from __future__ import annotations

import streamlit as st

from core.database import get_engine
from dashboard.queries import available_date_range


st.set_page_config(page_title="home-lab", page_icon="💸", layout="wide")
engine = get_engine()
date_range = available_date_range(engine)

if date_range is None:
    st.title("home-lab")
    st.info("Todavía no hay transacciones importadas.")
    st.stop()

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
        st.Page("pages/overview.py", title="Resumen", icon="📊", default=True),
        st.Page("pages/movements.py", title="Movimientos", icon="🧾"),
    ]
)
navigation.run()
