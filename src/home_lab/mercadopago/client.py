"""Small client for Mercado Pago's Account Money Reports API."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


API_BASE_URL = "https://api.mercadopago.com"
ARGENTINA_TIMEZONE = ZoneInfo("America/Argentina/Buenos_Aires")
TERMINAL_FAILURE_STATES = {"error", "failed", "cancelled", "deleted"}


class MercadoPagoAPIError(RuntimeError):
    """A safe-to-display Mercado Pago API error."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class GeneratedReport:
    task_id: int
    file_name: str
    content: bytes


def _utc_boundary(value: date) -> str:
    local = datetime.combine(value, datetime_time.min, tzinfo=ARGENTINA_TIMEZONE)
    return local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class MercadoPagoClient:
    def __init__(
        self,
        access_token: str,
        *,
        timeout_seconds: float = 30,
        poll_interval_seconds: float = 5,
    ) -> None:
        if not access_token:
            raise ValueError("access_token cannot be empty")
        self._access_token = access_token
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        expect_json: bool = True,
    ) -> Any:
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            f"{API_BASE_URL}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._access_token}",
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                content = response.read()
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(detail)
                detail = parsed.get("message") or parsed.get("error") or detail
            except json.JSONDecodeError:
                pass
            raise MercadoPagoAPIError(
                f"Mercado Pago API returned HTTP {error.code}: {detail}",
                status_code=error.code,
            ) from error
        except URLError as error:
            raise MercadoPagoAPIError(
                f"Could not connect to Mercado Pago API: {error.reason}"
            ) from error

        if not expect_json:
            return content
        try:
            return json.loads(content)
        except json.JSONDecodeError as error:
            raise MercadoPagoAPIError(
                "Mercado Pago API returned an invalid JSON response"
            ) from error

    def configure_report(self) -> dict[str, Any]:
        """Create or update the stable CSV shape consumed by home-lab."""
        payload = {
            "file_name_prefix": "home-lab-account-money",
            "display_timezone": "GMT-03",
            "header_language": "en",
            "separator": ";",
            "include_withdraw": True,
            "frequency": {"hour": 4, "type": "daily", "value": 1},
            "columns": [
                {"key": "TRANSACTION_DATE"},
                {"key": "SETTLEMENT_DATE"},
                {"key": "SOURCE_ID"},
                {"key": "EXTERNAL_REFERENCE"},
                {"key": "TRANSACTION_TYPE"},
                {"key": "TRANSACTION_AMOUNT"},
                {"key": "SETTLEMENT_NET_AMOUNT"},
            ],
        }
        try:
            self._request("GET", "/v1/account/settlement_report/config")
        except MercadoPagoAPIError as error:
            if error.status_code != 404:
                raise
            method = "POST"
        else:
            method = "PUT"
        result = self._request(
            method,
            "/v1/account/settlement_report/config",
            payload=payload,
        )
        if not isinstance(result, dict):
            raise MercadoPagoAPIError(
                "Mercado Pago returned an invalid report configuration"
            )
        return result

    def create_report(self, start: date, end: date) -> int:
        if end < start:
            raise ValueError("end date cannot be before start date")
        task = self._request(
            "POST",
            "/v1/account/settlement_report",
            payload={
                "begin_date": _utc_boundary(start),
                # Mercado Pago expands the final date through the end of that
                # local calendar day, so the CLI and API boundaries are inclusive.
                "end_date": _utc_boundary(end),
            },
        )
        try:
            return int(task["id"])
        except (KeyError, TypeError, ValueError) as error:
            raise MercadoPagoAPIError(
                "Mercado Pago did not return a report task ID"
            ) from error

    def report_task(self, task_id: int) -> dict[str, Any]:
        result = self._request(
            "GET",
            f"/v1/account/settlement_report/task/{task_id}",
        )
        if not isinstance(result, dict):
            raise MercadoPagoAPIError("Mercado Pago returned an invalid report task")
        return result

    def wait_for_report(self, task_id: int, *, wait_seconds: float = 300) -> str:
        deadline = time.monotonic() + wait_seconds
        while True:
            task = self.report_task(task_id)
            status = str(task.get("status", "")).lower()
            file_name = task.get("file_name")
            if status == "processed" and isinstance(file_name, str) and file_name:
                return file_name
            if status == "available":
                files = task.get("files", [])
                csv_file = next(
                    (
                        item.get("name")
                        for item in files
                        if isinstance(item, dict)
                        and str(item.get("type", "")).lower() == "csv"
                    ),
                    None,
                )
                if isinstance(csv_file, str) and csv_file:
                    return csv_file
            if status in TERMINAL_FAILURE_STATES:
                raise MercadoPagoAPIError(
                    f"Mercado Pago could not generate report {task_id} "
                    f"(status: {status})"
                )
            if time.monotonic() >= deadline:
                raise MercadoPagoAPIError(
                    f"Report {task_id} is still being generated; retry the command later"
                )
            time.sleep(self._poll_interval_seconds)

    def download_report(self, file_name: str) -> bytes:
        return self._request(
            "GET",
            f"/v1/account/settlement_report/{quote(file_name, safe='')}",
            expect_json=False,
        )

    def generate_report(
        self,
        start: date,
        end: date,
        *,
        wait_seconds: float = 300,
    ) -> GeneratedReport:
        task_id = self.create_report(start, end)
        file_name = self.wait_for_report(task_id, wait_seconds=wait_seconds)
        return GeneratedReport(task_id, file_name, self.download_report(file_name))
