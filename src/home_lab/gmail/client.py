"""Minimal read-only Gmail API client."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from dataclasses import dataclass
from email.message import Message
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
EPE_INVOICE_HOSTS = {"epe.santafe.gov.ar", "www.epe.santafe.gov.ar"}
EPE_INVOICE_PATH = (
    "/comercial/facturacion/facturas/generar_facturacorreo.php"
)
ASSA_TRACKING_HOST = "relaytrk.aguassantafesinas.com"
ASSA_INVOICE_HOST = "assa.facturadospuntocero.com"
ASSA_INVOICE_PATH = "/download-comprobante.php"
LITORAL_TRACKING_HOST = "relaytrk.digital.litoralgas.com.ar"
LITORAL_INVOICE_HOST = "litoral.ecofactura.com.ar"
LITORAL_INVOICE_PATH = "/FD/"
NARANJA_STATEMENT_HOST = "resumen.naranja.com"
NARANJA_STATEMENT_PATH = "/statements/withoutkey"


@dataclass(frozen=True)
class LinkedPdf:
    attachment_id: str
    filename: str
    url: str


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


def authorize(client_secret_path: Path, token_path: Path) -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not client_secret_path.exists():
        raise FileNotFoundError(
            f"Gmail OAuth client secret not found at {client_secret_path}"
        )
    token_path.parent.mkdir(parents=True, exist_ok=True)
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    credentials = flow.run_local_server(port=0)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    token_path.chmod(0o600)


def build_service(client_secret_path: Path, token_path: Path) -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not token_path.exists():
        raise FileNotFoundError(
            f"Gmail token not found at {token_path}; run gmail-auth first"
        )

    credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token_path.write_text(credentials.to_json(), encoding="utf-8")
        token_path.chmod(0o600)
    if not credentials.valid:
        raise RuntimeError("Gmail OAuth credentials are invalid; run gmail-auth again")
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def list_message_ids(service: Any, query: str) -> list[str]:
    message_ids: list[str] = []
    page_token: str | None = None
    while True:
        request = service.users().messages().list(
            userId="me",
            q=query,
            pageToken=page_token,
            maxResults=500,
        )
        response = request.execute()
        message_ids.extend(message["id"] for message in response.get("messages", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return message_ids


def get_message(service: Any, message_id: str) -> dict[str, Any]:
    return (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )


def iter_parts(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for part in payload.get("parts", []):
        yield part
        yield from iter_parts(part)


def pdf_parts(message: dict[str, Any]) -> Iterator[dict[str, Any]]:
    payload = message.get("payload", {})
    candidates = [payload, *iter_parts(payload)]
    for part in candidates:
        filename = part.get("filename", "")
        mime_type = part.get("mimeType", "")
        if mime_type == "application/pdf" or filename.lower().endswith(".pdf"):
            yield part


def _decode_body(part: dict[str, Any]) -> str:
    encoded = part.get("body", {}).get("data")
    if not encoded:
        return ""
    content = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    header = next(
        (
            item.get("value", "")
            for item in part.get("headers", [])
            if item.get("name", "").lower() == "content-type"
        ),
        "",
    )
    message = Message()
    message["content-type"] = header
    charset = message.get_content_charset() or "utf-8"
    try:
        return content.decode(charset)
    except (LookupError, UnicodeDecodeError):
        return content.decode("latin-1")


def _tracking_target(url: str) -> str | None:
    """Decode provider-owned click tracking without requesting the tracker."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in {ASSA_TRACKING_HOST, LITORAL_TRACKING_HOST}:
        return None
    encoded = parse_qs(parsed.query).get("p", [None])[0]
    if not encoded:
        return None
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.b64decode(padded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    target = payload.get("linkUrl")
    return target if isinstance(target, str) else None


def _invoice_kind(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme in {"http", "https"}
        and host in EPE_INVOICE_HOSTS
        and parsed.path == EPE_INVOICE_PATH
    ):
        return "epe"
    if (
        parsed.scheme == "https"
        and host == ASSA_INVOICE_HOST
        and parsed.path == ASSA_INVOICE_PATH
    ):
        return "assa"
    if (
        parsed.scheme == "https"
        and host == LITORAL_INVOICE_HOST
        and parsed.path == LITORAL_INVOICE_PATH
    ):
        return "litoral-gas"
    if (
        parsed.scheme == "https"
        and host == NARANJA_STATEMENT_HOST
        and parsed.path == NARANJA_STATEMENT_PATH
        and parse_qs(parsed.query).get("statement")
    ):
        return "naranja-x"
    return None


def linked_pdfs(message: dict[str, Any]) -> Iterator[LinkedPdf]:
    """Find allow-listed utility invoice links embedded in a Gmail HTML body."""
    payload = message.get("payload", {})
    for part in [payload, *iter_parts(payload)]:
        if part.get("mimeType", "").lower() != "text/html":
            continue
        parser = _LinkParser()
        parser.feed(_decode_body(part))
        for url in parser.links:
            target = _tracking_target(url) or url
            kind = _invoice_kind(target)
            if kind is None:
                continue
            parsed = urlparse(target)
            query = parse_qs(parsed.query)
            if kind == "epe":
                customer = query.get("numerodecliente", ["unknown"])[0]
                year = query.get("anio", ["unknown"])[0]
                period = query.get("mes", ["unknown"])[0]
                filename = f"epe-{customer}-{year}-{period}.pdf"
            elif kind == "assa":
                customer = query.get("uf", ["unknown"])[0]
                period = query.get("periodo", ["unknown"])[0]
                filename = f"assa-{customer}-{period}.pdf"
            elif kind == "litoral-gas":
                reference = query.get("p", ["unknown"])[0]
                filename = f"litoral-gas-{reference}.pdf"
            else:
                filename = f"naranja-x-{sha256(target.encode('utf-8')).hexdigest()[:16]}.pdf"
            digest = sha256(target.encode("utf-8")).hexdigest()
            yield LinkedPdf(
                attachment_id=f"linked:{digest}",
                filename=filename,
                url=target,
            )


def download_linked_pdf(url: str, max_bytes: int) -> bytes:
    """Download an allow-listed invoice PDF with redirect and size checks."""
    expected_kind = _invoice_kind(url)
    if expected_kind is None:
        raise ValueError("Linked PDF URL is not an allow-listed invoice endpoint")
    user_agent = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        if expected_kind == "naranja-x"
        else "home-lab/0.1"
    )
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=30) as response:
        if _invoice_kind(response.geturl()) != expected_kind:
            raise ValueError("Linked PDF redirected outside its invoice endpoint")
        declared_size = int(response.headers.get("Content-Length") or 0)
        if declared_size > max_bytes:
            raise ValueError(
                f"Linked PDF exceeds DOCUMENT_MAX_BYTES: {declared_size} bytes"
            )
        content = response.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(
            f"Linked PDF exceeds DOCUMENT_MAX_BYTES: {len(content)} bytes"
        )
    if not content.startswith(b"%PDF-"):
        raise ValueError("Invoice link did not return a valid PDF")
    return content


def attachment_bytes(service: Any, message_id: str, part: dict[str, Any]) -> bytes:
    body = part.get("body", {})
    encoded = body.get("data")
    if encoded is None:
        attachment_id = body.get("attachmentId")
        if not attachment_id:
            raise ValueError("Gmail PDF part has neither inline data nor attachment id")
        response = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        encoded = response["data"]
    return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
