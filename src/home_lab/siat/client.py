"""HTTP client for Rosario's anonymous TGI debt-management flow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import (
    HTTPCookieProcessor,
    Request,
    build_opener,
)


BASE_URL = "https://siat.rosario.gob.ar"
ENTRY_PATH = (
    "/siat/seg/Login.do?id=14&method=anonimo"
    "&url=%2Fgde%2FAdministrarLiqDeuda.do%3Fmethod%3DinicializarContr"
)
ACCOUNT_PATH = "/siat/gde/AdministrarLiqDeuda.do"
CURRENT_ACCOUNT_PATH = "/siat/gde/AdministrarCuentaCorriente.do"
REISSUE_PATH = "/siat/gde/AdministrarLiqReconfeccion.do"
RESTART_PATH = "/gde/AdministrarLiqDeuda.do?method=inicializarContr"
USER_AGENT = "home-lab/0.1 (+personal TGI document sync)"


class SiatError(RuntimeError):
    """Raised when SIAT rejects or unexpectedly changes the expected flow."""


@dataclass(frozen=True, order=True)
class TgiPeriod:
    year: int
    month: int
    selection_id: str

    @property
    def period(self) -> date:
        return date(self.year, self.month, 1)


@dataclass(frozen=True)
class TgiBill:
    period: TgiPeriod
    content: bytes


def parse_selectable_periods(html: str) -> tuple[TgiPeriod, ...]:
    values = re.findall(
        r'name=["\']listIdPeriodoSelected["\']\s+'
        r'value=["\']((\d{4})\.(\d{1,2})-\d+)["\']',
        html,
        flags=re.IGNORECASE,
    )
    periods = {
        TgiPeriod(int(year), int(month), selection_id)
        for selection_id, year, month in values
        if 1 <= int(month) <= 12
    }
    return tuple(sorted(periods))


def parse_account_id(html: str) -> str:
    match = re.search(
        r'name=["\']cuentaId["\']\s+value=["\'](\d+)["\']',
        html,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise SiatError("SIAT response did not contain the selected account id")
    return match.group(1)


class SiatTgiClient:
    def __init__(self, *, timeout_seconds: float = 30) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def _opener(self):
        return build_opener(HTTPCookieProcessor(CookieJar()))

    def _request(
        self,
        opener,
        path: str,
        *,
        form: dict[str, str] | None = None,
    ) -> tuple[bytes, str]:
        data = urlencode(form).encode("ascii") if form is not None else None
        request = Request(
            BASE_URL + path,
            data=data,
            headers={"User-Agent": USER_AGENT},
        )
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                content = response.read()
                content_type = response.headers.get_content_type()
        except (HTTPError, URLError, TimeoutError) as error:
            raise SiatError(f"SIAT request failed: {error}") from error
        return content, content_type

    @staticmethod
    def _decode_html(content: bytes) -> str:
        return content.decode("iso-8859-1", errors="replace")

    def _open_account(self, account: str, management_code: str):
        opener = self._opener()
        self._request(opener, ENTRY_PATH)
        content, content_type = self._request(
            opener,
            ACCOUNT_PATH,
            form={
                "cuenta.idRecurso": "14",
                "cuenta.numeroCuenta": account,
                "cuenta.codGesPer": management_code,
                "method": "ingresarLiqDeudaContr",
                "anonimo": "1",
                "urlReComenzar": RESTART_PATH,
                "selectedId": "",
                "isSubmittedForm": "true",
            },
        )
        if content_type != "text/html":
            raise SiatError(f"Unexpected SIAT account response: {content_type}")
        html = self._decode_html(content)
        if "cuentaCorrienteIngresoAdapter" not in html:
            error = re.search(
                r'<(?:ul|UL)[^>]*class=["\']error["\'][^>]*>.*?'
                r"<(?:li|LI)>(.*?)</(?:li|LI)>",
                html,
                flags=re.DOTALL,
            )
            detail = re.sub(r"<[^>]+>", "", error.group(1)).strip() if error else ""
            suffix = f": {detail}" if detail else ""
            raise SiatError(f"SIAT rejected the TGI account credentials{suffix}")
        return opener, html

    def selectable_periods(
        self,
        account: str,
        management_code: str,
    ) -> tuple[TgiPeriod, ...]:
        _, html = self._open_account(account, management_code)
        return parse_selectable_periods(html)

    def download_bill(
        self,
        account: str,
        management_code: str,
        period: TgiPeriod,
    ) -> TgiBill:
        opener, account_html = self._open_account(account, management_code)
        available = parse_selectable_periods(account_html)
        if period not in available:
            raise SiatError(
                f"TGI period {period.year}-{period.month:02d} is not selectable"
            )
        account_id = parse_account_id(account_html)
        content, content_type = self._request(
            opener,
            CURRENT_ACCOUNT_PATH,
            form={
                "method": "reconfeccionar",
                "anonimo": "1",
                "urlReComenzar": RESTART_PATH,
                "selectedId": account_id,
                "cuentaId": account_id,
                "isSubmittedForm": "true",
                "listIdPeriodoSelected": period.selection_id,
            },
        )
        if content_type != "text/html":
            raise SiatError(f"Unexpected SIAT reissue response: {content_type}")
        reissue_html = self._decode_html(content)
        if "liqReconfeccionAdapter" not in reissue_html:
            raise SiatError("SIAT did not prepare the selected TGI bill")

        content, content_type = self._request(
            opener,
            REISSUE_PATH,
            form={
                "method": "impRecibos",
                "anonimo": "1",
                "urlReComenzar": RESTART_PATH,
                "selectedId": "",
                "isSubmittedForm": "true",
            },
        )
        if content_type != "text/html":
            raise SiatError(f"Unexpected SIAT print response: {content_type}")
        print_html = self._decode_html(content)
        if "method=getPDF" not in print_html:
            raise SiatError("SIAT print response did not expose a PDF")

        pdf, content_type = self._request(opener, f"{REISSUE_PATH}?method=getPDF")
        if content_type != "application/pdf" or not pdf.startswith(b"%PDF-"):
            raise SiatError(f"Unexpected SIAT bill response: {content_type}")
        return TgiBill(period=period, content=pdf)
