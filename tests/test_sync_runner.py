from __future__ import annotations

import json
import subprocess
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread

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
) -> tuple[int, dict[str, str]]:
    connection = HTTPConnection(*runner_server, timeout=2)
    connection.request(method, path)
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
