from typing import Any

from home_lab.arca.client import (
    DEVELOPMENT_TAX_ID,
    EXPORT_INVOICE_TYPE,
    AfipSdkClient,
)


def test_http_client_identifies_itself(monkeypatch: Any) -> None:
    captured_user_agent: str | None = None

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"{}"

    def fake_urlopen(request: Any, *, timeout: float) -> Response:
        nonlocal captured_user_agent
        assert timeout == 30
        captured_user_agent = request.get_header("User-agent")
        return Response()

    monkeypatch.setattr("home_lab.arca.client.urlopen", fake_urlopen)

    AfipSdkClient("sdk-access-token")._post("/test", {})

    assert captured_user_agent == "home-lab/0.1"


def test_wsfex_requests_reuse_the_access_ticket(
    monkeypatch: Any,
) -> None:
    client = AfipSdkClient("sdk-access-token")
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((path, payload))
        if path == "/v1/afip/auth":
            return {"token": "arca-token", "sign": "arca-sign"}
        if payload["method"] == "FEXGetLast_ID":
            return {
                "FEXGetLast_IDResult": {
                    "FEXResultGet": {"Id": "41"},
                    "FEXErr": {"ErrCode": 0, "ErrMsg": ""},
                }
            }
        return {
            "FEXGetLast_CMPResult": {
                "FEXResult_LastCMP": {"Cbte_nro": "8"},
                "FEXErr": {"ErrCode": 0, "ErrMsg": ""},
            }
        }

    monkeypatch.setattr(client, "_post", fake_post)

    assert client.get_last_request_id() == 41
    assert client.get_last_voucher(3) == 8
    assert calls[0] == (
        "/v1/afip/auth",
        {
            "environment": "dev",
            "tax_id": str(DEVELOPMENT_TAX_ID),
            "wsid": "wsfex",
        },
    )
    assert len([path for path, _ in calls if path == "/v1/afip/auth"]) == 1
    last_voucher_request = calls[2][1]
    assert last_voucher_request["environment"] == "dev"
    assert last_voucher_request["method"] == "FEXGetLast_CMP"
    assert last_voucher_request["params"]["Auth"] == {
        "Token": "arca-token",
        "Sign": "arca-sign",
        "Cuit": DEVELOPMENT_TAX_ID,
        "Pto_venta": 3,
        "Cbte_Tipo": EXPORT_INVOICE_TYPE,
    }


def test_authorize_wraps_the_persisted_voucher(
    monkeypatch: Any,
) -> None:
    client = AfipSdkClient("sdk-access-token")
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((path, payload))
        if path == "/v1/afip/auth":
            return {"token": "arca-token", "sign": "arca-sign"}
        return {"FEXAuthorizeResult": {}}

    monkeypatch.setattr(client, "_post", fake_post)
    voucher = {"Id": 123, "Cbte_nro": 9}

    client.authorize(voucher)

    request = calls[1][1]
    assert request["method"] == "FEXAuthorize"
    assert request["params"]["Cmp"] is voucher
    assert request["params"]["Auth"]["Cuit"] == DEVELOPMENT_TAX_ID
