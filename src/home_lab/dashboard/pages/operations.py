"""Explicit maintenance actions for the local home-lab instance."""

from __future__ import annotations

import hmac
import json
import os
from urllib.error import HTTPError, URLError
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


st.title("Operaciones")
st.caption(
    "Sincronizá las fuentes externas y reconstruí Silver/Gold. "
    "Sólo puede ejecutarse una sincronización por vez."
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
