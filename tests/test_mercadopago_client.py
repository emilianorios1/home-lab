from datetime import date

import pytest

from home_lab.mercadopago.client import (
    GeneratedReport,
    MercadoPagoAPIError,
    MercadoPagoClient,
)


def test_create_report_uses_inclusive_argentina_dates() -> None:
    client = MercadoPagoClient("secret")
    captured = {}

    def request(method, path, *, payload=None, expect_json=True):
        captured.update(method=method, path=path, payload=payload)
        return {"id": 42}

    client._request = request  # type: ignore[method-assign]
    assert client.create_report(date(2026, 6, 1), date(2026, 6, 2)) == 42
    assert captured == {
        "method": "POST",
        "path": "/v1/account/settlement_report",
        "payload": {
            "begin_date": "2026-06-01T03:00:00Z",
            "end_date": "2026-06-02T03:00:00Z",
        },
    }


def test_wait_for_report_returns_processed_filename() -> None:
    client = MercadoPagoClient("secret", poll_interval_seconds=0)
    tasks = iter(
        [
            {"status": "pending"},
            {"status": "processed", "file_name": "report.csv"},
        ]
    )
    client.report_task = lambda task_id: next(tasks)  # type: ignore[method-assign]
    assert client.wait_for_report(42, wait_seconds=1) == "report.csv"


def test_wait_for_report_supports_current_available_files_response() -> None:
    client = MercadoPagoClient("secret")
    client.report_task = lambda task_id: {  # type: ignore[method-assign]
        "status": "available",
        "files": [
            {"type": "json", "name": "report.json"},
            {"type": "csv", "name": "report.csv"},
        ],
    }
    assert client.wait_for_report(42) == "report.csv"


def test_wait_for_report_rejects_terminal_failure() -> None:
    client = MercadoPagoClient("secret")
    client.report_task = lambda task_id: {"status": "failed"}  # type: ignore[method-assign]
    with pytest.raises(MercadoPagoAPIError, match="status: failed"):
        client.wait_for_report(42)


def test_generate_report_downloads_processed_task() -> None:
    client = MercadoPagoClient("secret")
    client.create_report = lambda start, end: 42  # type: ignore[method-assign]
    client.wait_for_report = lambda task_id, wait_seconds: "report.csv"  # type: ignore[method-assign]
    client.download_report = lambda filename: b"csv"  # type: ignore[method-assign]
    assert client.generate_report(
        date(2026, 6, 1),
        date(2026, 6, 1),
    ) == GeneratedReport(42, "report.csv", b"csv")


def test_configure_report_updates_an_existing_configuration() -> None:
    client = MercadoPagoClient("secret")
    calls = []

    def request(method, path, *, payload=None, expect_json=True):
        calls.append((method, path, payload))
        if method == "GET":
            return {"columns": []}
        return payload

    client._request = request  # type: ignore[method-assign]
    result = client.configure_report()
    assert [call[0] for call in calls] == ["GET", "PUT"]
    assert result["header_language"] == "en"
    assert {"key": "TRANSACTION_TYPE"} in result["columns"]
    assert {"key": "DESCRIPTION"} in result["columns"]
