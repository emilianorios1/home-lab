import base64

from integrations.gmail import attachment_bytes, pdf_parts


def test_finds_nested_pdf_parts() -> None:
    message = {
        "payload": {
            "parts": [
                {"mimeType": "text/plain", "body": {"data": ""}},
                {
                    "mimeType": "multipart/mixed",
                    "parts": [
                        {
                            "partId": "2",
                            "filename": "expensas.pdf",
                            "mimeType": "application/pdf",
                            "body": {"data": "JVBERi0="},
                        }
                    ],
                },
            ]
        }
    }
    assert [part["filename"] for part in pdf_parts(message)] == ["expensas.pdf"]


def test_decodes_inline_attachment_without_api_call() -> None:
    content = b"%PDF-1.4"
    encoded = base64.urlsafe_b64encode(content).decode().rstrip("=")
    assert attachment_bytes(None, "message", {"body": {"data": encoded}}) == content
