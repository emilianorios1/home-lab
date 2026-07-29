import base64
from unittest.mock import MagicMock, patch

from home_lab.gmail.client import (
    attachment_bytes,
    download_linked_pdf,
    linked_pdfs,
    pdf_parts,
)


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


def test_downloads_epe_invoice_over_https() -> None:
    url = (
        "http://www.epe.santafe.gov.ar/comercial/facturacion/facturas/"
        "generar_facturacorreo.php?numerodecliente=2028476&anio=2026&mes=4"
    )
    content = b"%PDF-1.4"
    response = MagicMock()
    response.__enter__.return_value = response
    response.geturl.return_value = url.replace("http://", "https://")
    response.headers = {"Content-Length": str(len(content))}
    response.read.return_value = content

    with patch("home_lab.gmail.client.urlopen", return_value=response) as opener:
        assert download_linked_pdf(url, 1024) == content

    assert opener.call_args.args[0].full_url == url.replace("http://", "https://")


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


def _html_message(html: str) -> dict:
    encoded = base64.urlsafe_b64encode(html.encode()).decode().rstrip("=")
    return {
        "payload": {
            "mimeType": "text/html",
            "body": {"data": encoded},
        }
    }


def test_finds_assa_invoice_behind_tracking_link() -> None:
    import json
    from urllib.parse import quote

    target = (
        "https://assa.facturadospuntocero.com/download-comprobante.php"
        "?uf=00380921&tc=1&periodo=2026-04&key=secret"
    )
    payload = base64.b64encode(
        json.dumps({"linkUrl": target}).encode()
    ).decode()
    tracking = (
        "https://relaytrk.aguassantafesinas.com/Click/Track"
        f"?p={quote(payload)}"
    )

    links = list(linked_pdfs(_html_message(f"<a href='{tracking}'>Ver Factura</a>")))

    assert len(links) == 1
    assert links[0].filename == "assa-00380921-2026-04.pdf"
    assert links[0].url == target


def test_finds_litoral_gas_invoice_behind_tracking_link() -> None:
    import json
    from urllib.parse import quote

    target = "https://litoral.ecofactura.com.ar/FD/?p=invoice-reference"
    payload = base64.b64encode(
        json.dumps({"linkUrl": target}).encode()
    ).decode()
    tracking = (
        "https://relaytrk.digital.litoralgas.com.ar/Click/Track"
        f"?p={quote(payload)}"
    )

    links = list(linked_pdfs(_html_message(f"<a href='{tracking}'>Descargala</a>")))

    assert len(links) == 1
    assert links[0].filename == "litoral-gas-invoice-reference.pdf"
    assert links[0].url == target


def test_finds_naranja_x_statement_link() -> None:
    target = (
        "https://resumen.naranja.com/statements/withoutkey"
        "?statement=opaque-statement-token"
    )

    links = list(
        linked_pdfs(_html_message(f"<a href='{target}'>Descargar resumen</a>"))
    )

    assert len(links) == 1
    assert links[0].filename.startswith("naranja-x-")
    assert links[0].filename.endswith(".pdf")
    assert links[0].url == target
