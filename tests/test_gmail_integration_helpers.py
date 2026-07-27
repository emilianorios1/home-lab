import base64

from home_lab.gmail.client import attachment_bytes, linked_pdfs, pdf_parts


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


def test_finds_epe_invoice_link_in_html_body() -> None:
    url = (
        "http://www.epe.santafe.gov.ar/comercial/facturacion/facturas/"
        "generar_facturacorreo.php?numerodecliente=2028476&anio=2026&mes=4"
    )
    html = f"<a href='{url}'>ver factura</a>".encode("iso-8859-1")
    encoded = base64.urlsafe_b64encode(html).decode().rstrip("=")
    message = {
        "payload": {
            "mimeType": "text/html",
            "headers": [
                {
                    "name": "Content-Type",
                    "value": 'text/html; charset="iso-8859-1"',
                }
            ],
            "body": {"data": encoded},
        }
    }

    links = list(linked_pdfs(message))

    assert len(links) == 1
    assert links[0].filename == "epe-2028476-2026-4.pdf"
    assert links[0].url == url


def test_ignores_untrusted_pdf_link() -> None:
    html = b"<a href='https://example.com/invoice.pdf'>ver factura</a>"
    encoded = base64.urlsafe_b64encode(html).decode().rstrip("=")
    message = {
        "payload": {
            "mimeType": "text/html",
            "body": {"data": encoded},
        }
    }

    assert list(linked_pdfs(message)) == []
