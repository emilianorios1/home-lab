"""Invoice and source-document explorer."""

from __future__ import annotations

import streamlit as st
import pandas as pd

from core.config import document_store_path
from core.database import get_engine
from dashboard.queries import documents
from documents.storage import resolve_document_path


def ars(value: object) -> str:
    if value is None:
        return "—"
    return f"$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


engine = get_engine()
start_date = st.session_state["start_date"]
end_date = st.session_state["end_date"]

st.title("Documentos y facturas")
search = st.text_input(
    "Buscar documento",
    placeholder="Ej.: CONCORDE, 04-02 o nombre de archivo",
)
data = documents(engine, start_date, end_date, search)

parsed_count = int((data["parse_status"] == "parsed").sum()) if not data.empty else 0
failed_count = int((data["parse_status"] == "failed").sum()) if not data.empty else 0
first, second, third = st.columns(3)
first.metric("Documentos", len(data))
second.metric("Parseados", parsed_count)
third.metric("Con error", failed_count)

if data.empty:
    st.info("No hay documentos para el período y filtro seleccionados.")
    st.stop()

visible_columns = [
    "document_date",
    "period",
    "issuer",
    "unit",
    "first_due_date",
    "first_due_amount",
    "second_due_date",
    "second_due_amount",
    "parse_status",
    "original_filename",
]
st.dataframe(data[visible_columns], width="stretch", hide_index=True)

labels = {
    int(row.document_id): (
        f"{row.document_date:%d/%m/%Y} · "
        f"{row.issuer if pd.notna(row.issuer) else 'Sin emisor'} · {row.original_filename}"
    )
    for row in data.itertuples()
}
selected_id = st.selectbox(
    "Abrir documento",
    options=list(labels),
    format_func=labels.get,
)
selected = data.loc[data["document_id"] == selected_id].iloc[0]

left, right = st.columns(2)
left.metric("Primer vencimiento", ars(selected["first_due_amount"]))
right.metric("Segundo vencimiento", ars(selected["second_due_amount"]))
if pd.notna(selected["error_message"]) and selected["error_message"]:
    st.error(str(selected["error_message"]))

try:
    path = resolve_document_path(document_store_path(), str(selected["storage_path"]))
    st.download_button(
        "Descargar PDF",
        data=path.read_bytes(),
        file_name=str(selected["original_filename"]),
        mime="application/pdf",
    )
except (OSError, ValueError) as error:
    st.warning(f"El archivo no está disponible en el almacenamiento local: {error}")
