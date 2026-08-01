"""Internal HTTP runner for the dashboard's allow-listed sync operations."""

from __future__ import annotations

import json
import logging
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from urllib.parse import unquote

from home_lab.logging import configure_logging


SYNC_COMMANDS = {
    "/sync/gmail": "sync-gmail",
    "/sync/mercadopago": "sync-mercadopago",
    "/sync/siat-tgi": "sync-siat-tgi",
}
STATEMENT_IMPORT_PATH = "/import/mercadopago-statement"
MAX_STATEMENT_BYTES = 10 * 1024 * 1024
# ponytail: one global lock is enough while every operation finishes with dbt build.
SYNC_LOCK = Lock()


class SyncRequestHandler(BaseHTTPRequestHandler):
    """Run only allow-listed maintenance operations on the Docker network."""

    def do_GET(self) -> None:
        if self.path != "/health":
            self._respond(HTTPStatus.NOT_FOUND, "Endpoint inexistente.")
            return
        self._respond(HTTPStatus.OK, "Runner disponible.")

    def do_POST(self) -> None:
        if self.path == STATEMENT_IMPORT_PATH:
            self._import_statement()
            return

        command = SYNC_COMMANDS.get(self.path)
        if command is None:
            self._respond(HTTPStatus.NOT_FOUND, "Sincronización inexistente.")
            return
        if not SYNC_LOCK.acquire(blocking=False):
            self._respond(
                HTTPStatus.CONFLICT,
                "Ya hay una sincronización en ejecución.",
            )
            return

        try:
            logging.info("Starting %s", command)
            result = subprocess.run(
                ["home-lab", command],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode:
                logging.error("%s failed with exit code %s", command, result.returncode)
                self._respond(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "La sincronización falló.",
                )
                return
            logging.info("%s completed", command)
            self._respond(HTTPStatus.OK, "Sincronización completada.")
        except OSError:
            logging.exception("Could not start %s", command)
            self._respond(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "No se pudo iniciar la sincronización.",
            )
        finally:
            SYNC_LOCK.release()

    def _import_statement(self) -> None:
        encoded_filename = self.headers.get("X-Filename", "")
        filename = unquote(encoded_filename)
        if (
            not filename
            or filename in {".", ".."}
            or "/" in filename
            or "\\" in filename
            or Path(filename).suffix.lower() != ".csv"
        ):
            self._respond(HTTPStatus.BAD_REQUEST, "Seleccioná un archivo CSV válido.")
            return

        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            content_length = 0
        if content_length <= 0:
            self._respond(HTTPStatus.LENGTH_REQUIRED, "El archivo está vacío.")
            return
        if content_length > MAX_STATEMENT_BYTES:
            self._respond(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "El CSV supera el límite de 10 MB.",
            )
            return

        content = self.rfile.read(content_length)
        if len(content) != content_length:
            self._respond(HTTPStatus.BAD_REQUEST, "No se recibió el archivo completo.")
            return
        if not SYNC_LOCK.acquire(blocking=False):
            self._respond(HTTPStatus.CONFLICT, "Ya hay una operación en ejecución.")
            return

        try:
            with TemporaryDirectory() as temporary_directory:
                source = Path(temporary_directory) / filename
                source.write_bytes(content)
                imported = subprocess.run(
                    ["home-lab", "import-account-statement", str(source)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            if imported.returncode:
                logging.error(
                    "Mercado Pago statement import failed with exit code %s",
                    imported.returncode,
                )
                self._respond(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "No se pudo importar el extracto. Revisá el formato y los logs.",
                )
                return

            transformed = subprocess.run(
                ["home-lab", "transform"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if transformed.returncode:
                logging.error(
                    "Transform after statement import failed with exit code %s",
                    transformed.returncode,
                )
                self._respond(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "El extracto se importó, pero no se pudo reconstruir Silver/Gold.",
                )
                return
            self._respond(HTTPStatus.OK, "Extracto importado y datos actualizados.")
        except OSError:
            logging.exception("Could not import Mercado Pago statement")
            self._respond(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "No se pudo iniciar la importación.",
            )
        finally:
            SYNC_LOCK.release()

    def _respond(self, status: HTTPStatus, message: str) -> None:
        body = json.dumps({"message": message}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            logging.info("Client disconnected before receiving the sync result")

    def log_message(self, format: str, *args: object) -> None:
        logging.info("%s - %s", self.client_address[0], format % args)


def main() -> None:
    configure_logging()
    server = ThreadingHTTPServer(("0.0.0.0", 8080), SyncRequestHandler)
    logging.info("Sync runner listening on port 8080")
    server.serve_forever()


if __name__ == "__main__":
    main()
