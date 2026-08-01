from __future__ import annotations

import json
import subprocess
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import quote

import pytest

from home_lab import sync_runner


@pytest.fixture
def runner_server() -> tuple[str, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), sync_runner.SyncRequestHandler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def request(
    runner_server: tuple[str, int],
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str]]:
    connection = HTTPConnection(*runner_server, timeout=2)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    payload = json.loads(response.read())
    connection.close()
    return response.status, payload


def test_health_endpoint(runner_server: tuple[str, int]) -> None:
    status, payload = request(runner_server, "GET", "/health")

    assert status == 200
    assert payload == {"message": "Runner disponible."}


@pytest.mark.parametrize(
    ("path", "command"),
    [
        ("/sync/gmail", "sync-gmail"),
        ("/sync/mercadopago", "sync-mercadopago"),
        ("/sync/siat-tgi", "sync-siat-tgi"),
    ],
)
def test_sync_endpoint_runs_only_allowlisted_command(
    runner_server: tuple[str, int],
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    command: str,
) -> None:
    calls: list[list[str]] = []

    def run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(sync_runner.subprocess, "run", run)

    status, payload = request(runner_server, "POST", path)

    assert status == 200
    assert payload == {"message": "Sincronización completada."}
    assert calls == [["home-lab", command]]


def test_unknown_sync_is_rejected(runner_server: tuple[str, int]) -> None:
    status, _ = request(runner_server, "POST", "/sync/arbitrary-command")

    assert status == 404


def test_statement_endpoint_imports_csv_and_rebuilds_models(
    runner_server: tuple[str, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    imported: dict[str, object] = {}

    def run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[1] == "import-account-statement":
            source = Path(args[2])
            imported["name"] = source.name
            imported["content"] = source.read_bytes()
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(sync_runner.subprocess, "run", run)
    content = b"synthetic Mercado Pago statement"

    status, payload = request(
        runner_server,
        "POST",
        sync_runner.STATEMENT_IMPORT_PATH,
        body=content,
        headers={"X-Filename": quote("resumen agosto.csv", safe="")},
    )

    assert status == 200
    assert payload == {"message": "Extracto importado y datos actualizados."}
    assert imported == {"name": "resumen agosto.csv", "content": content}
    assert calls[0][0:2] == ["home-lab", "import-account-statement"]
    assert calls[1] == ["home-lab", "transform"]


@pytest.mark.parametrize("filename", ["../extracto.csv", "extracto.txt"])
def test_statement_endpoint_rejects_invalid_filename(
    runner_server: tuple[str, int],
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        sync_runner.subprocess,
        "run",
        lambda args, **_: calls.append(args),
    )

    status, payload = request(
        runner_server,
        "POST",
        sync_runner.STATEMENT_IMPORT_PATH,
        body=b"not used",
        headers={"X-Filename": quote(filename, safe="")},
    )

    assert status == 400
    assert payload == {"message": "Seleccioná un archivo CSV válido."}
    assert calls == []


def test_statement_endpoint_rejects_oversized_file(
    runner_server: tuple[str, int],
) -> None:
    status, payload = request(
        runner_server,
        "POST",
        sync_runner.STATEMENT_IMPORT_PATH,
        body=b"",
        headers={
            "Content-Length": str(sync_runner.MAX_STATEMENT_BYTES + 1),
            "X-Filename": "extracto.csv",
        },
    )

    assert status == 413
    assert payload == {"message": "El CSV supera el límite de 10 MB."}


def test_second_sync_is_rejected_while_runner_is_busy(
    runner_server: tuple[str, int],
) -> None:
    sync_runner.SYNC_LOCK.acquire()
    try:
        status, payload = request(runner_server, "POST", "/sync/gmail")
    finally:
        sync_runner.SYNC_LOCK.release()

    assert status == 409
    assert payload == {"message": "Ya hay una sincronización en ejecución."}
