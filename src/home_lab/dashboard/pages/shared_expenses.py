"""Monthly household expenses shared with Vitoria."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st

from home_lab.config import document_store_path
from home_lab.dashboard.periods import month_label
from home_lab.dashboard.queries import monthly_shared_expenses
from home_lab.dashboard.rents import save_monthly_rent
from home_lab.database import get_engine
from home_lab.documents.storage import resolve_document_path


def ars(value: object) -> str:
    return f"$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def date_label(value: object) -> str:
    if value is None or pd.isna(value):
        return "Sin fecha"
    return value.strftime("%d/%m/%Y")


def document_downloads(documents: list[dict[str, object]], key: str) -> None:
    for document in documents:
        try:
            path = resolve_document_path(
                document_store_path(),
                str(document["storage_path"]),
            )
            st.download_button(
                "Descargar PDF",
                data=path.read_bytes(),
                file_name=str(document["original_filename"]),
                mime="application/pdf",
                key=f"{key}_{document['document_id']}",
            )
        except (OSError, ValueError) as error:
            st.warning(
                "El archivo no está disponible en el almacenamiento local: "
                f"{error}"
            )


SERVICE_ICONS = {
    "Expensas": "🏢",
    "Luz": "⚡",
    "Agua": "💧",
    "Gas": "🔥",
    "TGI": "🏛️",
    "Internet": "🌐",
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
    "Internet": 5,
}


engine = get_engine()
selected_month = st.session_state["selected_month"]

st.title("Gastos compartidos")
st.caption("Resumen del hogar y monto mensual a dividir con Vitoria.")

summary = monthly_shared_expenses(engine, selected_month)
services = summary["services"].copy()
rent = summary["rent"]
expenses = services.loc[services["category"] == "Expensas"].iloc[0]

st.subheader(f"Resumen de {month_label(selected_month).lower()}")
share, total = st.columns([1.5, 1])
share.metric("Parte total de cada uno", ars(summary["per_person"]))
total.metric("Total compartido del mes", ars(summary["shared_total"]))

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
st.subheader("Cómo se calculan las transferencias")

with st.container(border=True):
    st.markdown("#### 🏠 Alquiler")
    gross, discount, net = st.columns(3)
    gross.metric("Alquiler bruto", ars(rent["gross"]))
    discount.metric("− Expensas extraordinarias", ars(rent["extraordinary"]))
    net.metric("= Alquiler neto a transferir", ars(rent["net"]))
    st.caption(
        "Las expensas extraordinarias se descuentan del alquiler antes de "
        "transferírselo al propietario."
    )

with st.container(border=True):
    st.markdown("#### 🏢 Expensas")
    total_expenses, people, per_person = st.columns(3)
    total_expenses.metric("Expensas totales", ars(expenses["amount"]))
    people.metric("÷ Personas", "2")
    per_person.metric("= Parte de cada uno", ars(expenses["amount"] / 2))
    issuer = expenses["issuer"] or "Factura todavía no disponible"
    due_text = (
        f" · Vence {date_label(expenses['due_date'])}"
        if expenses["due_date"] is not None and not pd.isna(expenses["due_date"])
        else ""
    )
    st.caption(
        f"{issuer}{due_text} · "
        f"{STATUS_ICONS.get(expenses['status'], '•')} {expenses['status']}. "
        "Las expensas totales se transfieren completas a Zetace y ese importe "
        "se divide entre ambos."
    )
    document_downloads(
        expenses["documents"],
        f"{selected_month.isoformat()}_expenses",
    )

st.divider()
st.subheader("Otros servicios")

status_order = {"Pendiente": 0, "Parcial": 1, "Sin factura": 2, "Pagado": 3}
services_without_expenses = services[services["category"] != "Expensas"].copy()
services_without_expenses["_order"] = services_without_expenses["status"].map(
    status_order
)
services_without_expenses["_service_order"] = services_without_expenses[
    "category"
].map(SERVICE_ORDER)
services_without_expenses = services_without_expenses.sort_values(
    ["_order", "_service_order"]
)

for service in services_without_expenses.itertuples(index=False):
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
        document_downloads(
            service.documents,
            f"{selected_month.isoformat()}_{service.category}",
        )

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
    detail = services.rename(
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

with st.expander("✏️ Cargar alquiler bruto", expanded=not rent["configured"]):
    st.caption(
        "Ingresá el importe informado por la inmobiliaria. Las expensas "
        "extraordinarias se descuentan automáticamente."
    )
    with st.form(f"rent_{selected_month.isoformat()}"):
        gross_amount = st.number_input(
            "Alquiler bruto",
            min_value=0.01,
            value=float(rent["gross"]) or 0.01,
            step=1000.0,
            format="%.2f",
        )
        submitted = st.form_submit_button("Guardar alquiler", type="primary")
    if submitted:
        saved_amount = save_monthly_rent(
            engine,
            selected_month,
            Decimal(str(gross_amount)),
        )
        st.session_state["saved_rent"] = (selected_month, saved_amount)
        st.rerun()

saved_rent = st.session_state.pop("saved_rent", None)
if saved_rent and saved_rent[0] == selected_month:
    st.success(f"Alquiler bruto guardado: {ars(saved_rent[1])}.")
