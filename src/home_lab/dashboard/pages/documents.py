"""Invoice and source-document explorer."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from home_lab.config import document_store_path
from home_lab.dashboard.queries import document_filter_options, documents
from home_lab.database import get_engine
from home_lab.documents.storage import resolve_document_path


DOCUMENT_TYPE_LABELS = {
    "condominium_expense": "Expensas",
    "credit_card_statement": "Resumen de tarjeta",
    "electricity_bill": "Luz",
    "export_service_invoice": "Factura E",
    "gas_bill": "Gas",
    "property_tax_bill": "TGI",
    "water_bill": "Agua",
}


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
options = document_filter_options(engine, start_date, end_date)
document_type_options = sorted(options["document_type"].dropna().unique())

document_types = st.multiselect(
    "Tipo",
    document_type_options,
    format_func=lambda value: DOCUMENT_TYPE_LABELS.get(value, value),
)
data = documents(
    engine,
    start_date,
    end_date,
    search,
    document_types=tuple(document_types),
)

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
    "document_type",
    "parse_status",
    "original_filename",
]
selection = st.dataframe(
    data[visible_columns],
    width="stretch",
    hide_index=True,
    key="documents",
    on_select="rerun",
    selection_mode="single-row-required",
)
selected = data.iloc[selection.selection.rows[0]]

st.subheader("Documento seleccionado")
st.caption(str(selected["original_filename"]))
left, right = st.columns(2)
left.metric("Primer vencimiento", ars(selected["first_due_amount"]))
right.metric("Segundo vencimiento", ars(selected["second_due_amount"]))
if pd.notna(selected["error_message"]) and selected["error_message"]:
    st.error(str(selected["error_message"]))

try:
    path = resolve_document_path(document_store_path(), str(selected["storage_path"]))
    pdf = path.read_bytes()
    st.download_button(
        "Descargar PDF",
        data=pdf,
        file_name=str(selected["original_filename"]),
        mime="application/pdf",
    )
    st.pdf(
        pdf,
        height=700,
        key=f"document-preview-{selected['document_id']}",
    )
except (OSError, ValueError) as error:
    st.warning(f"El archivo no está disponible en el almacenamiento local: {error}")
