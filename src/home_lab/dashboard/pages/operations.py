"""Explicit maintenance actions for the local House Ledger instance."""

from __future__ import annotations

import hmac
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import streamlit as st


OPERATIONS_PASSWORD = os.getenv("HOME_LAB_OPERATIONS_PASSWORD", "")
SYNC_RUNNER_URL = os.getenv(
    "HOME_LAB_SYNC_RUNNER_URL",
    "http://sync-runner:8080",
).rstrip("/")


def trigger_sync(source: str) -> str:
    request = Request(f"{SYNC_RUNNER_URL}/sync/{source}", method="POST")
    with urlopen(request, timeout=900) as response:
        payload = json.load(response)
    return str(payload["message"])


def import_mercadopago_statement(filename: str, content: bytes) -> str:
    request = Request(
        f"{SYNC_RUNNER_URL}/import/mercadopago-statement",
        data=content,
        headers={
            "Content-Type": "text/csv",
            "X-Filename": quote(filename, safe=""),
        },
        method="POST",
    )
    with urlopen(request, timeout=900) as response:
        payload = json.load(response)
    return str(payload["message"])


def runner_error(error: HTTPError, fallback: str) -> str:
    try:
        return str(json.load(error)["message"])
    except (KeyError, TypeError, ValueError):
        return fallback


st.title("Operaciones")
st.caption(
    "Sincronizá las fuentes externas y reconstruí Silver/Gold. "
    "Sólo puede ejecutarse una operación por vez."
)

if not OPERATIONS_PASSWORD:
    st.error(
        "Las operaciones están deshabilitadas. "
        "Configurá HOME_LAB_OPERATIONS_PASSWORD."
    )
    st.stop()

if not st.session_state.get("operations_unlocked"):
    with st.form("operations-login"):
        password = st.text_input("Clave de operaciones", type="password")
        submitted = st.form_submit_button("Desbloquear")
    if submitted:
        if hmac.compare_digest(password, OPERATIONS_PASSWORD):
            st.session_state["operations_unlocked"] = True
            st.rerun()
        st.error("Clave incorrecta.")
    st.stop()

if st.button("Bloquear operaciones"):
    st.session_state.pop("operations_unlocked", None)
    st.rerun()

operations = (
    ("gmail", "Sincronizar Gmail", "Documentos y facturas recibidos por correo."),
    (
        "mercadopago",
        "Sincronizar Mercado Pago",
        "Movimientos correspondientes al día anterior.",
    ),
    ("siat-tgi", "Sincronizar TGI", "Boletas disponibles en SIAT Rosario."),
)

for column, (source, label, help_text) in zip(st.columns(3), operations):
    with column:
        st.subheader(label.removeprefix("Sincronizar "))
        st.caption(help_text)
        requested = st.button(label, key=f"sync-{source}", width="stretch")
    if not requested:
        continue

    with st.spinner(f"{label}…"):
        try:
            message = trigger_sync(source)
        except HTTPError as error:
            if error.code == 409:
                st.warning("Ya hay una sincronización en ejecución.")
            else:
                st.error("La sincronización falló. Revisá los logs del runner.")
        except (URLError, TimeoutError):
            st.error(
                "No se pudo confirmar el resultado. La sincronización puede "
                "seguir ejecutándose en el runner."
            )
        else:
            st.success(message)

st.divider()
st.subheader("Importar extracto de Mercado Pago")
st.caption(
    "Subí el CSV de Resumen de cuenta. Se validan los saldos, se conserva el "
    "original y se actualizan Silver/Gold."
)
uploaded_statement = st.file_uploader(
    "Extracto CSV",
    type="csv",
    accept_multiple_files=False,
)
import_requested = st.button(
    "Importar extracto",
    type="primary",
    disabled=uploaded_statement is None,
)

if import_requested and uploaded_statement is not None:
    with st.spinner("Importando extracto y actualizando datos…"):
        try:
            message = import_mercadopago_statement(
                uploaded_statement.name,
                uploaded_statement.getvalue(),
            )
        except HTTPError as error:
            if error.code == 409:
                st.warning(runner_error(error, "Ya hay una operación en ejecución."))
            else:
                st.error(
                    runner_error(
                        error,
                        "La importación falló. Revisá los logs del runner.",
                    )
                )
        except (URLError, TimeoutError):
            st.error(
                "No se pudo confirmar el resultado. La importación puede seguir "
                "ejecutándose en el runner."
            )
        else:
            st.success(message)
