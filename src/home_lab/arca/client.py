"""Minimal Afip SDK REST client for ARCA's WSFEX sandbox."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_BASE_URL = "https://app.afipsdk.com/api"
DEVELOPMENT_TAX_ID = 20409378472
EXPORT_INVOICE_TYPE = 19


class AfipSdkError(RuntimeError):
    """A safe-to-display Afip SDK or WSFEX error."""


class AfipSdkClient:
    """Call WSFEX through Afip SDK using its shared development CUIT."""

    def __init__(self, access_token: str, *, timeout_seconds: float = 30) -> None:
        if not access_token:
            raise ValueError("access_token cannot be empty")
        self._access_token = access_token
        self._timeout_seconds = timeout_seconds
        self._ticket: dict[str, str] | None = None

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{API_BASE_URL}{path}",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
                "User-Agent": "home-lab/0.1",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                content = response.read()
        except HTTPError as error:
            raise AfipSdkError(
                f"Afip SDK devolvió HTTP {error.code}."
            ) from error
        except URLError as error:
            raise AfipSdkError(
                "No se pudo conectar con Afip SDK."
            ) from error

        try:
            result = json.loads(content)
        except json.JSONDecodeError as error:
            raise AfipSdkError("Afip SDK devolvió una respuesta inválida.") from error
        if not isinstance(result, dict):
            raise AfipSdkError("Afip SDK devolvió una respuesta inválida.")
        return result

    def _access_ticket(self) -> dict[str, str]:
        if self._ticket is None:
            response = self._post(
                "/v1/afip/auth",
                {
                    "environment": "dev",
                    "tax_id": str(DEVELOPMENT_TAX_ID),
                    "wsid": "wsfex",
                },
            )
            token = response.get("token")
            sign = response.get("sign")
            if not isinstance(token, str) or not isinstance(sign, str):
                raise AfipSdkError(
                    "Afip SDK no devolvió un ticket de acceso válido."
                )
            self._ticket = {"Token": token, "Sign": sign}
        return self._ticket

    def _auth(self, **extra: int) -> dict[str, Any]:
        return {
            **self._access_ticket(),
            "Cuit": DEVELOPMENT_TAX_ID,
            **extra,
        }

    def _execute(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._post(
            "/v1/afip/requests",
            {
                "environment": "dev",
                "method": method,
                "wsid": "wsfex",
                "params": params,
            },
        )

    @staticmethod
    def _service_error(result: dict[str, Any]) -> AfipSdkError | None:
        error = result.get("FEXErr")
        if not isinstance(error, dict):
            return None
        try:
            code = int(error.get("ErrCode") or 0)
        except (TypeError, ValueError):
            code = -1
        if code == 0:
            return None
        message = str(error.get("ErrMsg") or "error sin detalle")
        return AfipSdkError(f"WSFEX devolvió el error {code}: {message}")

    def get_last_request_id(self) -> int:
        response = self._execute(
            "FEXGetLast_ID",
            {"Auth": self._auth()},
        )
        result = response.get("FEXGetLast_IDResult")
        if not isinstance(result, dict):
            raise AfipSdkError("WSFEX no devolvió el último ID.")
        if error := self._service_error(result):
            raise error
        try:
            return int(result["FEXResultGet"]["Id"])
        except (KeyError, TypeError, ValueError) as error:
            raise AfipSdkError("WSFEX no devolvió el último ID.") from error

    def get_last_voucher(self, point_of_sale: int) -> int:
        response = self._execute(
            "FEXGetLast_CMP",
            {
                "Auth": self._auth(
                    Pto_venta=point_of_sale,
                    Cbte_Tipo=EXPORT_INVOICE_TYPE,
                )
            },
        )
        result = response.get("FEXGetLast_CMPResult")
        if not isinstance(result, dict):
            raise AfipSdkError("WSFEX no devolvió el último comprobante.")
        if error := self._service_error(result):
            raise error
        try:
            return int(result["FEXResult_LastCMP"]["Cbte_nro"])
        except (KeyError, TypeError, ValueError) as error:
            raise AfipSdkError(
                "WSFEX no devolvió el último comprobante."
            ) from error

    def authorize(self, voucher: dict[str, Any]) -> dict[str, Any]:
        return self._execute(
            "FEXAuthorize",
            {"Auth": self._auth(), "Cmp": voucher},
        )
