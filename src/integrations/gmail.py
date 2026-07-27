"""Minimal read-only Gmail API client."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from pathlib import Path
from typing import Any


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


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
