"""Transaction explorer page."""

from __future__ import annotations

import streamlit as st

from core.database import get_engine
from dashboard.queries import movements


engine = get_engine()
start_date = st.session_state["start_date"]
end_date = st.session_state["end_date"]

st.title("Movimientos")
search = st.text_input("Buscar en tipo de transacción", placeholder="Ej.: Pago, transferencia, Netflix")
data = movements(engine, start_date, end_date, search)

first, second = st.columns(2)
first.metric("Movimientos", len(data))
second.metric("Resultado neto", f"$ {data['transaction_net_amount'].sum():,.2f}")
st.dataframe(data, use_container_width=True, hide_index=True)
